import { IconBot, IconCheck, IconSpinner, IconX } from '../../../shared/ui/Icons';
import { CardError, CardLoading } from '../../../shared/ui/primitives';
import type { SubagentItem } from '../../../shared/types/view';

/** 子智能体：一行流水（谁在跑、跑到哪），不再单独占一张渐变卡片。 */
export function SubagentCard({
  subagent,
  loading = false,
  error = null,
}: {
  subagent: SubagentItem | null;
  loading?: boolean;
  error?: string | null;
}) {
  if (loading) {
    return (
      <div className="rounded-control border border-line bg-surface px-2.5 py-2">
        <CardLoading label="子智能体启动中…" rows={1} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-control border border-danger-line bg-surface px-2.5 py-2">
        <CardError message={error} />
      </div>
    );
  }

  if (!subagent) {
    return <div className="px-2.5 py-1.5 text-mini text-faint">暂无子智能体</div>;
  }

  const status = {
    running: { label: '运行中', className: 'text-brand' },
    done: { label: '已完成', className: 'text-ok' },
    failed: { label: '失败', className: 'text-danger' },
  }[subagent.status];

  return (
    <div className="rounded-control border border-[#e9d7fe] bg-accent-soft/35 px-2.5 py-1.5">
      <div className="flex items-center gap-2">
        <IconBot size={13} className="shrink-0 text-accent" />
        <span className="shrink-0 text-mini font-medium text-ink">{subagent.name}</span>
        {subagent.role ? (
          <span className="shrink-0 text-caption text-faint">{subagent.role}</span>
        ) : null}
        <span
          className={`ml-auto inline-flex shrink-0 items-center gap-1 text-caption ${status.className}`}
        >
          {subagent.status === 'running' ? (
            <IconSpinner size={11} />
          ) : subagent.status === 'done' ? (
            <IconCheck size={11} />
          ) : (
            <IconX size={11} />
          )}
          {status.label}
        </span>
      </div>
      {subagent.summary ? (
        <div className="mt-0.5 truncate pl-[21px] text-caption text-muted">{subagent.summary}</div>
      ) : null}
    </div>
  );
}
