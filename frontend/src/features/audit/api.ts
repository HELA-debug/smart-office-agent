/** 审计与用量接口（feature: audit，正式 /api/v1）。 */
import { isMockMode } from '../../shared/config/runtime';
import { encodeId, requestV1 } from '../../shared/lib/api';
import { mockGetAudit } from '../../shared/lib/mock-run';
import type { AuditOut, UsageOut } from '../../shared/api/types';
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
          calls: 5,
          tokens: 8123,
          cost_cny: 0.06,
          cache_hit_tokens: 0,
          cache_miss_tokens: 8123,
          // 演示数据也把账本填上：否则「账本不可用」这种异常态会出现在演示里
          ledger: {
            calls: 7,
            failed_calls: 1,
            tokens: 8123,
            input_tokens: 6000,
            output_tokens: 2123,
            cache_hit_tokens: 0,
            cache_miss_tokens: 6000,
            cost_cny: 0.06,
            since: new Date().toISOString(),
            by_purpose: [
              { purpose: 'engine', calls: 4, failed_calls: 0, tokens: 6000, cost_cny: 0.045 },
              { purpose: 'reading', calls: 2, failed_calls: 0, tokens: 2123, cost_cny: 0.015 },
              { purpose: 'probe', calls: 1, failed_calls: 1, tokens: 0, cost_cny: 0 },
            ],
            by_provider: [
              { provider: 'deepseek', calls: 7, failed_calls: 1, tokens: 8123, cost_cny: 0.06 },
            ],
            by_day: [
              {
                date: new Date().toISOString().slice(0, 10),
                calls: 7,
                failed_calls: 1,
                tokens: 8123,
                cost_cny: 0.06,
              },
            ],
          },
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
};
