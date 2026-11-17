import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { IconAlertTriangle, IconCheckCircle, IconInfo, IconX } from './Icons';
import { ToastContext } from './toast-context';
import type { ToastApi, ToastOptions, ToastTone } from './toast-context';
import type { ReactNode } from 'react';

/**
 * 全局轻提示（Toast）：复制成功、删除结果、后台失败这类「做了什么」的短反馈。
 *
 * 设计取舍：
 *   - 无第三方依赖，用 portal + fixed 挂在 body 上，不受任何父级 overflow 裁剪；
 *   - 容器常驻（哪怕没有提示），这样 aria-live 区域在内容插入时才会被读屏播报；
 *   - 容器 `pointer-events-none`、每条 `pointer-events-auto`：不挡住底下的界面，
 *     但关闭按钮仍然可点；
 *   - 危险提示用 role="alert"（打断式播报），其余用 role="status"（ polite ）。
 */

const DEFAULT_DURATION = 3200;
/** 同屏最多几条：超过就挤掉最早的一条，避免刷屏盖住整页 */
const MAX_VISIBLE = 3;

interface ToastItem {
  id: string;
  message: string;
  tone: ToastTone;
  duration: number;
}

const TONE_ICON: Record<ToastTone, typeof IconInfo> = {
  info: IconInfo,
  ok: IconCheckCircle,
  warn: IconAlertTriangle,
  danger: IconAlertTriangle,
};

const TONE_ICON_CLASS: Record<ToastTone, string> = {
  info: 'text-brand',
  ok: 'text-ok',
  warn: 'text-warn',
  danger: 'text-danger',
};

const TONE_BORDER: Record<ToastTone, string> = {
  info: 'border-line',
  ok: 'border-ok-line',
  warn: 'border-warn-line',
  danger: 'border-danger-line',
};

/** 单条提示：纯展示，可脱离 Provider 单独用（也方便单测）。 */
export function Toast({
  message,
  tone = 'info',
  onClose,
}: {
  message: string;
  tone?: ToastTone;
  onClose: () => void;
}) {
  const Icon = TONE_ICON[tone];
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={`rise-in pointer-events-auto flex items-start gap-2 rounded-card border bg-surface px-3 py-2 text-ink shadow-pop ${TONE_BORDER[tone]}`}
    >
      <Icon size={15} className={`mt-[1px] shrink-0 ${TONE_ICON_CLASS[tone]}`} />
      <span className="min-w-0 flex-1 break-words text-mini">{message}</span>
      <button
        type="button"
        aria-label="关闭提示"
        onClick={onClose}
        className="-mr-1 shrink-0 rounded-control p-1 text-faint transition-colors hover:bg-surface-hover hover:text-ink"
      >
        <IconX size={12} />
      </button>
    </div>
  );
}

/** 轻提示宿主：挂在应用根部（app/providers.tsx），全站共用一处提示栈。 */
export function ToastProvider({
  children,
  max = MAX_VISIBLE,
}: {
  children: ReactNode;
  max?: number;
}) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef(new Map<string, number>());
  const seq = useRef(0);

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const show = useCallback(
    (message: string, options: ToastOptions = {}) => {
      const id = `toast_${++seq.current}`;
      const item: ToastItem = {
        id,
        message,
        tone: options.tone ?? 'info',
        duration: options.duration ?? DEFAULT_DURATION,
      };
      setItems((prev) => [...prev, item].slice(-max));
      if (item.duration > 0) {
        timers.current.set(
          id,
          window.setTimeout(() => dismiss(id), item.duration),
        );
      }
      return id;
    },
    [dismiss, max],
  );

  // 卸载时清掉全部计时器：否则定时器会在组件销毁后继续触发 setState
  useEffect(
    () => () => {
      timers.current.forEach((timer) => window.clearTimeout(timer));
      timers.current.clear();
    },
    [],
  );

  const api = useMemo<ToastApi>(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div
          aria-live="polite"
          aria-atomic="false"
          className="pointer-events-none fixed right-4 bottom-4 z-[90] flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2"
        >
          {items.map((item) => (
            <Toast
              key={item.id}
              message={item.message}
              tone={item.tone}
              onClose={() => dismiss(item.id)}
            />
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}
