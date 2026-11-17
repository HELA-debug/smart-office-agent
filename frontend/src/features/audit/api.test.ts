/**
 * 审计/用量接口单测。
 *
 * 关注点：mock 数据与真实响应的字段对齐（导出 CSV/JSON 依赖这些字段）、
 * 查询串拼装、以及导出 URL 的生成（带不带 thread_id 两种形态）。
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

async function freshAuditApi() {
  vi.resetModules();
  const module = await import('./api');
  return module.auditApi;
}

function stubFetch(impl: () => Promise<Response>): void {
  vi.stubGlobal('fetch', vi.fn(impl));
}

function fetchMock(): ReturnType<typeof vi.fn> {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

function lastUrl(): string {
  const mock = fetchMock();
  const call = mock.mock.calls[mock.mock.calls.length - 1] as [string] | undefined;
  if (!call) throw new Error('还没有发生任何 fetch 调用');
  return call[0];
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

describe('auditApi（mock 模式）', () => {
  beforeEach(() => {
    state.mockMode = true;
  });

  it('getAudit 固定标题为「演示会话」，运行记录字段完整', async () => {
    const api = await freshAuditApi();
    const result = await api.getAudit('th_mock_001');
    expect(result.data.thread_id).toBe('th_mock_001');
    expect(result.data.thread_title).toBe('演示会话');
    for (const run of result.data.runs) {
      expect(run.mode).toBe('mock');
      expect(run.engine).toBe('mock');
      expect(typeof run.tokens).toBe('number');
      expect(typeof run.cost_cny).toBe('number');
      expect(run.started_at).toBeTruthy();
    }
    expect(result.data.approvals).toEqual([]);
    expect(result.data.artifacts).toEqual([]);
  });

  it('getUsageSummary 返回可直接渲染的聚合数据', async () => {
    const api = await freshAuditApi();
    const result = await api.getUsageSummary();
    expect(result.data).toMatchObject({ range: 'all', runs: 1, tokens: 8123 });
    expect(result.data.by_day).toHaveLength(1);
    expect(result.data.by_status).toEqual({ completed: 1 });
  });

  it('getUsageSummary 带 threadId 时回填到响应', async () => {
    const api = await freshAuditApi();
    const result = await api.getUsageSummary({ threadId: 'th_mock_001' });
    expect(result.data.thread_id).toBe('th_mock_001');
  });
});

describe('auditApi（真实请求）', () => {
  it('getAudit 走 /threads/{id}/audit 并编码 id', async () => {
    const api = await freshAuditApi();
    stubFetch(async () => jsonResponse(200, { trace_id: 't', thread_id: 'a b', runs: [] }));
    await api.getAudit('a b');
    expect(lastUrl()).toBe('/api/v1/threads/a%20b/audit');
  });

  it('getUsageSummary 无参数时不带问号', async () => {
    const api = await freshAuditApi();
    await api.getUsageSummary();
    expect(lastUrl()).toBe('/api/v1/usage/summary');
  });

  it('getUsageSummary 拼装 thread_id / limit / range', async () => {
    const api = await freshAuditApi();
    await api.getUsageSummary({ threadId: 't1', limit: 30, range: '7d' });
    const params = new URLSearchParams(lastUrl().split('?')[1]);
    expect(params.get('thread_id')).toBe('t1');
    expect(params.get('limit')).toBe('30');
    expect(params.get('range')).toBe('7d');
  });

  it('exportUrl 生成正确的导出地址（带/不带 thread_id）', async () => {
    const api = await freshAuditApi();
    expect(api.exportUrl('csv')).toBe('/api/v1/audit/export?format=csv');
    expect(api.exportUrl('json', 't 1')).toBe('/api/v1/audit/export?format=json&thread_id=t+1');
    // 两种格式都要能解析回
    const parsed = new URLSearchParams(api.exportUrl('json', 't1').split('?')[1]);
    expect(parsed.get('format')).toBe('json');
    expect(parsed.get('thread_id')).toBe('t1');
  });
});
