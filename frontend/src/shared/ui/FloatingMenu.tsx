/**
 * 浮层菜单（portal + fixed 定位）。
 *
 * 为什么不用 `absolute right-0 top-7`：菜单挂在列表行里，而列表容器是 `overflow-y-auto`，
 * 一旦行靠近容器底部，菜单后半截就被裁掉——用户看到的正是「打开项目」只剩半行。
 * 用 portal 渲染到 body 并按视口坐标算位置，容器裁切就管不着了；
 * 下方空间不够时向上翻，水平按宽度右对齐并夹到视口内，保证**一次性完整显示**。
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode, RefObject } from 'react';

/** 菜单与触发按钮之间的间距 */
const MENU_GAP = 6;
/** 菜单距视口边缘的最小留白 */
const MENU_MARGIN = 8;

export interface FloatingMenuProps {
  open: boolean;
  onClose: () => void;
  /** 触发按钮（用它算位置，也用于判断「点在外面」） */
  anchorRef: RefObject<HTMLElement | null>;
  /** 右对齐（默认，贴着按钮右边缘向左展开）还是左对齐 */
  align?: 'end' | 'start';
  /** 固定宽度：先定宽再测量，避免首帧宽度为 auto 导致闪一下 */
  width?: number;
  label?: string;
  className?: string;
  children: ReactNode;
}

export function FloatingMenu({
  open,
  onClose,
  anchorRef,
  align = 'end',
  width = 168,
  label,
  className = '',
  children,
}: FloatingMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  const place = useCallback(() => {
    const anchor = anchorRef.current;
    const menu = menuRef.current;
    if (!anchor || !menu) return;
    const rect = anchor.getBoundingClientRect();
    const height = menu.offsetHeight;
    const width = menu.offsetWidth;

    // 垂直：优先在下方；下方放不下就翻到上方；两边都放不下就贴着视口底部往上顶
    let top = rect.bottom + MENU_GAP;
    if (top + height > window.innerHeight - MENU_MARGIN) {
      const above = rect.top - MENU_GAP - height;
      top =
        above >= MENU_MARGIN
          ? above
          : Math.max(MENU_MARGIN, window.innerHeight - MENU_MARGIN - height);
    }
    // 水平：右对齐时让菜单右边缘贴着按钮右边缘，再夹进视口
    const raw = align === 'end' ? rect.right - width : rect.left;
    const left = Math.min(Math.max(MENU_MARGIN, raw), window.innerWidth - MENU_MARGIN - width);

    setPos({ top, left });
  }, [align, anchorRef]);

  // 打开后先量一次再显示（首帧藏在视口外，避免出现在错误位置闪一下）
  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    place();
  }, [open, place, children]);

  useEffect(() => {
    if (!open) return;
    // 滚动/改窗口大小时跟随锚点重新定位；捕获阶段才能收到列表容器的滚动
    const onScroll = () => place();
    window.addEventListener('resize', onScroll);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      window.removeEventListener('resize', onScroll);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose, anchorRef]);

  if (!open) return null;

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      aria-label={label}
      style={{
        top: pos ? pos.top : -9999,
        left: pos ? pos.left : -9999,
        width,
        visibility: pos ? 'visible' : 'hidden',
      }}
      className={`fixed z-50 overflow-hidden rounded-control border border-line bg-surface py-1 shadow-pop ${className}`}
    >
      {children}
    </div>,
    document.body,
  );
}
