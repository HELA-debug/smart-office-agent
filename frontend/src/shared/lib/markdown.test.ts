/**
 * 轻量 Markdown 解析单测。
 *
 * 这是自研解析器（无第三方依赖），没有上游兜底，边界全在这里：
 * 围栏未闭合、列表混入另一种类型、CRLF 换行、行内标签不完整等
 * 都会直接反映到消息气泡的渲染上。
 */
import { describe, expect, it } from 'vitest';
import { parseInline, parseMarkdown } from './markdown';

describe('parseMarkdown 块级解析', () => {
  it('空输入返回空数组', () => {
    expect(parseMarkdown('')).toEqual([]);
  });

  it('纯空行 / 空白行被忽略', () => {
    expect(parseMarkdown('\n\n   \n\t\n')).toEqual([]);
  });

  it('归一化 CRLF 换行', () => {
    expect(parseMarkdown('# 标题\r\n\r\n正文')).toEqual([
      { type: 'heading', level: 1, text: '标题' },
      { type: 'paragraph', text: '正文' },
    ]);
  });

  it('解析 1-6 级标题，7 个 # 不再算标题', () => {
    expect(parseMarkdown('###### 六级')).toEqual([{ type: 'heading', level: 6, text: '六级' }]);
    expect(parseMarkdown('####### 七级')[0]?.type).toBe('paragraph');
  });

  it('# 后无空格不算标题（避免误判话题标签）', () => {
    expect(parseMarkdown('#标签')[0]).toEqual({ type: 'paragraph', text: '#标签' });
  });

  it('解析围栏代码块并保留语言标识与内部缩进', () => {
    expect(parseMarkdown('```python\nprint("hi")\n  indented\n```')).toEqual([
      { type: 'code', lang: 'python', code: 'print("hi")\n  indented' },
    ]);
  });

  it('无语言标识时 lang 为空串', () => {
    expect(parseMarkdown('```\nplain\n```')).toEqual([{ type: 'code', lang: '', code: 'plain' }]);
  });

  it('围栏未闭合时把剩余内容全部收进代码块（不丢内容）', () => {
    expect(parseMarkdown('```js\nlet a = 1;\nlet b = 2;')).toEqual([
      { type: 'code', lang: 'js', code: 'let a = 1;\nlet b = 2;' },
    ]);
  });

  it('可解析多个连续代码块', () => {
    expect(parseMarkdown('```\na\n```\n\n```\nb\n```')).toEqual([
      { type: 'code', lang: '', code: 'a' },
      { type: 'code', lang: '', code: 'b' },
    ]);
  });

  it('识别三种分隔线写法', () => {
    for (const divider of ['---', '***', '___', '-----']) {
      expect(parseMarkdown(divider)).toEqual([{ type: 'divider' }]);
    }
  });

  it('两个连字符不算分隔线', () => {
    expect(parseMarkdown('--')[0]?.type).toBe('paragraph');
  });

  it('多行引用合并为一段（用空格连接）', () => {
    expect(parseMarkdown('> 第一句\n> 第二句')).toEqual([{ type: 'quote', text: '第一句 第二句' }]);
  });

  it('引用后紧跟普通段落', () => {
    expect(parseMarkdown('> 引用\n\n正文')).toEqual([
      { type: 'quote', text: '引用' },
      { type: 'paragraph', text: '正文' },
    ]);
  });

  it('无序列表（- * +）合并成一块', () => {
    expect(parseMarkdown('- a\n* b\n+ c')).toEqual([
      { type: 'list', ordered: false, items: ['a', 'b', 'c'] },
    ]);
  });

  it('有序列表（1. 2) ）合并成一块并标记 ordered', () => {
    expect(parseMarkdown('1. 第一\n2) 第二')).toEqual([
      { type: 'list', ordered: true, items: ['第一', '第二'] },
    ]);
  });

  it('有序与无序相邻时切成两块（类型切换即分块）', () => {
    expect(parseMarkdown('- a\n1. b')).toEqual([
      { type: 'list', ordered: false, items: ['a'] },
      { type: 'list', ordered: true, items: ['b'] },
    ]);
  });

  it('带缩进的列表项也能识别', () => {
    expect(parseMarkdown('  - 缩进项')).toEqual([
      { type: 'list', ordered: false, items: ['缩进项'] },
    ]);
  });

  it('段落遇到空行 / 标题 / 列表 / 引用 / 围栏时结束', () => {
    const blocks = parseMarkdown(
      '第一段\n# 标题\n第二段\n- 列表\n第三段\n> 引用\n第四段\n```\ncode\n```',
    );
    expect(blocks.map((block) => block.type)).toEqual([
      'paragraph',
      'heading',
      'paragraph',
      'list',
      'paragraph',
      'quote',
      'paragraph',
      'code',
    ]);
  });

  it('段落内换行合并为空格，仅在整体首尾 trim（行内缩进保留）', () => {
    expect(parseMarkdown('  第一行  \n第二行  ')).toEqual([
      { type: 'paragraph', text: '第一行   第二行' },
    ]);
  });
});

describe('parseInline 行内解析', () => {
  it('纯文本返回单个 text token', () => {
    expect(parseInline('普通文本')).toEqual([{ type: 'text', text: '普通文本' }]);
  });

  it('空串返回空数组', () => {
    expect(parseInline('')).toEqual([]);
  });

  it('解析行内代码', () => {
    expect(parseInline('用 `npm run dev` 启动')).toEqual([
      { type: 'text', text: '用 ' },
      { type: 'code', text: 'npm run dev' },
      { type: 'text', text: ' 启动' },
    ]);
  });

  it('解析加粗', () => {
    expect(parseInline('这是**重点**内容')).toEqual([
      { type: 'text', text: '这是' },
      { type: 'strong', text: '重点' },
      { type: 'text', text: '内容' },
    ]);
  });

  it('解析链接', () => {
    expect(parseInline('见 [文档](https://example.com) 说明')).toEqual([
      { type: 'text', text: '见 ' },
      { type: 'link', text: '文档', href: 'https://example.com' },
      { type: 'text', text: ' 说明' },
    ]);
  });

  it('同一行里混合三种标记', () => {
    expect(parseInline('`code` 与 **bold** 与 [链接](https://a.b)')).toEqual([
      { type: 'code', text: 'code' },
      { type: 'text', text: ' 与 ' },
      { type: 'strong', text: 'bold' },
      { type: 'text', text: ' 与 ' },
      { type: 'link', text: '链接', href: 'https://a.b' },
    ]);
  });

  it('标记位于首尾时不产生空 text token', () => {
    expect(parseInline('**开头**')).toEqual([{ type: 'strong', text: '开头' }]);
    expect(parseInline('**a**')).toHaveLength(1);
  });

  it('未闭合标记按纯文本处理（不误吞内容）', () => {
    expect(parseInline('**未闭合')).toEqual([{ type: 'text', text: '**未闭合' }]);
    expect(parseInline('`未闭合')).toEqual([{ type: 'text', text: '`未闭合' }]);
    expect(parseInline('[未闭合](url')).toEqual([{ type: 'text', text: '[未闭合](url' }]);
  });

  it('link href 含空格时不匹配（避免吞掉后面的正文）', () => {
    expect(parseInline('[名称](https://a.b c)')).toEqual([
      { type: 'text', text: '[名称](https://a.b c)' },
    ]);
  });

  it('复用同一正则实例仍从头部开始匹配（lastIndex 已重置）', () => {
    const first = parseInline('`a`');
    const second = parseInline('`b`');
    expect(first).toEqual([{ type: 'code', text: 'a' }]);
    expect(second).toEqual([{ type: 'code', text: 'b' }]);
  });
});
