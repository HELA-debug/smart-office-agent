import { useRef, useState } from 'react';
import {
  buildThreadMarkdown,
  copyText,
  downloadTextFile,
  safeFilename,
} from '../../../shared/lib/share';
import { FloatingMenu } from '../../../shared/ui/FloatingMenu';
import { IconDownload, IconExport, IconFile } from '../../../shared/ui/Icons';
import { IconButton } from '../../../shared/ui/primitives';
import { useToast } from '../../../shared/ui/toast-context';
import type { ThreadSummary } from '../../../shared/types/api';

/**
 * 会话条目上的「导出」。
 *
 * 只做两件真能做到的事：复制正文 Markdown、下载 .md。
 * 之前那排「分享到微信/企微/QQ/钉钉/腾讯文档」已经删掉——那些按钮除了往剪贴板塞一句话
 * 什么也没做，点了还让人以为发出去了；「复制链接」更假，应用里没有 /threads/:id，
 * 链接打开就是首页。与其摆六个假的，不如把两个真的做顺手。
 */
export function ExportMenu({ session }: { session: ThreadSummary }) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const toast = useToast();

  const title = session.title || '未命名会话';
  const updatedLabel = new Date(session.updated_at).toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

  const markdown = () =>
    buildThreadMarkdown({
      title,
      updatedAt: updatedLabel,
      messageCount: session.message_count,
      artifactCount: session.artifact_count ?? 0,
    });

  const onCopy = async () => {
    setOpen(false);
    const ok = await copyText(markdown());
    toast.show(ok ? '已复制 Markdown' : '复制失败：浏览器拒绝了剪贴板权限', {
      tone: ok ? 'ok' : 'warn',
    });
  };

  const onDownload = () => {
    setOpen(false);
    downloadTextFile(`${safeFilename(title)}.md`, markdown());
    toast.show('已导出 .md 文件', { tone: 'ok' });
  };

  return (
    <>
      <span ref={anchorRef} className="inline-flex">
        <IconButton
          label="导出会话"
          // 不要悬浮气泡：这一行右边只剩 24px，气泡会往上盖住上一行的标题与产物数，
          // 两个会话行叠在一起看像渲染错位。图标本身（带箭头的方框）够直观。
          tip={false}
          aria-expanded={open}
          className={`h-6 w-6 ${open ? 'bg-surface-sunken text-ink' : ''}`}
          onClick={() => setOpen((value) => !value)}
        >
          <IconExport size={12} />
        </IconButton>
      </span>

      <FloatingMenu
        open={open}
        onClose={() => setOpen(false)}
        anchorRef={anchorRef}
        width={188}
        label="导出会话"
      >
        <div className="px-2.5 pt-0.5 pb-1.5 text-caption text-faint">导出</div>
        <button
          type="button"
          role="menuitem"
          onClick={() => void onCopy()}
          className="flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left text-caption text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
        >
          <IconFile size={12} className="shrink-0 text-muted" />
          复制 Markdown
        </button>
        <button
          type="button"
          role="menuitem"
          onClick={onDownload}
          className="flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left text-caption text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
        >
          <IconDownload size={12} className="shrink-0 text-muted" />
          下载 .md
        </button>
      </FloatingMenu>
    </>
  );
}
