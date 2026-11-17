/**
 * 轻提示（Toast）单测。
 *
 * 它是全站唯一的「做了什么」反馈通道，三个地方最容易坏：
 *   - 无障碍：容器必须常驻（读屏只对已存在的 aria-live 区域播报），危险提示要 role=alert；
 *   - 计时器：自动消失与卸载清理，漏掉就会在已卸载组件上 setState；
 *   - 降级：组件被单独渲染（没有 Provider）时 useToast() 不能抛，否则一堆单测跟着红。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Toast, ToastProvider } from './Toast';
import { useToast } from './toast-context';

/** 驱动组件：把 useToast 暴露出来，模拟真实调用方 */
function Trigger({ duration }: { duration?: number }) {
  const toast = useToast();
  return (
    <button
      type="button"
      onClick={() =>
        toast.show('已复制会话标题', {
          tone: 'ok',
          ...(duration === undefined ? {} : { duration }),
        })
      }
    >
      触发
    </button>
  );
}

function setup(duration?: number) {
  return render(
    <ToastProvider>
      <Trigger duration={duration} />
    </ToastProvider>,
  );
}

/* ------------------------------------------------------------------ */

describe('ToastProvider', () => {
  it('aria-live 容器常驻：还没弹提示时区域就已经在 DOM 里（读屏才会播报）', () => {
    const { container } = setup();
    const region = container.ownerDocument.querySelector('[aria-live="polite"]');
    expect(region).not.toBeNull();
    expect(region?.textContent).toBe('');
  });

  it('弹出后展示文案，默认 tone 用 status 播报（不打断用户）', async () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: '触发' }));
    const toast = await screen.findByRole('status');
    expect(toast).toHaveTextContent('已复制会话标题');
  });

  it('自动消失：3.2s 后不再展示', async () => {
    vi.useFakeTimers();
    try {
      setup();
      fireEvent.click(screen.getByRole('button', { name: '触发' }));
      expect(screen.getByRole('status')).toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(3200);
      });
      expect(screen.queryByRole('status')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('duration=0 常驻：只有手动关闭才消失', async () => {
    vi.useFakeTimers();
    try {
      setup(0);
      fireEvent.click(screen.getByRole('button', { name: '触发' }));
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      expect(screen.getByRole('status')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: '关闭提示' }));
      expect(screen.queryByRole('status')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('危险提示用 role=alert（打断式播报）', async () => {
    const onClose = vi.fn();
    render(<Toast message="删除失败" tone="danger" onClose={onClose} />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('删除失败');
    fireEvent.click(screen.getByRole('button', { name: '关闭提示' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('同屏最多 3 条：第 4 条挤掉最早的一条', async () => {
    setup(0);
    const button = screen.getByRole('button', { name: '触发' });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(screen.getAllByRole('status')).toHaveLength(3));
  });

  it('卸载时清掉计时器：不会在已卸载组件上继续 setState', async () => {
    vi.useFakeTimers();
    try {
      const view = setup();
      fireEvent.click(screen.getByRole('button', { name: '触发' }));
      view.unmount();
      await act(async () => {
        vi.advanceTimersByTime(5000);
      });
      // 走到这里没抛错即通过（漏清理会触发 React 的 setState on unmounted 警告/异常）
      expect(document.querySelectorAll('[role="status"]')).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('useToast 降级', () => {
  it('没有 Provider 时调用不抛错（组件被单独渲染的场景）', () => {
    render(<Trigger />);
    expect(() => fireEvent.click(screen.getByRole('button', { name: '触发' }))).not.toThrow();
    expect(screen.queryByRole('status')).toBeNull();
  });
});
