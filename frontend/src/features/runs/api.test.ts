/**
 * 运行/审批接口单测。
 *
 * 重点覆盖两类容易回归的地方：
 *   1) 后端版本较低时的优雅降级（404/405 → ENDPOINT_UNAVAILABLE，UI 提示而不是红字报错）；
 *   2) retryRun 的 SSE 分支——重试接口返回的是事件流而非 JSON，需要一路消费到 run.started。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ mockMode: false }));
const mockApproval = vi.hoisted(() => ({
  impl: null as null | ((...args: unknown[]) => unknown),
}));

vi.mock('../../shared/config/runtime', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/config/runtime')>();
  return { ...actual, isMockMode: () => state.mockMode };
});

vi.mock('../../shared/lib/mock-run', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/lib/mock-run')>();
  return {
    ...actual,
    // mock 审批回调由 runMockStream 内部注册，单测里替换为可控实现
    mockSubmitApproval: (...args: unknown[]) => {
      if (!mockApproval.impl) throw new Error('APPROVAL_ALREADY_DECIDED');
      return mockApproval.impl(...args);
    },
  };
});

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'text/event-stream' },
    text: async () => '',
    body: stream,
  } as unknown as Response;
}

async function freshRunsApi() {
  vi.resetModules();
  const module = await import('./api');
  return module.runsApi;
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
  mockApproval.impl = null;
  stubFetch(async () => jsonResponse(200, {}));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.resetModules();
});

/* ------------------------------------------------------------------ */
/* mock 模式                                                           */
/* ------------------------------------------------------------------ */

describe('runsApi（mock 模式）', () => {
  beforeEach(() => {
    state.mockMode = true;
  });

  it('listRuns / listThreadRuns / getRunEvents 返回空集合', async () => {
    const api = await freshRunsApi();
    expect((await api.listRuns()).data).toEqual({ runs: [], total: 0, page: 1, page_size: 0 });
    expect((await api.listThreadRuns('t1')).data).toEqual([]);
    expect((await api.getRunEvents('r1')).data).toEqual([]);
  });

  it('getRun 抛出 MOCK_EMPTY', async () => {
    const api = await freshRunsApi();
    await expect(api.getRun('r1')).rejects.toMatchObject({ code: 'MOCK_EMPTY' });
  });

  it('cancelRun / retryRun 抛出 ENDPOINT_UNAVAILABLE 且带 404 状态', async () => {
    const api = await freshRunsApi();
    await expect(api.cancelRun('r1')).rejects.toMatchObject({
      code: 'ENDPOINT_UNAVAILABLE',
      status: 404,
    });
    await expect(api.retryRun('r1')).rejects.toMatchObject({
      code: 'ENDPOINT_UNAVAILABLE',
      status: 404,
    });
  });

  it('submitApproval 已处理过时映射为 409', async () => {
    const api = await freshRunsApi();
    await expect(api.submitApproval('t1', 'a1', 'approved')).rejects.toMatchObject({
      code: 'APPROVAL_ALREADY_DECIDED',
      status: 409,
    });
  });

  it('submitApproval 成功时映射审批结果', async () => {
    mockApproval.impl = () => ({
      data: {
        approval_id: 'a1',
        decision: 'approved',
        decided_at: '2026-01-01T00:00:00Z',
        resumed: true,
      },
      traceId: 'mock-trace',
    });
    const api = await freshRunsApi();
    const result = await api.submitApproval('t1', 'a1', 'approved');
    expect(result.data).toEqual({
      trace_id: 'mock-trace',
      approval_id: 'a1',
      decision: 'approved',
      decided_at: '2026-01-01T00:00:00Z',
      resumed: true,
    });
    expect(result.traceId).toBe('mock-trace');
  });
});

/* ------------------------------------------------------------------ */
/* 真实请求路径                                                        */
/* ------------------------------------------------------------------ */

describe('runsApi（真实请求）', () => {
  it('listRuns 按条件拼查询串，空查询时不带 ?', async () => {
    const api = await freshRunsApi();
    stubFetch(async () =>
      jsonResponse(200, {
        trace_id: 't',
        runs: [{ run_id: 'r1' }],
        total: 1,
        page: 2,
        page_size: 20,
      }),
    );
    const result = await api.listRuns({
      threadId: 't1',
      status: 'succeeded',
      page: 2,
      pageSize: 20,
    });
    const params = new URLSearchParams(lastCall()[0].split('?')[1]);
    expect(params.get('thread_id')).toBe('t1');
    expect(params.get('status')).toBe('succeeded');
    expect(params.get('page')).toBe('2');
    expect(params.get('page_size')).toBe('20');
    expect(result.data).toMatchObject({ total: 1, page: 2, page_size: 20 });
  });

  it('listRuns 无参数时 URL 不带问号', async () => {
    const api = await freshRunsApi();
    await api.listRuns();
    expect(lastCall()[0]).toBe('/api/v1/runs');
  });

  it('listRuns 缺失分页字段时用默认值兜底', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(200, { trace_id: 't', runs: [{ run_id: 'r1' }] }));
    const result = await api.listRuns();
    expect(result.data).toMatchObject({ total: 1, page: 1, page_size: 0 });
  });

  it('listThreadRuns 兼容「裸数组」与「{runs:[]}」两种响应，异常结构返回空', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(200, [{ run_id: 'a' }]));
    expect((await api.listThreadRuns('t1')).data).toHaveLength(1);

    stubFetch(async () => jsonResponse(200, { runs: [{ run_id: 'b' }] }));
    expect((await api.listThreadRuns('t1')).data).toHaveLength(1);

    stubFetch(async () => jsonResponse(200, { unexpected: true }));
    expect((await api.listThreadRuns('t1')).data).toEqual([]);

    stubFetch(async () => jsonResponse(200, 'nonsense'));
    expect((await api.listThreadRuns('t1')).data).toEqual([]);
  });

  it('getRunEvents 携带 after 增量游标，并对 id 编码', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(200, { trace_id: 't', events: [{ seq: 1 }] }));
    const result = await api.getRunEvents('a b', 42);
    expect(lastCall()[0]).toBe('/api/v1/runs/a%20b/events?after=42');
    expect(result.data).toHaveLength(1);
  });

  it('getRunEvents 无 events 字段时返回空数组', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(200, { trace_id: 't' }));
    expect((await api.getRunEvents('r1', 0)).data).toEqual([]);
  });

  it('cancelRun 成功后直接返回', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(200, { trace_id: 't', run_id: 'r1', status: 'cancelled' }));
    const result = await api.cancelRun('r1');
    expect(lastCall()[0]).toBe('/api/v1/runs/r1/cancel');
    expect(result.data.status).toBe('cancelled');
  });

  it('cancelRun 遇 404/405 转为 ENDPOINT_UNAVAILABLE', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(404, { trace_id: 't' }));
    await expect(api.cancelRun('r1')).rejects.toMatchObject({
      code: 'ENDPOINT_UNAVAILABLE',
      status: 404,
    });
  });

  it('cancelRun 的其它错误（如 500）原样透出，便于重试', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(500, { trace_id: 't', error: { message: '服务端异常' } }));
    await expect(api.cancelRun('r1')).rejects.toMatchObject({ code: 'HTTP_500', status: 500 });
  });

  it('retryRun：非 SSE 响应（旧后端）直接从 JSON 取 run_id', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(200, { run_id: 'r_new' }));
    const result = await api.retryRun('r1');
    expect(result.data).toEqual({ run_id: 'r_new' });
  });

  it('retryRun：SSE 响应一路消费到 run.started 再返回新 run_id', async () => {
    vi.useFakeTimers();
    const api = await freshRunsApi();
    stubFetch(async () =>
      sseResponse([
        'event: run.created\ndata: {"run_id":"ignored"}\n\n',
        'event: run.started\ndata: {"run_id":"r_new_2"}\n\n',
        'event: run.completed\ndata: {}\n\n',
      ]),
    );
    const result = await api.retryRun('r1');
    expect(result.data).toEqual({ run_id: 'r_new_2' });
  });

  it('retryRun：流里没有 run.started 时返回 null', async () => {
    vi.useFakeTimers();
    const api = await freshRunsApi();
    stubFetch(async () => sseResponse(['event: message.delta\ndata: {"delta":"hi"}\n\n']));
    expect((await api.retryRun('r1')).data).toEqual({ run_id: null });
  });

  it('retryRun：HTTP 失败时用后端 error.message', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(400, { error: { message: '该运行不可重试' } }));
    await expect(api.retryRun('r1')).rejects.toMatchObject({
      code: 'RETRY_FAILED',
      status: 400,
      message: '该运行不可重试',
      retryable: false,
    });
  });

  it('retryRun：非 JSON 错误体时用状态码兜底文案', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => {
      const response = jsonResponse(502, null);
      return { ...response, text: async () => '<html>bad gateway</html>' } as unknown as Response;
    });
    await expect(api.retryRun('r1')).rejects.toMatchObject({
      code: 'RETRY_FAILED',
      status: 502,
      message: '重试失败（HTTP 502）',
      retryable: true,
    });
  });

  it('retryRun：404 转为 ENDPOINT_UNAVAILABLE', async () => {
    const api = await freshRunsApi();
    stubFetch(async () => jsonResponse(404, { trace_id: 't' }));
    await expect(api.retryRun('r1')).rejects.toMatchObject({
      code: 'ENDPOINT_UNAVAILABLE',
      status: 404,
    });
  });

  it('submitApproval 提交 decision，有 comment 时一并带上', async () => {
    const api = await freshRunsApi();
    stubFetch(async () =>
      jsonResponse(200, {
        trace_id: 't',
        approval_id: 'a1',
        decision: 'rejected',
        decided_at: 'now',
        resumed: false,
      }),
    );
    await api.submitApproval('t 1', 'a/1', 'rejected', '不同意');
    const [url, init] = lastCall();
    expect(url).toBe('/api/v1/threads/t%201/approvals/a%2F1');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ decision: 'rejected', comment: '不同意' });
  });

  it('submitApproval 无 comment 时不发送该字段', async () => {
    const api = await freshRunsApi();
    stubFetch(async () =>
      jsonResponse(200, { trace_id: 't', approval_id: 'a1', decision: 'approved' }),
    );
    await api.submitApproval('t1', 'a1', 'approved');
    expect(JSON.parse(lastCall()[1].body as string)).toEqual({ decision: 'approved' });
  });
});
