/**
 * 浮层菜单：列表行里的 ⋮ 菜单必须一次显示全 —— 之前用 absolute 挂在行里，
 * 被 `overflow-y-auto` 的列表容器裁掉半截（「打开项目」只剩半行）。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { useRef, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { FloatingMenu } from './FloatingMenu';

function Harness({ onClose }: { onClose?: () => void }) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(true);
  return (
    <div style={{ overflow: 'hidden', height: 40 }}>
      <span ref={anchorRef} data-testid="anchor">
        <button type="button" onClick={() => setOpen((value) => !value)}>
          打开
        </button>
      </span>
      <FloatingMenu
        open={open}
        onClose={() => {
          onClose?.();
          setOpen(false);
        }}
        anchorRef={anchorRef}
        label="会话操作"
      >
        <button type="button" role="menuitem">
          置顶
        </button>
      </FloatingMenu>
    </div>
  );
}

describe('FloatingMenu', () => {
  it('渲染到 body 上：不在 overflow:hidden 的列表容器里，不会被裁切', () => {
    render(<Harness />);
    const menu = screen.getByRole('menu', { name: '会话操作' });
    expect(menu.parentElement).toBe(document.body);
    expect(menu.className).toContain('fixed');
  });

  it('点菜单内部不关闭，点外面才关闭', () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);

    fireEvent.mouseDown(screen.getByRole('menuitem', { name: '置顶' }));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(document.body);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Esc 关闭', () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('下方放不下时向上翻，且不越出视口', () => {
    const original = window.innerHeight;
    Object.defineProperty(window, 'innerHeight', { value: 730, configurable: true });

    render(<Harness />);
    const anchor = screen.getByTestId('anchor');
    anchor.getBoundingClientRect = () =>
      ({
        top: 700,
        bottom: 720,
        left: 240,
        right: 300,
        width: 60,
        height: 20,
        x: 240,
        y: 700,
        toJSON: () => ({}),
      }) as DOMRect;

    // 触发一次滚动让位置重算（弹出时首帧也会量一次）
    fireEvent.scroll(window);
    const menu = screen.getByRole('menu', { name: '会话操作' });
    const top = Number.parseFloat(menu.style.top);
    expect(top).toBeLessThan(700);
    expect(top).toBeGreaterThanOrEqual(8);

    Object.defineProperty(window, 'innerHeight', { value: original, configurable: true });
  });
});
