/**
 * 预览排版的三条硬规则（钉在 CSS 上，不钉在「记得改」上）。
 *
 * 背景（两条都是真实返工）：
 *   1. Word 的 Title 和 Heading N 经 mammoth 转换后都会落到 `<h1>` 这个标签上。
 *      两者必须分开：只有 Title（大标题）居中且字号最大；Heading N 是小节标题，
 *      居中后读者每翻一节都要把视线拉回页面中间重找起行位置，长稿尤其累。
 *   2. 正文段落经 mammoth 转出来是裸 `<p>`，身上没有 doc-para 类。
 *      缩进只写在 `.p.doc-para` 上，界面里的正文就全是顶格的——用户在 Word 里
 *      明明看到空了两格，预览里却没有，会直接判定「你没按我说的做」。
 *
 * 所以这里读 tokens.css 原文断言：
 *   1. 大标题与文首标题块（副标题 / 信息行）居中；各级小节标题左对齐，并带
 *      !important 顶住老产物里带来的 w:jc="center"；
 *   2. 正文段落默认缩进两格，副标题 / 元信息 / 图注 / 表格里的段落除外。
 */

/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

// vitest 的 cwd 就是 frontend 根目录；不用 import.meta.url——jsdom 下它被换成 http URL
const css = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8');

/** 取出某个选择器的声明块（`{` 到第一个 `}` 之间）。 */
function blockOf(selector: string): string {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`tokens.css 里找不到选择器：${selector}`);
  const open = css.indexOf('{', start);
  const close = css.indexOf('}', open);
  return css.slice(open + 1, close);
}

function fontSizeOf(selector: string): number {
  const matched = /font-size:\s*([\d.]+)px/.exec(blockOf(selector));
  if (!matched) throw new Error(`${selector} 没写 font-size`);
  return Number(matched[1]);
}

describe('产物预览的文档标题', () => {
  it('只有文档大标题居中', () => {
    expect(blockOf('.prose-docx h1.doc-title')).toContain('text-align: center');
  });

  it('小节标题一律左对齐，并顶住文件里带来的对齐属性', () => {
    const block = blockOf('.prose-docx h1:not(.doc-title)');
    // !important 是必需的：改版前生成的 docx 里 Heading 存的是 w:jc="center"，
    // mammoth 会把它转成 inline style 带进预览，普通声明压不住
    expect(block).toContain('text-align: left !important');
    expect(block).not.toContain('center');
  });

  it('副标题：居中、比正文大一档、加粗——它是标题块的第二行', () => {
    const block = blockOf('.prose-docx .doc-lead');
    expect(block).toContain('text-align: center');
    expect(block).toContain('font-weight: 600');
    // 信息行是「正文那一档」的字号，副标题得比它大一档，否则只靠居中区分
    expect(fontSizeOf('.prose-docx .doc-lead')).toBeGreaterThan(
      fontSizeOf('.prose-docx .doc-byline'),
    );
  });

  it('文首信息行：居中、不缩进', () => {
    const block = blockOf('.prose-docx .doc-byline');
    expect(block).toContain('text-align: center');
    expect(block).toContain('text-indent: 0');
  });

  it('大标题仍然是全文最大的字', () => {
    const title = fontSizeOf('.prose-docx h1.doc-title');
    expect(title).toBeGreaterThan(fontSizeOf('.prose-docx h1 {'));
    expect(title).toBeGreaterThan(fontSizeOf('.prose-docx h2 {'));
    expect(title).toBeGreaterThan(fontSizeOf('.prose-docx h3 {'));
  });

  it('层级之间字号递减，读者靠字号就能看出第几级', () => {
    const h1 = fontSizeOf('.prose-docx h1 {');
    const h2 = fontSizeOf('.prose-docx h2 {');
    const h3 = fontSizeOf('.prose-docx h3 {');
    expect(h1).toBeGreaterThan(h2);
    expect(h2).toBeGreaterThan(h3);
  });
});

// 缩进类只服务「左对齐」的版式（公文那套顶格靠国标，不缩）：
// 默认版式居中排列，后端不会输出 .doc-hN，这里只守住「真要用时值是 1em 一档」。
describe('产物预览的层级缩进（左对齐版式专用）', () => {
  const indentOf = (selector: string): number => {
    // 一级写的是 `margin-left: 0`（没有单位），其余是 `2em`；两种都要认
    const matched = /margin-left:\s*([\d.]+)(?:em)?\s*;/.exec(blockOf(selector));
    if (!matched) throw new Error(`${selector} 没写 margin-left`);
    return Number(matched[1]);
  };

  it('一级顶格，往下每级缩 1 字符', () => {
    expect(indentOf('.prose-docx .doc-h1')).toBe(0);
    expect(indentOf('.prose-docx .doc-h2')).toBe(1);
    expect(indentOf('.prose-docx .doc-h3')).toBe(2);
    expect(indentOf('.prose-docx .doc-h4')).toBe(3);
  });

  it('缩进不能大到和正文段首撞线', () => {
    // 正文首行空两格；标题要是也缩 2 字符，两者的左边缘会重合，
    // 而正文续行在最左边，读起来像正文比标题还宽
    expect(indentOf('.prose-docx .doc-h2')).toBeLessThan(2);
  });

  it('缩进用 em 而不是 px：字号一改，两格跟着变', () => {
    // Word 存的是 w:leftChars（字符），px 会让二号字的 2 字符和五号字一样宽
    for (const selector of ['.prose-docx .doc-h2', '.prose-docx .doc-h3', '.prose-docx .doc-h4']) {
      expect(blockOf(selector)).not.toContain('margin-left: 2px');
    }
  });
});

describe('产物预览的正文缩进', () => {
  it('正文段落默认首行缩进两格', () => {
    const block = blockOf('.prose-docx p {');
    expect(block).toContain('text-indent: 2em');
    expect(block).not.toContain('text-indent: 0');
  });

  it('副标题、元信息、图注、表格与列表里的段落不缩进', () => {
    // 选择器写在 `{` 之前，blockOf 只拿得到声明，所以选择器列表查原文
    const block = blockOf('.prose-docx p.doc-lead');
    expect(block).toContain('text-indent: 0');
    for (const selector of [
      '.prose-docx p.doc-meta',
      '.prose-docx p.doc-caption',
      '.prose-docx td p',
      '.prose-docx li p',
    ]) {
      expect(css).toContain(selector);
    }
  });

  it('紧凑版式可以显式顶格（doc-flat）', () => {
    expect(blockOf('.prose-docx p.doc-flat')).toContain('text-indent: 0');
  });
});

describe('正文对齐与字型（来自「文档格式」面板）', () => {
  /**
   * 后端按 `Preset.body_align` 给包裹层加 `doc-align-*`，CSS 只认这一个类。
   * 副标题必须排除：它跟着大标题居中、不吃正文那套对齐。
   */
  it('正文默认两端对齐：不靠类名，基础 p 规则本身就是 justify', () => {
    // 默认值不会生成 doc-align-*（只有显式改左/中/右才有），所以「没选对齐」时的
    // 两端对齐只能由这条基础规则兜住；漏了它，预览就退回浏览器默认的左对齐。
    expect(blockOf('.prose-docx p {')).toContain('text-align: justify');
  });

  it('正文居中由包裹层的 doc-align-center 提供，且跳过副标题', () => {
    // 选择器本身也要带上 :not(.doc-lead)——副标题跟着大标题居中，不吃正文那套
    expect(css).toContain('.prose-docx .doc-align-center > p:not(.doc-lead)');
    expect(blockOf('.prose-docx .doc-align-center > p')).toContain('text-align: center');
  });

  it('首行缩进读后端给的 --doc-indent（否则面板改成 0 也不生效）', () => {
    expect(blockOf('.prose-docx .doc-body > p')).toContain('text-indent: var(--doc-indent');
  });

  it('B / I / U 三个字型各有一条声明', () => {
    expect(blockOf('.prose-docx .doc-bold > p')).toContain('font-weight');
    expect(blockOf('.prose-docx .doc-italic > p')).toContain('font-style: italic');
    expect(blockOf('.prose-docx .doc-underline > p')).toContain('text-decoration: underline');
  });
});

describe('紧凑版式（.doc-compact）', () => {
  it('整篇缩一档：字更小、行更紧', () => {
    const body = blockOf('.prose-docx .doc-compact {');
    expect(body).toContain('font-size: 14px');
    expect(body).toContain('line-height: 24px');
    // 默认正文 15/27；紧凑要真的更密，不能只是写个类名
    expect(fontSizeOf('.prose-docx .doc-compact {')).toBeLessThan(fontSizeOf('.prose-docx {'));
  });

  it('标题层级跟着缩，但层级关系不变', () => {
    const title = fontSizeOf('.prose-docx .doc-compact h1.doc-title');
    const level1 = fontSizeOf('.prose-docx .doc-compact h2');
    const level2 = fontSizeOf('.prose-docx .doc-compact h3');
    const level3 = fontSizeOf('.prose-docx .doc-compact h4,');
    expect(title).toBeGreaterThan(level1);
    expect(level1).toBeGreaterThan(level2);
    expect(level2).toBeGreaterThan(level3);
  });

  it('不抹掉缩进：正文照样空两格（doc-flat 只留给显式顶格的版式）', () => {
    const block = blockOf('.prose-docx .doc-compact p {');
    expect(block).not.toContain('text-indent: 0');
  });
});
