/**
 * 统一圆角下拉（自绘 listbox）。
 *
 * 为什么不用原生 `<select>`：Windows / Chromium 的展开弹层由系统绘制，
 * 选项高亮是直角深灰块、边框也无法圆角化，和整体风格格格不入。
 * 这里用 button + portal 列表自绘：圆角面板、圆角选项、勾选标记，
 * 支持方向键 / Enter / Esc、空间不足自动上翻、滚动缩放收起。
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { IconCheck, IconChevronDown } from './Icons';
import type { KeyboardEvent, ReactNode } from 'react';

export interface SelectOption<T extends string> {
  value: T;
  label: ReactNode;
  /** 右侧备注（如「默认·同素材」「已配置」） */
  note?: ReactNode;
  disabled?: boolean;
}

const GAP = 6;
const MARGIN = 8;

type SelectVariant = 'control' | 'pill' | 'ghost';

const TRIGGER: Record<SelectVariant, string> = {
  // 表单里的标准控件：占满一行、左对齐、圆角 8px
  control:
    'flex h-8 w-full items-center justify-between gap-2 rounded-control border border-line bg-surface px-2.5 text-mini text-ink transition-colors hover:border-line-strong hover:bg-surface-hover',
  // 输入区工具栏里的胶囊按钮
  pill: 'flex h-7 max-w-[200px] items-center gap-1 rounded-full border border-line bg-surface px-2 text-caption text-ink-soft transition-colors hover:border-line-strong hover:bg-surface-hover hover:text-ink',
  // 面板标题栏里的轻量切换
  ghost:
    'flex h-8 w-full items-center justify-between gap-2 rounded-control bg-surface-soft px-2.5 text-mini text-ink hover:bg-surface-hover',
};

export function Select<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
  variant = 'control',
  disabled = false,
  leading,
  hint,
  className = '',
  minWidth = 180,
}: {
  value: T;
  options: SelectOption<T>[];
  onChange: (value: T) => void;
  ariaLabel: string;
  variant?: SelectVariant;
  disabled?: boolean;
  /** 触发器左侧图标（如产物格式的文件图标） */
  leading?: ReactNode;
  /** 弹层底部的说明文案（避免用 hover 提示，展开时不会互相遮挡） */
  hint?: string;
  className?: string;
  /** 弹层最小宽度，默认 180px */
  minWidth?: number;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<{
    top: number;
    left: number;
    width: number;
    above: boolean;
  } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const current = options.find((option) => option.value === value) ?? options[0];

  const place = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const width = Math.max(rect.width, minWidth);
    const height = listRef.current?.offsetHeight ?? 0;
    const spaceBelow = window.innerHeight - rect.bottom;
    const above = spaceBelow < height + GAP + MARGIN && rect.top > spaceBelow;
    const left = Math.min(Math.max(rect.left, MARGIN), window.innerWidth - width - MARGIN);
    setPos({ top: above ? rect.top - GAP : rect.bottom + GAP, left, width, above });
  }, [minWidth]);

  const openList = useCallback(() => {
    const index = options.findIndex((option) => option.value === value);
    setActive(index >= 0 ? index : 0);
    setOpen(true);
  }, [options, value]);

  // 首次打开时列表还没高度：布局阶段再量一次，用于判定是否需要向上翻面
  useLayoutEffect(() => {
    if (!open) return;
    place();
    listRef.current?.focus({ preventScroll: true });
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || listRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onDismiss = () => setOpen(false);
    document.addEventListener('mousedown', onPointerDown);
    window.addEventListener('scroll', onDismiss, true);
    window.addEventListener('resize', onDismiss);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      window.removeEventListener('scroll', onDismiss, true);
      window.removeEventListener('resize', onDismiss);
    };
  }, [open]);

  const choose = (next: T) => {
    onChange(next);
    setOpen(false);
    triggerRef.current?.focus({ preventScroll: true });
  };

  const onListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape' || event.key === 'Tab') {
      setOpen(false);
      triggerRef.current?.focus({ preventScroll: true });
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((index) => (index + 1) % options.length);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((index) => (index - 1 + options.length) % options.length);
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      const picked = options[active];
      if (picked && !picked.disabled) choose(picked.value);
    }
  };

  if (!current) return null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openList())}
        className={`${TRIGGER[variant]} transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      >
        {leading ? <span className="shrink-0">{leading}</span> : null}
        <span className="min-w-0 flex-1 truncate text-left">{current.label}</span>
        <IconChevronDown
          size={12}
          className={`shrink-0 text-muted transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open
        ? createPortal(
            <div
              ref={listRef}
              role="listbox"
              aria-label={ariaLabel}
              tabIndex={-1}
              onKeyDown={onListKeyDown}
              style={{
                top: pos?.top ?? 0,
                left: pos?.left ?? 0,
                width: pos?.width ?? minWidth,
              }}
              className={`fixed z-[90] overflow-hidden rounded-2xl border border-line bg-surface p-1 shadow-pop outline-none ${
                pos?.above ? '-translate-y-full' : ''
              }`}
            >
              <div className="max-h-[280px] overflow-y-auto">
                {options.map((option, index) => {
                  const selected = option.value === value;
                  const highlighted = index === active;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      disabled={option.disabled}
                      onMouseEnter={() => setActive(index)}
                      onClick={() => choose(option.value)}
                      className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-1.5 text-left text-mini transition-colors ${
                        highlighted ? 'bg-surface-sunken text-ink' : 'text-ink-soft'
                      } ${option.disabled ? 'cursor-not-allowed opacity-50' : ''}`}
                    >
                      <span className="min-w-0 flex-1 truncate">
                        {option.label}
                        {option.note ? (
                          <span className="ml-1 text-caption text-faint">{option.note}</span>
                        ) : null}
                      </span>
                      {selected ? <IconCheck size={13} className="shrink-0 text-brand" /> : null}
                    </button>
                  );
                })}
              </div>
              {hint ? (
                <p className="mt-1 border-t border-line/70 px-2.5 pt-1.5 pb-1 text-caption text-faint">
                  {hint}
                </p>
              ) : null}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
