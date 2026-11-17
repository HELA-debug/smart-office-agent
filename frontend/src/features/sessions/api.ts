/** 会话接口（feature: sessions，正式 /api/v1）。 */
import { isMockMode } from '../../shared/config/runtime';
import { asRecord, encodeId, requestV1 } from '../../shared/lib/api';
import { mockCreateThread, mockGetThread, mockListThreads } from '../../shared/lib/mock-run';
import type {
  ThreadBulkDeleteOut,
  ThreadCreateOut,
  ThreadDetailEnvelope,
  ThreadListOut,
  ThreadOut,
  ThreadUpdateIn,
} from '../../shared/api/types';
import type { ApiResponse } from '../../shared/types/api';

function normalizeThreadList(raw: unknown): ThreadOut[] {
  if (Array.isArray(raw)) return raw as ThreadOut[];
  const record = asRecord(raw);
  if (!record) return [];
  for (const key of ['threads', 'items', 'data']) {
    const candidate = record[key];
    if (Array.isArray(candidate)) return candidate as ThreadOut[];
  }
  return [];
}

function withPinned(thread: ThreadOut): ThreadOut {
  return { ...thread, pinned: thread.pinned ?? false };
}

export const sessionsApi = {
  /** 会话列表：支持服务端搜索（q）与分页（page/page_size）。 */
  async listThreads(
    options: { q?: string; page?: number; pageSize?: number; signal?: AbortSignal } = {},
  ): Promise<ApiResponse<ThreadListOut>> {
    if (isMockMode()) {
      const response = mockListThreads();
      const threads = response.data.map((thread) =>
        withPinned(thread as ThreadOut),
      ) as unknown as ThreadOut[];
      return {
        data: {
          trace_id: response.traceId ?? '',
          threads,
          total: threads.length,
          page: 1,
          page_size: threads.length,
        },
        traceId: response.traceId,
      };
    }
    const params = new URLSearchParams();
    if (options.q) params.set('q', options.q);
    if (options.page) params.set('page', String(options.page));
    if (options.pageSize) params.set('page_size', String(options.pageSize));
    const suffix = params.toString();
    const response = await requestV1<unknown>(`/threads${suffix ? `?${suffix}` : ''}`, 'GET', {
      signal: options.signal,
    });
    const threads = normalizeThreadList(response.data).map(withPinned);
    const record = asRecord(response.data) ?? {};
    return {
      data: {
        trace_id: response.traceId ?? '',
        threads,
        total: typeof record.total === 'number' ? record.total : threads.length,
        page: typeof record.page === 'number' ? record.page : 1,
        page_size: typeof record.page_size === 'number' ? record.page_size : threads.length,
      },
      traceId: response.traceId,
    };
  },

  async createThread(title?: string, signal?: AbortSignal): Promise<ApiResponse<ThreadCreateOut>> {
    if (isMockMode()) {
      const response = mockCreateThread(title);
      return {
        data: { ...response.data, pinned: false } as unknown as ThreadCreateOut,
        traceId: response.traceId,
      };
    }
    return requestV1<ThreadCreateOut>('/threads', 'POST', {
      signal,
      body: JSON.stringify({ title: title ?? null }),
    });
  },

  async getThread(
    threadId: string,
    signal?: AbortSignal,
  ): Promise<ApiResponse<ThreadDetailEnvelope>> {
    if (isMockMode()) {
      const response = mockGetThread(threadId);
      return {
        data: {
          ...response.data,
          pinned: false,
          trace_id: response.traceId ?? '',
        } as unknown as ThreadDetailEnvelope,
        traceId: response.traceId,
      };
    }
    return requestV1<ThreadDetailEnvelope>(`/threads/${encodeId(threadId)}`, 'GET', { signal });
  },

  /** 重命名 / 置顶（PATCH，字段可选）。 */
  async updateThread(
    threadId: string,
    patch: ThreadUpdateIn,
    signal?: AbortSignal,
  ): Promise<ApiResponse<ThreadCreateOut>> {
    if (isMockMode()) {
      const response = mockGetThread(threadId);
      return {
        data: {
          ...response.data,
          title: patch.title ?? response.data.title,
          pinned: patch.pinned ?? false,
          trace_id: response.traceId ?? '',
        } as unknown as ThreadCreateOut,
        traceId: response.traceId,
      };
    }
    return requestV1<ThreadCreateOut>(`/threads/${encodeId(threadId)}`, 'PATCH', {
      signal,
      body: JSON.stringify(patch),
    });
  },

  /** 软删会话。 */
  async deleteThread(threadId: string, signal?: AbortSignal): Promise<void> {
    if (isMockMode()) return;
    await requestV1<null>(`/threads/${encodeId(threadId)}`, 'DELETE', { signal });
  },

  /**
   * 重排会话顺序（左栏拖动）。
   *
   * 传的是**整份**顺序而不只是「我拖的这一条」：后端按数组下标重写 sort_index，
   * 这样翻页、置顶、删会话都不会让顺序错位；只传一条就得在服务端猜前后关系。
   */
  async reorderThreads(threadIds: string[], signal?: AbortSignal): Promise<void> {
    if (threadIds.length === 0 || isMockMode()) return;
    await requestV1<{ trace_id: string; reordered: number }>('/threads/reorder', 'POST', {
      signal,
      body: JSON.stringify({ thread_ids: threadIds }),
    });
  },

  /**
   * 批量软删（左栏「批量清理」）：一次请求删一批。
   * 逐个 DELETE 要发 N 次，中途失败还会留下一半已删一半没删的状态；
   * 后端按 ID 集合做一条 UPDATE，返回真正删掉的条数（不存在的 ID 不计）。
   */
  async bulkDeleteThreads(
    threadIds: string[],
    signal?: AbortSignal,
  ): Promise<ApiResponse<ThreadBulkDeleteOut>> {
    if (threadIds.length === 0) return { data: { trace_id: '', deleted: 0 }, traceId: null };
    if (isMockMode()) {
      return { data: { trace_id: '', deleted: threadIds.length }, traceId: null };
    }
    return requestV1<ThreadBulkDeleteOut>('/threads/bulk-delete', 'POST', {
      signal,
      body: JSON.stringify({ thread_ids: threadIds }),
    });
  },
};
