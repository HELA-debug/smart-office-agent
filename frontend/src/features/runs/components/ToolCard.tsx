import { useMemo, useState } from 'react';
import { formatDuration, toolLabel } from '../../../shared/lib/format';
import { redactValue } from '../../../shared/lib/redact';
import { IconCheck, IconChevronDown, IconTerminal, IconX } from '../../../shared/ui/Icons';
import { CardError, CardLoading } from '../../../shared/ui/primitives';
import type { ToolCallItem } from '../../../shared/types/view';

function JsonBlock({ value, emptyLabel }: { value: unknown; emptyLabel: string }) {
  const text = useMemo(() => {
    if (value == null) return '';
    try {
      return JSON.stringify(redactValue(value), null, 2);
    } catch {
      return String(value);
    }
  }, [value]);

  if (!text) return <div className="text-caption text-faint">{emptyLabel}</div>;

  return (
    <pre className="max-h-56 overflow-auto rounded-control border border-line bg-surface-soft px-2.5 py-2 font-mono text-caption leading-relaxed text-ink-soft">
      {text}
    </pre>
  );
}

/**
 * 一次工具调用：一行流水（做了什么 + 结果 + 耗时），点开才看入参/出参。
 * 原来一个调用就是一张带图标方块、风险徽标、成功徽标的卡片，
 * 一次运行五六个调用就把对话刷满屏——现在收成一行，展开才占地方。
 */
export function ToolCard({
  tool,
  loading = false,
  loadError = null,
  retried = false,
}: {
  tool: ToolCallItem;
  loading?: boolean;
  loadError?: string | null;
  /** 这一次没成，但同一件工具后面成功了——它只是一次草稿，不该画成事故 */
  retried?: boolean;
}) {
  const [open, setOpen] = useState(false);
  // 有意跳过（门控没放行）不是故障：以前一律按失败画红框 + 红叉，界面上就成了
  // 「×1 步失败」——用户以为程序坏了，其实是我们替他把了道门。
  const skipped = tool.skipped === true && !tool.ok;
  const bad = !tool.ok && !skipped && !retried;

  if (loading) {
    return (
      <div className="rounded-control border border-line bg-surface px-2.5 py-2">
        <CardLoading label="正在调用工具…" rows={1} />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="rounded-control border border-danger-line bg-surface px-2.5 py-2">
        <CardError message={loadError} />
      </div>
    );
  }

  return (
    <div className={bad ? 'overflow-hidden rounded-control border border-warn-line/70' : ''}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 rounded-control px-2.5 py-1.5 text-left transition-colors hover:bg-surface-hover"
        aria-expanded={open}
      >
        <IconTerminal
          size={13}
          className={`shrink-0 ${bad ? 'text-warn' : skipped || retried ? 'text-faint' : 'text-muted'}`}
        />
        <span className="shrink-0 text-mini font-medium text-ink">{toolLabel(tool.tool)}</span>
        <span className="min-w-0 flex-1 truncate text-mini text-faint">{tool.summary}</span>
        {bad ? (
          <IconX size={12} className="shrink-0 text-warn" />
        ) : skipped ? (
          <span className="shrink-0 text-caption text-faint">已跳过</span>
        ) : retried ? (
          <span className="shrink-0 text-caption text-faint">已重试</span>
        ) : (
          <IconCheck size={12} className="shrink-0 text-ok" />
        )}
        <span className="shrink-0 text-caption tabular-nums text-faint">
          {formatDuration(tool.duration_ms)}
        </span>
        <IconChevronDown
          size={13}
          className={`shrink-0 text-faint transition-transform ${open ? '' : '-rotate-90'}`}
        />
      </button>

      {open ? (
        <div className="border-t border-line px-2.5 py-2.5">
          <div className="mb-2 font-mono text-caption text-faint">{tool.tool}</div>
          {tool.error ? (
            // 报错只在这层出现：外层那一行已经说了「这次没成」，展开是给想深究的人看的。
            <div className="mb-2 rounded-control border border-line bg-surface-soft px-2.5 py-1.5 text-caption text-ink-soft">
              <span className="break-words">
                {tool.error.message || '这次没有成功，错误已回传给模型继续处理'}
              </span>
              <span className="ml-2 shrink-0 font-mono text-[10px] text-faint">
                {tool.error.code}
              </span>
            </div>
          ) : null}
          <div className="grid gap-2.5 md:grid-cols-2">
            <div>
              <div className="mb-1 text-caption font-medium text-faint">入参</div>
              <JsonBlock value={tool.input} emptyLabel="无入参" />
            </div>
            <div>
              <div className="mb-1 text-caption font-medium text-faint">出参</div>
              <JsonBlock value={tool.output} emptyLabel="无出参" />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
