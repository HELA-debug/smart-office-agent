import mammoth from 'mammoth';
import { useEffect, useState } from 'react';
import { errorMessage } from '../../../shared/lib/api';
import { saveRemoteFile } from '../../../shared/lib/download';
import { formatBytes, formatDateTime } from '../../../shared/lib/format';
import {
  IconAlertTriangle,
  IconCollapse,
  IconDownload,
  IconExpand,
  IconExternal,
  IconFile,
  IconFolder,
  IconShield,
  IconSpinner,
} from '../../../shared/ui/Icons';
import { Button, IconButton, Modal } from '../../../shared/ui/primitives';
import { ARTIFACT_TYPE_LABELS, artifactsApi } from '../api';
import { artifactTypeStyle } from '../type-style';
import type { ComponentType, ReactNode } from 'react';

type PreviewState = 'loading' | 'ready' | 'error';

/** 预览只需要这几个字段：产物中心（ArtifactOut）与工作台（ArtifactItem）都能直接传。 */
export interface PreviewTarget {
  artifact_id: string;
  filename: string;
  type: string;
  size: number;
  /** 产出时间：弹窗副标题用，缺了只是少一项，不影响预览 */
  created_at?: string;
}

/** 轻量清洗：去掉 script/iframe/事件属性，防止 docx 内嵌内容执行脚本。 */
function sanitizeHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
    .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '');
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 行内 Markdown：粗体 / 行内代码 / 链接。 */
function inlineMarkdown(text: string): string {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer">$1</a>',
    );
}

/** 表格分隔行：`| --- | :---: |` 这种，只有竖线、短横、冒号和空白。 */
function isTableSeparator(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.includes('|') && trimmed.includes('-') && /^[|\s:-]+$/.test(trimmed);
}

/** 把 `| a | b |` 拆成 ['a', 'b']：首尾竖线只是边框，不属于单元格。 */
function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

/** 列表缩进：两个空格或一个 Tab 算一级，最多认四级（再深也读不出区别）。 */
function indentOf(raw: string): number {
  const expanded = raw.replace(/\t/g, '  ');
  const spaces = expanded.length - expanded.trimStart().length;
  return Math.min(Math.floor(spaces / 2), 3) * 2;
}

/**
 * 轻量 Markdown → HTML：标题 / 段落 / 有序无序列表（含二级）/ 引用 / 分隔线 / 代码块。
 *
 * 两个和「排版」直接相关的决定：
 * 1. **连续正文行合成一段**（内部用 `<br/>`）：Markdown 里一行的硬换行不是分段，
 *    以前每行都包一个 `<p>`，段间距被放大成一整段空白，整篇看着像被拆散了；
 * 2. **保留列表层级**：缩进不再被 trim 吃掉，二级条目挂在父项里，
 *    「新增 / 变更 / 修复」下面的子项才看得出从属关系。
 */
function renderMarkdown(source: string): string {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const out: string[] = [];
  let paragraph: string[] = [];
  const lists: { type: 'ul' | 'ol'; indent: number }[] = [];

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    out.push(`<p>${paragraph.map(inlineMarkdown).join('<br/>')}</p>`);
    paragraph = [];
  };

  const closeAllLists = () => {
    while (lists.length > 0) {
      const top = lists.pop();
      if (top) out.push(`</li></${top.type}>`);
    }
  };

  const openList = (type: 'ul' | 'ol', indent: number) => {
    out.push(`<${type}>`);
    lists.push({ type, indent });
  };

  /** 当前这一项是否还没闭合（列表栈非空就说明有一项开着） */
  const hasOpenItem = () => lists.length > 0;

  const pushItem = (type: 'ul' | 'ol', indent: number, text: string) => {
    if (!hasOpenItem()) {
      openList(type, indent);
    } else {
      const top = lists[lists.length - 1];
      if (top && indent > top.indent) {
        // 更深一级：父项还开着，直接嵌一个新列表
        openList(type, indent);
      } else if (top && indent === top.indent) {
        out.push('</li>');
        if (top.type !== type) {
          out.push(`</${top.type}>`);
          lists.pop();
          openList(type, indent);
        }
      } else {
        // 回到更浅的一级：逐层收掉，再在同层结束上一项
        while (lists.length > 0) {
          const current = lists[lists.length - 1];
          if (!current || current.indent < indent) break;
          if (current.indent === indent) {
            out.push('</li>');
            if (current.type !== type) {
              out.push(`</${current.type}>`);
              lists.pop();
              openList(type, indent);
            }
            break;
          }
          out.push(`</li></${current.type}>`);
          lists.pop();
        }
        if (!hasOpenItem()) openList(type, indent);
      }
    }
    out.push(`<li>${inlineMarkdown(text)}`);
  };

  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index] ?? '';
    const trimmed = raw.trim();

    // 代码块：围栏之间原样保留（含缩进），不参与任何行内解析
    if (trimmed.startsWith('```')) {
      flushParagraph();
      closeAllLists();
      const lang = trimmed.slice(3).trim();
      const buffer: string[] = [];
      index += 1;
      while (index < lines.length && !(lines[index] ?? '').trim().startsWith('```')) {
        buffer.push(lines[index] ?? '');
        index += 1;
      }
      out.push(
        `<pre><code${lang ? ` class="language-${escapeHtml(lang)}"` : ''}>${escapeHtml(
          buffer.join('\n'),
        )}</code></pre>`,
      );
      continue;
    }

    if (!trimmed) {
      // 空行只收段落、不关列表：Markdown 的「松散列表」在项之间就是有空行的，
      // 以前在这里关掉列表，五项会被拆成五个 <ul>，项间凭空多出两倍行距。
      flushParagraph();
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      closeAllLists();
      const level = (heading[1] ?? '#').length;
      out.push(`<h${level}>${inlineMarkdown(heading[2] ?? '')}</h${level}>`);
      continue;
    }

    if (/^(---|\*\*\*|___)$/.test(trimmed)) {
      flushParagraph();
      closeAllLists();
      out.push('<hr/>');
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      flushParagraph();
      closeAllLists();
      const quoted: string[] = [];
      while (index < lines.length) {
        const next = (lines[index] ?? '').trim();
        if (!/^>\s?/.test(next)) break;
        quoted.push(next.replace(/^>\s?/, ''));
        index += 1;
      }
      index -= 1;
      out.push(`<blockquote><p>${quoted.map(inlineMarkdown).join('<br/>')}</p></blockquote>`);
      continue;
    }

    // 表格：本行带竖线、下一行是 |---|---| 的分隔行。以前这里没有分支，
    // 整张表会被当成正文，读者看到的是「| 现象 | 根因 |」+「| --- | --- |」两行裸竖线。
    if (trimmed.includes('|') && isTableSeparator(lines[index + 1] ?? '')) {
      flushParagraph();
      closeAllLists();
      const head = splitRow(trimmed);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length) {
        const row = (lines[index] ?? '').trim();
        if (!row || !row.includes('|')) break;
        rows.push(splitRow(row));
        index += 1;
      }
      index -= 1;
      const cell = (tag: 'th' | 'td', text: string | undefined) =>
        `<${tag}>${inlineMarkdown(text ?? '')}</${tag}>`;
      out.push(
        `<table><thead><tr>${head.map((text) => cell('th', text)).join('')}</tr></thead>` +
          `<tbody>${rows
            .map((row) => `<tr>${head.map((_, i) => cell('td', row[i])).join('')}</tr>`)
            .join('')}</tbody></table>`,
      );
      continue;
    }

    if (/^[-*+]\s+/.test(trimmed)) {
      flushParagraph();
      pushItem('ul', indentOf(raw), trimmed.replace(/^[-*+]\s+/, ''));
      continue;
    }

    const ordered = /^\d+[.)]\s+(.*)$/.exec(trimmed);
    if (ordered) {
      flushParagraph();
      pushItem('ol', indentOf(raw), ordered[1] ?? '');
      continue;
    }

    // 列表项的缩进续行：Markdown 里这是「懒续行」，属于上一项的内容。
    // 以前这里直接关列表另起一段，列表被切成两截、段落插在中间，从属关系全丢了。
    const innermost = lists[lists.length - 1];
    if (innermost && indentOf(raw) > innermost.indent) {
      out.push(`<br/>${inlineMarkdown(trimmed)}`);
      continue;
    }

    // 普通正文：先收列表，再攒进同一段
    closeAllLists();
    paragraph.push(trimmed);
  }

  flushParagraph();
  closeAllLists();
  return out.join('\n');
}

/** Word 报告的第二段常是「生成时间：… | 模式：… | 来源：…」这类机器信息。
 *  它和正文同字号同颜色，读起来像正文的第一句，把真正的「摘要」往下推。
 *  收成 .doc-meta 注释块，和纯文本预览的处理保持一致。 */
function markDocxMeta(html: string): string {
  return html.replace(/<p>(\s*(?:生成时间|创建时间|更新时间)[：:])/, '<p class="doc-meta">$1');
}

/**
 * 图文对照：把「单独一段的图片」和紧跟其后的图注包进 <figure>。
 *
 * 不包的时候，图和图注是两个独立段落，图注会继承正文的 15px / 1.8 行高、
 * 和下一段挤在一起，看着像正文第一句；包成 figure 之后才能做「图居中、
 * 注在下、注比正文小一号」的版式——和正式 Word 文档的读法一致。
 */
function decorateDocxFigures(html: string): string {
  return html.replace(
    /<p>(<img\b[^>]*>)<\/p>\s*(?:<p class="doc-caption">([\s\S]*?)<\/p>)?/g,
    (_match, img: string, caption?: string) =>
      `<figure>${img}${caption ? `<figcaption>${caption}</figcaption>` : ''}</figure>`,
  );
}

/** mammoth 的转换选项：图片转成 data URI（否则图片会被静默丢掉），图注按样式名认出来。
 *  运行时再拼：单测里 mammoth 是 stub，没有 images 分支，模块加载阶段不能直接调用。 */
function docxOptions(): Record<string, unknown> {
  const styleMap = [
    "p[style-name='Caption'] => p.doc-caption:fresh",
    "p[style-name='Title'] => h1.doc-title:fresh",
    // 小节标题：Heading 1 起映射到 h2，并带上 doc-hN —— 与后端 blocks_to_html
    // 输出的标签、类名一字不差，两条预览路径才会排成同一个样子。
    // 不用 h1 是因为 h1 已经被文档大标题占了（居中、全文最大）。
    "p[style-name='Heading 1'] => h2.doc-h1:fresh",
    "p[style-name='Heading 2'] => h3.doc-h2:fresh",
    "p[style-name='Heading 3'] => h4.doc-h3:fresh",
    "p[style-name='Heading 4'] => h5.doc-h4:fresh",
    // 副标题：不标出来的话它就是一个普通段落，会被正文的「首行缩进两格」推歪，
    // 而它本身是居中的——居中的字再缩进两格，看着像整行往右跑了。
    "p[style-name='Subtitle'] => p.doc-lead:fresh",
    // Word 把项目符号写在样式定义里（numPr），mammoth 只认段落上的编号，
    // 不映射的话它们会变成一串没有圆点/序号的普通段落（打开别人给的 docx 时会遇到）。
    "p[style-name='List Bullet'] => ul > li:fresh",
    "p[style-name='List Number'] => ol > li:fresh",
  ];
  type ImageElement = { read: (encoding: string) => Promise<string>; contentType: string };
  const images = (
    mammoth as unknown as {
      images?: {
        imgElement?: (convert: (image: ImageElement) => Promise<{ src: string }>) => unknown;
      };
    }
  ).images;
  if (!images?.imgElement) return { styleMap };
  const convertImage = images.imgElement(async (image) => {
    const base64 = await image.read('base64');
    return { src: `data:${image.contentType};base64,${base64}` };
  });
  return { styleMap, convertImage };
}

/** 预览器认识这些类型 */
const PREVIEWABLE = new Set(['docx', 'xlsx', 'pdf', 'txt', 'md', 'csv', 'html']);

/**
 * 上传进来的素材后端只记成 upload，看不出是 Word 还是 PDF。
 * 卡片上虽然统一显示「上传文件」，预览时按扩展名还原真实类型，别让用户白点一次。
 */
function previewKind(type: string, filename: string): string {
  if (PREVIEWABLE.has(type)) return type;
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  return PREVIEWABLE.has(ext) ? ext : 'other';
}

/** 句末标点：以它收尾说明「这句话说完了」，下一行是新的一段，不是折行的下半句。
    ASCII 的 `)` 不算——`chat_with_tools()` 这种行末括注常被折行截在中间，后面还接着半句。 */
const PARAGRAPH_END = /[。．.！？!?；;：:…」』”"）】]$/;

/**
 * 只认「真的说完了」的句末标点：右括号、右引号、】都排除。
 *
 * 标题和副标题常以括注收尾——「实验二 光照自适应调光（2026 年第 47 周，工作周报）」——
 * 用 PARAGRAPH_END 判，这一行会被当成一句说完的正文，整块标题降级成正文段落
 * （不居中、不放大、还吃两格缩进），用户在截图里看到的「标题不像标题」就是它。
 */
const SENTENCE_END = /[。．.！？!?；;：:…]$/;

/**
 * 判断下一行是不是上一行的「折行续行」。
 *
 * 只有「上一行写到接近行宽、又没有句末标点」才接：太短的一行（落款、地址、诗句、
 * 一行一条的日志）多半是作者有意断的，合起来反而糊成一团。
 */
function continuesPreviousLine(previous: string, next: string): boolean {
  const line = previous.trim();
  if (line.length < 18) return false;
  if (PARAGRAPH_END.test(line)) return false;
  // 下一行自己是标题 / 列表项 / 机器信息，各自有归属，不能并进这段
  return !(
    /^【.+】\s*$/.test(next) ||
    /^#{1,4}\s+\S/.test(next) ||
    /^[-*·•]\s+/.test(next) ||
    /^\d+[.)、]\s*\S/.test(next)
  );
}

/**
 * 文首信息行的字段名（「实验名称 / 姓名 / 学号 …」）。和后端
 * `doc_render.BYLINE_KEYS` 是同一张表：Word 那边靠它把「字段：值」排成 byline，
 * 纯文本预览没有样式信息，只能按同样的判据认一遍。
 */
const BYLINE_KEYS = [
  '实验名称',
  '实验方式',
  '实验时间',
  '课程',
  '课题',
  '项目',
  '姓名',
  '学号',
  '专业',
  '班级',
  '院系',
  '学院',
  '单位',
  '部门',
  '指导教师',
  '指导老师',
  '报告人',
  '撰写人',
  '组员',
  '成员',
  '日期',
];

/**
 * 这一行是不是文首的「字段：值」信息行（如「姓名：张三 / 学号：2024001」）。
 *
 * 信息行不是标题：它和副标题一起居中，但字号跟正文一样、不加粗——样张的标题块
 * 是「大标题 / 副标题 / 信息行」三档，全都按副标题排会糊成一坨。
 */
function looksLikeByline(line: string): boolean {
  if (line.length > 80) return false;
  if (/[。！？.!?]/.test(line)) return false;
  // 至少两组「字段：值」——一个冒号更像正文里的「结论：……」
  if ((line.match(/[：:]/g) ?? []).length < 2) return false;
  return BYLINE_KEYS.filter((key) => line.includes(key)).length >= 2;
}

/**
 * 「一行一条」的记录：日志、定宽表、时间戳打头的工单。它们靠行首对齐才读得出来，
 * 既不能并成一段，也不该带首行缩进（缩进一进去，整列就歪了）。
 */
function isRecordLine(line: string): boolean {
  return (
    /^\[?\d{4}[-/年]\d{1,2}[-/月]/.test(line) ||
    /^\d{1,2}:\d{2}/.test(line) ||
    /\s{2,}|\t/.test(line)
  );
}

/**
 * 接续两行：中文之间直接贴（折行处本来就没空格），跨到西文/数字时补一个空格。
 *
 * 补空格不是猜的：折行工具是在空格处断的，断完那个空格就没了——`… 取段落加表格行，pptx`
 * 接上 `按页取…` 会粘成「pptx按页」。中文排印本来也要求中西文之间留一个空格。
 */
function joinWrappedLine(previous: string, next: string): string {
  const left = previous.replace(/\s+$/, '');
  const right = next.replace(/^\s+/, '');
  // 行末的右括号/引号算「西文那一侧」：`chat_with_tools()` 接「与 …」要留一个空格
  const word = /[A-Za-z0-9)\]}"']/;
  const han = /[\u4e00-\u9fff]/;
  const needsSpace =
    (word.test(left.slice(-1)) && word.test(right.slice(0, 1))) ||
    (han.test(left.slice(-1)) && word.test(right.slice(0, 1))) ||
    (word.test(left.slice(-1)) && han.test(right.slice(0, 1)));
  return left + (needsSpace ? ' ' : '') + right;
}

/**
 * 纯文本（txt / csv 单元格）→ 结构化 HTML。
 * 生成出来的文档常用「【小标题】」分节、用「- 」列举：
 * 直接塞进 <pre> 会是一大坨等宽字，看不出层次，这里按结构还原。
 *
 * 文首第一行是文档名字，走 docx 的 Title 那套：`h1.doc-title` 居中且全文最大；
 * 紧随的一两行小字是副标题，走 `p.doc-lead` 跟着居中。.txt 文件本身没有对齐属性，
 * 也不许往行首塞空格假装居中——居中只发生在预览渲染这一层。
 * 「关键文件索引」这类节和「来源：…」「依据《…》整理」这类落款是写稿人核对用的，
 * 预览里同样不展示（用户 2026-11-09 要求，11-10 又点名了索引节）。
 *
 * **硬折行要还原**（2026-11-16）：老文件、外部素材常按 38 个汉字折过行，每行末尾
 * 根本没有句号。原样保留就是「每行一句半截话、右缘参差不齐」，两端对齐也拉不动
 * （`<br/>` 后面的每一段都是「末行」）。所以这里按语义把同一段的续行接回去，
 * 只在作者真的分段（空行、句末标点、标题、列表）处断开。
 */
export function renderTextDoc(text: string): string {
  // 开头这几类行是生成时写入的机器信息，正文从第一个小标题开始才算「内容」
  const META_KEY = /^(生成时间|创建时间|更新时间|模式|来源|会话|运行|任务|作者|模板)[:：]/;
  /** 整行就是出处落款 */
  const CREDIT_LINE =
    /^\s*(?:来源|资料来源|参考来源|参考资料|参考文献|出处|引用)\s*[:：]|^\s*(?:依据|根据|整理自|摘录自|改编自|基于)\s*《[^》]+》\s*(?:整理|编写|改写|摘录|汇总|而成)|^\s*代码位置沿用/;
  /** 「六、关键文件索引」这类小节标题（可带井号 / 中文编号） */
  const INDEX_HEADING =
    /^\s*(?:#{0,6}\s*)?(?:[一二三四五六七八九十]{1,3}\s*[、.．]\s*)?(?:关键文件索引|文件索引|代码索引|源码索引)\s*[:：]?\s*$/;
  /** 小节标题：确认这是一份结构化文档，才把第一行当大标题 */
  const SECTION_HEADING =
    /^\s*【.+】\s*$|^\s*#{1,4}\s+\S|^\s*[一二三四五六七八九十]{1,3}\s*[、.．]\s*\S/;

  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const hasSections = lines.some((line) => SECTION_HEADING.test(line));
  const firstIndex = lines.findIndex((line) => Boolean(line.trim()));
  const firstLine = (lines[firstIndex] ?? '').trim();
  const titleLike =
    hasSections &&
    firstIndex >= 0 &&
    firstLine.length > 0 &&
    firstLine.length <= 40 &&
    !SENTENCE_END.test(firstLine) &&
    !META_KEY.test(firstLine) &&
    !CREDIT_LINE.test(firstLine) &&
    !/^【|^#|^\d+[.)、]|^[-*·•]\s/.test(firstLine);

  /**
   * 副标题：标题块里的那行说明。它和标题之间常常隔着一个空行（大标题一行、
   * 空行、副标题），也可能夹着一行「依据《…》整理」的落款，所以不能只看
   * 「第一个空行之前」。判据是「短、不带句末标点、后面紧跟小节标题」——
   * 撞上正文（长句或带句末标点）就整块放弃，宁可认不出，也不要把正文第一段
   * 居中成副标题。
   */
  const leadIndexes = new Set<number>();
  if (titleLike) {
    let cursor = firstIndex + 1;
    let collected = 0;
    while (cursor < lines.length && collected < 2) {
      const candidate = (lines[cursor] ?? '').trim();
      if (!candidate || CREDIT_LINE.test(candidate)) {
        cursor += 1;
        continue;
      }
      if (SECTION_HEADING.test(candidate)) break;
      const leadLike =
        candidate.length <= 48 &&
        !SENTENCE_END.test(candidate) &&
        !/^【|^#|^\d+[.)、]|^[-*·•]\s/.test(candidate) &&
        !META_KEY.test(candidate);
      if (!leadLike) {
        leadIndexes.clear();
        break;
      }
      leadIndexes.add(cursor);
      collected += 1;
      cursor += 1;
    }
  }

  const out: string[] = [];
  const meta: string[] = [];
  const paragraph: string[] = [];
  let listType: 'ul' | 'ol' | null = null;
  let seenHeading = false;
  let skippingIndex = false;
  /** 上一项在 out 里的下标：缩进续行要接在它后面，而不是另起一段 */
  let lastItem = -1;
  /** 上一项的纯文本（`\n` 表示作者真的换了行）：续行要按原文字重新拼，不能拼 HTML */
  const listText = new Map<number, string>();

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    out.push(`<p>${paragraph.map(inlineMarkdown).join('<br/>')}</p>`);
    paragraph.length = 0;
  };
  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`);
      listType = null;
    }
    lastItem = -1;
  };
  const flushMeta = () => {
    if (meta.length === 0) return;
    out.push(`<p class="doc-meta">${meta.map((line) => inlineMarkdown(line)).join('<br/>')}</p>`);
    meta.length = 0;
  };

  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index] ?? '';
    const line = raw.trim();
    if (!line) {
      // 同 Markdown：空行不结束列表，否则一条条列表会各自成段
      flushParagraph();
      continue;
    }

    // 文首标题块：第一行 = 文档名字（居中、全文最大），其余行 = 副标题（跟着居中）
    if (titleLike && index === firstIndex) {
      out.push(`<h1 class="doc-title">${inlineMarkdown(line)}</h1>`);
      seenHeading = true;
      continue;
    }
    if (leadIndexes.has(index)) {
      // 标题块里再分两档：一行说明是副标题（比正文大一档、加粗），
      // 「实验名称：… / 姓名：…」这类字段行是信息行（正文字号、不加粗）。
      const leadClass = looksLikeByline(line) ? 'doc-byline' : 'doc-lead';
      out.push(`<p class="${leadClass}">${inlineMarkdown(line)}</p>`);
      seenHeading = true;
      continue;
    }

    // 索引节：连标题带下面那串源码路径一起跳过，遇到下一节才停
    if (INDEX_HEADING.test(line)) {
      flushParagraph();
      closeList();
      flushMeta();
      skippingIndex = true;
      continue;
    }
    if (skippingIndex) {
      if (SECTION_HEADING.test(line) && !INDEX_HEADING.test(line)) skippingIndex = false;
      else continue;
    }
    if (CREDIT_LINE.test(line)) {
      flushParagraph();
      continue;
    }

    // 「一、总览：…」这种中文编号也算小节标题：外部素材和早期产物常常不裹【】，
    // 只按【】认会把标题当成正文，跟着首行缩进空两格、还和上一段粘在一起。
    const shortLine = line.length <= 40 && !/[。！？!?]$/.test(line);
    const cnHeading = shortLine
      ? /^([一二三四五六七八九十]{1,3}\s*[、.．]\s*\S.*)$/.exec(line)
      : null;
    // 下一层：「（一）…」「1.1 …」——比「一、」低一档，标题层级不能全压成一级
    const subHeading = shortLine
      ? /^((?:[（(][一二三四五六七八九十]{1,3}[）)]|\d+(?:\.\d+)+)\s*\S.*)$/.exec(line)
      : null;
    const heading = /^【(.+)】$/.exec(line) ?? /^#{1,4}\s+(.*)$/.exec(line) ?? cnHeading;
    const headingText = heading?.[1] ?? subHeading?.[1];
    if (headingText) {
      flushParagraph();
      closeList();
      flushMeta();
      seenHeading = true;
      const tag = heading ? 'h3' : 'h4';
      out.push(`<${tag}>${inlineMarkdown(headingText)}</${tag}>`);
      continue;
    }
    if (!seenHeading && meta.length < 4 && META_KEY.test(line)) {
      meta.push(line.replace(/\s*\|\s*/g, ' · '));
      continue;
    }
    flushMeta();
    if (/^[-*·•]\s+/.test(line)) {
      flushParagraph();
      if (listType !== 'ul') {
        closeList();
        out.push('<ul>');
        listType = 'ul';
      }
      const bullet = line.replace(/^[-*·•]\s+/, '');
      out.push(`<li>${inlineMarkdown(bullet)}</li>`);
      listText.set(out.length - 1, bullet);
      lastItem = out.length - 1;
      continue;
    }
    const ordered = /^\d+[.)、]\s*(.+)$/.exec(line);
    if (ordered) {
      flushParagraph();
      if (listType !== 'ol') {
        closeList();
        out.push('<ol>');
        listType = 'ol';
      }
      out.push(`<li>${inlineMarkdown(ordered[1] ?? '')}</li>`);
      listText.set(out.length - 1, ordered[1] ?? '');
      lastItem = out.length - 1;
      continue;
    }
    // 列表项的缩进续行：并进上一项，别把列表拆成「列表 + 段落 + 列表」。
    // 是折行的下半句就直接接上（和正文同一套判断）；真是另起一行才留 `<br/>`。
    if (listType && lastItem >= 0 && /^\s/.test(raw)) {
      const text = listText.get(lastItem) ?? '';
      const merged = continuesPreviousLine(text, line)
        ? joinWrappedLine(text, line)
        : `${text}\n${line}`;
      listText.set(lastItem, merged);
      out[lastItem] = `<li>${inlineMarkdown(merged).replace(/\n/g, '<br/>')}</li>`;
      continue;
    }
    closeList();
    // 一行一条的记录：自己成段、不吃首行缩进（`doc-flat` 就是清缩进那个类）
    if (isRecordLine(line)) {
      flushParagraph();
      out.push(`<p class="doc-flat">${inlineMarkdown(line)}</p>`);
      continue;
    }
    // 折行续行：并回同一段，不要每行都按 `<br/>` 断开——断开的每一行在浏览器里都是
    // 「段落末行」，两端对齐拉不动，右缘就是一排参差的半句。
    const previous = paragraph[paragraph.length - 1];
    if (previous !== undefined && continuesPreviousLine(previous, line)) {
      paragraph[paragraph.length - 1] = joinWrappedLine(previous, line);
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  closeList();
  flushMeta();
  return out.join('\n');
}

/** CSV → 表格：逗号分隔栏，首行当表头（引号包裹的字段里可以有逗号）。 */
function renderCsv(text: string): string {
  const rows: string[][] = [];
  const lineRe = /(?:^|\n)((?:[^",\n]|"(?:[^"]|"")*")*)/g;
  let match: RegExpExecArray | null;
  while ((match = lineRe.exec(text)) !== null) {
    const line = match[1];
    if (line === undefined || line.trim() === '') continue;
    const cells: string[] = [];
    let cell = '';
    let quoted = false;
    for (let i = 0; i < line.length; i += 1) {
      const char = line[i];
      if (quoted) {
        if (char === '"' && line[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else if (char === '"') {
          quoted = false;
        } else {
          cell += char;
        }
      } else if (char === '"') {
        quoted = true;
      } else if (char === ',') {
        cells.push(cell.trim());
        cell = '';
      } else {
        cell += char;
      }
    }
    cells.push(cell.trim());
    rows.push(cells);
    if (rows.length > 200) break;
  }
  if (rows.length === 0) return '';
  const [head, ...body] = rows;
  const thead = `<thead><tr>${(head ?? []).map((cell) => `<th>${escapeHtml(cell)}</th>`).join('')}</tr></thead>`;
  const tbody = `<tbody>${body
    .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`)
    .join('')}</tbody>`;
  return `<table>${thead}${tbody}</table>`;
}

/** 空态 / 错误态统一成一块：图标 + 一句结论 + 一句原因 + 可选动作。 */
function PreviewNotice({
  tone = 'neutral',
  icon: Icon,
  title,
  body,
  actions,
}: {
  tone?: 'neutral' | 'danger';
  icon: ComponentType<{ size?: number; className?: string }>;
  title: string;
  body?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex min-h-[16rem] flex-1 flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <span
        className={`grid h-11 w-11 place-items-center rounded-panel ${
          tone === 'danger' ? 'bg-danger-soft text-danger' : 'bg-surface-sunken text-muted'
        }`}
      >
        <Icon size={20} />
      </span>
      <div className="max-w-[28rem]">
        <p className="text-regular font-semibold text-ink">{title}</p>
        {body ? <p className="mt-1 text-caption leading-relaxed text-muted">{body}</p> : null}
      </div>
      {actions ? (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2">{actions}</div>
      ) : null}
    </div>
  );
}

/**
 * 产物预览弹窗：
 * - docx：mammoth 本地转 HTML（保真渲染标题/段落）
 * - md：轻量 Markdown 渲染；txt：识别【小标题】/列表/生成信息后按文档排版
 * - csv：解析成表格（首行当表头），比一串逗号好读
 * - xlsx：后端 openpyxl 读表渲染 HTML 表格（只读前若干行）
 * - pdf：浏览器内置阅读器（iframe 指向下载流，带 `inline=1` 否则会被当附件下载）
 * 另外提供「用系统程序打开」：装了 WPS 就会用 WPS 打开原文件，改完直接存盘。
 *
 * 版式（第六十轮）：
 * - 标题栏 = 类型图块（36px）+ 文件名 + 一行副标题（类型/大小/时间/本机预览）；
 * - 正文 = 深一档的底子上铺一张「纸」（.doc-paper），纸上的留白由该类统一给：
 *   窄屏 22/18，≥640px 36/40，正文 15px/27px、每行 40~45 个汉字；
 * - 表格类换宽纸（880px）并允许横向滚动，宽表不再被挤成竖条；
 * - 页脚 = 一句说明（或操作结果）+ 关闭/系统打开/下载，窄屏整组换行。
 *
 * 两个窗口尺寸（第六十四轮）：默认「半窗口」——弹窗 900px、一张纸摆在桌面上，
 * 够看清版式又不压掉背后的对话；标题栏右侧的展开键切成「全窗口」——铺满整个
 * 窗口（只让出桌面端窗口按钮那一条），纸变成一整页、表格换满宽，Esc 退回半窗口。
 * 默认永远是半窗口：全窗口是临时放大来看，不该被记住成下一次的默认。
 *
 * 注意：**文档内部不再写 rem**。阅读区不该跟着「外观 · 基准字号」（默认 90%）
 * 一起缩——14rem 实际只有 12.6px，既小于中文可读下限，又是分数像素（发虚）。
 * 字号/行高/间距的像素值写在 tokens.css 的 .prose-docx 与 .doc-paper 里。
 */
export function ArtifactPreviewModal({
  artifact,
  onClose,
}: {
  artifact: PreviewTarget;
  onClose: () => void;
}) {
  const [state, setState] = useState<PreviewState>('loading');
  const [html, setHtml] = useState('');
  const [text, setText] = useState('');
  const [message, setMessage] = useState('');
  const [opening, setOpening] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  /** 全窗口阅读：默认半窗口（一张纸摆在桌面上），要细看时再铺满整个窗口 */
  const [full, setFull] = useState(false);
  const kind = previewKind(artifact.type, artifact.filename);
  const typeLabel = ARTIFACT_TYPE_LABELS[artifact.type] ?? artifact.type.toUpperCase();
  const style = artifactTypeStyle(artifact.type);
  const TypeIcon = style.icon;

  useEffect(() => {
    const controller = new AbortController();
    setState('loading');
    setNotice(null);

    const load = async () => {
      const type = kind;
      try {
        if (type === 'docx') {
          const response = await fetch(artifactsApi.artifactDownloadUrl(artifact.artifact_id), {
            signal: controller.signal,
            cache: 'no-store',
          });
          if (!response.ok) throw new Error(`下载不可用（HTTP ${response.status}）`);
          const arrayBuffer = await response.arrayBuffer();
          const result = await mammoth.convertToHtml(
            { arrayBuffer },
            // mammoth 的类型定义没覆盖 convertImage 的完整签名，这里按库的公开用法传
            docxOptions() as never,
          );
          setHtml(decorateDocxFigures(markDocxMeta(sanitizeHtml(result.value))));
          setState('ready');
          return;
        }
        if (type === 'xlsx') {
          // 表格排版交给后端（openpyxl → HTML 表格），前端只负责注入
          const response = await fetch(artifactsApi.artifactPreviewUrl(artifact.artifact_id), {
            signal: controller.signal,
            cache: 'no-store',
          });
          if (!response.ok) throw new Error(`预览不可用（HTTP ${response.status}）`);
          setHtml(sanitizeHtml(await response.text()));
          setState('ready');
          return;
        }
        if (type === 'md' || type === 'txt' || type === 'csv') {
          const response = await fetch(artifactsApi.artifactDownloadUrl(artifact.artifact_id), {
            signal: controller.signal,
            cache: 'no-store',
          });
          if (!response.ok) throw new Error(`预览不可用（HTTP ${response.status}）`);
          setText((await response.text()).slice(0, 200_000));
          setState('ready');
          return;
        }
        if (type === 'pdf' || type === 'html') {
          // PDF 交给浏览器内置阅读器，比「请下载后查看」有用得多
          setState('ready');
          return;
        }
        setMessage('该类型暂不支持内嵌预览，可以用系统程序打开或下载。');
        setState('ready');
      } catch (error) {
        if (controller.signal.aborted) return;
        setMessage(error instanceof Error ? error.message : '预览失败');
        setState('error');
      }
    };

    void load();
    return () => controller.abort();
    // 只认产物 id 与预览类型：父组件每次渲染都传新对象（内联 { artifact_id, ... }）时，
    // 依赖对象本身会让 effect 反复重跑 → setState('loading') → 再渲染，预览窗就一直频闪。
  }, [artifact.artifact_id, kind]);

  const download = async () => {
    setNotice(null);
    try {
      await saveRemoteFile(
        artifactsApi.artifactDownloadUrl(artifact.artifact_id),
        artifact.filename,
      );
      setNotice('已开始下载，文件在浏览器的下载目录里');
    } catch (error) {
      setNotice(`下载失败：${errorMessage(error)}`);
    }
  };

  const openWithSystem = async () => {
    setOpening(true);
    setNotice(null);
    try {
      const response = await artifactsApi.openArtifact(artifact.artifact_id);
      if (response.data.opened) {
        setNotice('已交给系统默认程序打开（装了 WPS 就会用 WPS）');
      } else {
        setNotice(`打开失败：${response.data.error ?? '未知原因'}`);
      }
    } catch (error) {
      setNotice(`打开失败：${errorMessage(error)}`);
    } finally {
      setOpening(false);
    }
  };

  const isDocContent = kind === 'docx' || kind === 'xlsx' || kind === 'md' || kind === 'txt';
  const isTable = kind === 'xlsx' || kind === 'csv';
  const fallbackActions = (
    <>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => void openWithSystem()}
        loading={opening}
        leading={<IconFolder size={12} />}
      >
        用系统程序打开
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => void download()}
        leading={<IconExternal size={12} />}
      >
        改为下载
      </Button>
    </>
  );

  return (
    <Modal
      title={artifact.filename}
      subtitle={
        <>
          <span className="shrink-0">{typeLabel}</span>
          <span aria-hidden className="text-line-strong">
            ·
          </span>
          <span className="shrink-0 tabular-nums">{formatBytes(artifact.size)}</span>
          {artifact.created_at ? (
            <>
              <span aria-hidden className="text-line-strong">
                ·
              </span>
              <span className="shrink-0 tabular-nums">{formatDateTime(artifact.created_at)}</span>
            </>
          ) : null}
          <span aria-hidden className="text-line-strong">
            ·
          </span>
          <span className="truncate">本机预览</span>
        </>
      }
      leading={
        <span className={`grid h-[36px] w-[36px] place-items-center ${style.tile} rounded-control`}>
          <TypeIcon size={17} />
        </span>
      }
      onClose={onClose}
      // 全窗口时 Esc 先退回半窗口（像看全屏 PDF 那样），再按一次才关；
      // 直接关掉会让人「一按 Esc 预览就没了」，还得重新点开。
      onEscape={() => (full ? setFull(false) : onClose())}
      size="lg"
      padded={false}
      fullscreen={full}
      actions={
        <IconButton
          label={full ? '还原半窗口' : '全窗口查看'}
          className="h-7 w-7"
          onClick={() => setFull((value) => !value)}
        >
          {full ? <IconCollapse size={14} /> : <IconExpand size={14} />}
        </IconButton>
      }
      footer={
        <>
          <div className="mr-auto flex min-w-0 flex-1 basis-full items-center gap-1.5 sm:basis-auto">
            <IconShield size={12} className="shrink-0 text-faint" />
            <span className="min-w-0 truncate text-caption text-muted">
              {/* 全窗口下顺手说清怎么退出去：展开键只有一枚图标，光靠气泡不好发现 */}
              {notice ??
                (full
                  ? '全窗口 · 按 Esc 退回半窗口 · 文件仍在本机解析'
                  : '预览在本机完成，不会上传文件内容')}
            </span>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={opening}
            onClick={() => void openWithSystem()}
            leading={<IconFolder size={13} />}
          >
            {/* 同一个动作在这儿和空态里都出现，名字必须一致；也不写「WPS」——
                 macOS/Linux 上调的是各自的系统程序 */}
            用系统程序打开
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void download()}
            leading={<IconDownload size={13} />}
          >
            下载
          </Button>
        </>
      }
    >
      <div className="flex h-full min-h-[16rem] flex-col bg-doc-backdrop">
        {state === 'loading' ? (
          <PreviewNotice
            icon={IconSpinner}
            title="正在渲染预览…"
            body="文档只在本机解析，不会上传"
          />
        ) : state === 'error' ? (
          <PreviewNotice
            tone="danger"
            icon={IconAlertTriangle}
            title="预览没能打开"
            body={message}
            actions={fallbackActions}
          />
        ) : kind === 'pdf' || kind === 'html' ? (
          <div className={full ? 'min-h-0 flex-1' : 'min-h-0 flex-1 p-3 sm:p-4'}>
            <iframe
              // inline=1：下载接口默认是 attachment，iframe 拉它会让浏览器直接下载
              src={artifactsApi.artifactInlineUrl(artifact.artifact_id)}
              title={artifact.filename}
              // html 只是本地文件，别给它同源脚本权限
              sandbox={kind === 'html' ? '' : undefined}
              className={
                full
                  ? 'h-full w-full border-0 bg-surface'
                  : 'h-[min(70vh,46rem)] w-full rounded-control border border-line bg-surface'
              }
            />
          </div>
        ) : isDocContent || kind === 'csv' ? (
          <div
            className={
              full
                ? 'min-h-0 flex-1 overflow-auto'
                : 'min-h-0 flex-1 overflow-auto px-3 py-3 sm:px-6 sm:py-5'
            }
          >
            <article
              data-testid="preview-doc"
              className={`prose-docx doc-paper ${isTable ? 'doc-paper--table' : ''} ${
                full ? 'doc-paper--full' : ''
              }`}
              // 两种来源都是服务端/本地解析器产出且已清洗过脚本与事件属性
              dangerouslySetInnerHTML={{
                __html:
                  kind === 'docx' || kind === 'xlsx'
                    ? html
                    : kind === 'md'
                      ? renderMarkdown(text)
                      : kind === 'csv'
                        ? renderCsv(text) || renderTextDoc(text)
                        : renderTextDoc(text),
              }}
            />
          </div>
        ) : (
          <PreviewNotice
            icon={IconFile}
            title="这个类型还不能内嵌预览"
            body={message || '可以用系统程序打开，或者下载到本机查看。'}
            actions={
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void openWithSystem()}
                  loading={opening}
                  leading={<IconFolder size={12} />}
                >
                  用系统程序打开
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void download()}
                  leading={<IconExternal size={12} />}
                >
                  下载
                </Button>
              </>
            }
          />
        )}
      </div>
    </Modal>
  );
}
