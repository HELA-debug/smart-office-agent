/**
 * 外观偏好（主题 / 界面缩放 / 字号 / 字重 / 字体样式）落点必须在 html 上，
 * 否则组件各自缓存一份，改一处别处不跟着变。
 *
 * 其中「界面缩放」与「字号」必须是两个互不干扰的变量：
 * 前者写 --ui-scale（html font-size，间距与控件），后者写 --font-scale（只乘字号）。
 */
import { beforeEach, describe, expect, it } from 'vitest';
import {
  FONT_FAMILIES,
  FONT_SCALE_DEFAULT,
  UI_SCALE_DEFAULT,
  WEIGHT_DEFAULT,
  getFontFamily,
  getFontScale,
  getFontWeight,
  getUiScale,
  resetAppearance,
  setFontFamily,
  setFontScale,
  setFontWeight,
  setUiScale,
} from './theme';

const root = () => document.documentElement;

beforeEach(() => {
  window.localStorage.clear();
  root().removeAttribute('style');
  root().classList.remove('dark');
  resetAppearance();
});

describe('字体粗细', () => {
  it('写进 --ui-font-weight 并落在本地（刷新后还在）', () => {
    setFontWeight(500);
    expect(root().style.getPropertyValue('--ui-font-weight')).toBe('500');
    expect(window.localStorage.getItem('oa:font-weight')).toBe('500');
    expect(getFontWeight()).toBe(500);
  });

  it('按 50 取整并夹在 300~600：太细中文会缺笔画，太粗整页糊成一团', () => {
    setFontWeight(320);
    expect(getFontWeight()).toBe(300);
    setFontWeight(900);
    expect(getFontWeight()).toBe(600);
    setFontWeight(Number.NaN);
    expect(getFontWeight()).toBe(WEIGHT_DEFAULT);
  });
});

describe('界面缩放与字号互相独立', () => {
  it('字号只写 --font-scale，不动 --ui-scale', () => {
    setUiScale(90);
    setFontScale(130);
    expect(root().style.getPropertyValue('--font-scale')).toBe('1.3');
    expect(root().style.getPropertyValue('--ui-scale')).toBe('90%');
    expect(getUiScale()).toBe(90);
    expect(window.localStorage.getItem('oa:font-scale')).toBe('130');
  });

  it('界面缩放只写 --ui-scale，不动 --font-scale', () => {
    setFontScale(110);
    setUiScale(110);
    expect(root().style.getPropertyValue('--ui-scale')).toBe('110%');
    expect(root().style.getPropertyValue('--font-scale')).toBe('1.1');
    expect(getFontScale()).toBe(110);
  });

  it('字号按 5 取整并夹在 85~130：太小读不清，太大整页都得重排', () => {
    setFontScale(101);
    expect(getFontScale()).toBe(100);
    setFontScale(60);
    expect(getFontScale()).toBe(85);
    setFontScale(400);
    expect(getFontScale()).toBe(130);
    setFontScale(Number.NaN);
    expect(getFontScale()).toBe(FONT_SCALE_DEFAULT);
  });

  it('旧的 --ui-scale 记忆照旧生效：老用户升级后版式不变', () => {
    window.localStorage.setItem('oa:ui-scale', '100');
    expect(UI_SCALE_DEFAULT).toBe(90);
    resetAppearance();
    setUiScale(100);
    expect(getUiScale()).toBe(100);
  });
});

describe('字体样式', () => {
  it('选一套字族会改写 --font-sans，body 与 font-sans 工具类一起跟着变', () => {
    const kaiti = FONT_FAMILIES.find((item) => item.key === 'kaiti');
    setFontFamily('kaiti');
    expect(root().style.getPropertyValue('--font-sans')).toContain('KaiTi');
    expect(kaiti?.stack).toContain('KaiTi');
    expect(window.localStorage.getItem('oa:font-family')).toBe('kaiti');
  });

  it('选回默认要删掉内联变量，否则会把 CSS 里的原始字体栈顶掉', () => {
    setFontFamily('xingkai');
    expect(root().style.getPropertyValue('--font-sans')).not.toBe('');
    setFontFamily('system');
    expect(root().style.getPropertyValue('--font-sans')).toBe('');
    expect(getFontFamily()).toBe('system');
  });

  it('存了个不认识的 key（旧版本残留）就回落到默认，不把界面弄成空白字体', () => {
    setFontFamily('comic-sans');
    expect(getFontFamily()).toBe('system');
  });
});

describe('恢复默认外观', () => {
  it('五项一起回到初始值：深色、界面 90%、字号 100%、400、默认字体', () => {
    setUiScale(100);
    setFontScale(130);
    setFontWeight(600);
    setFontFamily('songti');
    resetAppearance();

    expect(root().classList.contains('dark')).toBe(true);
    expect(getUiScale()).toBe(90);
    expect(getFontScale()).toBe(FONT_SCALE_DEFAULT);
    expect(root().style.getPropertyValue('--font-scale')).toBe('1');
    expect(getFontWeight()).toBe(WEIGHT_DEFAULT);
    expect(getFontFamily()).toBe('system');
    expect(root().style.getPropertyValue('--ui-font-weight')).toBe('400');
  });
});
