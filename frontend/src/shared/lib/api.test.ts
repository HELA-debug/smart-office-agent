/**
 * HTTP 基础设施单测：错误映射、超时/取消、FormData、路径前缀、降级判定。
 *
 * 这一层是所有 feature api 的公共底座，出问题会表现为「所有页面一起报错」，
 * 因此按契约逐条断言，不依赖真实后端。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  asRecord,
  encodeId,
  endpointUnavailableMessage,
  errorMessage,
  extractTraceId,
  isEndpointUnavailable,
  request,
  requestV1,
  requestWithBase,
} from './api';
import { onBackendStatus } from './backend-status';

/* ------------------------------------------------------------------ */
/* 工具                                                                */
/* ------------------------------------------------------------------ */

interface FetchInitLike {
  method?: string;
  headers?: Record<string, string>;
  body?: BodyInit | null;
  signal?: AbortSignal;
  cache?: string;
}

/** 构造一个最小 Response，只提供被测代码用到的 text() / ok / status。 */
function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function textResponse(status: number, text: string): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => text,
  } as unknown as Response;
}

/** 永不 resolve、但会在 signal abort 时 reject 的 fetch（模拟超时被中断）。 */
function hangingFetch(_url: string, init: FetchInitLike): Promise<Response> {
  return new Promise((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => {
      reject(new DOMException('The operation was aborted.', 'AbortError'));
    });
  });
}

type FetchCall = [string, FetchInitLike];

/** 取最近一次 fetch 调用（项目开启了 noUncheckedIndexedAccess，需非空断言）。 */
function lastFetchCall(): FetchCall {
  const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  const calls = fetchMock.mock.calls as FetchCall[];
  const call = calls[calls.length - 1];
  if (!call) throw new Error('还没有发生任何 fetch 调用');
  return call;
}

function lastFetchInit(): FetchInitLike {
  return lastFetchCall()[1];
}

function lastFetchUrl(): string {
  return lastFetchCall()[0];
}

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/* ------------------------------------------------------------------ */
/* 纯函数                                                              */
/* ------------------------------------------------------------------ */

describe('ApiError / errorMessage', () => {
  it('默认 status=0、traceId=null、retryable=false', () => {
    const error = new ApiError('boom', { code: 'X' });
    expect(error.name).toBe('ApiError');
    expect(error.status).toBe(0);
    expect(error.traceId).toBeNull();
    expect(error.retryable).toBe(false);
  });

  it('errorMessage 带 trace_id 时追加（trace: xxx）', () => {
    expect(errorMessage(new ApiError('失败', { code: 'X', traceId: 't-1' }))).toBe(
      '失败（trace: t-1）',
    );
  });

  it('errorMessage 无 trace_id 时只返回 message', () => {
    expect(errorMessage(new ApiError('失败', { code: 'X' }))).toBe('失败');
  });

  it('errorMessage 透传普通 Error，其他值兜底为「未知错误」', () => {
    expect(errorMessage(new TypeError('类型错误'))).toBe('类型错误');
    expect(errorMessage('字符串错误')).toBe('未知错误');
    expect(errorMessage(undefined)).toBe('未知错误');
  });
});

describe('extractTraceId / asRecord / encodeId', () => {
  it('extractTraceId 只读字符串 trace_id', () => {
    expect(extractTraceId({ trace_id: 'abc' })).toBe('abc');
    expect(extractTraceId({ trace_id: 123 })).toBeNull();
    expect(extractTraceId({})).toBeNull();
    expect(extractTraceId(null)).toBeNull();
    expect(extractTraceId('abc')).toBeNull();
  });

  it('asRecord 区分对象与原始值，数组仍算对象（由调用方自行收窄）', () => {
    expect(asRecord({ a: 1 })).toEqual({ a: 1 });
    expect(asRecord(null)).toBeNull();
    expect(asRecord(undefined)).toBeNull();
    expect(asRecord(7)).toBeNull();
  });

  it('encodeId 转义路径中的特殊字符', () => {
    expect(encodeId('a/b')).toBe('a%2Fb');
    expect(encodeId('a b&c')).toBe('a%20b%26c');
    expect(encodeId('普通')).toBe('%E6%99%AE%E9%80%9A');
  });
});

/* ------------------------------------------------------------------ */
/* 请求内核                                                            */
/* ------------------------------------------------------------------ */

describe('requestWithBase 成功路径', () => {
  it('解析 JSON 并取出 trace_id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, { data: { ok: true }, trace_id: 'tr-1' })),
    );
    const result = await requestWithBase<{ ok: boolean }>('/api/v1', '/models', 'GET');
    // 内核不拆信封，整段 JSON 作为 data 返回，解包由 feature api 层负责
    expect(result.data).toEqual({ data: { ok: true }, trace_id: 'tr-1' });
    expect(result.traceId).toBe('tr-1');
    expect(lastFetchUrl()).toBe('/api/v1/models');
  });

  it('默认带 Accept 与 Content-Type，并合并自定义 headers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, {})),
    );
    await requestWithBase('/api/v1', '/x', 'POST', {
      body: JSON.stringify({ a: 1 }),
      headers: { 'X-Trace': 'keep' },
    });
    const init = lastFetchInit();
    expect(init.headers?.Accept).toBe('application/json');
    expect(init.headers?.['Content-Type']).toBe('application/json');
    expect(init.headers?.['X-Trace']).toBe('keep');
  });

  it('FormData 不设置 Content-Type（交给浏览器带 boundary）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, {})),
    );
    const form = new FormData();
    form.append('file', new Blob(['x']), 'a.txt');
    await requestWithBase('/api/v1', '/uploads', 'POST', { body: form });
    expect(lastFetchInit().headers?.['Content-Type']).toBeUndefined();
  });

  it('响应体为空时 data 为 null，不抛错', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => textResponse(204, '')),
    );
    const result = await requestWithBase('/api/v1', '/x', 'DELETE');
    expect(result.data).toBeNull();
    expect(result.traceId).toBeNull();
  });

  it('响应体非 JSON 时降级为 null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => textResponse(200, 'not-json')),
    );
    const result = await requestWithBase('/api/v1', '/x', 'GET');
    expect(result.data).toBeNull();
  });
});

describe('requestWithBase 错误路径', () => {
  it('标准错误体：取 error.code / error.message / trace_id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(400, {
          error: { code: 'INVALID_ARGUMENT', message: '参数不对' },
          trace_id: 't-9',
        }),
      ),
    );
    await expect(requestWithBase('/api/v1', '/x', 'POST')).rejects.toMatchObject({
      name: 'ApiError',
      code: 'INVALID_ARGUMENT',
      status: 400,
      traceId: 't-9',
      retryable: false,
    });
  });

  it('FastAPI 风格 detail 字符串作为消息兜底', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(422, { detail: '字段缺失' })),
    );
    await expect(requestWithBase('/api/v1', '/x', 'POST')).rejects.toMatchObject({
      code: 'HTTP_422',
      message: '字段缺失',
      retryable: false,
    });
  });

  it('无任何错误体时用 HTTP 状态码兜底', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => textResponse(500, '')),
    );
    await expect(requestWithBase('/api/v1', '/x', 'GET')).rejects.toMatchObject({
      code: 'HTTP_500',
      message: '请求失败（HTTP 500）',
      retryable: true,
    });
  });

  it('429 与 5xx 标记为可重试，4xx 不可重试', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => textResponse(429, '')),
    );
    await expect(requestWithBase('/api/v1', '/x', 'GET')).rejects.toMatchObject({
      status: 429,
      retryable: true,
    });
  });

  it('网络异常（fetch reject）映射为 NETWORK_ERROR', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    await expect(requestWithBase('/api/v1', '/x', 'GET')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      retryable: true,
      message: '无法连接后端（/api 代理未通或服务未启动）',
    });
  });

  it('调用方主动取消映射为 ABORTED', async () => {
    const controller = new AbortController();
    vi.stubGlobal('fetch', vi.fn(hangingFetch));
    const promise = requestWithBase('/api/v1', '/x', 'GET', { signal: controller.signal });
    // 先挂上断言再触发，避免 rejection 在断言前无人接管
    const assertion = expect(promise).rejects.toMatchObject({
      code: 'ABORTED',
      message: '请求已取消',
    });
    controller.abort();
    await assertion;
  });

  it('超时按秒提示，且标记为可重试', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(hangingFetch));
    const promise = requestWithBase('/api/v1', '/slow', 'GET', { timeoutMs: 3000 });
    const assertion = expect(promise).rejects.toMatchObject({
      code: 'TIMEOUT',
      retryable: true,
      message: '请求超时（3s）',
    });
    await vi.advanceTimersByTimeAsync(3000);
    await assertion;
  });

  it('成功后清理定时器（不留下悬挂 timer）', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, {})),
    );
    await requestWithBase('/api/v1', '/x', 'GET', { timeoutMs: 1000 });
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('request / requestV1 前缀', () => {
  it('request 走旧 /api，requestV1 走 /api/v1', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, {})),
    );
    await request('/x', 'GET');
    expect(lastFetchUrl()).toBe('/api/x');
    await requestV1('/y', 'GET');
    expect(lastFetchUrl()).toBe('/api/v1/y');
  });
});

describe('后端版本降级判定', () => {
  it('404/405 视为接口不存在', () => {
    expect(isEndpointUnavailable(new ApiError('x', { code: 'HTTP_404', status: 404 }))).toBe(true);
    expect(isEndpointUnavailable(new ApiError('x', { code: 'HTTP_405', status: 405 }))).toBe(true);
    expect(isEndpointUnavailable(new ApiError('x', { code: 'HTTP_500', status: 500 }))).toBe(false);
    expect(isEndpointUnavailable(new Error('x'))).toBe(false);
  });

  it('降级提示文案带特性名', () => {
    expect(endpointUnavailableMessage('用量统计')).toContain('用量统计');
  });
});

/* ------------------------------------------------------------------ */

describe('本机服务在线/离线广播', () => {
  it('收到响应就算在线——500 是业务错误，不等于服务没开', async () => {
    const seen: string[] = [];
    const off = onBackendStatus((status) => seen.push(status));
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(500, { error: { code: 'BOOM', message: '炸了' } })),
    );

    await expect(requestV1('/x', 'GET')).rejects.toBeInstanceOf(ApiError);
    off();
    expect(seen).toEqual(['online']);
  });

  it('连不上本地服务（fetch 直接失败）广播离线', async () => {
    const seen: string[] = [];
    const off = onBackendStatus((status) => seen.push(status));
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );

    await expect(requestV1('/x', 'GET')).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
    off();
    expect(seen).toEqual(['offline']);
  });

  it('超时不广播离线：可能只是接口慢，不能误报「服务没开」', async () => {
    const seen: string[] = [];
    const off = onBackendStatus((status) => seen.push(status));
    vi.stubGlobal('fetch', vi.fn(hangingFetch));

    await expect(requestV1('/x', 'GET', { timeoutMs: 10 })).rejects.toMatchObject({
      code: 'TIMEOUT',
    });
    off();
    expect(seen).toEqual([]);
  });

  it('主动取消也不广播离线', async () => {
    const seen: string[] = [];
    const off = onBackendStatus((status) => seen.push(status));
    vi.stubGlobal('fetch', vi.fn(hangingFetch));
    const controller = new AbortController();

    const pending = requestV1('/x', 'GET', { signal: controller.signal, timeoutMs: 5000 });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ code: 'ABORTED' });
    off();
    expect(seen).toEqual([]);
  });
});
