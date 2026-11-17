import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { IconSpinner, IconX } from './Icons';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

/* ------------------------------------------------------------------ */
/* 输入方式（指针 / 键盘）                                              */
/* ------------------------------------------------------------------ */

/**
 * 最近一次交互是不是键盘。
 *
 * 用来区分「键盘 Tab 过来」和「鼠标点完顺手获得焦点」——两者都会派 focus 事件，
 * 但只有前者该弹提示气泡。不用 `:focus-visible` 判断：那个伪类没法在 jsdom 里
 * 复现，测试和真实浏览器会分成两套行为。
 */
let lastInputWasKeyboard = true;
if (typeof window !== 'undefined') {
  window.addEventListener(
    'keydown',
    () => {
      lastInputWasKeyboard = true;
    },
    true,
  );
  window.addEventListener(
    'pointerdown',
    () => {
      lastInputWasKeyboard = false;
    },
    true,
  );
}

/* ------------------------------------------------------------------ */
/* Button                                                              */
/* ------------------------------------------------------------------ */

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success';
export type ButtonSize = 'sm' | 'md';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  // 主按钮禁用时也保持实色（只用 cursor/无阴影区分）：半透明浅蓝看着像「坏掉的按钮」。
  // hover 用 brand-strong（比 brand 更深的蓝）而不是 90% 透明，深浅差看得见。
  primary:
    'bg-brand-solid text-white border border-transparent hover:bg-brand-solid-hover active:bg-brand-solid-hover shadow-card focus-visible:outline-brand disabled:opacity-100 disabled:hover:bg-brand-solid disabled:active:bg-brand-solid disabled:shadow-none',
  secondary:
    'bg-surface text-ink-soft border border-line hover:border-line-strong hover:bg-surface-hover hover:text-ink focus-visible:outline-brand disabled:opacity-50',
  ghost:
    'bg-transparent text-muted border border-transparent hover:bg-surface-hover hover:text-ink focus-visible:outline-brand disabled:opacity-50',
  danger:
    'bg-surface text-danger border border-danger-line hover:border-danger hover:bg-danger-soft focus-visible:outline-danger disabled:opacity-50',
  success:
    'bg-ok text-white border border-transparent hover:brightness-110 shadow-card focus-visible:outline-ok disabled:opacity-100',
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-2.5 text-mini gap-1.5 rounded-control',
  md: 'h-9 px-3.5 text-regular gap-2 rounded-control',
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leading?: ReactNode;
  trailing?: ReactNode;
}

export function Button({
  variant = 'secondary',
  size = 'sm',
  loading = false,
  leading,
  trailing,
  className = '',
  disabled,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`inline-flex shrink-0 select-none items-center justify-center font-medium whitespace-nowrap transition-colors duration-150 disabled:cursor-not-allowed ${BUTTON_VARIANTS[variant]} ${BUTTON_SIZES[size]} ${className}`}
      {...rest}
    >
      {loading ? <IconSpinner size={size === 'sm' ? 13 : 15} /> : leading}
      {children}
      {trailing}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Badge                                                               */
/* ------------------------------------------------------------------ */

export type BadgeTone = 'neutral' | 'brand' | 'ok' | 'warn' | 'danger' | 'accent';

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: 'bg-surface-sunken text-muted border-line',
  brand: 'bg-brand-soft text-brand-strong border-brand-line',
  ok: 'bg-ok-soft text-ok border-ok-line',
  warn: 'bg-warn-soft text-warn border-warn-line',
  danger: 'bg-danger-soft text-danger border-danger-line',
  // 紫色描边以前写死成 #ddd6fe（暗色下会变成一圈突兀的亮紫），现在走 accent-line 令牌
  accent: 'bg-accent-soft text-accent border-accent-line',
};

export function Badge({
  tone = 'neutral',
  className = '',
  children,
  dot = false,
  title,
}: {
  tone?: BadgeTone;
  className?: string;
  children: ReactNode;
  dot?: boolean;
  /** 悬停说明：徽标本身只有两三个字，原因写不下，放这儿 */
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-chip border px-1.5 py-[1px] text-caption font-medium whitespace-nowrap ${BADGE_TONES[tone]} ${className}`}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Card / Section                                                      */
/* ------------------------------------------------------------------ */

export function Card({
  className = '',
  children,
  as: Tag = 'section',
}: {
  className?: string;
  children: ReactNode;
  as?: 'section' | 'div' | 'article';
}) {
  return (
    <Tag className={`rise-in rounded-card border border-line bg-surface shadow-card ${className}`}>
      {children}
    </Tag>
  );
}

export function SectionLabel({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`text-caption font-semibold tracking-wider text-faint uppercase ${className}`}>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 三态辅助                                                            */
/* ------------------------------------------------------------------ */

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`shimmer rounded-chip ${className}`} />;
}

export function CardLoading({ label = '加载中…', rows = 2 }: { label?: string; rows?: number }) {
  return (
    <div className="space-y-2 px-4 py-3" role="status" aria-live="polite">
      <div className="text-mini text-muted">{label}</div>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-3.5 w-full" />
      ))}
    </div>
  );
}

export function CardError({
  message,
  onRetry,
  retryLabel = '重试',
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 px-4 py-3">
      <div className="flex min-w-0 items-start gap-2 text-mini text-danger">
        <span className="mt-[2px] inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-danger-soft text-[calc(10px*var(--font-scale))] font-bold">
          !
        </span>
        <span className="break-words">{message}</span>
      </div>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}

export function CardEmpty({ label, hint }: { label: string; hint?: string }) {
  return (
    <div className="px-4 py-5 text-center">
      <div className="text-mini font-medium text-muted">{label}</div>
      {hint ? <div className="mt-1 text-caption text-faint">{hint}</div> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Tooltip（统一 hover 提示：浅色浮层气泡 + 可选快捷键）                    */
/* ------------------------------------------------------------------ */

/** 气泡与目标元素的间距 */
const TIP_GAP = 6;
/** 气泡距视口边缘的最小留白 */
const TIP_MARGIN = 8;
/** 上方/下方剩余空间不足该值时就翻到另一侧 */
const TIP_MIN_SPACE = 34;

type TipPlacement = 'top' | 'bottom';

/**
 * 统一 hover 提示（浅色浮层气泡 + 可选快捷键）。
 *
 * 用 fixed + portal 渲染：顶栏按钮、被 `overflow-hidden` 裁剪的卡片里的提示
 * 都不会再被裁掉或顶出视口；上方空间不足时自动翻到下方。
 *
 * 两种形态：
 * - 默认单行（label）：按钮/图标用，居中、单行截断；
 * - 富内容（content）：传 ReactNode，渲染成左上对齐的圆角小卡片，支持多行元信息；
 *   相比浏览器原生 title，圆角/内边距/配色都跟主题走，不会蹦出一块白底直角系统气泡。
 */
export function Tooltip({
  label,
  content,
  shortcut,
  side = 'bottom',
  delayMs = 0,
  enabled = true,
  className = 'inline-flex',
  children,
}: {
  label?: string;
  /** 多行富提示：给了它就忽略 label（原生 title 做不到圆角与多行排版） */
  content?: ReactNode;
  shortcut?: string;
  side?: 'bottom' | 'top';
  /** 出现前的迟疑时间：整行/大块区域用 200ms 上下，鼠标划过时才不会一路弹气泡 */
  delayMs?: number;
  /**
   * 关掉提示。气泡是 portal 到 body 的 z-80，比弹窗还高一层：
   * 在「点开预览后仍压着原行」这种场景下必须主动关，否则会浮在弹窗上面挡内容。
   */
  enabled?: boolean;
  /** 包裹层样式：默认 inline-flex（跟按钮/链接同宽）；
   *  包整行按钮时传 `block w-full`，否则内部 w-full 只有文字那么宽，
   *  鼠标划过的底色会短一截（这就是「框架那么宽、背景阴影那么短」的原因）。 */
  className?: string;
  children: ReactNode;
}) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number; placement: TipPlacement } | null>(
    null,
  );
  // 关闭开关一落下就把已经浮出来的气泡收掉（不能只靠下一次 mouseleave）
  useEffect(() => {
    if (!enabled) setPos(null);
  }, [enabled]);

  /**
   * 依据锚点与气泡尺寸计算位置：
   * - 优先 side，空间不足则翻面；
   * - 水平按「气泡实际宽度」夹取到视口内，避免贴边时只露出一半。
   */
  const place = () => {
    const anchor = anchorRef.current;
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    const spaceAbove = rect.top;
    const spaceBelow = window.innerHeight - rect.bottom;
    let placement: TipPlacement = side;
    if (side === 'top' && spaceAbove < TIP_MIN_SPACE && spaceBelow > spaceAbove) {
      placement = 'bottom';
    } else if (side === 'bottom' && spaceBelow < TIP_MIN_SPACE && spaceAbove > spaceBelow) {
      placement = 'top';
    }
    const half = (tipRef.current?.offsetWidth ?? 0) / 2;
    const center = rect.left + rect.width / 2;
    const minLeft = TIP_MARGIN + half;
    const maxLeft = Math.max(window.innerWidth - TIP_MARGIN - half, minLeft);
    setPos({
      top: placement === 'top' ? rect.top - TIP_GAP : rect.bottom + TIP_GAP,
      left: Math.min(Math.max(center, minLeft), maxLeft),
      placement,
    });
  };

  const clearTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const show = () => {
    if (!enabled) return;
    clearTimer();
    if (delayMs <= 0) {
      place();
      return;
    }
    timerRef.current = setTimeout(place, delayMs);
  };

  const hide = () => {
    clearTimer();
    setPos(null);
  };

  // 卸载时清掉未触发的延时，避免对已卸载组件 setState
  useEffect(() => clearTimer, []);

  // 首次渲染后气泡才有宽度：布局阶段再夹一次，避免贴边裁切（不会闪烁）
  useLayoutEffect(() => {
    if (pos) place();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅在气泡首次出现时重新夹取
  }, [pos?.placement]);

  // 滚动/缩放时直接收起，避免气泡与目标错位
  useEffect(() => {
    if (!pos) return;
    const hideOnMove = () => setPos(null);
    window.addEventListener('scroll', hideOnMove, true);
    window.addEventListener('resize', hideOnMove);
    return () => {
      window.removeEventListener('scroll', hideOnMove, true);
      window.removeEventListener('resize', hideOnMove);
    };
  }, [pos]);

  const placementClass = pos?.placement === 'top' ? '-translate-y-full' : '';

  return (
    <span
      ref={anchorRef}
      className={className}
      onMouseEnter={show}
      onMouseLeave={hide}
      // 点下去就收起：气泡是在「你要对这东西做点什么」之前给提示的，
      // 手已经按下去了还留着，关掉浮层之后它就变成光标上的一句残影。
      onPointerDown={hide}
      onFocus={() => {
        // 鼠标点完按钮浏览器同样会派 focus，紧接着冒出一个「预览」气泡停在
        // 按钮上，看着就像关掉的窗口留下了残影。只有键盘过来才弹。
        if (!lastInputWasKeyboard) return;
        show();
      }}
      onBlur={hide}
    >
      {children}
      {enabled && pos
        ? createPortal(
            content ? (
              <span
                ref={tipRef}
                role="tooltip"
                style={{ top: pos.top, left: pos.left }}
                className={`tip-in pointer-events-none fixed z-[80] block w-max max-w-[260px] -translate-x-1/2 rounded-control border border-line bg-tooltip/95 px-3 py-2 text-left text-caption leading-relaxed text-tooltip-ink shadow-pop backdrop-blur-[2px] ${placementClass}`}
              >
                {content}
              </span>
            ) : (
              <span
                ref={tipRef}
                role="tooltip"
                style={{ top: pos.top, left: pos.left }}
                className={`pointer-events-none fixed z-[80] inline-flex max-w-[300px] -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-tooltip/95 px-2.5 py-1.5 text-mini font-medium leading-snug text-tooltip-ink shadow-pop backdrop-blur-[2px] ${placementClass}`}
              >
                <span className="truncate">{label}</span>
                {shortcut ? <span className="shrink-0 text-faint">{shortcut}</span> : null}
              </span>
            ),
            document.body,
          )
        : null}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Modal（居中弹窗：Esc / 点击遮罩关闭）                                */
/* ------------------------------------------------------------------ */

/** 弹窗内可聚焦元素：焦点陷阱与初始焦点都按这个顺序取 */
const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

export function Modal({
  title,
  subtitle,
  leading,
  actions,
  onClose,
  onEscape,
  children,
  footer,
  size = 'sm',
  padded = true,
  fullscreen = false,
}: {
  title: string;
  /** 标题下的第二行（类型 / 大小 / 时间）：和标题一起构成弹窗的信息头 */
  subtitle?: ReactNode;
  /** 标题左侧的类型图块（产物预览用），不传就是纯文字标题 */
  leading?: ReactNode;
  /** 标题栏右侧、关闭键左边的额外操作（预览的「全窗口」开关就放这儿） */
  actions?: ReactNode;
  onClose: () => void;
  /**
   * 接管 Esc。传了就不再直接关闭，由调用方决定——比如预览想「全窗口时先退回半窗口，
   * 再按一次才关」。要关就在里面调 onClose。
   */
  onEscape?: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /**
   * sm：确认类小弹窗；md：带说明/示例的引导类弹窗（太窄会把每行都挤断）；
   * lg：文档预览这类需要横向空间的内容
   */
  size?: 'sm' | 'md' | 'lg';
  /** 正文是否套用默认内边距。预览类内容自己排布留白时传 false */
  padded?: boolean;
  /**
   * 铺满整个窗口（预览的「全窗口」）：去圆角、去外边距、高度吃掉整屏，
   * 只让出桌面端窗口按钮那一条（--titlebar-h）。正文自己负责滚动。
   */
  fullscreen?: boolean;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);

  // 注意：这里监听的是 window 原生事件，必须用 DOM 的 KeyboardEvent，
  // 不能用 React 的合成事件类型（两者结构不兼容）。
  const onKeyDown = (event: globalThis.KeyboardEvent) => {
    if (event.key === 'Escape') {
      if (onEscape) onEscape();
      else onClose();
      return;
    }
    // 焦点陷阱：Tab 走到头就绕回弹窗内第一个元素，焦点不会跑到背后的页面上
    if (event.key !== 'Tab') return;
    const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
    if (!nodes || nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    // noUncheckedIndexedAccess：查不到节点就当作没有可聚焦元素
    if (!first || !last) return;
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === dialogRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };
  useEffect(() => {
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onKeyDown 每次渲染重建，依赖这两个回调即可
  }, [onClose, onEscape]);

  // 打开时把焦点搬进弹窗容器（不是第一个按钮：多数弹窗第一个可聚焦元素是「关闭」，
  // 焦点落那儿既念不出标题、回车还容易误关）。
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    // 按「怎么打开的」判断要不要还焦点，而不是「怎么关的」：
    // 鼠标点开、Esc 关掉很常见，但那次还原出来的 focus() 已经脱离用户手势，
    // 浏览器一律判成 :focus-visible——按钮上留一圈焦点环、依赖 focus-visible 的
    // 悬浮条也一直挂着，「窗口关了、框和按钮还在」就是这么来的。
    // 只有键盘打开的（回车/空格进弹窗），关闭时才把焦点还回去，这是无障碍该有的。
    const restoreFocus = lastInputWasKeyboard;
    dialogRef.current?.focus();
    return () => {
      if (!restoreFocus) return;
      previous?.focus?.({ preventScroll: true });
    };
  }, []);

  return (
    /* 独立窗口里窗口按钮浮在最上面一条：弹窗容器让出这条高度，
       否则弹窗标题行会压到 — □ ✕ 底下（遮罩不需要让，background 仍铺满整屏） */
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center ${
        fullscreen ? 'p-0' : 'p-4'
      }`}
      style={{
        paddingTop: fullscreen ? 'var(--titlebar-h, 0px)' : 'calc(var(--titlebar-h, 0px) + 1rem)',
      }}
    >
      <button
        type="button"
        aria-label="关闭弹窗"
        className="absolute inset-0 cursor-default bg-[#101828]/35 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        data-fullscreen={fullscreen ? 'true' : undefined}
        className={`rise-in relative flex w-full flex-col bg-surface ${
          fullscreen
            ? 'h-full max-h-none max-w-none rounded-none border-0'
            : `max-h-[calc(100dvh-2rem)] rounded-card border border-line shadow-pop ${
                /*
                  宽档也给固定像素：文档预览要在弹窗里留出「桌面上一张纸」的关系，
                  max-w-[54rem] 被 90% 基准压到 778px 后，720px 的纸只剩 7px 边，桌面的感觉就没了。
                */
                size === 'lg' ? 'max-w-[900px]' : size === 'md' ? 'max-w-[520px]' : 'max-w-[380px]'
              }`
        }`}
      >
        <div className="flex items-start gap-3 border-b border-line px-5 py-3">
          {leading ? <div className="mt-0.5 shrink-0">{leading}</div> : null}
          <div className="min-w-0 flex-1">
            {/*
              标题写 15px 而不是 text-regular：Tailwind 字号走 rem，默认 90% 基准下
              regular 只有 11.7px，弹窗标题比正文还小，层级是反的。
              这里按「标题 15 > 界面正文 13 > 副信息 12」给固定像素，不随界面缩放漂移。
            */}
            <h2
              className="truncate text-[calc(15px*var(--font-scale))] font-semibold text-ink"
              title={title}
            >
              {title}
            </h2>
            {subtitle ? (
              <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[calc(12px*var(--font-scale))] text-muted">
                {subtitle}
              </div>
            ) : null}
          </div>
          <div className="-mr-1 -mt-0.5 ml-auto flex shrink-0 items-start gap-1">
            {actions}
            <IconButton label="关闭" className="h-7 w-7" onClick={onClose}>
              <IconX size={14} />
            </IconButton>
          </div>
        </div>
        {/* 内容可能比窗口高（引导类弹窗），正文自己滚，标题与底部按钮始终可见。
            全窗口时不再套一层滚动：内容区（纸 / iframe）自己滚，两层滚动会互相抢滚轮。 */}
        <div
          className={`min-h-0 flex-1 ${
            fullscreen ? 'overflow-hidden' : 'overflow-y-auto'
          } ${padded && !fullscreen ? 'max-h-[calc(100dvh-9rem)] px-5 py-4' : ''}`}
        >
          {children}
        </div>
        {footer ? (
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* IconButton                                                          */
/* ------------------------------------------------------------------ */

export function IconButton({
  label,
  className = '',
  wrapperClassName = '',
  children,
  tone = 'default',
  tip = true,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  /**
   * 危险动作（删除 / 移除）用 `danger`：图标常驻红色、hover 走危险底色。
   * 不能靠外部 className 传 `text-danger` —— 它和基类的 `text-muted` 同权重，
   * 谁生效只看 Tailwind 产出顺序（实测被 muted 盖掉，红色的确认键看着像普通灰图标）。
   */
  tone?: 'default' | 'danger';
  /** 是否带 hover 气泡。菜单打开时传 false：气泡会压在刚展开的菜单上，看着像两条提示打架。 */
  tip?: boolean;
  /**
   * 带气泡时按钮外面会多一层 span（气泡锚点），`ml-auto` 这类**布局**类必须传给它，
   * 传在 className 上只会作用到 span 内部的按钮，推不开外层——弹窗关闭键就一直贴在标题后面。
   */
  wrapperClassName?: string;
}) {
  const toneClass =
    tone === 'danger'
      ? 'text-danger hover:bg-danger-soft hover:text-danger'
      : 'text-muted hover:bg-surface-hover hover:text-ink';
  const button = (
    <button
      type="button"
      aria-label={label}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-control transition-colors disabled:opacity-40 ${toneClass} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
  // 统一 hover 提示：所有图标按钮自带浮层气泡 tooltip（label 即提示文案）
  if (!tip) return button;
  return (
    <Tooltip label={label} side="top" className={`inline-flex shrink-0 ${wrapperClassName}`}>
      {button}
    </Tooltip>
  );
}
