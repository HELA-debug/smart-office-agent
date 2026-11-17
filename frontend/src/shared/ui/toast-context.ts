import { createContext, useContext } from 'react';

/**
 * 轻提示（Toast）的契约层：只放类型与 context，不放组件。
 *
 * 与组件分文件是为了两点：
 *   1. `Toast.tsx` 只导出组件，满足 react-refresh（文件内混导出 hook 会被判为不可热更新）；
 *   2. 组件想弹提示时只 import `useToast`，不必把 Provider 一起拖进依赖。
 */

export type ToastTone = 'info' | 'ok' | 'warn' | 'danger';

export interface ToastOptions {
  tone?: ToastTone;
  /** 自动消失时间（ms），传 0 表示常驻直到手动关闭。默认 3200。 */
  duration?: number;
}

export interface ToastApi {
  /** 弹出一条提示，返回 id（需要提前收起时传给 dismiss）。 */
  show: (message: string, options?: ToastOptions) => string;
  dismiss: (id: string) => void;
}

/**
 * 没有 Provider 时的降级实现：单测里单独渲染某个组件、嵌入预览等场景都能安全调用，
 * 调用方不需要先判断「有没有 Provider」。
 */
const NOOP_TOAST: ToastApi = { show: () => '', dismiss: () => undefined };

export const ToastContext = createContext<ToastApi>(NOOP_TOAST);

/** 弹出轻提示。放在 shared/ui，任何 feature 都可以直接用。 */
export function useToast(): ToastApi {
  return useContext(ToastContext);
}
