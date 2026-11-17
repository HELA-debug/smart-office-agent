/**
 * 「本机服务已断开」提示条单测。
 *
 * 这个提示存在的唯一理由是把「点了没反应」变成一句人话：桌面图标只是窗口，
 * 服务停了就得回去双击启动器。所以断言重点不是样式，而是
 *   - 服务正常时完全不出现（网页态界面不变）；
 *   - 出现时说明白「去双击哪个文件」；
 *   - 重试成功就自动消失，失败就留在原地不假装恢复。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { emitBackendStatus } from '../lib/backend-status';
import { ServiceDownBanner } from './ServiceDownBanner';

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetchHealthy() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, status: 200 }) as Response),
  );
}

function stubFetchDown() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }),
  );
}

describe('本机服务断开提示', () => {
  it('服务正常时不占位', () => {
    render(<ServiceDownBanner />);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('连不上后出现：说清「桌面图标只是窗口」，并点名启动器文件', () => {
    render(<ServiceDownBanner />);
    act(() => emitBackendStatus('offline'));

    const banner = screen.getByRole('status');
    expect(banner.textContent).toContain('本机服务已断开');
    // 用户得知道去哪儿修：文件名要原样出现，别写成「启动器」这种抽象说法
    expect(banner.textContent).toContain('启动 Office Agent.cmd');
    expect(banner.textContent).toContain('启动完成，可以用了');
  });

  it('重试探测成功就自动消失，不用刷新页面', async () => {
    stubFetchHealthy();
    render(<ServiceDownBanner />);
    act(() => emitBackendStatus('offline'));

    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
  });

  it('重试仍连不上就留在原地，不假装恢复', async () => {
    stubFetchDown();
    render(<ServiceDownBanner />);
    act(() => emitBackendStatus('offline'));

    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '重试' })).toBeTruthy());
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('后续随便哪个请求成功，提示都会自己消失', () => {
    render(<ServiceDownBanner />);
    act(() => emitBackendStatus('offline'));
    expect(screen.getByRole('status')).toBeTruthy();

    act(() => emitBackendStatus('online'));
    expect(screen.queryByRole('status')).toBeNull();
  });
});
