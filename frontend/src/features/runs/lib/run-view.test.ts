import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatRunElapsed, runStatusLabel, runStatusTone, sumRuns, useNotice } from './run-view';

describe('runStatusTone / runStatusLabel', () => {
  it('已知状态映射到固定色板与文案', () => {
    expect(runStatusTone('completed')).toBe('ok');
    expect(runStatusTone('rejected')).toBe('warn');
    expect(runStatusTone('failed')).toBe('danger');
    expect(runStatusTone('running')).toBe('brand');

    expect(runStatusLabel('completed')).toBe('已完成');
    expect(runStatusLabel('rejected')).toBe('已拒绝');
    expect(runStatusLabel('failed')).toBe('失败');
    expect(runStatusLabel('running')).toBe('运行中');
    expect(runStatusLabel('cancelled')).toBe('已取消');
  });

  it('未知状态：色板为 neutral，文案原样透出（便于后端新增状态时不丢信息）', () => {
    expect(runStatusTone('queued')).toBe('neutral');
    expect(runStatusTone('')).toBe('neutral');
    expect(runStatusLabel('queued')).toBe('queued');
    expect(runStatusLabel('')).toBe('');
  });
});

describe('formatRunElapsed', () => {
  it('优先取 extra.elapsed_ms（后端记录的真实耗时）', () => {
    expect(
      formatRunElapsed({
        started_at: '2026-10-23T10:00:00+08:00',
        finished_at: '2026-10-23T10:00:09+08:00',
        extra: { elapsed_ms: 2400 },
      }),
    ).toBe('2.4 s');
  });

  it('无 elapsed_ms 时按起止时间计算', () => {
    expect(
      formatRunElapsed({
        started_at: '2026-10-23T10:00:00+08:00',
        finished_at: '2026-10-23T10:00:01+08:00',
      }),
    ).toBe('1.0 s');
  });

  it('未结束显示「进行中」', () => {
    expect(formatRunElapsed({ started_at: '2026-10-23T10:00:00+08:00', finished_at: null })).toBe(
      '进行中',
    );
    expect(formatRunElapsed({ started_at: '2026-10-23T10:00:00+08:00' })).toBe('进行中');
  });

  it('时间非法时显示占位符，不抛错', () => {
    expect(formatRunElapsed({ started_at: 'bad', finished_at: 'worse' })).toBe('—');
    expect(formatRunElapsed({ started_at: '2026-10-23T10:00:00Z', finished_at: 'bad' })).toBe('—');
  });

  it('elapsed_ms 为 0 也算有效值（不足 1s 用 ms 展示）', () => {
    expect(formatRunElapsed({ started_at: 'x', finished_at: 'y', extra: { elapsed_ms: 0 } })).toBe(
      '0 ms',
    );
  });

  it('extra 里非数字字段被忽略', () => {
    expect(
      formatRunElapsed({
        started_at: '2026-10-23T10:00:00Z',
        finished_at: '2026-10-23T10:00:03Z',
        extra: { elapsed_ms: '2400' },
      }),
    ).toBe('3.0 s');
  });
});

describe('sumRuns', () => {
  it('累加 tokens 与成本', () => {
    expect(
      sumRuns([
        { tokens: 100, cost_cny: 0.01 },
        { tokens: 50, cost_cny: 0.02 },
      ]),
    ).toEqual({ tokens: 150, cost: 0.03 });
  });

  it('空列表返回零值', () => {
    expect(sumRuns([])).toEqual({ tokens: 0, cost: 0 });
  });

  it('null / undefined / NaN 字段按 0 处理（后端缺字段时不显示 NaN）', () => {
    const runs = [
      { tokens: 10, cost_cny: 0 },
      { tokens: undefined as unknown as number, cost_cny: null as unknown as number },
    ];
    const result = sumRuns(runs);
    expect(result).toEqual({ tokens: 10, cost: 0 });
    expect(Number.isNaN(result.tokens)).toBe(false);
    expect(Number.isNaN(result.cost)).toBe(false);
  });
});

describe('useNotice', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('初始为 null，设置后展示文案', () => {
    const { result } = renderHook(() => useNotice());
    expect(result.current[0]).toBeNull();
    act(() => result.current[1]('已复制'));
    expect(result.current[0]).toBe('已复制');
  });

  it('6 秒后自动消失', () => {
    const { result } = renderHook(() => useNotice());
    act(() => result.current[1]('已复制'));
    act(() => {
      vi.advanceTimersByTime(5900);
    });
    expect(result.current[0]).toBe('已复制');
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(result.current[0]).toBeNull();
  });

  it('切换为新文案时重新计时（旧定时器被清理）', () => {
    const { result } = renderHook(() => useNotice());
    act(() => result.current[1]('提示A'));
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    act(() => result.current[1]('提示B'));
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(result.current[0]).toBe('提示B');
  });

  // React 对相同值会跳过重渲染，因此重复设置同一文案不会延长展示时间。
  // 这是已知行为（6s 后必消失），若将来需要「重复提示也续时」，应改用带计数器的对象。
  it('重复设置同一文案不延长展示时间（React 对相同值跳过更新）', () => {
    const { result } = renderHook(() => useNotice());
    act(() => result.current[1]('提示'));
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    act(() => result.current[1]('提示'));
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(result.current[0]).toBeNull();
  });

  it('手动置 null 可提前关闭，卸载后不再残留定时器', () => {
    const { result, unmount } = renderHook(() => useNotice());
    act(() => result.current[1]('提示'));
    act(() => result.current[1](null));
    expect(result.current[0]).toBeNull();

    act(() => result.current[1]('再来'));
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
