/** 项目接口（feature: projects，正式 /api/v1）：登记本地文档文件夹。 */
import { isMockMode } from '../../shared/config/runtime';
import { ApiError, asRecord, encodeId, requestV1 } from '../../shared/lib/api';
import type { ProjectFile, ProjectSummary } from './types';
import type { ApiResponse } from '../../shared/types/api';

/** 演示模式没有真实后端：本地存储里放一份，至少能走通「添加/移除」交互。 */
const MOCK_KEY = 'oa.mock.projects';

function mockList(): ProjectSummary[] {
  try {
    const raw = window.localStorage.getItem(MOCK_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as ProjectSummary[]) : [];
  } catch {
    return [];
  }
}

function mockSave(items: ProjectSummary[]): void {
  try {
    window.localStorage.setItem(MOCK_KEY, JSON.stringify(items));
  } catch {
    // 隐私模式下写不进去：演示模式不影响主流程
  }
}

function normalizeProject(raw: unknown): ProjectSummary | null {
  const record = asRecord(raw);
  if (!record || typeof record.id !== 'string') return null;
  return {
    id: record.id,
    name: typeof record.name === 'string' ? record.name : '未命名项目',
    path: typeof record.path === 'string' ? record.path : '',
    created_at: typeof record.created_at === 'string' ? record.created_at : '',
    pinned: Boolean(record.pinned),
    file_count: typeof record.file_count === 'number' ? record.file_count : 0,
    missing: Boolean(record.missing),
    modified_at: typeof record.modified_at === 'string' ? record.modified_at : null,
  };
}

export const projectsApi = {
  async list(signal?: AbortSignal): Promise<ApiResponse<ProjectSummary[]>> {
    if (isMockMode()) return { data: mockList(), traceId: null };
    const response = await requestV1<unknown>('/projects', 'GET', { signal });
    const record = asRecord(response.data) ?? {};
    const items = Array.isArray(record.projects) ? record.projects : [];
    return {
      data: items.map(normalizeProject).filter((item): item is ProjectSummary => item !== null),
      traceId: response.traceId,
    };
  },

  async add(path: string, name?: string): Promise<ApiResponse<ProjectSummary>> {
    if (isMockMode()) {
      const items = mockList();
      if (items.some((item) => item.path.toLowerCase() === path.toLowerCase())) {
        throw new ApiError('这个文件夹已经在项目列表里了', { code: 'CONFLICT', status: 409 });
      }
      const created: ProjectSummary = {
        id: `prj_mock_${Date.now().toString(36)}`,
        name: name?.trim() || path.split(/[\\/]/).filter(Boolean).pop() || path,
        path,
        created_at: new Date().toISOString(),
        pinned: false,
        file_count: 0,
        missing: false,
        modified_at: null,
      };
      mockSave([...items, created]);
      return { data: created, traceId: null };
    }
    const response = await requestV1<unknown>('/projects', 'POST', {
      body: JSON.stringify({ path, name }),
    });
    const project = normalizeProject(asRecord(response.data)?.project);
    if (!project) throw new ApiError('后端没有返回项目信息', { code: 'INTERNAL' });
    return { data: project, traceId: response.traceId };
  },

  async update(
    projectId: string,
    patch: { name?: string; pinned?: boolean },
  ): Promise<ApiResponse<ProjectSummary>> {
    if (isMockMode()) {
      const items = mockList().map((item) =>
        item.id === projectId
          ? { ...item, ...(patch.name !== undefined ? { name: patch.name } : {}), ...patch }
          : item,
      );
      mockSave(items);
      const found = items.find((item) => item.id === projectId);
      if (!found) throw new ApiError('项目不存在', { code: 'NOT_FOUND', status: 404 });
      return { data: found, traceId: null };
    }
    const response = await requestV1<unknown>(`/projects/${encodeId(projectId)}`, 'PATCH', {
      body: JSON.stringify(patch),
    });
    const project = normalizeProject(asRecord(response.data)?.project);
    if (!project) throw new ApiError('后端没有返回项目信息', { code: 'INTERNAL' });
    return { data: project, traceId: response.traceId };
  },

  async remove(projectId: string): Promise<ApiResponse<{ removed: boolean }>> {
    if (isMockMode()) {
      mockSave(mockList().filter((item) => item.id !== projectId));
      return { data: { removed: true }, traceId: null };
    }
    const response = await requestV1<unknown>(`/projects/${encodeId(projectId)}`, 'DELETE');
    return {
      data: { removed: Boolean(asRecord(response.data)?.removed) },
      traceId: response.traceId,
    };
  },

  async files(
    projectId: string,
    options: { q?: string; signal?: AbortSignal } = {},
  ): Promise<ApiResponse<{ project: ProjectSummary | null; files: ProjectFile[] }>> {
    if (isMockMode()) {
      return {
        data: { project: mockList().find((item) => item.id === projectId) ?? null, files: [] },
        traceId: null,
      };
    }
    const suffix = options.q ? `?q=${encodeURIComponent(options.q)}` : '';
    const response = await requestV1<unknown>(
      `/projects/${encodeId(projectId)}/files${suffix}`,
      'GET',
      {
        signal: options.signal,
      },
    );
    const record = asRecord(response.data) ?? {};
    const raw = Array.isArray(record.files) ? record.files : [];
    const files: ProjectFile[] = raw.flatMap((entry) => {
      const item = asRecord(entry);
      if (!item || typeof item.name !== 'string') return [];
      return [
        {
          name: item.name,
          rel_path: typeof item.rel_path === 'string' ? item.rel_path : item.name,
          ext: typeof item.ext === 'string' ? item.ext : '',
          size: typeof item.size === 'number' ? item.size : 0,
          modified_at: typeof item.modified_at === 'string' ? item.modified_at : '',
          path: typeof item.path === 'string' ? item.path : undefined,
        },
      ];
    });
    return {
      data: { project: normalizeProject(record.project), files },
      traceId: response.traceId,
    };
  },

  async reveal(
    projectId: string,
  ): Promise<ApiResponse<{ opened: boolean; error?: string | null }>> {
    if (isMockMode()) {
      throw new ApiError('演示模式不能打开本机文件夹', { code: 'ENDPOINT_UNAVAILABLE' });
    }
    const response = await requestV1<unknown>(`/projects/${encodeId(projectId)}/reveal`, 'POST');
    const record = asRecord(response.data) ?? {};
    return {
      data: {
        opened: Boolean(record.opened),
        error: typeof record.error === 'string' ? record.error : null,
      },
      traceId: response.traceId,
    };
  },
};
