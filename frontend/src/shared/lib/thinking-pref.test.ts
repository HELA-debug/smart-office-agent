import { beforeEach, describe, expect, it } from 'vitest';
import {
  THINKING_VIEW_OPTIONS,
  getThinkingView,
  resetThinkingView,
  setThinkingView,
} from './thinking-pref';

describe('思考过程显示偏好', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setThinkingView('full');
  });

  it('默认完全显示：不设也能用，且不乱改用户的对话', () => {
    expect(getThinkingView()).toBe('full');
  });

  it('切换后落到 localStorage，下次打开还是这档', () => {
    setThinkingView('brief');
    expect(getThinkingView()).toBe('brief');
    expect(window.localStorage.getItem('oa.thinking_view')).toBe('brief');
  });

  it('恢复默认回到完全显示', () => {
    setThinkingView('off');
    resetThinkingView();
    expect(getThinkingView()).toBe('full');
  });

  it('存了脏值不炸，退回默认', () => {
    window.localStorage.setItem('oa.thinking_view', 'super-detailed');
    // 直接调用也走同一套校验
    setThinkingView('super-detailed' as never);
    expect(getThinkingView()).toBe('full');
  });

  it('三档都在选项里，顺序是「全量 → 精简 → 关闭」', () => {
    expect(THINKING_VIEW_OPTIONS.map((item) => item.value)).toEqual(['full', 'brief', 'off']);
  });
});
