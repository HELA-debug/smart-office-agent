/**
 * 文档格式（doc style）：输入区「文档格式」面板的唯一事实来源。
 *
 * 这一组就是 WPS / Word 工具栏上最常动的那一排：字体、字号、字型（B I U）、
 * 行距、首行缩进、对齐方式。**不发明 WPS 没有的东西**——用户认的是那几张下拉，
 * 换一套自造的名字只会让人从头学一遍。
 *
 * 与后端 `services/doc_render.py::preset_with_style` 一一对应：
 * - `font` 是中文字体（后端在 `doc_lexicon.FONTS` 里能查到才生效）；
 * - `size` 传号数（「小四」），后端认号数也认 pt；
 * - `line` 传倍数字符串或「固定值28磅」，交给后端 `resolve_line` 解析；
 * - `indent_chars` 是首行缩进几个字符（0 = 顶格）；
 * - `align` 只给四档：两端对齐 / 左对齐 / 居中 / 右对齐。
 *
 * 每一个字段都是「没选就不发」：用户只改字号时，字体、行距、缩进仍由 Agent 按
 * 版式预设决定。整份为空 = 全交给 Agent（这也是默认）。
 */

/** 中文字体：只列国内办公文档真正常用的几种，后端 `FONTS` 里都有。 */
export const DOC_FONTS = ['宋体', '仿宋_GB2312', '黑体', '楷体', '微软雅黑'] as const;
export type DocFont = (typeof DOC_FONTS)[number];

/** 字号：按中文字号从大到小。数值是后端号数表里的键，不是 pt——别在这里写死磅值。 */
export const DOC_SIZES = ['二号', '三号', '四号', '小四', '五号', '小五'] as const;
export type DocSize = (typeof DOC_SIZES)[number];

/** 行距：三个倍数值 + 一个固定值（公文常用 28 磅）。 */
export const DOC_LINES = [
  { value: '1.0', label: '单倍' },
  { value: '1.15', label: '1.15 倍' },
  { value: '1.5', label: '1.5 倍' },
  { value: '2.0', label: '2 倍' },
  { value: '固定值28磅', label: '固定值 28 磅' },
] as const;

/** 对齐方式：和 WPS 段落对话框里的四个按钮同序。 */
export const DOC_ALIGNS = [
  { value: 'justify', label: '两端对齐' },
  { value: 'left', label: '左对齐' },
  { value: 'center', label: '居中' },
  { value: 'right', label: '右对齐' },
] as const;
export type DocAlign = (typeof DOC_ALIGNS)[number]['value'];

/** 首行缩进（字符）：中文正文的「空两格」就是 2。 */
export const DOC_INDENTS = [
  { value: '0', label: '不缩进' },
  { value: '1', label: '1 字符' },
  { value: '2', label: '2 字符' },
] as const;

export interface DocStyle {
  font?: DocFont;
  size?: DocSize;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  line?: string;
  indent_chars?: string;
  align?: DocAlign;
}

/**
 * 预设默认值：用户一项都不选时，文档就是照这套排的。
 *
 * 事实来源不在这里，而在后端 `doc_render.PRESETS`（report 那一档：宋体、小四、
 * 1.5 倍行距、两端对齐、首行缩进 2 字符）。这份常量只做一件事——把「当前默认」
 * 显示到面板上，好让用户知道不选的时候会发生什么。**不往请求里塞这些值**：
 * 一旦默认值也当成用户选择发出去，Agent 就再也不能按文档类型换版式
 * （公文要仿宋三号、资料要五号），「不选 = 交给 Agent」等于被废掉。
 */
export const DOC_DEFAULTS = {
  font: '宋体',
  size: '小四',
  line: '1.5',
  indent_chars: '2',
  align: 'justify',
} as const;

/** 字体名在窄面板里不写全称：`仿宋_GB2312` 太长，连面板上的 chip 也显示「仿宋」。 */
export function docFontLabel(font: DocFont): string {
  return font === '仿宋_GB2312' ? '仿宋' : font;
}

/** 底部那一行的组成项。 */
export interface DocStyleLineItem {
  /** 字体 / 字号 / 字型 / 行距 / 缩进 / 对齐；同一项在一行里只出现一次 */
  key: 'font' | 'size' | 'marks' | 'line' | 'indent' | 'align';
  /** 面板上的叫法：「1.5 倍」「2 字符」「两端对齐」 */
  text: string;
  /** true = 这一项是用户自己定的，不是预设默认 */
  overridden: boolean;
}

/** 未设值时用预设默认补齐——底部要显示的是完整的一份样式，不是残缺的几项。 */
function pickStyle(style: DocStyle): {
  font: DocFont;
  size: DocSize;
  line: string;
  indent_chars: string;
  align: DocAlign;
} {
  return {
    font: style.font ?? DOC_DEFAULTS.font,
    size: style.size ?? DOC_DEFAULTS.size,
    line: style.line ?? DOC_DEFAULTS.line,
    indent_chars: style.indent_chars ?? DOC_DEFAULTS.indent_chars,
    align: style.align ?? DOC_DEFAULTS.align,
  };
}

/**
 * 面板底部「一行看全」：**完整的一份样式**，用户改过的那一项就地替换成新值。
 *
 * 不是只列动过的项。只列「缩进 1 字符」的话，其余四项此刻是什么用户就看不见了——
 * 面板底部要回答的是「这份稿子最终排成什么样」，默认值和改动值在这里是同一条线上的
 * 不同取值：改了哪项换哪项，没改的照预设走（宋体 · 小四 · 1.5 倍 · 2 字符 · 两端对齐）。
 *
 * 字型是唯一的例外：预设里没有字型，全部关掉时干脆不占位，
 * 否则会出现「宋体 · 小四 · 无 · 1.5 倍」这种读起来像出错的写法。
 */
export function docStyleLine(style: DocStyle): DocStyleLineItem[] {
  const merged = pickStyle(style);
  const items: DocStyleLineItem[] = [
    { key: 'font', text: docFontLabel(merged.font), overridden: Boolean(style.font) },
    { key: 'size', text: merged.size, overridden: Boolean(style.size) },
  ];

  const marks = [style.bold && 'B', style.italic && 'I', style.underline && 'U'].filter(
    Boolean,
  ) as string[];
  if (marks.length > 0) items.push({ key: 'marks', text: marks.join(' '), overridden: true });

  const line = DOC_LINES.find((item) => item.value === merged.line);
  items.push({ key: 'line', text: line?.label ?? merged.line, overridden: Boolean(style.line) });

  const indent = DOC_INDENTS.find((item) => item.value === merged.indent_chars);
  items.push({
    key: 'indent',
    text: indent?.label ?? `${merged.indent_chars} 字符`,
    overridden: style.indent_chars !== undefined,
  });

  const align = DOC_ALIGNS.find((item) => item.value === merged.align);
  items.push({
    key: 'align',
    text: align?.label ?? merged.align,
    overridden: Boolean(style.align),
  });

  return items;
}

/**
 * 整行拼成一句，给 title / 测试 / 需要纯文本的地方用：
 * 全默认时前面带「默认」，动过任何一项就不带——那时候它已经不是默认样式了。
 */
export function docStyleText(style: DocStyle): string {
  const body = docStyleLine(style)
    .map((item) => item.text)
    .join(' · ');
  return hasDocStyle(style) ? body : `默认 ${body}`;
}

export const EMPTY_DOC_STYLE: DocStyle = {};

/** 只在真的选了值时才发出去：空对象等于「这一轮不干预」。 */
export function compactDocStyle(style: DocStyle): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (style.font) out.font = style.font;
  if (style.size) out.size = style.size;
  if (style.bold) out.bold = true;
  if (style.italic) out.italic = true;
  if (style.underline) out.underline = true;
  if (style.line) out.line = style.line;
  if (style.indent_chars) out.indent_chars = Number(style.indent_chars);
  if (style.align) out.align = style.align;
  return out;
}

export function hasDocStyle(style: DocStyle): boolean {
  return Object.keys(compactDocStyle(style)).length > 0;
}

/**
 * 收起状态下那一行右侧显示的摘要：只报「动过几项」，不把值全列出来——
 * 一行宽度有限，列全了必被省略号截断（「宋体 · 小四 · 加粗 · 1.5 倍…」看不出改了什么）。
 */
export function docStyleSummary(style: DocStyle): string {
  const count =
    (style.font ? 1 : 0) +
    (style.size ? 1 : 0) +
    (style.bold || style.italic || style.underline ? 1 : 0) +
    (style.line ? 1 : 0) +
    (style.indent_chars ? 1 : 0) +
    (style.align ? 1 : 0);
  return count > 0 ? `已设 ${count} 项` : '跟随文档';
}
