/**
 * 主题、界面缩放、字号缩放、字重、字体样式。
 *
 * 默认深色（首次进入、没存过偏好时）；用户一旦切换就把选择写进本地。
 * 只改 `html` 上的 class、`--ui-scale`、`--font-scale`、`--ui-font-weight`、`--font-sans`：
 * 颜色、间距与字号全部由 `styles/tokens.css` 的令牌派生，组件不用感知当前偏好。
 * 用 useSyncExternalStore 暴露给 React，多个入口（顶栏、设置页）天然同步。
 *
 * 「页面缩放」与「字号缩放」是两个独立变量（用户明确要求拆开）：
 *   --ui-scale  → html font-size，rem 派生的一切（间距、控件、栏宽）
 *   --font-scale→ 只乘进 --text-* 令牌（文字大小）
 * 以前两者共用一个滑块，调字号会把整页排版一起放大，这版不再有此副作用。
 */

import { useSyncExternalStore } from 'react';
import { setThinkingView } from './thinking-pref';

export type ThemeMode = 'light' | 'dark';

const THEME_KEY = 'oa:theme';
const SCALE_KEY = 'oa:ui-scale';
const FONT_SCALE_KEY = 'oa:font-scale';
const WEIGHT_KEY = 'oa:font-weight';
const FAMILY_KEY = 'oa:font-family';

/** 界面缩放范围：只动间距、控件、容器（html 的 rem 基准），不动字号 */
export const UI_SCALE_MIN = 85;
export const UI_SCALE_MAX = 110;
export const UI_SCALE_DEFAULT = 90;

/**
 * 字号缩放范围：只动文字（`--font-scale` 乘进每个 --text-* 令牌），不动间距。
 *
 * 这两件事以前是同一个滑块（`--ui-scale` 同时是 html 的 font-size），
 * 于是「想看清字」和「想多放点内容」被迫绑在一起：调大字号，按钮、留白、栏宽
 * 一起胀，排版就跑样。现在拆成两个独立变量：
 *   界面缩放 → --ui-scale（html font-size，rem 派生的一切）
 *   字体大小 → --font-scale（px 派生的字号令牌）
 * 100 = 当前默认观感（字号令牌里已经内置 ×0.9 的历史基准）。
 */
export const FONT_SCALE_MIN = 85;
export const FONT_SCALE_MAX = 130;
export const FONT_SCALE_DEFAULT = 100;

/**
 * 字重：只调「正文与控件」的基准粗细。
 *
 * 语义类（.font-medium / .font-semibold / .font-bold）在 tokens.css 里
 * 写成「基准 + 一档」，所以调基准不会让标题和按钮的层级消失：
 * 常规 400 时 medium=500、semibold=600，与原来一模一样；调细或调粗整体平移。
 */
export const WEIGHT_MIN = 300;
export const WEIGHT_MAX = 600;
export const WEIGHT_DEFAULT = 400;

/**
 * 字体样式可选项。
 *
 * stack 里一律把「本机常见名」排在前面、同义名排后面（KaiTi / STKaiti / Kaiti SC）：
 * Windows、macOS 与国产 Linux 发行版对同一款字体的注册名不一样，
 * 少列一个就会在某个平台上悄悄回退到默认字体，用户以为「选了没反应」。
 * system 用 null：不改写 --font-sans，直接吃 index.css 里那套默认栈。
 */
export interface FontFamilyOption {
  key: string;
  label: string;
  /** 说明：给谁用、缺字体时回退到哪 */
  hint: string;
  stack: string | null;
}

export const FONT_FAMILIES: FontFamilyOption[] = [
  {
    key: 'system',
    label: '默认（系统黑体）',
    hint: '与当前一致：Windows 走微软雅黑，macOS 走苹方',
    stack: null,
  },
  {
    key: 'yahei',
    label: '微软雅黑',
    hint: '笔画更硬朗，屏幕小字最清楚；macOS / Linux 回退到系统黑体',
    stack: "'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', system-ui, sans-serif",
  },
  {
    key: 'source-han',
    label: '思源黑体',
    hint: '开源无衬线体，装了才有；没装回退到系统黑体',
    stack: "'Source Han Sans SC', 'Noto Sans SC', 'Microsoft YaHei', system-ui, sans-serif",
  },
  {
    key: 'songti',
    label: '宋体（衬线）',
    hint: '长文阅读更省眼，数字表格会显细；缺字体回退到系统衬线体',
    stack: "'Source Han Serif SC', 'Songti SC', 'SimSun', 'Noto Serif SC', serif",
  },
  {
    key: 'kaiti',
    label: '楷体',
    hint: '手写感，适合看稿；缺字体回退到宋体',
    stack: "'Kaiti SC', 'KaiTi', 'STKaiti', 'Noto Serif SC', serif",
  },
  {
    key: 'xingkai',
    label: '行楷',
    hint: '更潇洒的手写体，长段落略吃力；缺字体回退到楷体',
    stack: "'Xingkai SC', 'STXingkai', '华文行楷', 'KaiTi', 'Kaiti SC', serif",
  },
];

export const FONT_FAMILY_DEFAULT = 'system';

let theme: ThemeMode = 'light';
let scale = UI_SCALE_DEFAULT;
let fontScale = FONT_SCALE_DEFAULT;
let weight = WEIGHT_DEFAULT;
let family: string = FONT_FAMILY_DEFAULT;
let initialized = false;

const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function clampScale(value: number): number {
  if (!Number.isFinite(value)) return UI_SCALE_DEFAULT;
  return Math.min(UI_SCALE_MAX, Math.max(UI_SCALE_MIN, Math.round(value)));
}

/** 字号按 5 取整：0.85 / 0.9 / … / 1.3，够密又不至于「调一格没反应」。 */
function clampFontScale(value: number): number {
  if (!Number.isFinite(value)) return FONT_SCALE_DEFAULT;
  const snapped = Math.round(value / 5) * 5;
  return Math.min(FONT_SCALE_MAX, Math.max(FONT_SCALE_MIN, snapped));
}

/** 字重按 50 取整落在 300~600：400 是默认，太小在中文里等于缺笔画。 */
function clampWeight(value: number): number {
  if (!Number.isFinite(value)) return WEIGHT_DEFAULT;
  const snapped = Math.round(value / 50) * 50;
  return Math.min(WEIGHT_MAX, Math.max(WEIGHT_MIN, snapped));
}

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* 隐私模式下写不进去也不影响本次会话 */
  }
}

/** 浏览器 UI 的颜色（PWA 标题栏、移动端状态栏）：取窗口最外层的 --color-canvas。
 *  必须等于页面最上方那一块的颜色，否则装成桌面端后，屏幕上沿会多出一条
 *  「另一套配色」的横带，和下面的界面明显断层。 */
const THEME_COLOR: Record<ThemeMode, string> = {
  light: '#f3f5f9',
  dark: '#101317',
};

function applyTheme(next: ThemeMode) {
  const root = document.documentElement;
  root.classList.toggle('dark', next === 'dark');
  root.dataset.theme = next;
  applyThemeColor(next);
}

/**
 * 把 `meta[name=theme-color]` 改成当前主题的壳色。
 *
 * index.html 里写了两条 media 查询的 meta 兜住「JS 还没跑」的首屏；
 * 但用户可以在应用内手动切主题，和系统主题不一致时 media 就会选错，
 * 于是装成桌面端后标题栏是一条与界面不同的颜色——这里统一改掉。
 */
function applyThemeColor(next: ThemeMode) {
  const metas = document.querySelectorAll('meta[name="theme-color"]');
  metas.forEach((meta) => meta.setAttribute('content', THEME_COLOR[next]));
}

function applyScale(next: number) {
  document.documentElement.style.setProperty('--ui-scale', `${next}%`);
}

/** 字号缩写成无单位倍数：tokens.css 里 `calc(13px * 0.9 * var(--font-scale))` 直接乘。 */
function applyFontScale(next: number) {
  document.documentElement.style.setProperty('--font-scale', String(next / 100));
}

/** 字重写成一个变量：tokens.css 里 body 与字重语义类都读它。 */
function applyWeight(next: number) {
  document.documentElement.style.setProperty('--ui-font-weight', String(next));
}

/**
 * 字体样式通过改写 `--font-sans` 生效。
 *
 * 不直接给 body 写 font-family：项目里 `font-sans` 工具类、`.prose-docx`
 * 都读这个令牌，改令牌才能一处改、处处跟着变；选「默认」时把内联值删掉，
 * 让 CSS 里那套原始栈接管（否则会在 html 上留一个空值把默认栈顶掉）。
 */
function applyFamily(next: string) {
  const option = FONT_FAMILIES.find((item) => item.key === next) ?? FONT_FAMILIES[0];
  const root = document.documentElement;
  if (option?.stack) {
    root.style.setProperty('--font-sans', option.stack);
  } else {
    root.style.removeProperty('--font-sans');
  }
}

/** 首屏渲染前调用（main.tsx）：避免先闪一下浅色再切深色。 */
export function initTheme() {
  if (initialized) return;
  initialized = true;
  const stored = readStorage(THEME_KEY);
  if (stored === 'light' || stored === 'dark') {
    theme = stored;
  } else {
    // 没存过偏好就按深色起步：长时间盯着的办公界面，暗底更省眼；
    // 用户在顶栏/设置页改过之后，一律听他的。
    theme = 'dark';
  }
  const storedScale = Number(readStorage(SCALE_KEY));
  scale = storedScale ? clampScale(storedScale) : UI_SCALE_DEFAULT;
  const storedFontScale = Number(readStorage(FONT_SCALE_KEY));
  fontScale = storedFontScale ? clampFontScale(storedFontScale) : FONT_SCALE_DEFAULT;
  weight = clampWeight(Number(readStorage(WEIGHT_KEY)) || WEIGHT_DEFAULT);
  const storedFamily = readStorage(FAMILY_KEY);
  family = FONT_FAMILIES.some((item) => item.key === storedFamily)
    ? (storedFamily as string)
    : FONT_FAMILY_DEFAULT;
  applyTheme(theme);
  applyScale(scale);
  applyFontScale(fontScale);
  applyWeight(weight);
  applyFamily(family);
}

export function getTheme(): ThemeMode {
  return theme;
}

export function setTheme(next: ThemeMode) {
  theme = next;
  applyTheme(next);
  writeStorage(THEME_KEY, next);
  emit();
}

export function toggleTheme() {
  setTheme(theme === 'dark' ? 'light' : 'dark');
}

export function getUiScale(): number {
  return scale;
}

export function setUiScale(next: number) {
  scale = clampScale(next);
  applyScale(scale);
  writeStorage(SCALE_KEY, String(scale));
  emit();
}

export function resetUiScale() {
  setUiScale(UI_SCALE_DEFAULT);
}

export function getFontScale(): number {
  return fontScale;
}

export function setFontScale(next: number) {
  fontScale = clampFontScale(next);
  applyFontScale(fontScale);
  writeStorage(FONT_SCALE_KEY, String(fontScale));
  emit();
}

export function resetFontScale() {
  setFontScale(FONT_SCALE_DEFAULT);
}

export function getFontWeight(): number {
  return weight;
}

export function setFontWeight(next: number) {
  weight = clampWeight(next);
  applyWeight(weight);
  writeStorage(WEIGHT_KEY, String(weight));
  emit();
}

export function getFontFamily(): string {
  return family;
}

export function setFontFamily(next: string) {
  family = FONT_FAMILIES.some((item) => item.key === next) ? next : FONT_FAMILY_DEFAULT;
  applyFamily(family);
  writeStorage(FAMILY_KEY, family);
  emit();
}

/** 一键回到出厂外观：主题深色、界面 90%、字号 100%、字重 400、默认字体、思考过程全显示。 */
export function resetAppearance() {
  setThinkingView('full');
  setTheme('dark');
  setUiScale(UI_SCALE_DEFAULT);
  setFontScale(FONT_SCALE_DEFAULT);
  setFontWeight(WEIGHT_DEFAULT);
  setFontFamily(FONT_FAMILY_DEFAULT);
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 当前主题（组件内使用；与顶栏开关实时同步）。 */
export function useTheme(): ThemeMode {
  return useSyncExternalStore(subscribe, getTheme, () => 'light' as ThemeMode);
}

/** 当前界面缩放百分比。 */
export function useUiScale(): number {
  return useSyncExternalStore(subscribe, getUiScale, () => UI_SCALE_DEFAULT);
}

/** 当前字号缩放百分比（100 = 默认观感）。 */
export function useFontScale(): number {
  return useSyncExternalStore(subscribe, getFontScale, () => FONT_SCALE_DEFAULT);
}

/** 当前基准字重（300~600）。 */
export function useFontWeight(): number {
  return useSyncExternalStore(subscribe, getFontWeight, () => WEIGHT_DEFAULT);
}

/** 当前字体样式 key（见 FONT_FAMILIES）。 */
export function useFontFamily(): string {
  return useSyncExternalStore(subscribe, getFontFamily, () => FONT_FAMILY_DEFAULT);
}
