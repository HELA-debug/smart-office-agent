import { useEffect } from 'react';
import {
  formatCost,
  formatDateTime,
  formatDuration,
  formatNumber,
} from '../../../shared/lib/format';
import { IconDownload, IconRefresh, IconX } from '../../../shared/ui/Icons';
import {
  Badge,
  Button,
  Card,
  CardEmpty,
  CardError,
  IconButton,
} from '../../../shared/ui/primitives';
import type { AuditViewState } from '../../../shared/types/view';

function AuditRunRow({
  run,
  traceId,
}: {
  run: NonNullable<AuditViewState['data']>['runs'][number];
  traceId?: string;
}) {
  const status = run.status ?? 'unknown';
  const approvals = (run.approvals ?? []) as Array<{
    approval_id?: string;
    tool?: string;
    decision?: string;
    decided_at?: string;
  }>;
  const artifacts = (run.artifacts ?? []) as Array<{ artifact_id?: string; filename?: string }>;
  const tone = status === 'completed' ? 'ok' : status === 'rejected' ? 'warn' : 'neutral';
  // 供应商回执：请求 id 能拿去控制台对账，是「这轮真调了模型」最硬的证据
  const requestIds = run.request_ids ?? [];
  const calls = run.calls ?? 0;
  const verified = run.verified_calls ?? 0;
  const isReal = (run.mode ?? '') === 'real';
  // 配置名与官方回执名不一致很常见（deepseek-chat 会被路由到 deepseek-flash），
  // 控制台按回执名归账单，不写出来用户会以为压根没调。
  const servedAs = run.provider_model && run.provider_model !== run.model ? run.provider_model : '';

  return (
    <Card className="p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={tone}>
          {status === 'completed' ? '已完成' : status === 'rejected' ? '已拒绝' : status}
        </Badge>
        <span className="font-mono text-caption text-muted">{run.run_id}</span>
        {run.started_at ? (
          <span className="text-caption text-faint">{formatDateTime(run.started_at)}</span>
        ) : null}
        {traceId ? (
          <span className="ml-auto font-mono text-caption text-faint">trace: {traceId}</span>
        ) : null}
      </div>

      <div className="mt-2 grid grid-cols-3 gap-2 text-caption">
        <div>
          <span className="text-faint">tokens </span>
          <span className="font-medium text-ink-soft">{formatNumber(run.tokens)}</span>
        </div>
        <div>
          <span className="text-faint">成本 </span>
          <span className="font-medium text-ink-soft">{formatCost(run.cost_cny)}</span>
        </div>
        <div>
          <span className="text-faint">耗时 </span>
          <span className="font-medium text-ink-soft">{formatDuration(run.elapsed_ms)}</span>
        </div>
      </div>

      {servedAs ? (
        <div className="mt-1.5 text-caption text-faint">
          官方按 <span className="font-mono text-ink-soft">{servedAs}</span>{' '}
          计费（控制台账单归类以此为准）
        </div>
      ) : null}

      {isReal ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-1 text-caption">
          <span className="text-faint">请求 id</span>
          {requestIds.length > 0 ? (
            requestIds.map((id) => (
              <span
                key={id}
                title={id}
                className="rounded-chip bg-surface-sunken px-1 py-px font-mono text-[calc(10px*var(--font-scale))] text-ink-soft"
              >
                {id.length > 8 ? `${id.slice(0, 8)}…` : id}
              </span>
            ))
          ) : (
            <span className="text-warn">这次没拿到回执（未真正打到官方接口？）</span>
          )}
          {calls > 0 ? (
            <span className={verified >= calls ? 'text-ok' : 'text-warn'}>
              {verified}/{calls} 次带回执
            </span>
          ) : null}
        </div>
      ) : (
        <div className="mt-1.5 text-caption text-faint">本地 mock 运行：不调用外部模型</div>
      )}

      {approvals.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {approvals.map((approval) => (
            <span
              key={approval.approval_id ?? approval.tool}
              className="inline-flex items-center gap-1 rounded-chip border border-line bg-surface-soft px-1.5 py-[1px] text-caption text-muted"
            >
              <span className="font-mono">{approval.tool}</span>
              <span className={approval.decision === 'approved' ? 'text-ok' : 'text-danger'}>
                {approval.decision === 'approved' ? '已批准' : '已拒绝'}
              </span>
              {approval.decided_at ? (
                <span className="text-faint">{formatDateTime(approval.decided_at)}</span>
              ) : null}
            </span>
          ))}
        </div>
      ) : null}

      {artifacts.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {artifacts.map((artifact) => (
            <span
              key={artifact.artifact_id ?? artifact.filename}
              className="inline-flex items-center gap-1 rounded-chip border border-line bg-surface-soft px-1.5 py-[1px] text-caption text-ink-soft"
            >
              <IconDownload size={10} />
              {artifact.filename ?? artifact.artifact_id}
            </span>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

export function AuditDrawer({
  audit,
  onClose,
  onRetry,
}: {
  audit: AuditViewState;
  onClose: () => void;
  onRetry: () => void;
}) {
  useEffect(() => {
    if (!audit.open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [audit.open, onClose]);

  if (!audit.open) return null;

  const runs = audit.data?.runs ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ paddingTop: 'calc(var(--titlebar-h, 0px) + 1rem)' }}
      role="dialog"
      aria-modal
    >
      <button
        type="button"
        aria-label="关闭审计"
        className="absolute inset-0 cursor-default bg-[#101828]/40 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <div className="relative flex max-h-[82vh] w-full max-w-[680px] flex-col overflow-hidden rounded-card border border-line bg-surface shadow-pop">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
          <span className="text-regular font-semibold text-ink">审计记录</span>
          <span className="text-caption text-faint">GET /api/threads/:id/audit</span>
          {audit.data?.trace_id ? (
            <span className="ml-1 font-mono text-caption text-faint">
              trace: {audit.data.trace_id}
            </span>
          ) : null}
          <IconButton label="关闭" wrapperClassName="ml-auto" onClick={onClose}>
            <IconX size={16} />
          </IconButton>
        </div>

        <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-4">
          {audit.status === 'loading' ? (
            <div className="flex items-center gap-2 py-8 text-mini text-muted">
              <IconRefresh size={14} className="animate-spin" />
              正在读取审计数据…
            </div>
          ) : audit.status === 'error' ? (
            <CardError message={audit.error ?? '审计数据读取失败'} onRetry={onRetry} />
          ) : runs.length === 0 ? (
            <CardEmpty
              label="本次会话还没有运行记录"
              hint="完成一次任务后自动记录运行摘要、耗用与产物"
            />
          ) : (
            runs.map((run) => (
              <AuditRunRow key={run.run_id} run={run} traceId={audit.data?.trace_id} />
            ))
          )}
        </div>

        <div className="flex shrink-0 items-center justify-between border-t border-line px-4 py-2.5">
          <span className="text-caption text-faint">审计包含运行摘要、耗用明细与产物清单</span>
          <Button variant="secondary" size="sm" onClick={onClose}>
            关闭
          </Button>
        </div>
      </div>
    </div>
  );
}
