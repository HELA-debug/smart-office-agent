/**
 * 标题栏让位：算高度要稳（量不到就 0），写变量要能跟着窗口变化刷新。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { applyTitlebarInset, titlebarInset } from './titlebar';
import type { WindowControlsOverlayLike } from './titlebar';

function overlay(visible: boolean, height: number): WindowControlsOverlayLike {
  return Object.assign(new EventTarget(), {
    visible,
    getTitlebarAreaRect: () => ({ height }),
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute('data-titlebar');
  document.documentElement.style.removeProperty('--titlebar-h');
});

describe('titlebarInset', () => {
  it('没有 overlay 能力 / 没激活时都是 0', () => {
    expect(titlebarInset(undefined)).toBe(0);
    expect(titlebarInset(null)).toBe(0);
    expect(titlebarInset(overlay(false, 32))).toBe(0);
  });

  it('量到的整数高度直接用', () => {
    expect(titlebarInset(overlay(true, 32))).toBe(32);
  });

  it('量不到或数值异常时退回 0，不会让内容凭空下移', () => {
    expect(titlebarInset(overlay(true, 0))).toBe(0);
    expect(titlebarInset(overlay(true, -8))).toBe(0);
    expect(titlebarInset(overlay(true, Number.NaN))).toBe(0);
    expect(titlebarInset(Object.assign(new EventTarget(), { visible: true }))).toBe(0);
  });

  it('异常大的高度封顶，双屏切换时不把内容顶出屏幕', () => {
    expect(titlebarInset(overlay(true, 400))).toBe(80);
  });
});

describe('applyTitlebarInset', () => {
  it('把高度写进 --titlebar-h，并跟着 geometrychange 更新', () => {
    const fake = overlay(true, 34);
    vi.stubGlobal('navigator', { ...navigator, windowControlsOverlay: fake });

    const dispose = applyTitlebarInset();
    const root = document.documentElement;
    expect(root.style.getPropertyValue('--titlebar-h')).toBe('34px');
    expect(root.dataset.titlebar).toBe('overlay');

    // 用户把窗口拖到另一块屏：退出 overlay
    Object.defineProperty(fake, 'visible', { value: false, configurable: true });
    fake.dispatchEvent(new Event('geometrychange'));
    // 不是写 0px：内联样式会压住 tokens.css 里的 env() 兜底，得把属性删掉
    expect(root.style.getPropertyValue('--titlebar-h')).toBe('');
    expect(root.dataset.titlebar).toBe('browser');

    dispose();
  });

  it('量到 0 时清掉内联变量，交给 CSS 的 env() 兜底（桌面端右上角被压住的回归）', () => {
    // 有些 Chromium 在 overlay 刚生效时 getTitlebarAreaRect().height 还是 0。
    // 旧实现这时写死 `--titlebar-h: 0px`，内联优先级更高 → env(titlebar-area-height)
    // 永远不生效 → 界面顶到窗口按钮底下（— □ ✕ 压住主题/右栏按钮）。
    const fake = overlay(true, 0);
    vi.stubGlobal('navigator', { ...navigator, windowControlsOverlay: fake });
    document.documentElement.style.setProperty('--titlebar-h', '34px'); // 上一轮的残留

    const dispose = applyTitlebarInset();
    expect(document.documentElement.style.getPropertyValue('--titlebar-h')).toBe('');
    dispose();
  });

  it('浏览器没有这个能力时不写内联变量（留给 CSS 的 env() 兜底）', () => {
    vi.stubGlobal('navigator', { ...navigator });

    const dispose = applyTitlebarInset();
    expect(document.documentElement.style.getPropertyValue('--titlebar-h')).toBe('');
    expect(document.documentElement.dataset.titlebar).toBe('browser');
    dispose();
  });
});
