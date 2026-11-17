/**
 * 「跑的不是这份代码」提示条：只认比对结果，不自己发请求猜。
 *
 * 三种情况要说清**该做什么**：
 * - 界面旧 → 重新 `npm run build` 再刷新；
 * - 后端进程旧 → 关掉启动窗口重启（重建前端没用）；
 * - 两边都旧 → 先重建再重启。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { emitStaleBuild } from '../lib/build-info';
import { StaleBuildBanner } from './StaleBuildBanner';

function stubFetch(payload: Record<string, unknown> = {}, ok = false) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok, json: async () => payload })),
  );
}

describe('StaleBuildBanner', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('没有不一致时什么都不渲染（不打扰）', () => {
    stubFetch();
    render(<StaleBuildBanner />);
    expect(screen.queryByTestId('stale-build-banner')).toBeNull();
  });

  it('界面旧：说清两边 sha、让人重新构建，并能忽略', () => {
    stubFetch();
    render(<StaleBuildBanner />);

    act(() => {
      emitStaleBuild({
        frontend: 'aaa1111',
        backend: 'bbb2222',
        live: 'bbb2222',
        kind: 'frontend',
      });
    });

    const banner = screen.getByTestId('stale-build-banner');
    expect(banner).toHaveTextContent('旧版界面');
    expect(banner).toHaveTextContent('aaa1111');
    expect(banner).toHaveTextContent('bbb2222');
    expect(banner).toHaveTextContent('npm run build');

    fireEvent.click(screen.getByRole('button', { name: '忽略旧构建提示' }));
    expect(screen.queryByTestId('stale-build-banner')).toBeNull();
  });

  it('后端进程旧：让人重启，不要再让人重建（重建也治不好）', () => {
    stubFetch();
    render(<StaleBuildBanner />);

    act(() => {
      emitStaleBuild({
        frontend: '8195a64',
        backend: '1daa671',
        live: '8195a64',
        kind: 'backend',
      });
    });

    const banner = screen.getByTestId('stale-build-banner');
    expect(banner).toHaveTextContent('服务端进程还是旧版本');
    expect(banner).toHaveTextContent('1daa671');
    expect(banner).toHaveTextContent('8195a64');
    expect(banner).toHaveTextContent('启动器');
    expect(banner).not.toHaveTextContent('npm run build');
    expect(screen.getByRole('button', { name: '重新检查' })).toBeInTheDocument();
  });

  it('后端旧时的「重新检查」：重启后对上了就自己收起来', async () => {
    stubFetch();
    render(<StaleBuildBanner />);

    act(() => {
      emitStaleBuild({
        frontend: '8195a64',
        backend: '1daa671',
        live: '8195a64',
        kind: 'backend',
      });
    });

    fireEvent.click(screen.getByRole('button', { name: '重新检查' }));
    await waitFor(() => expect(screen.queryByTestId('stale-build-banner')).toBeNull());
  });

  it('「刷新」按钮会重新加载页面', () => {
    stubFetch();
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });

    render(<StaleBuildBanner />);
    act(() => {
      emitStaleBuild({
        frontend: 'aaa1111',
        backend: 'bbb2222',
        live: 'bbb2222',
        kind: 'frontend',
      });
    });
    fireEvent.click(screen.getByRole('button', { name: '刷新' }));
    expect(reload).toHaveBeenCalled();
  });
});
