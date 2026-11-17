import { useMemo, useState } from 'react';
import {
  IconCheckCircle,
  IconChevronDown,
  IconCircle,
  IconList,
  IconSpinner,
  IconX,
} from '../../../shared/ui/Icons';
import { CardError, CardLoading } from '../../../shared/ui/primitives';
import type { TodoStatus } from '../../../shared/types/events';
import type { PlanSnapshot } from '../../../shared/types/view';

function TodoIcon({ status }: { status: TodoStatus }) {
  switch (status) {
    case 'completed':
      return <IconCheckCircle size={13} className="shrink-0 text-ok" />;
    case 'in_progress':
      return <IconSpinner size={13} className="shrink-0 text-brand" />;
    case 'cancelled':
      return <IconX size={13} className="shrink-0 text-faint" />;
    default:
      return <IconCircle size={13} className="shrink-0 text-line-strong" />;
  }
}

/**
 * 执行计划：一行流水（步骤数 + 当前在做什么），点开才展开明细。
 * 之前的整卡 + 头部 + 进度条 + 「收起/展开」占了太多纵向空间，
 * 用户要的是「扫一眼就知道在干什么」，不是一块仪表盘。
 *
 * 全部步骤完成后进一步降级成一行淡字：此时这条已经不再回答「还要多久」，
 * 留着整块卡片只是把回答和产物挤开。想看明细再点开。
 */
export function PlanCard({
  plan,
  loading = false,
  error = null,
}: {
  plan: PlanSnapshot | null;
  loading?: boolean;
  error?: string | null;
}) {
  const [open, setOpen] = useState(false);

  const stats = useMemo(() => {
    const todos = plan?.todos ?? [];
    const done = todos.filter((todo) => todo.status === 'completed').length;
    const total = todos.length;
    const current = todos.find((todo) => todo.status === 'in_progress');
    return {
      todos,
      done,
      total,
      current,
      finished: total > 0 && done === total,
      percent: total === 0 ? 0 : Math.round((done / total) * 100),
    };
  }, [plan]);

  if (loading) {
    return (
      <div className="rounded-control border border-line bg-surface px-2.5 py-2">
        <CardLoading label="正在生成计划…" rows={2} />
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

  if (!plan || plan.todos.length === 0) {
    return (
      <div className="flex items-center gap-2 px-2.5 py-1.5 text-mini text-faint">
        <IconList size={13} />
        计划尚未生成
      </div>
    );
  }

  // 跑完了：只留一行淡字，想追究再点开。整块卡片留给「正在做」的时候。
  if (stats.finished && !open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 px-1 py-0.5 text-caption text-faint transition-colors hover:text-muted"
        aria-expanded={false}
      >
        <IconCheckCircle size={12} className="shrink-0 opacity-70" />
        {/* 不报步数：计划里有几条是我们替他拆的，他关心的是「做完了没有」 */}
        <span>执行计划已完成</span>
        <IconChevronDown size={12} className="shrink-0 -rotate-90" />
      </button>
    );
  }

  const summary = stats.current
    ? `正在：${stats.current.content}`
    : stats.done === stats.total
      ? '全部步骤已完成'
      : '等待下一步';

  return (
    <div className="overflow-hidden rounded-control border border-line bg-surface">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-surface-hover"
        aria-expanded={open}
      >
        <IconList size={13} className="shrink-0 text-brand" />
        <span className="shrink-0 text-mini font-medium text-ink">执行计划</span>
        <span className="shrink-0 text-mini text-faint">
          {stats.done}/{stats.total} 已完成
        </span>
        <span className="min-w-0 flex-1 truncate text-mini text-muted">{summary}</span>
        <IconChevronDown
          size={13}
          className={`shrink-0 text-faint transition-transform ${open ? '' : '-rotate-90'}`}
        />
      </button>

      {/* 2px 细线就够了：既能看出进度，又不占一行高度 */}
      <div className="h-[2px] w-full bg-surface-sunken">
        <div
          className="h-full bg-brand transition-all duration-500"
          style={{ width: `${stats.percent}%` }}
        />
      </div>

      {open ? (
        <ul className="space-y-px px-1.5 py-1.5">
          {stats.todos.map((todo) => {
            const isActive = todo.status === 'in_progress';
            return (
              <li
                key={todo.id}
                className={`flex items-center gap-2 rounded-control px-1.5 py-1 ${
                  isActive ? 'bg-brand-soft/60' : ''
                }`}
              >
                <TodoIcon status={todo.status} />
                <span
                  className={
                    todo.status === 'completed'
                      ? 'truncate text-mini text-muted'
                      : todo.status === 'cancelled'
                        ? 'truncate text-mini text-faint line-through'
                        : isActive
                          ? 'truncate text-mini font-medium text-ink'
                          : 'truncate text-mini text-ink-soft'
                  }
                >
                  {todo.content}
                </span>
                {isActive ? (
                  <span className="ml-auto shrink-0 text-caption text-brand">进行中</span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
