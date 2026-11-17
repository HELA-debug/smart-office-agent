/**
 * 技能状态：已安装技能 + 技能库（可一键添加的内置技能）。
 * 输入框的技能弹层与技能页共用同一套动作（启停 / 删除 / 导入 / 添加）。
 */
import { useCallback, useEffect, useState } from 'react';
import { errorMessage } from '../../shared/lib/api';
import { skillsApi } from './api';
import type { CatalogSkill, SkillDraft, SkillItem } from './api';

export interface SkillsState {
  items: SkillItem[];
  promptChars: number;
  status: 'loading' | 'ready' | 'error';
  error: string | null;
  /** 技能库里可以添加的技能（含已添加标记） */
  catalog: CatalogSkill[];
  /** 技能库里出现过的分类，按后端给的顺序（首见顺序） */
  categories: string[];
  catalogStatus: 'loading' | 'ready' | 'error';
  catalogError: string | null;
  /** 正在启停/删除/添加的那一个（按钮转圈用） */
  busyName: string | null;
  notice: string | null;
  reload: () => void;
  toggle: (name: string, enabled: boolean) => Promise<void>;
  remove: (name: string) => Promise<void>;
  importFile: (file: File) => Promise<void>;
  install: (skillId: string) => Promise<void>;
  /** 让模型按一句话需求写一版（不落盘）；失败返回 null，原因在 draftError */
  draft: (idea: string) => Promise<SkillDraft | null>;
  drafting: boolean;
  draftError: string | null;
  /** 把草稿当成一份 SKILL.md 导入（复用 importFile 的全部校验与提示） */
  importDraft: (draft: SkillDraft) => Promise<void>;
  dismissNotice: () => void;
}

export function useSkills(): SkillsState {
  const [items, setItems] = useState<SkillItem[]>([]);
  const [promptChars, setPromptChars] = useState(0);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<CatalogSkill[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [catalogStatus, setCatalogStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [busyName, setBusyName] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);

  const loadInstalled = useCallback(async (signal?: AbortSignal) => {
    setStatus((current) => (current === 'ready' ? current : 'loading'));
    try {
      const response = await skillsApi.list(signal);
      setItems(response.data.skills);
      setPromptChars(response.data.prompt_chars);
      setError(null);
      setStatus('ready');
    } catch (cause) {
      if (signal?.aborted) return;
      setError(errorMessage(cause));
      setStatus('error');
    }
  }, []);

  const loadCatalog = useCallback(async (signal?: AbortSignal) => {
    setCatalogStatus((current) => (current === 'ready' ? current : 'loading'));
    try {
      const response = await skillsApi.catalog(signal);
      setCatalog(response.data.skills);
      setCategories(response.data.categories);
      setCatalogError(null);
      setCatalogStatus('ready');
    } catch (cause) {
      if (signal?.aborted) return;
      setCatalogError(errorMessage(cause));
      setCatalogStatus('error');
    }
  }, []);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      await Promise.all([loadInstalled(signal), loadCatalog(signal)]);
    },
    [loadInstalled, loadCatalog],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 3500);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const toggle = useCallback(async (name: string, enabled: boolean) => {
    setBusyName(name);
    try {
      const response = await skillsApi.setEnabled(name, enabled);
      setItems((current) =>
        current.map((item) => (item.name === name ? { ...item, enabled } : item)),
      );
      setPromptChars(response.data.prompt_chars);
    } catch (cause) {
      setNotice(`操作失败：${errorMessage(cause)}`);
    } finally {
      setBusyName(null);
    }
  }, []);

  const remove = useCallback(
    async (name: string) => {
      setBusyName(name);
      try {
        await skillsApi.deleteSkill(name);
        const removed = items.find((item) => item.name === name);
        setNotice(`已移除「${removed?.title ?? name}」（技能库还在，随时能再加回来）`);
        // 删掉的技能不再进提示词；技能库里那一项会重新变成「可添加」，两边都得重读
        await load();
      } catch (cause) {
        setNotice(`删除失败：${errorMessage(cause)}`);
      } finally {
        setBusyName(null);
      }
    },
    [items, load],
  );

  const importFile = useCallback(
    async (file: File) => {
      setBusyName('__import__');
      try {
        const response = await skillsApi.importSkill(file);
        setNotice(`已导入「${response.data.name}」`);
        await load();
      } catch (cause) {
        setNotice(`导入失败：${errorMessage(cause)}`);
      } finally {
        setBusyName(null);
      }
    },
    [load],
  );

  const install = useCallback(
    async (skillId: string) => {
      setBusyName(skillId);
      try {
        const response = await skillsApi.install(skillId);
        // 提示里用展示名（「会议纪要」），不要甩一坨 slug 给用户
        setNotice(`已添加「${response.data.skill?.title ?? response.data.name}」，立即生效`);
        await load();
      } catch (cause) {
        setNotice(`添加失败：${errorMessage(cause)}`);
      } finally {
        setBusyName(null);
      }
    },
    [load],
  );

  const draft = useCallback(async (idea: string) => {
    setDrafting(true);
    setDraftError(null);
    try {
      const response = await skillsApi.draft(idea);
      // 拿到空文本说明后端异常但没报错，别让用户对着空预览点导入
      if (!response.data.markdown.trim()) {
        setDraftError('模型这次没写出内容，换句话再说一次试试');
        return null;
      }
      return response.data;
    } catch (cause) {
      setDraftError(errorMessage(cause));
      return null;
    } finally {
      setDrafting(false);
    }
  }, []);

  const importDraft = useCallback(
    async (draftValue: SkillDraft) => {
      const file = new File([draftValue.markdown], `${draftValue.name || 'SKILL'}.md`, {
        type: 'text/markdown;charset=utf-8',
      });
      await importFile(file);
    },
    [importFile],
  );

  return {
    items,
    promptChars,
    status,
    error,
    catalog,
    categories,
    catalogStatus,
    catalogError,
    busyName,
    notice,
    reload: () => void load(),
    toggle,
    remove,
    importFile,
    install,
    draft,
    drafting,
    draftError,
    importDraft,
    dismissNotice: () => setNotice(null),
  };
}
