/**
 * 「思考过程」显示多少：完全显示 / 只看主要步骤 / 不显示。
 *
 * 为什么要做成设置：同一段推理，写代码的人想看清每一步，给领导演示时只想看结论。
 * 之前是写死的「折叠一行 + 点开全文」，谁都不能改，长会话里那几行过程还挤占正文。
 *
 * 存在本地：这是显示偏好，跟账号无关；换台电脑想换回去也不用同步。
 */

export type ThinkingView = 'full' | 'brief' | 'off';

import { useSyncExternalStore } from 'react';

const STORAGE_KEY = 'oa.thinking_view';

export const THINKING_VIEW_OPTIONS: { value: ThinkingView; label: string; note: string }[] = [
  { value: 'full', label: '完全显示', note: '决策行、计划与每一步工具调用都摊开' },
  { value: 'brief', label: '只看主要步骤', note: '留决策行与计划主线，工具明细和旁白收走' },
  { value: 'off', label: '不显示', note: '对话里只留回复与产物，过程全收走' },
];

const VALUES: ThinkingView[] = ['full', 'brief', 'off'];

function isView(value: unknown): value is ThinkingView {
  return typeof value === 'string' && (VALUES as string[]).includes(value);
}

function read(): ThinkingView {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return isView(raw) ? raw : 'full';
  } catch {
    return 'full';
  }
}

let current: ThinkingView = read();
const listeners = new Set<() => void>();

export function getThinkingView(): ThinkingView {
  return current;
}

export function setThinkingView(next: ThinkingView) {
  current = isView(next) ? next : 'full';
  try {
    window.localStorage.setItem(STORAGE_KEY, current);
  } catch {
    /* 隐私模式下写不进去：本次会话仍然生效 */
  }
  listeners.forEach((listener) => listener());
}

export function subscribeThinkingView(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function resetThinkingView() {
  setThinkingView('full');
}

/** 组件内订阅：设置页一改，已有对话立刻跟着变，不用刷新。 */
export function useThinkingView(): ThinkingView {
  return useSyncExternalStore(subscribeThinkingView, getThinkingView, () => 'full' as ThinkingView);
}
