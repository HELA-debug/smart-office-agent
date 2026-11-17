import { useEffect, useState } from 'react';
import { formatDuration } from '../../../shared/lib/format';

export function formatRunElapsed(run: {
  started_at: string;
  finished_at?: string | null;
  extra?: Record<string, unknown>;
}): string {
  const extraElapsed = run.extra?.elapsed_ms;
  if (typeof extraElapsed === 'number') return formatDuration(extraElapsed);
  if (!run.finished_at) return '进行中';
  const start = new Date(run.started_at).getTime();
  const end = new Date(run.finished_at).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '—';
  return formatDuration(end - start);
}

export function runStatusTone(status: string): 'ok' | 'warn' | 'danger' | 'brand' | 'neutral' {
  switch (status) {
    case 'completed':
      return 'ok';
    case 'rejected':
      return 'warn';
    case 'failed':
      return 'danger';
    case 'running':
      return 'brand';
    default:
      return 'neutral';
  }
}

export function runStatusLabel(status: string): string {
  switch (status) {
    case 'completed':
      return '已完成';
    case 'rejected':
      return '已拒绝';
    case 'failed':
      return '失败';
    case 'running':
      return '运行中';
    case 'cancelled':
      return '已取消';
    default:
      return status;
  }
}

export function sumRuns(runs: Array<{ tokens: number; cost_cny: number }>): {
  tokens: number;
  cost: number;
} {
  return runs.reduce(
    (acc, run) => ({
      tokens: acc.tokens + (run.tokens || 0),
      cost: acc.cost + (run.cost_cny || 0),
    }),
    { tokens: 0, cost: 0 },
  );
}

export function useNotice(): [string | null, (text: string | null) => void] {
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);
  return [notice, setNotice];
}
