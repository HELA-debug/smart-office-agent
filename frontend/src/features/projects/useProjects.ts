/**
 * 项目列表状态：左栏「项目」区与项目页共用一份数据。
 *
 * 左栏只显示前几个项目（余下在项目页看），所以这里不做分页，只维护「加载中 / 失败 / 空」三态，
 * 并把增删改后的最新列表直接回写，避免每次操作都整表重拉。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '../../shared/lib/api';
import { projectsApi } from './api';
import type { ProjectSummary } from './types';

export interface ProjectsController {
  items: ProjectSummary[];
  status: 'idle' | 'loading' | 'ready' | 'error';
  error: string | null;
  reload: () => Promise<void>;
  add: (path: string) => Promise<ProjectSummary | null>;
  remove: (projectId: string) => Promise<boolean>;
  rename: (projectId: string, name: string) => Promise<boolean>;
  reveal: (projectId: string) => Promise<{ opened: boolean; error: string | null }>;
}

export function useProjects(): ProjectsController {
  const [items, setItems] = useState<ProjectSummary[]>([]);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const aliveRef = useRef(true);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const reload = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus('loading');
    try {
      const response = await projectsApi.list(controller.signal);
      if (!aliveRef.current) return;
      setItems(response.data);
      setError(null);
      setStatus('ready');
    } catch (cause) {
      if (!aliveRef.current || controller.signal.aborted) return;
      setError(errorMessage(cause));
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const add = useCallback(async (path: string) => {
    try {
      const response = await projectsApi.add(path);
      setItems((current) => [...current, response.data]);
      setStatus('ready');
      return response.data;
    } catch (cause) {
      setError(errorMessage(cause));
      throw cause;
    }
  }, []);

  const remove = useCallback(async (projectId: string) => {
    try {
      await projectsApi.remove(projectId);
      setItems((current) => current.filter((item) => item.id !== projectId));
      return true;
    } catch (cause) {
      setError(errorMessage(cause));
      return false;
    }
  }, []);

  const rename = useCallback(async (projectId: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return false;
    try {
      const response = await projectsApi.update(projectId, { name: trimmed });
      setItems((current) =>
        current.map((item) => (item.id === projectId ? { ...item, ...response.data } : item)),
      );
      return true;
    } catch (cause) {
      setError(errorMessage(cause));
      return false;
    }
  }, []);

  const reveal = useCallback(async (projectId: string) => {
    try {
      const response = await projectsApi.reveal(projectId);
      return { opened: response.data.opened, error: response.data.error ?? null };
    } catch (cause) {
      return { opened: false, error: errorMessage(cause) };
    }
  }, []);

  return { items, status, error, reload, add, remove, rename, reveal };
}
