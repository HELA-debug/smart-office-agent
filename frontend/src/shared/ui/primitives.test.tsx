/**
 * UI 基础组件单测。
 *
 * Tooltip 是本轮重点：它曾用 absolute 定位，被 `overflow-hidden` 的卡片裁掉、
 * 或贴边时只露出一半。改为 portal + fixed 后，这里用断言锁住新行为：
 *   - 气泡挂在 document.body 上（不受父级 overflow 影响）；
 *   - 视口上方空间不足时自动翻到下方；
 *   - 滚动 / 缩放时收起，避免与目标错位。
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  Badge,
  Button,
  Card,
  CardEmpty,
  CardError,
  CardLoading,
  Modal,
  SectionLabel,
  Skeleton,
  Tooltip,
} from './primitives';

// 注意：不要手动清空 document.body.innerHTML —— Tooltip 用 portal 挂在 body 上，
// 手动移除会让 React 卸载时二次删除同一节点而报错。交给 RTL 的自动 cleanup。

/* ------------------------------------------------------------------ */

describe('Button', () => {
  it('默认 type=button、size=sm、variant=secondary（避免表单里误提交）', () => {
    render(<Button>保存</Button>);
    const button = screen.getByRole('button', { name: '保存' });
    expect(button).toHaveAttribute('type', 'button');
    expect(button.className).toContain('h-8');
  });

  it('loading 时禁用并渲染 spinner，且不再显示 leading', () => {
    render(
      <Button loading leading={<span data-testid="leading" />}>
        提交
      </Button>,
    );
    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
    expect(screen.queryByTestId('leading')).toBeNull();
  });

  it('disabled 与 loading 都会禁用按钮', () => {
    const { rerender } = render(<Button disabled>禁用</Button>);
    expect(screen.getByRole('button')).toBeDisabled();
    rerender(<Button loading>加载</Button>);
    expect(screen.getByRole('button')).toBeDisabled();
  });

  it('渲染 leading / trailing 插槽，并透出点击事件', () => {
    const onClick = vi.fn();
    render(
      <Button leading={<span>L</span>} trailing={<span>T</span>} onClick={onClick}>
        中间
      </Button>,
    );
    expect(screen.getByText('L')).toBeTruthy();
    expect(screen.getByText('T')).toBeTruthy();
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('md 尺寸与自定义 className 生效', () => {
    render(
      <Button size="md" className="w-full">
        宽按钮
      </Button>,
    );
    const button = screen.getByRole('button');
    expect(button.className).toContain('h-9');
    expect(button.className).toContain('w-full');
  });
});

describe('Badge / Card / SectionLabel', () => {
  it('Badge 支持圆点标记与自定义 className', () => {
    const { container, rerender } = render(<Badge tone="ok">已完成</Badge>);
    expect(container.querySelectorAll('span').length).toBe(1);
    rerender(
      <Badge tone="ok" dot className="custom">
        已完成
      </Badge>,
    );
    expect(container.querySelectorAll('span').length).toBe(2);
    expect(container.firstElementChild?.className).toContain('custom');
  });

  it('Card 可通过 as 切换标签，默认 section', () => {
    const { container } = render(<Card>内容</Card>);
    expect(container.firstElementChild?.tagName).toBe('SECTION');
    const { container: divContainer } = render(<Card as="div">内容</Card>);
    expect(divContainer.firstElementChild?.tagName).toBe('DIV');
  });

  it('SectionLabel 渲染文本', () => {
    render(<SectionLabel>审批</SectionLabel>);
    expect(screen.getByText('审批')).toBeTruthy();
  });
});

describe('三态辅助组件', () => {
  it('Skeleton 带 shimmer 动画类', () => {
    const { container } = render(<Skeleton className="h-4" />);
    expect(container.firstElementChild?.className).toContain('shimmer');
  });

  it('CardLoading 按 rows 渲染骨架条，带无障碍状态', () => {
    const { container } = render(<CardLoading label="加载产物…" rows={3} />);
    expect(screen.getByRole('status')).toBeTruthy();
    expect(screen.getByText('加载产物…')).toBeTruthy();
    // 1 条 label + 3 条骨架
    expect(container.querySelectorAll('.shimmer')).toHaveLength(3);
  });

  it('CardError 有 onRetry 才渲染按钮，文案可自定义', () => {
    const onRetry = vi.fn();
    const { rerender } = render(<CardError message="加载失败" />);
    expect(screen.queryByRole('button')).toBeNull();

    rerender(<CardError message="加载失败" onRetry={onRetry} retryLabel="重新加载" />);
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByText('加载失败')).toBeTruthy();
  });

  it('CardEmpty 可选提示文案', () => {
    const { rerender } = render(<CardEmpty label="暂无产物" />);
    expect(screen.queryByText('先跑一次任务')).toBeNull();
    rerender(<CardEmpty label="暂无产物" hint="先跑一次任务" />);
    expect(screen.getByText('先跑一次任务')).toBeTruthy();
  });
});

/* ------------------------------------------------------------------ */

describe('Tooltip', () => {
  function tip(): HTMLElement | null {
    return document.querySelector('[role="tooltip"]');
  }

  it('默认不展示，hover 后出现并挂在 body 上（不被父级裁剪）', () => {
    render(
      <div style={{ overflow: 'hidden' }}>
        <Tooltip label="导出为 CSV">
          <button type="button">导出</button>
        </Tooltip>
      </div>,
    );
    expect(tip()).toBeNull();

    fireEvent.mouseEnter(screen.getByText('导出').parentElement as HTMLElement);
    const bubble = tip();
    expect(bubble).not.toBeNull();
    // portal 到 body：不受 overflow:hidden 的父容器影响
    expect(bubble?.parentElement).toBe(document.body);
    expect(bubble?.className).toContain('fixed');
    expect(screen.getByText('导出为 CSV')).toBeTruthy();
  });

  it('移出鼠标后收起', () => {
    render(
      <Tooltip label="提示">
        <button type="button">目标</button>
      </Tooltip>,
    );
    const anchor = screen.getByText('目标').parentElement as HTMLElement;
    fireEvent.mouseEnter(anchor);
    expect(tip()).not.toBeNull();
    fireEvent.mouseLeave(anchor);
    expect(tip()).toBeNull();
  });

  it('支持键盘 focus / blur（不只依赖鼠标）', () => {
    render(
      <Tooltip label="提示">
        <button type="button">目标</button>
      </Tooltip>,
    );
    fireEvent.focus(screen.getByText('目标').parentElement as HTMLElement);
    expect(tip()).not.toBeNull();
    fireEvent.blur(screen.getByText('目标').parentElement as HTMLElement);
    expect(tip()).toBeNull();
  });

  it('可选快捷键一并展示', () => {
    render(
      <Tooltip label="新建会话" shortcut="⌘N">
        <button type="button">新建</button>
      </Tooltip>,
    );
    fireEvent.mouseEnter(screen.getByText('新建').parentElement as HTMLElement);
    expect(screen.getByText('⌘N')).toBeTruthy();
  });

  it('单行提示是胶囊形（两端全圆），不是 10px 的方角小卡', () => {
    render(
      <Tooltip label="打开产物中心，并定位到本会话的产物">
        <button type="button">仓库</button>
      </Tooltip>,
    );
    fireEvent.mouseEnter(screen.getByText('仓库').parentElement as HTMLElement);
    // label 分支永远单行（内层 truncate 钉死了），所以可以给满圆角；
    // 富提示那支是多行卡片，仍用 rounded-control，别跟着一起改
    expect(tip()?.className).toContain('rounded-full');
  });

  it('content 走富提示：多行、圆角卡片、左对齐（原生 title 做不到）', () => {
    render(
      <Tooltip
        content={
          <span>
            <span>摘要_随笔_2026-10-26.docx</span>
            <span>源自 随笔.docx</span>
          </span>
        }
      >
        <button type="button">产物</button>
      </Tooltip>,
    );
    fireEvent.mouseEnter(screen.getByText('产物').parentElement as HTMLElement);
    const bubble = tip();
    expect(bubble?.className).toContain('rounded-control');
    expect(bubble?.className).toContain('text-left');
    expect(bubble?.textContent).toContain('源自 随笔.docx');
  });

  it('delayMs 让提示晚一点出现，快速划过不弹气泡', () => {
    vi.useFakeTimers();
    render(
      <Tooltip label="提示" delayMs={200}>
        <button type="button">目标</button>
      </Tooltip>,
    );
    const anchor = screen.getByText('目标').parentElement as HTMLElement;
    fireEvent.mouseEnter(anchor);
    expect(tip()).toBeNull();
    // 还没到点就移出：计时器被清掉，永远不出现
    fireEvent.mouseLeave(anchor);
    act(() => vi.advanceTimersByTime(500));
    expect(tip()).toBeNull();
    // 正常停留够时间才出现
    fireEvent.mouseEnter(anchor);
    act(() => vi.advanceTimersByTime(200));
    expect(tip()).not.toBeNull();
    vi.useRealTimers();
  });

  it('滚动时收起，避免气泡与按钮错位', () => {
    render(
      <Tooltip label="提示">
        <button type="button">目标</button>
      </Tooltip>,
    );
    fireEvent.mouseEnter(screen.getByText('目标').parentElement as HTMLElement);
    expect(tip()).not.toBeNull();
    fireEvent.scroll(window);
    expect(tip()).toBeNull();
  });

  it('窗口缩放时收起', () => {
    render(
      <Tooltip label="提示">
        <button type="button">目标</button>
      </Tooltip>,
    );
    fireEvent.mouseEnter(screen.getByText('目标').parentElement as HTMLElement);
    expect(tip()).not.toBeNull();
    fireEvent(window, new Event('resize'));
    expect(tip()).toBeNull();
  });

  it('气泡位置为数值像素（fixed 定位），且带 z-index', () => {
    render(
      <Tooltip label="提示">
        <button type="button">目标</button>
      </Tooltip>,
    );
    fireEvent.mouseEnter(screen.getByText('目标').parentElement as HTMLElement);
    const bubble = tip() as HTMLElement;
    expect(bubble.style.top).toMatch(/px$/);
    expect(bubble.style.left).toMatch(/px$/);
    expect(bubble.className).toContain('z-[80]');
  });
});

/* ------------------------------------------------------------------ */

describe('Modal', () => {
  it('渲染标题与内容，带 dialog 语义', () => {
    render(
      <Modal title="添加 Key" onClose={() => undefined}>
        <p>内容</p>
      </Modal>,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAttribute('aria-label', '添加 Key');
    expect(screen.getByText('内容')).toBeTruthy();
  });

  it('Esc 关闭', () => {
    const onClose = vi.fn();
    render(
      <Modal title="测试" onClose={onClose}>
        <p>内容</p>
      </Modal>,
    );
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('其它按键不关闭', () => {
    const onClose = vi.fn();
    render(
      <Modal title="测试" onClose={onClose}>
        <p>内容</p>
      </Modal>,
    );
    fireEvent.keyDown(window, { key: 'Enter' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('点击遮罩关闭', () => {
    const onClose = vi.fn();
    render(
      <Modal title="测试" onClose={onClose}>
        <p>内容</p>
      </Modal>,
    );
    fireEvent.click(screen.getByLabelText('关闭弹窗'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('打开即把焦点搬进弹窗；键盘打开的，关闭后还给触发按钮', () => {
    // 弹窗以前不接管焦点：键盘用户按开之后还在背后页面上，Tab 半天进不来
    function Host() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            打开
          </button>
          {open ? (
            <Modal title="测试" onClose={() => setOpen(false)}>
              <button type="button">弹窗里的按钮</button>
            </Modal>
          ) : null}
        </>
      );
    }

    render(<Host />);
    const trigger = screen.getByRole('button', { name: '打开' });
    trigger.focus();
    fireEvent.keyDown(window, { key: 'Enter' }); // 键盘打开
    fireEvent.click(trigger);

    // 焦点落在弹窗容器上（读屏会念标题），而不是遮罩、也不是头部的「关闭」
    expect(document.activeElement).toBe(screen.getByRole('dialog'));

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(document.activeElement).toBe(trigger);
  });

  it('鼠标打开的弹窗，关掉后不回填焦点（否则按钮上留一圈焦点环）', () => {
    // 鼠标点开预览 → Esc 关掉是很常见的路径。若这时把焦点还给触发按钮，
    // 浏览器会判成 :focus-visible：按钮上一圈框、依赖它的悬浮条也一直挂着，
    // 用户看到的就是「窗口关了，框和按钮还在」。
    function Host() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            打开
          </button>
          {open ? (
            <Modal title="测试" onClose={() => setOpen(false)}>
              <button type="button">弹窗里的按钮</button>
            </Modal>
          ) : null}
        </>
      );
    }

    render(<Host />);
    const trigger = screen.getByRole('button', { name: '打开' });
    trigger.focus();
    fireEvent.pointerDown(trigger); // 记成「指针操作」
    fireEvent.click(trigger);

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(document.activeElement).not.toBe(trigger);
  });

  it('Tab 走到最后一个元素时绕回弹窗内第一个（焦点不外泄）', () => {
    render(
      <Modal title="测试" onClose={() => undefined}>
        <button type="button">第一个</button>
        <button type="button">最后一个</button>
      </Modal>,
    );
    // 弹窗内可聚焦元素依次是：头部「关闭」→ 第一个 → 最后一个
    screen.getByRole('button', { name: '最后一个' }).focus();
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '关闭' }));
  });

  it('无 footer 时不渲染底栏，有 footer 时渲染', () => {
    const { rerender } = render(
      <Modal title="测试" onClose={() => undefined}>
        <p>内容</p>
      </Modal>,
    );
    expect(screen.queryByText('保存')).toBeNull();
    rerender(
      <Modal title="测试" onClose={() => undefined} footer={<button type="button">保存</button>}>
        <p>内容</p>
      </Modal>,
    );
    expect(screen.getByText('保存')).toBeTruthy();
  });

  it('卸载后不再响应 Esc（监听器已清理）', () => {
    const onClose = vi.fn();
    const { unmount } = render(
      <Modal title="测试" onClose={onClose}>
        <p>内容</p>
      </Modal>,
    );
    unmount();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });

  it('全窗口：去掉圆角与最大宽度，标注 data-fullscreen 供样式定位', () => {
    render(
      <Modal title="测试" onClose={() => undefined} size="lg" fullscreen>
        <p>内容</p>
      </Modal>,
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('data-fullscreen', 'true');
    expect(dialog.className).toContain('max-w-none');
    expect(dialog.className).toContain('h-full');
    expect(dialog.className).not.toContain('max-w-[900px]');
  });

  it('onEscape 传了就先交给它（不再直接关），由它决定要不要关', () => {
    const onClose = vi.fn();
    const onEscape = vi.fn();
    render(
      <Modal title="测试" onClose={onClose} onEscape={onEscape}>
        <p>内容</p>
      </Modal>,
    );
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onEscape).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });
});
