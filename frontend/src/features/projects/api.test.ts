/**
 * 项目接口单测：真实模式下请求体与响应容错；演示模式下走 localStorage。
 *
 * 重点锁两件事：
 * 1. 添加项目必须把 path 原样发给后端（路径里有中文/空格时不能被吃掉）；
 * 2. 后端字段缺失时前端不能崩（file_count / missing 兜底），否则左栏整块白掉。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ mockMode: false }));

vi.mock('../../shared/config/runtime', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/config/runtime')>();
  return { ...actual, isMockMode: () => state.mockMode };
});

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

async function freshApi() {
  vi.resetModules();
  const module = await import('./api');
  return module.projectsApi;
}

function lastCall(): [string, { method?: string; body?: string }] {
  const mock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  return mock.mock.calls[mock.mock.calls.length - 1] as [
    string,
    { method?: string; body?: string },
  ];
}

beforeEach(() => {
  state.mockMode = false;
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('projectsApi（真实后端）', () => {
  it('列表把缺失字段兜成默认值', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, { trace_id: 't1', projects: [{ id: 'p1', path: 'D:/合同' }] }),
      ),
    );
    const api = await freshApi();
    const response = await api.list();
    expect(response.data).toEqual([
      {
        id: 'p1',
        name: '未命名项目',
        path: 'D:/合同',
        created_at: '',
        pinned: false,
        file_count: 0,
        missing: false,
        modified_at: null,
      },
    ]);
  });

  it('添加项目用 POST 带上原始路径与名称', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(201, {
          project: { id: 'p1', path: 'D:/我的 合同', name: '我的 合同', file_count: 3 },
        }),
      ),
    );
    const api = await freshApi();
    const created = await api.add('D:/我的 合同');
    const [url, init] = lastCall();
    expect(url).toBe('/api/v1/projects');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body ?? '{}')).toEqual({ path: 'D:/我的 合同' });
    expect(created.data.file_count).toBe(3);
  });

  it('后端报错时把 error.message 抛成 ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(409, { error: { code: 'CONFLICT', message: '这个文件夹已经在项目列表里了' } }),
      ),
    );
    const api = await freshApi();
    await expect(api.add('D:/合同')).rejects.toMatchObject({
      code: 'CONFLICT',
      message: '这个文件夹已经在项目列表里了',
    });
  });

  it('文件列表解析相对路径与大小', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, {
          project: { id: 'p1', name: '合同' },
          files: [{ name: 'a.docx', rel_path: '2026/a.docx', ext: 'docx', size: 2048 }],
        }),
      ),
    );
    const api = await freshApi();
    const response = await api.files('p1');
    expect(response.data.files[0]).toMatchObject({ rel_path: '2026/a.docx', size: 2048 });
  });
});

describe('projectsApi（演示模式）', () => {
  it('添加后能列出来，移除后不再出现', async () => {
    state.mockMode = true;
    const api = await freshApi();
    const created = await api.add('D:/材料');
    expect(created.data.name).toBe('材料');

    const listed = await api.list();
    expect(listed.data.map((item) => item.path)).toEqual(['D:/材料']);

    await api.remove(created.data.id);
    expect((await api.list()).data).toEqual([]);
  });

  it('重复添加同一个文件夹给 CONFLICT', async () => {
    state.mockMode = true;
    const api = await freshApi();
    await api.add('D:/材料');
    await expect(api.add('d:/材料')).rejects.toMatchObject({ code: 'CONFLICT' });
  });
});
