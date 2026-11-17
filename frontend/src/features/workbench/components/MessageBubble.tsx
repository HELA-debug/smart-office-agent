import { formatClock } from '../../../shared/lib/format';
import { IconInfo } from '../../../shared/ui/Icons';
import { Markdown } from '../../../shared/ui/Markdown';
import type { ChatMessage } from '../state/workbench';

function AssistantAvatar() {
  return (
    <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#3b82f6] to-[#1d4ed8] text-white shadow-card">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
        <rect x="4" y="8" width="16" height="11" rx="3.5" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 4v4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <circle cx="8.7" cy="13" r="1.2" fill="currentColor" />
        <circle cx="15.3" cy="13" r="1.2" fill="currentColor" />
      </svg>
    </div>
  );
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === 'system') {
    return (
      <div className="flex justify-center">
        <div className="inline-flex max-w-[90%] items-center gap-1.5 rounded-full border border-line bg-surface-sunken px-3 py-1 text-caption text-muted">
          <IconInfo size={12} />
          <span className="whitespace-pre-wrap">{message.content}</span>
        </div>
      </div>
    );
  }

  if (message.role === 'user') {
    return (
      <div className="flex flex-col items-end gap-1">
        <div className="max-w-[82%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-regular text-white shadow-card">
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
        </div>
        <div className="pr-1 text-caption text-faint">你 · {formatClock(message.created_at)}</div>
      </div>
    );
  }

  return (
    // data-streaming：滚动跟随用——正文后面还挂着思考过程与产物，贴容器底部会看不见正在输出的字
    <div
      className="flex items-start gap-2.5"
      data-streaming={message.streaming ? 'true' : undefined}
    >
      <AssistantAvatar />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-mini font-semibold text-ink-soft">Office Agent</span>
          <span className="text-caption text-faint">{formatClock(message.created_at)}</span>
          {message.streaming ? (
            <span className="inline-flex items-center gap-1 text-caption text-brand">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />
              正在输出
            </span>
          ) : null}
        </div>
        <div className="rounded-2xl rounded-tl-md border border-line bg-surface px-4 py-3 text-regular text-ink-soft shadow-card">
          <Markdown text={message.content} />
          {message.streaming ? <span className="caret" aria-hidden /> : null}
        </div>
      </div>
    </div>
  );
}
