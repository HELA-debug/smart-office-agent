import { useMemo, useState } from 'react';
import { parseInline, parseMarkdown } from '../lib/markdown';
import type { MarkdownBlock } from '../lib/markdown';

function Inline({ text }: { text: string }) {
  const tokens = useMemo(() => parseInline(text), [text]);
  return (
    <>
      {tokens.map((token, index) => {
        switch (token.type) {
          case 'code':
            return (
              <code
                key={index}
                className="rounded-xs border border-line bg-surface-sunken px-1 py-[1px] font-mono text-[0.92em] text-brand-strong"
              >
                {token.text}
              </code>
            );
          case 'strong':
            return (
              <strong key={index} className="font-semibold text-ink">
                {token.text}
              </strong>
            );
          case 'link':
            return (
              <a
                key={index}
                href={token.href}
                target="_blank"
                rel="noreferrer"
                className="text-brand-strong underline decoration-brand-line underline-offset-2 hover:decoration-brand"
              >
                {token.text}
              </a>
            );
          default:
            return <span key={index}>{token.text}</span>;
        }
      })}
    </>
  );
}

function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="my-3 overflow-hidden rounded-control border border-[#1e2a44] bg-[#0d1526]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-1.5">
        <span className="font-mono text-caption tracking-wide text-slate-400">
          {lang || 'code'}
        </span>
        <button
          type="button"
          onClick={() => void copy()}
          className="rounded-xs px-1.5 py-0.5 text-caption text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-100"
        >
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre className="overflow-x-auto px-3 py-2.5 font-mono text-mini leading-relaxed text-slate-100">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function Block({ block }: { block: MarkdownBlock }) {
  switch (block.type) {
    case 'code':
      return <CodeBlock code={block.code} lang={block.lang} />;
    case 'heading': {
      const className =
        block.level <= 2
          ? 'mt-3 mb-1 text-regular font-semibold text-ink'
          : 'mt-2 mb-0.5 text-mini font-semibold text-ink-soft';
      return <div className={className}>{block.text}</div>;
    }
    case 'list':
      return block.ordered ? (
        <ol className="my-1.5 list-decimal space-y-0.5 pl-5 text-ink-soft marker:text-faint">
          {block.items.map((item, index) => (
            <li key={index}>
              <Inline text={item} />
            </li>
          ))}
        </ol>
      ) : (
        <ul className="my-1.5 list-disc space-y-0.5 pl-5 text-ink-soft marker:text-faint">
          {block.items.map((item, index) => (
            <li key={index}>
              <Inline text={item} />
            </li>
          ))}
        </ul>
      );
    case 'quote':
      return (
        <blockquote className="my-2 border-l-2 border-brand-line pl-3 text-muted italic">
          <Inline text={block.text} />
        </blockquote>
      );
    case 'divider':
      return <hr className="my-3 border-line" />;
    default:
      return (
        <p className="whitespace-pre-wrap">
          <Inline text={block.text} />
        </p>
      );
  }
}

export function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdown(text), [text]);
  return (
    <div className="space-y-1.5 leading-[1.7] break-words">
      {blocks.map((block, index) => (
        <Block key={index} block={block} />
      ))}
    </div>
  );
}
