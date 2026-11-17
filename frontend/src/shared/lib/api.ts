/**
 * HTTP 基础设施（shared 层）：baseURL、超时、统一错误、trace_id。
 *
 * 业务接口按 feature 拆分：
 *   features/sessions/api.ts、features/artifacts/api.ts、features/runs/api.ts、
 *   features/audit/api.ts、features/settings/api.ts
 * 组件不直接调用本模块（数据请求只在 hooks / feature api 层）。
 */
import { API_BASE, API_V1_BASE, REQUEST_TIMEOUT_MS } from '../config/runtime';
import { emitBackendStatus } from './backend-status';
import type { ApiResponse } from '../types/api';

export type { ApiResponse } from '../types/api';

/* ------------------------------------------------------------------ */
/* 错误                                                                */
/* ------------------------------------------------------------------ */

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly traceId: string | null;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: {
      code: string;
      status?: number;
      traceId?: string | null;
      retryable?: boolean;
      cause?: unknown;
    },
  ) {
    super(message, { cause: options.cause });
    this.name = 'ApiError';
    this.code = options.code;
    this.status = options.status ?? 0;
    this.traceId = options.traceId ?? null;
    this.retryable = options.retryable ?? false;
  }
}

/** 统一展示文本（错误条/卡片 error 态都用它）。 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.traceId ? `${error.message}（trace: ${error.traceId}）` : error.message;
  }
  if (error instanceof Error) return error.message;
  return '未知错误';
}

/* ------------------------------------------------------------------ */
/* 请求内核                                                            */
/* ------------------------------------------------------------------ */

export interface RequestOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
  body?: BodyInit | null;
  headers?: Record<string, string>;
}

export function extractTraceId(raw: unknown): string | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const trace = (raw as { trace_id?: unknown }).trace_id;
  return typeof trace === 'string' ? trace : null;
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}

export function encodeId(value: string): string {
  return encodeURIComponent(value);
}

export async function requestWithBase<T>(
  base: string,
  path: string,
  method: string,
  options: RequestOptions = {},
): Promise<ApiResponse<T>> {
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const controller = new AbortController();
  let timedOut = false;

  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const onCallerAbort = () => controller.abort();
  options.signal?.addEventListener('abort', onCallerAbort, { once: true });

  try {
    const response = await fetch(`${base}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...options.headers,
      },
      body: options.body,
      signal: controller.signal,
      cache: 'no-store',
    });

    // 能收到响应就说明本机服务活着（4xx/5xx 是业务错误，不是「服务没开」）。
    // 这条广播让「服务断开」提示能自动消失，不需要用户刷新页面。
    emitBackendStatus('online');

    const text = await response.text().catch(() => '');
    let raw: unknown = null;
    if (text) {
      try {
        raw = JSON.parse(text) as unknown;
      } catch {
        raw = null;
      }
    }

    if (!response.ok) {
      const errorBody = raw as {
        error?: { code?: string; message?: string };
        detail?: unknown;
        trace_id?: string;
      } | null;
      const code = errorBody?.error?.code ?? `HTTP_${response.status}`;
      const message =
        errorBody?.error?.message ??
        (typeof errorBody?.detail === 'string' ? errorBody.detail : undefined) ??
        `请求失败（HTTP ${response.status}）`;
      throw new ApiError(message, {
        code,
        status: response.status,
        traceId: errorBody?.trace_id ?? null,
        retryable: response.status >= 500 || response.status === 429,
      });
    }

    return { data: raw as T, traceId: extractTraceId(raw) };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (options.signal?.aborted) {
      throw new ApiError('请求已取消', { code: 'ABORTED', cause: error });
    }
    if (timedOut) {
      throw new ApiError(`请求超时（${Math.round(timeoutMs / 1000)}s）`, {
        code: 'TIMEOUT',
        retryable: true,
        cause: error,
      });
    }
    // 超时不广播：可能只是某个接口慢（长任务），不代表服务没开。
    // 这里只处理 fetch 直接失败——连接被拒最常见的原因就是本地服务被关掉了。
    emitBackendStatus('offline');
    throw new ApiError('无法连接后端（/api 代理未通或服务未启动）', {
      code: 'NETWORK_ERROR',
      retryable: true,
      cause: error,
    });
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', onCallerAbort);
  }
}

/** 旧 /api 兼容路径（不再新增调用，仅迁移期保留）。 */
export function request<T>(
  path: string,
  method: string,
  options: RequestOptions = {},
): Promise<ApiResponse<T>> {
  return requestWithBase<T>(API_BASE, path, method, options);
}

/** 正式 /api/v1 路径（B3 起所有新调用走这里）。 */
export function requestV1<T>(
  path: string,
  method: string,
  options: RequestOptions = {},
): Promise<ApiResponse<T>> {
  return requestWithBase<T>(API_V1_BASE, path, method, options);
}

/** 后端版本较低导致接口不存在（404/405）时的判定，用于优雅降级提示。 */
export function isEndpointUnavailable(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 405);
}

export function endpointUnavailableMessage(feature: string): string {
  return `当前后端版本较低，暂不支持${feature}；后端升级后即可使用`;
}
