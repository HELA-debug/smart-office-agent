import { useEffect, useRef, useState } from 'react';
import {
  IconCheck,
  IconDownload,
  IconEye,
  IconPaperclip,
  IconSpinner,
} from '../../../shared/ui/Icons';
import { Tooltip } from '../../../shared/ui/primitives';
import type { ArtifactItem } from '../../../shared/types/view';
import type { ReactNode } from 'react';

/**
 * 产物行右侧的悬浮操作条：预览 / 添加到对话框 / 下载。
 *
 * 为什么把三件事收进一条「胶囊」里，而不是各放一个按钮：
 * 交付行本身是文件清单，一行只该读「叫什么、多大、什么格式」——三个常驻按钮会把
 * 文件名挤成一串省略号。鼠标经过时才浮出来，图标之间用一个浅色胶囊包住，
 * 视觉上是「这一行被拿起来操作」，跟页面其它悬浮控件（输入框工具条、顶栏）同一套语言。
 *
 * 下载与「添加到对话框」都是异步的，各自在按钮位上转圈；「添加到对话框」成功后
 * 图标变勾停留一会儿——这两个动作都没有跳转，不给反馈用户会以为没点上。
 */
export function ArtifactActions({
  artifact,
  onPreview,
  onAddToChat,
  onDownload,
  className = '',
}: {
  artifact: ArtifactItem;
  onPreview: () => void;
  /** 把这份产物放回对话框（作为下一轮的素材）；返回 false 表示没成功 */
  onAddToChat?: () => Promise<boolean>;
  onDownload?: () => Promise<void> | void;
  /** 定位/显隐交给调用方：交付行与右栏仓库的行内空间不一样 */
  className?: string;
}) {
  const [busy, setBusy] = useState<'download' | 'add' | null>(null);
  const [added, setAdded] = useState(false);
  const timerRef = useRef<number | null>(null);

  // 勾的停留靠定时器收尾：卸载时清掉，避免对已卸载组件 setState
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  const download = async () => {
    if (!onDownload || busy) return;
    setBusy('download');
    try {
      await onDownload();
    } finally {
      setBusy(null);
    }
  };

  const addToChat = async () => {
    // 刚加完的 1.6 秒里忽略第二次点击：同一份产物重复加只会多出一份一样的素材
    if (!onAddToChat || busy || added) return;
    setBusy('add');
    let ok = false;
    try {
      ok = (await onAddToChat()) !== false;
    } catch {
      // 失败原因由调用方弹提示；这里只负责把按钮恢复原状
      ok = false;
    } finally {
      setBusy(null);
    }
    if (!ok) return;
    setAdded(true);
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setAdded(false), 1600);
  };

  return (
    <span
      role="toolbar"
      aria-label={`${artifact.filename} 的操作`}
      className={`flex items-center gap-1 rounded-control border border-line bg-surface/95 p-1 shadow-card backdrop-blur-[2px] ${className}`}
    >
      <ActionButton label="预览" onClick={onPreview}>
        <IconEye size={12} />
      </ActionButton>

      {onAddToChat ? (
        <ActionButton
          label={added ? '已加入对话框' : '添加到对话框'}
          tone={added ? 'brand' : 'default'}
          disabled={busy !== null}
          onClick={() => void addToChat()}
        >
          {busy === 'add' ? (
            <IconSpinner size={12} />
          ) : added ? (
            <IconCheck size={12} />
          ) : (
            <IconPaperclip size={12} />
          )}
        </ActionButton>
      ) : null}

      {onDownload ? (
        <ActionButton label="下载" disabled={busy !== null} onClick={() => void download()}>
          {busy === 'download' ? <IconSpinner size={12} /> : <IconDownload size={12} />}
        </ActionButton>
      ) : null}
    </span>
  );
}

/** 胶囊里的单个图标按钮：hover 只改底色与字色，尺寸固定 24px，鼠标扫过去不会「跳」 */
function ActionButton({
  label,
  children,
  onClick,
  disabled = false,
  tone = 'default',
}: {
  label: string;
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  tone?: 'default' | 'brand';
}) {
  return (
    <Tooltip label={label} side="top" className="inline-flex">
      <button
        type="button"
        aria-label={label}
        disabled={disabled}
        onClick={onClick}
        className={`grid h-6 w-6 place-items-center rounded-[0.4rem] transition-colors focus-visible:ring-2 focus-visible:ring-brand-line focus-visible:outline-none disabled:opacity-50 ${
          tone === 'brand'
            ? 'bg-brand-soft text-brand-strong'
            : 'text-muted hover:bg-surface-hover hover:text-ink'
        }`}
      >
        {children}
      </button>
    </Tooltip>
  );
}
