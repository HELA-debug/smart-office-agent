/**
 * 桌面端（装到本机后的独立窗口）标题栏适配。
 *
 * 问题：以 `standalone` 打开时，Windows/macOS 会给一条浏览器画的标题栏（图标 + 名字 +
 * 窗口按钮），颜色由 `theme_color` 决定。这条栏是「浏览器的东西」——它在外壳的卡片式
 * 面板之外，还会自己占一条高度，看着像把网页塞进了一个套子里，和界面割裂。
 *
 * 做法：manifest 里声明 `window-controls-overlay`，让窗口按钮直接浮在网页右上角，
 * 页面自己铺满整个窗口。代价是必须自己给按钮让位，所以：
 *   · 这里把标题栏高度写成 CSS 变量 `--titlebar-h`（默认 0px，网页态完全不受影响）；
 *   · 各页面外壳的 `padding-top` 加上这个变量，于是外壳底色一直铺到窗口最上沿；
 *   · `.titlebar-drag-band` 在顶部留一条透明拖拽区，窗口照样能拖。
 *
 * 浏览器不支持 `windowControlsOverlay` 时变量保持 0，退化成原来的布局；
 * 老版本 Chromium 没有这个对象、但确实处于 overlay 模式的情况，由 tokens.css 里的
 * `@media (display-mode: window-controls-overlay)` 用 `env(titlebar-area-height)` 兜底。
 */

/** `navigator.windowControlsOverlay` 里我们真正用到的部分（lib.dom 还没带上它）。 */
export interface WindowControlsOverlayLike extends EventTarget {
  visible: boolean;
  getTitlebarAreaRect?: () => { height: number };
}

/** 标题栏最多让这么多位：双屏/缩放切换时高度偶尔会很夸张，不能把内容顶掉。 */
const MAX_INSET = 80;

/**
 * 从 overlay 对象算标题栏高度（px）。没激活、量不到、数值异常一律当 0。
 * 抽成纯函数是为了能直接单测边界，不用在 jsdom 里伪造整个 navigator。
 */
export function titlebarInset(overlay: WindowControlsOverlayLike | null | undefined): number {
  if (!overlay?.visible) return 0;
  const height = overlay.getTitlebarAreaRect?.().height ?? 0;
  if (!Number.isFinite(height) || height <= 0) return 0;
  return Math.min(Math.round(height), MAX_INSET);
}

/**
 * 把当前标题栏高度写进 `--titlebar-h`，并在窗口变化（拖到另一块屏、改缩放）时更新。
 * 返回清理函数，供 React effect 卸载时调用。
 *
 * 只在量到正数时才写内联变量；量不到（0）就把内联变量删掉，让 tokens.css 里
 * `--titlebar-h: env(titlebar-area-height, 0px)` 生效。曾经这里无条件写 `0px`，
 * 内联样式优先级高于样式表，于是 env() 兜底被永久压住——表现就是窗口按钮
 * 压着界面右上角的按钮，也就是「桌面端右上角有 bug」。
 */
export function applyTitlebarInset(): () => void {
  if (typeof document === 'undefined') return () => {};
  const root = document.documentElement;
  const overlay = (navigator as Navigator & { windowControlsOverlay?: WindowControlsOverlayLike })
    .windowControlsOverlay;

  // 浏览器根本没有这个能力：不写内联变量，留给 CSS 的 env() 兜底
  if (!overlay) {
    root.dataset.titlebar = 'browser';
    return () => {};
  }

  const update = () => {
    const inset = titlebarInset(overlay);
    if (inset > 0) root.style.setProperty('--titlebar-h', `${inset}px`);
    else root.style.removeProperty('--titlebar-h');
    root.dataset.titlebar = inset > 0 ? 'overlay' : 'browser';
  };
  update();
  overlay.addEventListener('geometrychange', update);
  return () => overlay.removeEventListener('geometrychange', update);
}
