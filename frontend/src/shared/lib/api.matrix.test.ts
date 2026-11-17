/**
 * HTTP 错误映射矩阵：状态码 × 响应体形态 的笛卡尔积。
 *
 * 真实事故往往不在「400 有 error 体」这种标准情况，而在边角：
 * 网关返回 502 纯 HTML、代理返回空体、旧后端只给 detail 字符串。
 * 这一层出错的症状是「所有页面一起报错，还报得看不懂」，所以按矩阵逐格钉住。
 */
import { afterEach, vi } from 'vitest';
import { describe, expect, it } from 'vitest';
import { ApiError, requestWithBase } from './api';
import { onBackendStatus } from './backend-status';

type BodyKind = 'envelope' | 'detail-string' | 'text' | 'empty' | 'json-without-error';

const BODIES: Record<BodyKind, { status: number; text: string }> = {
  envelope: {
    status: 0,
    text: JSON.stringify({
      trace_id: 'tr_matrix',
      error: { code: 'NOT_FOUND', message: '会话不存在：th_x' },
    }),
  },
  'detail-string': {
    status: 0,
    text: JSON.stringify({ detail: '缺少参数 message' }),
  },
  text: { status: 0, text: '<html><body>502 Bad Gateway</body></html>' },
  empty: { status: 0, text: '' },
  'json-without-error': { status: 0, text: JSON.stringify({ ok: false }) },
};

function makeResponse(status: number, kind: BodyKind): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => BODIES[kind].text,
  } as unknown as Response;
}

function stubFetch(status: number, kind: BodyKind) {
  // 显式写出参数类型，mock.calls 才是 [url, init] 元组，断言里能直接取下标
  const fetchMock = vi.fn(async (_url: string, _init: RequestInit): Promise<Response> =>
    makeResponse(status, kind),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

async function grabError(status: number, kind: BodyKind): Promise<ApiError> {
  stubFetch(status, kind);
  try {
    await requestWithBase('/api/v1', '/threads', 'GET');
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error('预期抛错，但请求成功了');
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const CLIENT_ERRORS = [400, 401, 403, 404, 405, 409, 413, 415, 422] as const;
const SERVER_ERRORS = [500, 502, 503, 504] as const;
const BODY_KINDS = Object.keys(BODIES) as BodyKind[];

describe('4xx：来自业务的拒绝', () => {
  for (const status of CLIENT_ERRORS) {
    for (const kind of BODY_KINDS) {
      it(`${status} + ${kind} 不标记为可重试`, async () => {
        const error = await grabError(status, kind);
        expect(error.status).toBe(status);
        expect(error.retryable).toBe(false);
        expect(error.message).not.toBe('');
      });
    }
  }
});

describe('4xx：错误码与文案的取值优先级', () => {
  it('标准错误体：code / message / trace_id 全部透传', async () => {
    const error = await grabError(404, 'envelope');
    expect(error.code).toBe('NOT_FOUND');
    expect(error.message).toBe('会话不存在：th_x');
    expect(error.traceId).toBe('tr_matrix');
  });

  it('只有 detail 字符串时，把它当文案，code 回落为 HTTP_<status>', async () => {
    const error = await grabError(400, 'detail-string');
    expect(error.code).toBe('HTTP_400');
    expect(error.message).toBe('缺少参数 message');
  });

  it('非 JSON 响应不把 HTML 当文案，走通用提示', async () => {
    const error = await grabError(502, 'text');
    expect(error.message).toBe('请求失败（HTTP 502）');
    expect(error.code).toBe('HTTP_502');
  });

  it('空响应体同样给通用提示', async () => {
    const error = await grabError(500, 'empty');
    expect(error.message).toBe('请求失败（HTTP 500）');
  });

  it('没有 error 字段的 JSON 也不会把对象塞进文案', async () => {
    const error = await grabError(404, 'json-without-error');
    expect(error.message).toBe('请求失败（HTTP 404）');
  });
});

describe('5xx / 429：可重试', () => {
  for (const status of SERVER_ERRORS) {
    for (const kind of BODY_KINDS) {
      it(`${status} + ${kind} 标记为可重试`, async () => {
        const error = await grabError(status, kind);
        expect(error.status).toBe(status);
        expect(error.retryable).toBe(true);
      });
    }
  }

  it('429 限流也算可重试', async () => {
    const error = await grabError(429, 'envelope');
    expect(error.retryable).toBe(true);
  });

  it('502 网关错误保留后端给的 code（如果有）', async () => {
    const error = await grabError(502, 'envelope');
    expect(error.code).toBe('NOT_FOUND');
    expect(error.traceId).toBe('tr_matrix');
  });
});

describe('2xx：成功路径', () => {
  it('返回 data 与 trace_id', async () => {
    stubFetch(200, 'envelope');
    const result = await requestWithBase<{ trace_id: string }>('/api/v1', '/health', 'GET');
    expect(result.traceId).toBe('tr_matrix');
    expect(result.data?.trace_id).toBe('tr_matrix');
  });

  it('204 空体不报错，data 为 null', async () => {
    stubFetch(204, 'empty');
    const result = await requestWithBase('/api/v1', '/threads/th_1', 'DELETE');
    expect(result.data).toBeNull();
    expect(result.traceId).toBeNull();
  });

  it('2xx 但 body 不是 JSON 时 data 为 null（不抛错）', async () => {
    stubFetch(200, 'text');
    const result = await requestWithBase('/api/v1', '/preview', 'GET');
    expect(result.data).toBeNull();
  });
});

describe('连通性广播', () => {
  it('拿到 4xx 说明服务活着，广播 online', async () => {
    const seen: string[] = [];
    const off = onBackendStatus((status) => seen.push(status));
    stubFetch(404, 'envelope');
    await expect(requestWithBase('/api/v1', '/threads/x', 'GET')).rejects.toBeInstanceOf(ApiError);
    off();
    expect(seen).toContain('online');
  });

  it('连接失败广播 offline', async () => {
    const seen: string[] = [];
    const off = onBackendStatus((status) => seen.push(status));
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    await expect(requestWithBase('/api/v1', '/threads', 'GET')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      retryable: true,
    });
    off();
    expect(seen).toContain('offline');
  });
});

describe('请求构造', () => {
  it('JSON 请求默认带 Content-Type 与 no-store', async () => {
    const fetchMock = stubFetch(200, 'envelope');
    await requestWithBase('/api/v1', '/threads', 'POST', { body: JSON.stringify({ a: 1 }) });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(init.cache).toBe('no-store');
  });

  it('FormData 请求不设 Content-Type（让浏览器带 boundary）', async () => {
    const fetchMock = stubFetch(200, 'envelope');
    const form = new FormData();
    form.append('file', new Blob(['x']), 'x.txt');
    await requestWithBase('/api/v1', '/files', 'POST', { body: form });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined();
  });

  it('base 与 path 直接拼接，不做二次编码', async () => {
    const fetchMock = stubFetch(200, 'envelope');
    await requestWithBase('/api/v1', '/threads/th_1', 'GET');
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/threads/th_1');
  });
});
