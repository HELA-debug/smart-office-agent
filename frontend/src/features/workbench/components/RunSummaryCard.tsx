import { formatCost, formatNumber } from '../../../shared/lib/format';
import { IconCheckCircle, IconChevronRight, IconX } from '../../../shared/ui/Icons';
import type { UsageSummary } from '../state/workbench';

/**
 * 一次运行结束后的收尾：一行说明白就行。
 * 「成了没、出了几个文件、花了多少」——不再摆 tokens / 耗时 / 成本三栏仪表盘。
 */
export function RunSummaryCard({
  usage,
  artifactCount,
  model,
  auditEnabled,
  onOpenAudit,
}: {
  usage: UsageSummary;
  artifactCount: number;
  model?: string | null;
  auditEnabled: boolean;
  onOpenAudit: () => void;
}) {
  const rejected = usage.status === 'rejected';
  const count = artifactCount || usage.artifact_ids.length;

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1.5 py-1.5 text-mini">
      {rejected ? (
        <IconX size={13} className="shrink-0 text-warn" />
      ) : (
        <IconCheckCircle size={13} className="shrink-0 text-ok" />
      )}
      <span className={`font-medium ${rejected ? 'text-warn' : 'text-ok'}`}>
        {rejected ? '运行结束（审批被拒绝，产物已保留）' : '运行完成'}
      </span>
      <span className="text-line-strong">·</span>
      <span className="text-muted">产物 {count} 个</span>
      {usage.tokens > 0 ? (
        <>
          <span className="text-line-strong">·</span>
          <span className="text-faint">共消耗 {formatNumber(usage.tokens)} tokens</span>
        </>
      ) : null}
      {usage.cost_cny > 0 ? (
        <>
          <span className="text-line-strong">·</span>
          <span className="text-faint">{formatCost(usage.cost_cny)}</span>
        </>
      ) : null}
      {model ? (
        <span className="max-w-[12rem] truncate rounded-full bg-surface-sunken px-1.5 text-caption text-muted">
          {model.includes('mock') ? '演示模型' : model}
        </span>
      ) : null}
      {auditEnabled ? (
        <button
          type="button"
          onClick={onOpenAudit}
          className="ml-auto inline-flex shrink-0 items-center gap-0.5 rounded-control px-1 text-caption text-faint transition-colors hover:text-ink"
        >
          查看审计记录
          <IconChevronRight size={11} />
        </button>
      ) : null}
    </div>
  );
}
