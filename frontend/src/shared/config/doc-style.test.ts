/**
 * 「文档格式」面板的数据层：点过什么就发什么，没点的一律不发。
 *
 * 这几条看着琐碎，但每一条都对应一种「面板点了没反应 / 反应过头」的线上体感，
 * 所以拿测试钉住，而不是靠读代码时记得。
 */
import {
  DOC_DEFAULTS,
  compactDocStyle,
  docFontLabel,
  docStyleLine,
  docStyleSummary,
  docStyleText,
  hasDocStyle,
} from './doc-style';

describe('compactDocStyle', () => {
  it('什么都没点 = 空对象（整轮交给 Agent 按文档类型判断）', () => {
    expect(compactDocStyle({})).toEqual({});
    expect(hasDocStyle({})).toBe(false);
    expect(docStyleSummary({})).toBe('跟随文档');
  });

  it('只发点过的那几项', () => {
    expect(compactDocStyle({ size: '三号' })).toEqual({ size: '三号' });
  });

  it('首行缩进 0 也要发出去：0 是「顶格」，不是「没填」', () => {
    // 后端 preset_with_style 用 0 表示顶格；这里漏掉，用户选「不缩进」就会没反应
    expect(compactDocStyle({ indent_chars: '0' })).toEqual({ indent_chars: 0 });
    // 字符串会被转成数字发：后端按字符数（float）读，不认「2 字符」这种带单位的写法
    expect(compactDocStyle({ indent_chars: '2' })).toEqual({ indent_chars: 2 });
  });

  it('左对齐和两端对齐都要发：它们和「默认值」长得像，但不能被当成没选', () => {
    expect(compactDocStyle({ align: 'left' })).toEqual({ align: 'left' });
    expect(compactDocStyle({ align: 'justify' })).toEqual({ align: 'justify' });
  });

  it('字型只发开着的那些（关掉 = 不发，回来后端按预设走）', () => {
    expect(compactDocStyle({ bold: true, italic: false, underline: true })).toEqual({
      bold: true,
      underline: true,
    });
  });

  it('摘要只报「动过几项」，不把值全列出来（一行放不下会被截断）', () => {
    expect(docStyleSummary({ font: '宋体', size: '小四' })).toBe('已设 2 项');
    // B / I / U 三个一起也只算一项：它们同属「字型」
    expect(docStyleSummary({ bold: true, italic: true, underline: true })).toBe('已设 1 项');
    expect(hasDocStyle({ line: '1.5' })).toBe(true);
  });
});

describe('预设默认值（面板上的浅底段）', () => {
  /**
   * 默认值的唯一事实来源是后端 `doc_render.PRESETS["report"]`：宋体、小四、
   * 1.5 倍行距、两端对齐、首行缩进 2 字符。这里钉住前端那份「显示用」的副本，
   * 免得哪天后端换了版式、面板还在拿旧值糊弄人。
   */
  it('和 report 预设是同一套：宋体 / 小四 / 1.5 倍 / 两端对齐 / 缩进 2 字符', () => {
    expect(DOC_DEFAULTS).toEqual({
      font: '宋体',
      size: '小四',
      line: '1.5',
      indent_chars: '2',
      align: 'justify',
    });
  });
  it('底部那行和默认值不会各说各话', () => {
    expect(docStyleText({})).toBe('默认 宋体 · 小四 · 1.5 倍 · 2 字符 · 两端对齐');
  });

  it('默认值只是「显示」：它不会自己进请求体，公文/紧凑那几档才换得动版式', () => {
    // 用户确实点了一遍默认值，才应该发出去；不点的时候整轮交给 Agent
    expect(hasDocStyle({})).toBe(false);
    expect(compactDocStyle(DOC_DEFAULTS)).toMatchObject({ font: '宋体', align: 'justify' });
  });
});

describe('docStyleLine（面板底部那一行完整样式）', () => {
  /**
   * 底部要回答的是「这份稿子最终排成什么样」，所以五项始终都在：
   * 改哪项就替换哪一项，其余照预设默认走。只列改过的项会让人看不见其余四项，
   * 而面板的作用正是让人一眼看全。
   */
  it('一项都没改：整行就是预设默认，前面带「默认」', () => {
    expect(docStyleLine({}).map((item) => item.text)).toEqual([
      '宋体',
      '小四',
      '1.5 倍',
      '2 字符',
      '两端对齐',
    ]);
    expect(docStyleLine({}).every((item) => !item.overridden)).toBe(true);
    expect(docStyleText({})).toMatch(/^默认 /);
  });

  it('只改一项：就地替换那一项，其余照默认显示', () => {
    // 用户只动了首行缩进——这就是他说的「1.5 倍那一格换掉，别的照旧」
    expect(docStyleText({ indent_chars: '1' })).toBe('宋体 · 小四 · 1.5 倍 · 1 字符 · 两端对齐');
    // 改过之后不再是默认样式，前缀「默认」跟着去掉
    expect(docStyleText({ indent_chars: '1' })).not.toContain('默认');
  });

  it('只有改过的那项标 overridden，其余仍是预设', () => {
    const line = docStyleLine({ size: '三号' });
    expect(line.filter((item) => item.overridden).map((item) => item.text)).toEqual(['三号']);
    expect(line.map((item) => item.text)).toContain('宋体');
  });

  it('顺序跟面板上那几行一致：字体 → 字号 → 字型 → 行距 → 缩进 → 对齐', () => {
    expect(docStyleLine({ bold: true }).map((item) => item.key)).toEqual([
      'font',
      'size',
      'marks',
      'line',
      'indent',
      'align',
    ]);
  });

  it('字型只在用户点过时才占位（预设里没有字型，别显示「无」）', () => {
    expect(docStyleLine({}).some((item) => item.key === 'marks')).toBe(false);
    expect(
      docStyleLine({ bold: true, underline: true }).find((item) => item.key === 'marks'),
    ).toEqual({ key: 'marks', text: 'B U', overridden: true });
  });

  it('缩进 0 是「不缩进」，不是没填', () => {
    expect(docStyleLine({ indent_chars: '0' }).find((item) => item.key === 'indent')).toEqual({
      key: 'indent',
      text: '不缩进',
      overridden: true,
    });
  });

  it('字体用面板上的简称，仿宋_GB2312 不撑破那一行', () => {
    expect(docStyleText({ font: '仿宋_GB2312' })).toContain('仿宋');
    expect(docStyleText({ font: '仿宋_GB2312' })).not.toContain('_GB2312');
    expect(docFontLabel('宋体')).toBe('宋体');
  });

  it('五项一起改也是同一行，按面板顺序排', () => {
    expect(
      docStyleText({
        font: '楷体',
        size: '三号',
        line: '2.0',
        indent_chars: '0',
        align: 'center',
      }),
    ).toBe('楷体 · 三号 · 2 倍 · 不缩进 · 居中');
  });
});
