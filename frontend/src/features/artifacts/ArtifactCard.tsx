import { useState } from 'react';
import { errorMessage } from '../../shared/lib/api';
import { saveRemoteFile } from '../../shared/lib/download';
import { formatBytes, formatDateTime, formatNumber } from '../../shared/lib/format';
import { Tooltip } from '../../shared/ui/primitives';
import { useToast } from '../../shared/ui/toast-context';
import { ARTIFACT_TYPE_LABELS, artifactsApi } from './api';
import { ArtifactActions } from './components/ArtifactActions';
import { ArtifactPreviewModal } from './components/ArtifactPreviewModal';
import { artifactTypeStyle, stripExtension } from './type-style';
import type { ArtifactItem } from '../../shared/types/view';

/**
 * 产物行（工作台右栏）。
 *
 * 参照文件浏览器的做法：一行一个文件，只有「类型图标 + 文件名 + 类型标签」，
 * 类型/大小/来源/花费收进 hover 提示。
 *
 * 提示不用浏览器原生 title：那是白底直角系统气泡，跟界面其余部分的圆角与配色对不上，
 * 也没法排版「从哪份素材来、花了多少」这类多行信息。
 *
 * 鼠标经过时右侧的「格式 + 花费」原地换成操作条（预览 / 添加到对话框 / 下载）：
 * 仓库是窄栏，三个常驻图标会把文件名压到只剩几个字。
 */
export function ArtifactCard({
  artifact,
  onAddToChat,
}: {
  artifact: ArtifactItem;
  /** 把这份旧产物放回对话框当下一轮的素材 */
  onAddToChat?: (artifact: ArtifactItem) => Promise<boolean>;
}) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const toast = useToast();
  const tokens = artifact.tokens ?? 0;
  const typeLabel = ARTIFACT_TYPE_LABELS[artifact.type] ?? artifact.type;
  const style = artifactTypeStyle(artifact.type);
  const Icon = style.icon;
  const ext = artifact.filename.split('.').pop() ?? artifact.type;
  const metaHint = `${typeLabel} · ${formatBytes(artifact.size)} · ${formatDateTime(artifact.created_at)}`;

  // 提示条只放「文件叫什么、多大、什么时候生成的」。
  // 曾经还列过「源自 a.docx、b.docx、c.docx…」和这一份花了多少 token：
  // 素材一多就占满四五行，而这两件事用户在文件名和右侧的 tokens 数字里已经看得到，
  // 提示条反而挡住了真正想确认的那一行。
  const tip = (
    <span className="block">
      <span className="block break-all font-semibold text-tooltip-ink">{artifact.filename}</span>
      <span className="mt-0.5 block text-tooltip-ink opacity-70">{metaHint}</span>
    </span>
  );

  const save = async () => {
    try {
      await saveRemoteFile(
        artifactsApi.artifactDownloadUrl(artifact.artifact_id),
        artifact.filename,
      );
      toast.show(`已开始下载《${artifact.filename}》`, { tone: 'ok' });
    } catch (error) {
      toast.show(`下载失败：${errorMessage(error)}`, { tone: 'danger' });
    }
  };

  return (
    <div className="artifact-row group relative flex items-center gap-2 rounded-control px-2 py-1.5 transition-colors hover:bg-surface-hover">
      <span
        className={`artifact-row__tile grid h-6 w-6 shrink-0 place-items-center rounded-control ${style.tile}`}
      >
        <Icon size={14} />
      </span>

      {/* 详细元信息只挂在文件名上：鼠标移到右侧操作条时不会再冒出第二团说明，两个气泡打架 */}
      <Tooltip
        content={tip}
        side="bottom"
        delayMs={400}
        // 预览打开后鼠标还压在这一行上：提示气泡是 body 级 z-80，会浮到弹窗上面挡正文
        enabled={!previewOpen}
        className="min-w-0 flex-1"
      >
        <button
          type="button"
          onClick={() => setPreviewOpen(true)}
          className="block w-full truncate text-left text-caption font-medium text-ink transition-colors hover:text-brand-strong"
        >
          {stripExtension(artifact.filename)}
        </button>
      </Tooltip>

      {/* 类型标签与操作条共用右侧这一格：hover 时标签原地淡出、胶囊浮上来，
          宽度永远够放下三个图标 —— 以前胶囊是绝对定位直接压上去的，
          行短的时候会盖住文件名尾巴和 DOCX 标签。 */}
      <span className="relative flex h-6 min-w-[5.75rem] shrink-0 items-center justify-end">
        <span className="pointer-events-none flex items-center gap-1.5 whitespace-nowrap transition-opacity duration-150 group-hover:opacity-0 group-has-[:focus-visible]:opacity-0">
          <span
            className={`shrink-0 rounded-chip px-1.5 py-px text-[calc(10px*var(--font-scale))] font-semibold tracking-wide uppercase ${style.chip}`}
          >
            {ext.toUpperCase()}
          </span>

          {tokens > 0 ? (
            <span className="shrink-0 text-[calc(10px*var(--font-scale))] tabular-nums text-faint">
              {formatNumber(tokens)} tokens
            </span>
          ) : null}
        </span>

        <ArtifactActions
          artifact={artifact}
          onPreview={() => setPreviewOpen(true)}
          onAddToChat={onAddToChat ? () => onAddToChat(artifact) : undefined}
          onDownload={save}
          className="absolute top-1/2 right-0 -translate-y-1/2 translate-x-1 opacity-0 transition-all duration-150 group-hover:pointer-events-auto group-hover:translate-x-0 group-hover:opacity-100 group-has-[:focus-visible]:pointer-events-auto group-has-[:focus-visible]:translate-x-0 group-has-[:focus-visible]:opacity-100 pointer-events-none"
        />
      </span>

      {previewOpen ? (
        <ArtifactPreviewModal artifact={artifact} onClose={() => setPreviewOpen(false)} />
      ) : null}
    </div>
  );
}
