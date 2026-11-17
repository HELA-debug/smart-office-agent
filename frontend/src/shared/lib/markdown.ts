/** 轻量 Markdown 块解析（不引入第三方依赖；够 Demo 用：标题/列表/代码/引用/段落）。 */

export type MarkdownBlock =
  | { type: 'paragraph'; text: string }
  | { type: 'heading'; level: number; text: string }
  | { type: 'code'; lang: string; code: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'quote'; text: string }
  | { type: 'divider' };

const FENCE = /^```(\S*)\s*$/;

export function parseMarkdown(source: string): MarkdownBlock[] {
  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const blocks: MarkdownBlock[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i] ?? '';

    if (line.trim() === '') {
      i += 1;
      continue;
    }

    // 代码块
    const fence = FENCE.exec(line.trim());
    if (fence) {
      const lang = fence[1] ?? '';
      const codeLines: string[] = [];
      i += 1;
      while (i < lines.length && !(lines[i] ?? '').trim().startsWith('```')) {
        codeLines.push(lines[i] ?? '');
        i += 1;
      }
      i += 1; // 跳过结束围栏
      blocks.push({ type: 'code', lang, code: codeLines.join('\n') });
      continue;
    }

    // 分隔线
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      blocks.push({ type: 'divider' });
      i += 1;
      continue;
    }

    // 标题
    const heading = /^(#{1,6})\s+(.*)$/.exec(line.trim());
    if (heading) {
      blocks.push({ type: 'heading', level: (heading[1] ?? '#').length, text: heading[2] ?? '' });
      i += 1;
      continue;
    }

    // 引用
    if (line.trimStart().startsWith('> ')) {
      const quoteLines: string[] = [];
      while (i < lines.length && (lines[i] ?? '').trimStart().startsWith('> ')) {
        quoteLines.push((lines[i] ?? '').trimStart().slice(2));
        i += 1;
      }
      blocks.push({ type: 'quote', text: quoteLines.join(' ') });
      continue;
    }

    // 列表（同类型的连续条目合成一块）
    const listItem = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line);
    if (listItem) {
      const ordered = /\d/.test(listItem[2] ?? '');
      const items: string[] = [];
      while (i < lines.length) {
        const match = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i] ?? '');
        if (!match) break;
        if (/\d/.test(match[2] ?? '') !== ordered) break;
        items.push(match[3] ?? '');
        i += 1;
      }
      blocks.push({ type: 'list', ordered, items });
      continue;
    }

    // 段落：连续非空、非其它块的行
    const paragraphLines: string[] = [];
    while (i < lines.length) {
      const current = lines[i] ?? '';
      if (current.trim() === '') break;
      if (FENCE.test(current.trim())) break;
      if (/^#{1,6}\s+/.test(current.trim())) break;
      if (/^(\s*)([-*+]|\d+[.)])\s+/.test(current)) break;
      if (current.trimStart().startsWith('> ')) break;
      paragraphLines.push(current);
      i += 1;
    }
    blocks.push({ type: 'paragraph', text: paragraphLines.join(' ').trim() });
  }

  return blocks;
}

/** 行内解析：[text](url)、`code`、**bold**。 */
export type InlineToken =
  | { type: 'text'; text: string }
  | { type: 'code'; text: string }
  | { type: 'strong'; text: string }
  | { type: 'link'; text: string; href: string };

const INLINE_PATTERN = /(`([^`]+)`)|(\*\*([^*]+)\*\*)|(\[([^\]]+)\]\(([^)\s]+)\))/g;

export function parseInline(text: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  let lastIndex = 0;
  INLINE_PATTERN.lastIndex = 0;

  let match: RegExpExecArray | null = INLINE_PATTERN.exec(text);
  while (match) {
    if (match.index > lastIndex) {
      tokens.push({ type: 'text', text: text.slice(lastIndex, match.index) });
    }
    if (match[2] != null) {
      tokens.push({ type: 'code', text: match[2] });
    } else if (match[4] != null) {
      tokens.push({ type: 'strong', text: match[4] });
    } else if (match[6] != null && match[7] != null) {
      tokens.push({ type: 'link', text: match[6], href: match[7] });
    }
    lastIndex = INLINE_PATTERN.lastIndex;
    match = INLINE_PATTERN.exec(text);
  }

  if (lastIndex < text.length) {
    tokens.push({ type: 'text', text: text.slice(lastIndex) });
  }
  return tokens;
}
