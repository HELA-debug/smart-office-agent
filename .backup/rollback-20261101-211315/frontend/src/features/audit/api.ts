/** 审计与用量接口（feature: audit，正式 /api/v1）。 */
import { isMockMode } from '../../shared/config/runtime';
import { encodeId, requestV1 } from '../../shared/lib/api';
import { mockGetAudit } from '../../shared/lib/mock-run';
import type { AuditOut, ProviderTokenOut, ProviderUsageOut, UsageOut } from '../../shared/api/types';
import type { ApiResponse } from '../../shared/types/api';

export const auditApi = {
  async getAudit(threadId: string, signal?: AbortSignal): Promise<ApiResponse<AuditOut>> {
    if (isMockMode()) {
      const response = mockGetAudit(threadId);
      return {
        data: {
          trace_id: response.traceId ?? '',
          thread_id: response.data.thread_id,
          thread_title: '演示会话',
          runs: (response.data.runs ?? []).map((run) => ({
            run_id: run.run_id,
            started_at: run.started_at ?? '',
            finished_at: run.finished_at ?? null,
            status: run.status ?? 'completed',
            mode: 'mock',
            engine: 'mock',
            provider: 'mock',
            model: 'mock-scripted',
            tokens: run.tokens ?? 0,
            cost_cny: run.cost_cny ?? 0,
            elapsed_ms: run.elapsed_ms ?? 0,
            error_code: null,
            degraded: false,
            request_ids: [],
            calls: 0,
            verified_calls: 0,
            approvals: run.approvals ?? [],
            artifacts: run.artifacts ?? [],
          })),
          approvals: [],
          artifacts: [],
        },
        traceId: response.traceId,
      };
    }
    return requestV1<AuditOut>(`/threads/${encodeId(threadId)}/audit`, 'GET', { signal });
  },

  async getUsageSummary(
    options: { threadId?: string; limit?: number; range?: string } = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<UsageOut>> {
    if (isMockMode()) {
      return {
        data: {
          trace_id: 'mock-trace',
          thread_id: options.threadId ?? null,
          range: 'all',
          runs: 1,
          real_runs: 1,
          mock_runs: 0,
          api_calls: 5,
          tokens: 8123,
          cost_cny: 0.06,
          cache_hit_tokens: 0,
          cache_miss_tokens: 8123,
          cancelled_runs: 0,
          cancelled_tokens: 0,
          cancelled_cost_cny: 0,
          price_note: '按官方价估算（示例数据）',
          elapsed_ms: 41_700,
          avg_elapsed_ms: 41_700,
          by_status: { completed: 1 },
          by_day: [
            {
              date: new Date().toISOString().slice(0, 10),
              runs: 1,
              tokens: 8123,
              cost_cny: 0.06,
              elapsed_ms: 41_700,
              calls: 5,
              mock_runs: 0,
            },
          ],
        },
        traceId: 'mock-trace',
      };
    }
    const params = new URLSearchParams();
    if (options.threadId) params.set('thread_id', options.threadId);
    if (options.limit) params.set('limit', String(options.limit));
    if (options.range) params.set('range', options.range);
    const query = params.toString();
    return requestV1<UsageOut>(`/usage/summary${query ? `?${query}` : ''}`, 'GET', { signal });
  },

  /** 审计导出由后端生成（CSV 带 BOM / JSON），返回可直接下载的 URL。 */
  exportUrl(format: 'json' | 'csv', threadId?: string): string {
    const params = new URLSearchParams({ format });
    if (threadId) params.set('thread_id', threadId);
    return `/api/v1/audit/export?${params.toString()}`;
  },

  /**
   * 官方控制台用量。
   *
   * 走的是平台网页端的私有接口，鉴权要浏览器登录态 token（不是 API Key）。
   * 后端取不到时一律回 200 + available=false，所以这里不会抛异常，
   * 调用方看 available 决定显示官方数据还是只显示本地账本。
   */
  async getProviderUsage(
    options: { provider?: string; force?: boolean } = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<ProviderUsageOut>> {
    const params = new URLSearchParams();
    if (options.provider) params.set('provider', options.provider);
    if (options.force) params.set('force', 'true');
    const query = params.toString();
    return requestV1<ProviderUsageOut>(
      `/usage/provider${query ? `?${query}` : ''}`,
      'GET',
      { signal },
    );
  },

  /**
   * 设置官方用量 token（只存后端进程内存，重启即失效）。
   * 用 PUT 而不是 GET：token 不该出现在 URL 里，否则会进访问日志。
   */
  async setProviderToken(
    token: string,
    provider = 'deepseek',
  ): Promise<ApiResponse<ProviderTokenOut>> {
    return requestV1<ProviderTokenOut>('/usage/provider/token', 'PUT', {
      body: JSON.stringify({ provider, token }),
    });
  },

  async clearProviderToken(provider = 'deepseek'): Promise<ApiResponse<ProviderTokenOut>> {
    return requestV1<ProviderTokenOut>(
      `/usage/provider/token?provider=${encodeURIComponent(provider)}`,
      'DELETE',
    );
  },
};
