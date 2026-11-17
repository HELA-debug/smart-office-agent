/**
 * 会话接口单测。
 *
 * 关注点：列表响应容错（后端可能返回裸数组 / {threads} / {items} / {data}）、
 * pinned 字段兜底、以及 id 的 URL 编码。
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

async function freshSessionsApi() {
  vi.resetModules();
  const module = await import('./api');
  return module.sessionsApi;
}

function stubFetch(impl: () => Promise<Response>): void {
  vi.stubGlobal('fetch', vi.fn(impl));
}

function fetchMock(): ReturnType<typeof vi.fn> {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

function lastCall(): [string, { method?: string; body?: string }] {
  const mock = fetchMock();
  return mock.mock.calls[mock.mock.calls.length - 1] as [
    string,
    { method?: string; body?: string },
  ];
}

beforeEach(() => {
  state.mockMode = false;
  stubFetch(async () => jsonResponse(200, {}));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

/* ------------------------------------------------------------------ */

describe('sessionsApi（mock 模式）', () => {
  beforeEach(() => {
    state.mockMode = true;
  });

  it('listThreads 补齐 pinned=false 并回填分页信息', async () => {
    const api = await freshSessionsApi();
    // mock 内存态初始为空，先建两条会话再断言列表形态
    await api.createThread('会话A');
    await api.createThread('会话B');
    const result = await api.listThreads();
    expect(result.data.threads.length).toBeGreaterThan(0);
    for (const thread of result.data.threads) {
      expect(thread.pinned).toBe(false);
    }
    expect(result.data.page).toBe(1);
    expect(result.data.page_size).toBe(result.data.threads.length);
    expect(result.data.total).toBe(result.data.threads.length);
  });

  it('createThread 不传标题时用默认标题，并置 pinned=false', async () => {
    const api = await freshSessionsApi();
    const created = await api.createThread();
    expect(created.data.title).toBe('新的会话');
    expect(created.data.pinned).toBe(false);
  });

  it('createThread 传入空白标题等价于不传', async () => {
    const api = await freshSessionsApi();
    expect((await api.createThread('   ')).data.title).toBe('新的会话');
  });

  it('getThread 返回带 messages 的详情', async () => {
    const api = await freshSessionsApi();
    const result = await api.getThread('th_mock_001');
    expect(result.data.messages).toEqual([]);
    expect(result.data.pinned).toBe(false);
  });

  // 注意：mock 模式的 updateThread 是无状态的（每次都基于 mockGetThread 重新组装），
  // 因此这里断言的是「字段覆盖规则」，而不是跨调用的持久化。
  it('updateThread 覆盖标题，未传 pinned 时置 false', async () => {
    const api = await freshSessionsApi();
    const renamed = await api.updateThread('th_mock_001', { title: '新名字' });
    expect(renamed.data.title).toBe('新名字');
    expect(renamed.data.pinned).toBe(false);
  });

  it('updateThread 只传 pinned 时保留原标题', async () => {
    const api = await freshSessionsApi();
    const created = await api.createThread('原标题');
    const pinned = await api.updateThread(created.data.thread_id, { pinned: true });
    expect(pinned.data.pinned).toBe(true);
    expect(pinned.data.title).toBe('原标题');
  });

  it('updateThread 空 patch 时 pinned 回落为 false', async () => {
    const api = await freshSessionsApi();
    const result = await api.updateThread('th_mock_001', {});
    expect(result.data.pinned).toBe(false);
  });

  it('deleteThread 在 mock 模式是空操作，不发请求', async () => {
    const api = await freshSessionsApi();
    await expect(api.deleteThread('th_mock_001')).resolves.toBeUndefined();
    expect(fetchMock()).not.toHaveBeenCalled();
  });
});

describe('sessionsApi（真实请求）', () => {
  it('listThreads 兼容裸数组 / threads / items / data 四种结构', async () => {
    const api = await freshSessionsApi();
    for (const body of [
      [{ thread_id: 'a' }],
      { threads: [{ thread_id: 'b' }] },
      { items: [{ thread_id: 'c' }] },
      { data: [{ thread_id: 'd' }] },
    ]) {
      stubFetch(async () => jsonResponse(200, body));
      const result = await api.listThreads();
      expect(result.data.threads).toHaveLength(1);
    }
  });

  it('listThreads 无法识别的结构返回空列表', async () => {
    const api = await freshSessionsApi();
    stubFetch(async () => jsonResponse(200, { unexpected: 1 }));
    const result = await api.listThreads();
    expect(result.data.threads).toEqual([]);
    expect(result.data.total).toBe(0);
  });

  it('listThreads 优先采用服务端返回的 total / page / page_size', async () => {
    const api = await freshSessionsApi();
    stubFetch(async () =>
      jsonResponse(200, { threads: [{ thread_id: 'a' }], total: 99, page: 3, page_size: 50 }),
    );
    const result = await api.listThreads();
    expect(result.data).toMatchObject({ total: 99, page: 3, page_size: 50 });
  });

  it('listThreads 打印查询参数', async () => {
    const api = await freshSessionsApi();
    await api.listThreads({ q: '周报', page: 2, pageSize: 10 });
    const params = new URLSearchParams(lastCall()[0].split('?')[1]);
    expect(params.get('q')).toBe('周报');
    expect(params.get('page')).toBe('2');
    expect(params.get('page_size')).toBe('10');
  });

  it('createThread 提交 {title|null}', async () => {
    const api = await freshSessionsApi();
    stubFetch(async () => jsonResponse(200, { thread_id: 't1', title: 'x', pinned: false }));
    await api.createThread('我的会话');
    const [url, init] = lastCall();
    expect(url).toBe('/api/v1/threads');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ title: '我的会话' });

    await api.createThread();
    expect(JSON.parse(lastCall()[1].body as string)).toEqual({ title: null });
  });

  it('getThread / updateThread / deleteThread 对 id 做 URL 编码', async () => {
    const api = await freshSessionsApi();
    stubFetch(async () => jsonResponse(200, { thread_id: 'a b', pinned: false }));

    await api.getThread('a b');
    expect(lastCall()[0]).toBe('/api/v1/threads/a%20b');

    await api.updateThread('a/b', { pinned: true });
    expect(lastCall()[0]).toBe('/api/v1/threads/a%2Fb');
    expect(lastCall()[1].method).toBe('PATCH');
    expect(JSON.parse(lastCall()[1].body as string)).toEqual({ pinned: true });

    await api.deleteThread('a?b');
    expect(lastCall()[0]).toBe('/api/v1/threads/a%3Fb');
    expect(lastCall()[1].method).toBe('DELETE');
  });
});
