import { Fragment, type ReactNode } from 'react';
import {
  DOC_ALIGNS,
  DOC_DEFAULTS,
  DOC_FONTS,
  DOC_INDENTS,
  DOC_LINES,
  DOC_SIZES,
  docFontLabel,
  docStyleLine,
  docStyleText,
  hasDocStyle,
} from '../../../shared/config/doc-style';
import { Button } from '../../../shared/ui/primitives';
import type { DocStyle } from '../../../shared/config/doc-style';

/**
 * 「文档格式」二级面板：字体 / 字号 / 字型 / 行距 / 首行缩进 / 对齐。
 *
 * 参照的是 WPS 段落与字体工具栏，不是自造一套：
 * - 字体、字号、行距、缩进、对齐各一行，选中的那项实心高亮——和下拉里「当前值」
 *   的读法一致；
 * - 字型是 B / I / U 三个可独立开关的按钮（和工具栏一样能叠着用）；
 * - 每一项都可以「不选」：不选的那一项就交给 Agent 按文档类型自己判断。
 *
 * 预设默认值（宋体 / 小四 / 1.5 倍 / 两端对齐 / 缩进 2 字符）用**浅色底**标出来，
 * 而不是当成选中态：选中意味着「这一轮我定了，别改」（蓝底 + 实线），默认意味着
 * 「不出声就按这个来、但 Agent 可以按文档类型换掉」（灰底 + 细边框）。上一版给默认项
 * 画的是虚线，白卡片上几乎看不出，所以换成只深一档的底色。
 *
 * 底部那一行是**完整的一份样式**，不是「只列改过的项」：改哪项就替换哪一项，
 * 其余照默认显示（`宋体 · 小四 · 1.5 倍 · 1 字符 · 两端对齐`）。只报「缩进 1 字符」
 * 会让用户看不到这份稿子最终排出来长什么样，而面板的作用正是让人一眼看全。
 *
 * 为什么不做成下拉弹层：这个面板本身已经在二级浮层里了，再叠一层下拉，
 * 点开时一半会飘到屏幕外；平铺成几行 chips 更稳，也一眼看全。
 */
export function DocStylePanel({
  value,
  onChange,
}: {
  value: DocStyle;
  onChange: (next: DocStyle) => void;
}) {
  /** 去掉某一项：键是泛型，动态 delete 会踩 no-dynamic-delete，改成过滤重建。 */
  const omit = (style: DocStyle, key: keyof DocStyle): DocStyle =>
    Object.fromEntries(Object.entries(style).filter(([name]) => name !== key)) as DocStyle;

  const set = <K extends keyof DocStyle>(key: K, next: DocStyle[K]) => {
    // 再点一次同一个值 = 取消这一项（回到「交给 Agent 判断」）
    onChange(next === value[key] ? omit(value, key) : { ...value, [key]: next });
  };

  /** B / I / U 三键：能叠着用，再点一次关掉。 */
  const toggle = (key: 'bold' | 'italic' | 'underline') => {
    onChange(value[key] ? omit(value, key) : { ...value, [key]: true });
  };

  /** 三种状态各有各的底：选中蓝、默认浅灰、普通白。 */
  const chip = (active: boolean, isDefault = false) =>
    `rounded-chip border px-2 py-[3px] text-caption transition-colors ${
      active
        ? 'border-brand-line bg-brand-soft font-semibold text-brand-strong'
        : isDefault
          ? 'border-line bg-surface-sunken text-ink-soft hover:border-line-strong hover:bg-surface-hover'
          : 'border-line bg-surface text-ink-soft hover:border-line-strong hover:bg-surface-hover'
    }`;

  /** 这一项没被选中、但值正是预设默认——只上浅底，不算「已设」。 */
  const isDefault = <K extends keyof DocStyle>(key: K, current: DocStyle[K]) =>
    value[key] === undefined && current === DOC_DEFAULTS[key as keyof typeof DOC_DEFAULTS];

  const facts = docStyleLine(value);

  const row = (label: string, children: ReactNode) => (
    <div className="flex items-start gap-2 py-1.5">
      <span className="mt-[3px] w-[3.5rem] shrink-0 text-caption text-muted">{label}</span>
      <div className="flex min-w-0 flex-1 flex-wrap gap-1">{children}</div>
    </div>
  );

  return (
    <div className="w-[24rem] max-w-[calc(100vw-2rem)] p-2.5" data-testid="doc-style-panel">
      <div className="flex items-center gap-1.5 px-0.5 pb-1">
        <span className="text-mini font-semibold text-ink">文档格式</span>
        <span className="text-caption text-faint">浅底是预设默认，不选就按文档类型定</span>
      </div>

      <div className="divide-y divide-line/70">
        <div>
          {row(
            '字体',
            DOC_FONTS.map((font) => (
              <button
                key={font}
                type="button"
                aria-pressed={value.font === font}
                className={chip(value.font === font, isDefault('font', font))}
                onClick={() => set('font', font)}
              >
                {docFontLabel(font)}
              </button>
            )),
          )}
          {row(
            '字号',
            DOC_SIZES.map((size) => (
              <button
                key={size}
                type="button"
                aria-pressed={value.size === size}
                className={chip(value.size === size, isDefault('size', size))}
                onClick={() => set('size', size)}
              >
                {size}
              </button>
            )),
          )}
          {row(
            '字型',
            (
              [
                ['bold', 'B', '加粗', 'font-bold'],
                ['italic', 'I', '斜体', 'italic'],
                ['underline', 'U', '下划线', 'underline'],
              ] as const
            ).map(([key, mark, label, cls]) => (
              <button
                key={key}
                type="button"
                aria-label={label}
                aria-pressed={Boolean(value[key])}
                className={`${chip(Boolean(value[key]))} w-8 text-center ${cls}`}
                onClick={() => toggle(key)}
              >
                {mark}
              </button>
            )),
          )}
        </div>

        <div>
          {row(
            '行距',
            DOC_LINES.map((line) => (
              <button
                key={line.value}
                type="button"
                aria-pressed={value.line === line.value}
                className={chip(value.line === line.value, isDefault('line', line.value))}
                onClick={() => set('line', line.value)}
              >
                {line.label}
              </button>
            )),
          )}
          {row(
            '首行缩进',
            DOC_INDENTS.map((indent) => (
              <button
                key={indent.value}
                type="button"
                aria-pressed={value.indent_chars === indent.value}
                className={chip(
                  value.indent_chars === indent.value,
                  isDefault('indent_chars', indent.value),
                )}
                onClick={() => set('indent_chars', indent.value)}
              >
                {indent.label}
              </button>
            )),
          )}
          {row(
            '对齐',
            DOC_ALIGNS.map((align) => (
              <button
                key={align.value}
                type="button"
                aria-pressed={value.align === align.value}
                className={chip(value.align === align.value, isDefault('align', align.value))}
                onClick={() => set('align', align.value)}
              >
                {align.label}
              </button>
            )),
          )}
        </div>
      </div>

      {/* 底部是**完整的一份样式**：五项始终都在，改了哪项就替换哪一项，
          其余照预设显示。只报「缩进 1 字符」的话，其余四项此刻是什么就看不见了。
          「恢复默认」始终在场——它是这个面板唯一的退路，不能因为没设值就藏起来。 */}
      <div className="mt-1 flex items-start justify-between gap-2 border-t border-line pt-2">
        <div
          className="min-w-0 flex-1 pt-[5px] text-caption leading-[1.45]"
          data-testid="doc-style-receipt"
          title={docStyleText(value)}
        >
          <div className="flex flex-wrap items-baseline gap-x-1 gap-y-0.5">
            {/* 「默认」只在真的没动过时说——改过一项就不再是默认样式了 */}
            {hasDocStyle(value) ? null : <span className="text-faint">默认</span>}
            {facts.map((fact, index) => (
              <Fragment key={fact.key}>
                {index > 0 ? <span className="text-faint/60">·</span> : null}
                <span
                  className={`whitespace-nowrap ${
                    fact.overridden ? 'font-semibold text-ink' : 'text-ink-soft'
                  }`}
                >
                  {fact.text}
                </span>
              </Fragment>
            ))}
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onChange({})}
          disabled={Object.keys(value).length === 0}
        >
          恢复默认
        </Button>
      </div>
    </div>
  );
}
