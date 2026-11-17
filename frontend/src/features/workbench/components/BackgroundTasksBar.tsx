import { useEffect, useRef, useState } from 'react';
import {
  IconArrowRight,
  IconChevronUp,
  IconShield,
  IconSpinner,
  IconStop,
} from '../../../shared/ui/Icons';
import { useBackgroundTasks } from '../state/background-tasks';
import type { BackgroundTask } from '../state/background-tasks';

function elapsedText(from: number, now: number): string {
  const total = Math.max(0, Math.floor((now - from) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function TaskRow({
  task,
  now,
  onOpen,
  onStop,
}: {
  task: BackgroundTask;
  now: number;
  onOpen: () => void;
  onStop: () => void;
}) {
  const waiting = task.status === 'waiting_approval';
  return (
    <div className="rounded-xl px-2.5 py-2 transition-colors hover:bg-surface-hover">
      <div className="flex items-center gap-2">
        {waiting ? (
          <IconShield size={13} className="shrink-0 text-warn" />
        ) : (
          <IconSpinner size={13} className="shrink-0 text-brand" />
        )}
        <span className="min-w-0 flex-1 truncate text-mini font-medium text-ink">{task.label}</span>
        <span className="shrink-0 font-mono text-caption text-faint tabular-nums">
          {elapsedText(task.startedAt, now)}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2 pl-[21px]">
        <span className={`truncate text-caption ${waiting ? 'text-warn' : 'text-muted'}`}>
          {waiting ? '等你审批' : '正在执行'}
          <span className="text-faint"> · {task.threadTitle}</span>
        </span>
        <button
          type="button"
          onClick={onOpen}
          className="ml-auto inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-caption text-muted transition-colors hover:bg-surface hover:text-ink"
        >
          回到会话
          <IconArrowRight size={11} />
        </button>
        <button
          type="button"
          onClick={onStop}
          className="inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-caption text-muted transition-colors hover:bg-danger-soft hover:text-danger"
        >
          <IconStop size={11} />
          停止
        </button>
      </div>
    </div>
  );
}

/**
 * 输入框上方的后台任务指示条（对齐聊天工具的「N 个后台任务运行中」）。
 * 切走会话后任务继续跑，这里能看到还有几个在跑、跑了多久，并随时回到对应会话。
 */
export function BackgroundTasksBar({
  onOpenThread,
  onStopTask,
}: {
  onOpenThread: (threadId: string) => void;
  onStopTask: (key: string) => void;
}) {
  const tasks = useBackgroundTasks();
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const rootRef = useRef<HTMLDivElement>(null);

  // 计时只在有任务时跑，避免空转
  useEffect(() => {
    if (tasks.length === 0) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [tasks.length]);

  // 任务全部结束就自动收起，避免留下一个空面板
  useEffect(() => {
    if (tasks.length === 0) setOpen(false);
  }, [tasks.length]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (tasks.length === 0) return null;

  return (
    <div ref={rootRef} className="relative mb-1.5 flex">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface py-1 pr-2.5 pl-2 text-mini text-muted shadow-card transition-colors hover:border-line-strong hover:text-ink"
      >
        <IconSpinner size={12} className="text-brand" />
        {tasks.length} 个后台任务运行中
        <IconChevronUp
          size={12}
          className={`text-faint transition-transform ${open ? '' : 'rotate-180'}`}
        />
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label="后台任务"
          className="absolute bottom-[calc(100%+0.375rem)] left-0 z-50 w-[21rem] rounded-2xl border border-line bg-surface p-1.5 shadow-pop"
        >
          <div className="flex items-center gap-2 px-2 py-1">
            <span className="text-caption font-semibold text-ink-soft">后台任务</span>
            <span className="text-caption text-faint">切走会话也不会中断</span>
          </div>
          <div className="space-y-0.5">
            {tasks.map((task) => (
              <TaskRow
                key={task.key}
                task={task}
                now={now}
                onOpen={() => {
                  onOpenThread(task.threadId);
                  setOpen(false);
                }}
                onStop={() => onStopTask(task.key)}
              />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
