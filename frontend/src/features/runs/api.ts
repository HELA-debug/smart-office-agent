/** 运行、事件回放与审批接口（feature: runs，正式 /api/v1）。 */
import { API_V1_BASE, isMockMode } from '../../shared/config/runtime';
import {
  ApiError,
  encodeId,
  endpointUnavailableMessage,
  isEndpointUnavailable,
  requestV1,
} from '../../shared/lib/api';
import { mockSubmitApproval } from '../../shared/lib/mock-run';
import { parseSseFrame } from '../../shared/lib/sse';
import type {
  ApprovalDecisionOut,
  RunCancelOut,
  RunEnvelope,
  RunEventOut,
  RunEventsOut,
  RunListOut,
  RunOut,
} from '../../shared/api/types';
import type { ApiResponse } from '../../shared/types/api';
import type { ApprovalDecision } from '../../shared/types/events';

export { resumeRunEvents, streamRun } from '../../shared/lib/sse';
export type {
  ResumeRunInput,
  RunStreamHandlers,
  RunStreamInput,
  SseFrame,
  StreamFailure,
} from '../../shared/lib/sse';

export interface RunWithContext extends RunOut {
  /** 会话标题（跨会话展示用，由调用方拼装）。 */
  thread_title?: string;
}

function normalizeRuns(raw: unknown): RunOut[] {
  if (Array.isArray(raw)) return raw as RunOut[];
  if (raw && typeof raw === 'object' && Array.isArray((raw as { runs?: unknown }).runs)) {
    return (raw as { runs: RunOut[] }).runs;
  }
  return [];
}

export interface RetryRunResult {
  run_id: string | null;
}

/**
 * 重试接口返回新的 SSE 流（不是 JSON）：
 * 先读到 run.started 拿到新 run_id，再后台持续消费到流结束（避免连接中断影响后端运行）。
 */
async function startRetryStream(runId: string, signal?: AbortSignal): Promise<string | null> {
  const response = await fetch(`${API_V1_BASE}/runs/${encodeURIComponent(runId)}/retry`, {
    method: 'POST',
    headers: { Accept: 'text/event-stream' },
    signal,
    cache: 'no-store',
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    let message = `重试失败（HTTP ${response.status}）`;
    try {
      const payload = JSON.parse(text) as { error?: { message?: string } };
      message = payload.error?.message ?? message;
    } catch {
      // 非 JSON 错误体
    }
    throw new ApiError(message, {
      code: 'RETRY_FAILED',
      status: response.status,
      retryable: response.status >= 500,
    });
  }

  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('text/event-stream')) {
    const text = await response.text().catch(() => '');
    try {
      const payload = JSON.parse(text) as { run_id?: unknown };
      return typeof payload.run_id === 'string' ? payload.run_id : null;
    } catch {
      return null;
    }
  }
  if (!response.body) return null;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  let resolveStarted: (id: string | null) => void = () => undefined;
  const started = new Promise<string | null>((resolve) => {
    resolveStarted = resolve;
  });

  // 后台持续消费到流结束；首次拿到 run.started 时 resolve
  void (async () => {
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) {
          resolveStarted(null);
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        let index = buffer.indexOf('\n\n');
        while (index >= 0) {
          const raw = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          const frame = parseSseFrame(raw);
          if (frame?.event === 'run.started') {
            try {
              const data = JSON.parse(frame.data) as { run_id?: unknown };
              if (typeof data.run_id === 'string') resolveStarted(data.run_id);
            } catch {
              // 忽略坏帧
            }
          }
          index = buffer.indexOf('\n\n');
        }
      }
    } catch {
      resolveStarted(null);
    }
  })();

  const timeout = new Promise<null>((resolve) => {
    window.setTimeout(() => resolve(null), 5000);
  });
  return Promise.race([started, timeout]);
}

export interface RunListQuery {
  threadId?: string;
  status?: string;
  page?: number;
  pageSize?: number;
}

export const runsApi = {
  /** 全局运行列表（跨会话，支持状态/会话过滤与分页）。 */
  async listRuns(
    query: RunListQuery = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<{ runs: RunOut[]; total: number; page: number; page_size: number }>> {
    if (isMockMode()) {
      return { data: { runs: [], total: 0, page: 1, page_size: 0 }, traceId: null };
    }
    const params = new URLSearchParams();
    if (query.threadId) params.set('thread_id', query.threadId);
    if (query.status) params.set('status', query.status);
    if (query.page) params.set('page', String(query.page));
    if (query.pageSize) params.set('page_size', String(query.pageSize));
    const suffix = params.toString();
    const response = await requestV1<RunListOut>(`/runs${suffix ? `?${suffix}` : ''}`, 'GET', {
      signal,
    });
    return {
      data: {
        runs: response.data.runs ?? [],
        total: response.data.total ?? response.data.runs?.length ?? 0,
        page: response.data.page ?? 1,
        page_size: response.data.page_size ?? 0,
      },
      traceId: response.traceId,
    };
  },

  async listThreadRuns(threadId: string, signal?: AbortSignal): Promise<ApiResponse<RunOut[]>> {
    if (isMockMode()) return { data: [], traceId: null };
    const response = await requestV1<unknown>(`/threads/${encodeId(threadId)}/runs`, 'GET', {
      signal,
    });
    return { data: normalizeRuns(response.data), traceId: response.traceId };
  },

  async getRun(runId: string, signal?: AbortSignal): Promise<ApiResponse<RunEnvelope>> {
    if (isMockMode()) throw new ApiError('mock 模式无运行详情数据', { code: 'MOCK_EMPTY' });
    return requestV1<RunEnvelope>(`/runs/${encodeId(runId)}`, 'GET', { signal });
  },

  /** 事件回放：after 为已收到的最大 seq，用于增量拉取。 */
  async getRunEvents(
    runId: string,
    after = 0,
    signal?: AbortSignal,
  ): Promise<ApiResponse<RunEventOut[]>> {
    if (isMockMode()) return { data: [], traceId: null };
    const response = await requestV1<RunEventsOut>(
      `/runs/${encodeId(runId)}/events?after=${after}`,
      'GET',
      { signal },
    );
    return { data: response.data.events ?? [], traceId: response.traceId };
  },

  /** 取消运行（B3 后端补充中；404 时抛 ENDPOINT_UNAVAILABLE 供 UI 优雅提示）。 */
  async cancelRun(runId: string, signal?: AbortSignal): Promise<ApiResponse<RunCancelOut>> {
    if (isMockMode())
      throw new ApiError(endpointUnavailableMessage('取消运行'), {
        code: 'ENDPOINT_UNAVAILABLE',
        status: 404,
      });
    try {
      return await requestV1<RunCancelOut>(`/runs/${encodeId(runId)}/cancel`, 'POST', { signal });
    } catch (error) {
      if (isEndpointUnavailable(error)) {
        throw new ApiError(endpointUnavailableMessage('取消运行'), {
          code: 'ENDPOINT_UNAVAILABLE',
          status: 404,
          cause: error,
        });
      }
      throw error;
    }
  },

  /** 重试运行（同上，404 优雅提示）。 */
  async retryRun(runId: string, signal?: AbortSignal): Promise<ApiResponse<RetryRunResult>> {
    if (isMockMode()) {
      throw new ApiError(endpointUnavailableMessage('重试运行'), {
        code: 'ENDPOINT_UNAVAILABLE',
        status: 404,
      });
    }
    try {
      const newRunId = await startRetryStream(runId, signal);
      return { data: { run_id: newRunId }, traceId: null };
    } catch (error) {
      if (isEndpointUnavailable(error)) {
        throw new ApiError(endpointUnavailableMessage('重试运行'), {
          code: 'ENDPOINT_UNAVAILABLE',
          status: 404,
          cause: error,
        });
      }
      throw error;
    }
  },

  async submitApproval(
    threadId: string,
    approvalId: string,
    decision: ApprovalDecision,
    comment?: string,
    signal?: AbortSignal,
  ): Promise<ApiResponse<ApprovalDecisionOut>> {
    if (isMockMode()) {
      try {
        const response = mockSubmitApproval(threadId, approvalId, decision, comment);
        return {
          data: {
            trace_id: response.traceId ?? 'mock-trace',
            approval_id: response.data.approval_id,
            decision: response.data.decision,
            decided_at: response.data.decided_at,
            resumed: response.data.resumed,
          },
          traceId: response.traceId,
        };
      } catch {
        throw new ApiError('该审批已处理过', {
          code: 'APPROVAL_ALREADY_DECIDED',
          status: 409,
          traceId: null,
        });
      }
    }
    return requestV1<ApprovalDecisionOut>(
      `/threads/${encodeId(threadId)}/approvals/${encodeId(approvalId)}`,
      'POST',
      {
        signal,
        body: JSON.stringify({ decision, ...(comment ? { comment } : {}) }),
      },
    );
  },
};
