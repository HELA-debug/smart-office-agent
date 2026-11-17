/**
 * 待确认操作：Agent 要动「对外 / 不可逆」的动作时，停下来等用户点一下。
 *
 * 状态机早就有这条路——`approval.required` 事件把审批收进 `state.approvals`，
 * `run.status` 也会转成 `waiting_approval`，`controller.submitApproval` 也接好了；
 * 缺的就是这块界面。没有它，运行停在等审批上，用户只看到输入框变灰、不知道在等什么，
 * 也点不了「允许」——一条跑到一半的活就那么悬着。
 *
 * 排布按「先看要干什么，再看影响，最后才给按钮」：把允许按钮和预览信息贴在一起，
 * 避免用户还没看清就顺手点了允许。
 */
import {
  IconAlertTriangle,
  IconCheck,
  IconShield,
  IconSpinner,
  IconX,
} from '../../../shared/ui/Icons';
import type { ApprovalDecision, ApprovalPreview } from '../../../shared/types/events';
import type { ApprovalItem } from '../../../shared/types/view';
import type { RefObject } from 'react';

const RISK_LABELS: Record<string, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
};

/** 预览里认识的字段；其余字段按原样列，值不是字符串就跳过（嵌套结构列不明白）。 */
const PREVIEW_LABELS: Record<string, string> = {
  to: '收件人',
  subject: '主题',
  body_preview: '正文预览',
  impact: '影响范围',
};

function previewRows(preview: ApprovalPreview): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(preview ?? {})) {
    if (typeof value !== 'string' || !value.trim()) continue;
    rows.push([PREVIEW_LABELS[key] ?? key, value.trim()]);
  }
  return rows;
}

function PendingCard({
  approval,
  onSubmit,
}: {
  approval: ApprovalItem;
  onSubmit: (approvalId: string, decision: ApprovalDecision) => void;
}) {
  const rows = previewRows(approval.preview);
  return (
    <article className="rounded-card border border-warn-line bg-warn-soft p-3">
      <header className="flex flex-wrap items-center gap-1.5">
        <IconShield size={13} className="shrink-0 text-warn" />
        <span className="text-mini font-semibold text-ink">需要你确认</span>
        <span className="rounded-chip bg-surface px-1.5 py-px text-[calc(10px*var(--font-scale))] font-medium text-warn">
          {RISK_LABELS[approval.risk] ?? approval.risk}
        </span>
        <span className="ml-auto font-mono text-caption text-faint">{approval.tool}</span>
      </header>

      <p className="mt-1.5 text-caption leading-relaxed text-ink">{approval.message}</p>

      {rows.length > 0 ? (
        <dl className="mt-2 space-y-0.5 rounded-control bg-surface px-2.5 py-2">
          {rows.map(([label, value]) => (
            <div key={label} className="flex gap-2 text-caption">
              <dt className="shrink-0 text-muted">{label}</dt>
              <dd className="min-w-0 flex-1 break-words text-ink-soft">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {approval.error ? (
        <p className="mt-2 flex items-center gap-1 text-caption text-danger">
          <IconAlertTriangle size={11} className="shrink-0" />
          {approval.error}
        </p>
      ) : null}

      <div className="mt-2.5 flex items-center gap-2">
        <button
          type="button"
          disabled={approval.submitting}
          onClick={() => onSubmit(approval.approval_id, 'approved')}
          className="inline-flex items-center gap-1 rounded-control bg-brand px-2.5 py-1 text-caption font-medium text-white transition-colors hover:bg-brand-strong disabled:opacity-60"
        >
          {approval.submitting ? <IconSpinner size={11} /> : <IconCheck size={11} />}
          允许
        </button>
        <button
          type="button"
          disabled={approval.submitting}
          onClick={() => onSubmit(approval.approval_id, 'rejected')}
          className="inline-flex items-center gap-1 rounded-control border border-line-strong px-2.5 py-1 text-caption text-muted transition-colors hover:bg-surface-hover hover:text-ink disabled:opacity-60"
        >
          <IconX size={11} />
          拒绝
        </button>
        <span className="text-caption text-faint">拒绝后这一步会跳过，整件事接着往下做</span>
      </div>
    </article>
  );
}

function SettledRow({ approval }: { approval: ApprovalItem }) {
  const approved = approval.decision === 'approved';
  return (
    <div className="flex items-center gap-1.5 px-1 text-caption">
      {approved ? (
        <IconCheck size={11} className="shrink-0 text-ok" />
      ) : (
        <IconX size={11} className="shrink-0 text-faint" />
      )}
      <span className="min-w-0 flex-1 truncate text-muted">
        {approved ? '已允许' : '已拒绝'} · {approval.tool}
        <span className="text-faint"> · {approval.message}</span>
      </span>
    </div>
  );
}

export function ApprovalPanel({
  approvals,
  onSubmit,
  panelRef,
}: {
  approvals: ApprovalItem[];
  onSubmit: (approvalId: string, decision: ApprovalDecision) => void;
  /** 输入区那条提示要能滚到这里（「去确认」按钮）。 */
  panelRef?: RefObject<HTMLDivElement | null>;
}) {
  if (approvals.length === 0) return null;
  const pending = approvals.filter((item) => item.decision === null);
  const settled = approvals.filter((item) => item.decision !== null);

  return (
    <div ref={panelRef} className="mb-2 space-y-1.5">
      {pending.map((approval) => (
        <PendingCard key={approval.approval_id} approval={approval} onSubmit={onSubmit} />
      ))}
      {settled.length > 0 ? (
        <div className="space-y-0.5">
          {settled.map((approval) => (
            <SettledRow key={approval.approval_id} approval={approval} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
