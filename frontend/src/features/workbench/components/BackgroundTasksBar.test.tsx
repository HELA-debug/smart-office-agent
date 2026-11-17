import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetBackgroundTasks, upsertBackgroundTask } from '../state/background-tasks';
import { BackgroundTasksBar } from './BackgroundTasksBar';

function makeTask(patch: Record<string, unknown> = {}) {
  return {
    key: 'k1',
    threadId: 't1',
    threadTitle: '旧会话',
    label: '把这份材料整理成周报',
    runId: 'r1',
    startedAt: Date.now() - 65_000,
    status: 'running' as const,
    ...patch,
  };
}

describe('BackgroundTasksBar', () => {
  beforeEach(() => resetBackgroundTasks());

  it('没有后台任务时整条不渲染', () => {
    const { container } = render(
      <BackgroundTasksBar onOpenThread={vi.fn()} onStopTask={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('显示任务数，点开能看到任务、耗时与回到会话入口', () => {
    upsertBackgroundTask(makeTask());
    const onOpenThread = vi.fn();

    render(<BackgroundTasksBar onOpenThread={onOpenThread} onStopTask={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: /1 个后台任务运行中/ });
    fireEvent.click(trigger);

    expect(screen.getByRole('dialog', { name: '后台任务' })).toBeInTheDocument();
    expect(screen.getByText('把这份材料整理成周报')).toBeInTheDocument();
    expect(screen.getByText(/01:0/)).toBeInTheDocument();
    expect(screen.getByText(/正在执行/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /回到会话/ }));
    expect(onOpenThread).toHaveBeenCalledWith('t1');
    // 点了就收起
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('等待审批的任务显示「等你审批」，可以单独停止', () => {
    upsertBackgroundTask(makeTask({ key: 'k2', status: 'waiting_approval' }));
    const onStopTask = vi.fn();

    render(<BackgroundTasksBar onOpenThread={vi.fn()} onStopTask={onStopTask} />);
    fireEvent.click(screen.getByRole('button', { name: /1 个后台任务运行中/ }));

    expect(screen.getByText(/等你审批/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /停止/ }));
    expect(onStopTask).toHaveBeenCalledWith('k2');
  });

  it('多个任务时数量跟着变', () => {
    upsertBackgroundTask(makeTask({ key: 'k1' }));
    upsertBackgroundTask(makeTask({ key: 'k2', label: '做一份 PDF 周报' }));

    render(<BackgroundTasksBar onOpenThread={vi.fn()} onStopTask={vi.fn()} />);
    expect(screen.getByRole('button', { name: /2 个后台任务运行中/ })).toBeInTheDocument();
  });
});
