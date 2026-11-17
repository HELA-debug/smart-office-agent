import { useState } from 'react';
import { errorMessage } from '../../../shared/lib/api';
import { saveRemoteFile } from '../../../shared/lib/download';
import { formatBytes } from '../../../shared/lib/format';
import { IconChevronDown } from '../../../shared/ui/Icons';
import { Tooltip } from '../../../shared/ui/primitives';
import { useToast } from '../../../shared/ui/toast-context';
import {
  ArtifactActions,
  ArtifactPreviewModal,
  artifactsApi,
  artifactTypeStyle,
} from '../../artifacts';
import type { ArtifactItem } from '../../../shared/types/view';

/**
 * 对话里的交付区：一轮跑完，把产物直接摆到对话里。
 *
 * 版式对齐「像一份附件清单」而不是「一个可展开的日志」：
 * 左侧一行小字「产物」，右侧一行一个文件——类型图块、文件名（带扩展名）、大小、
 * 以及鼠标经过时才浮出来的操作条（预览 / 添加到对话框 / 下载）。
 *
 * **只铺最新一份，其余全部折叠**（用户定的规矩，不看 run_id）：
 * 同一轮出两张 PDF、或者一次跑出「会议纪要 + 周报」时，全铺开会让对话底部变成
 * 文件列表，用户反而找不到「刚生成的那一份」。所以只要有第 2 份，就收进
 * 「更早的产物 · N 个」，默认收起，点开是一个限高可滚动的小盒子。
 * 默认收起是刻意的：历史文件是用来「回头找」的，不是每次都要看的。
 *
 * 「最新」按列表顺序取末位，不按挂载时间：产物列表是创建时间升序
 * （后端 `created_at asc`、实时事件按发生顺序追加），刷新页面回到刚跑完的会话时
 * 末位仍然是那一轮最后出的文件，界面前后一致。
 */
export function ArtifactDelivery({
  artifacts,
  onAddToChat,
}: {
  artifacts: ArtifactItem[];
  /** 把这份产物放回对话框：交给工作台（上传成下一轮素材 + 提示） */
  onAddToChat?: (artifact: ArtifactItem) => Promise<boolean>;
}) {
  /** 用户点了「更早的产物」：把折叠区摊开 */
  const [showOlder, setShowOlder] = useState(false);

  // 列表已按创建时间升序：末位是最新的一份，其余一律进折叠区（含同轮出的其它文件）。
  // 空数组时末位是 undefined，直接整块不渲染。
  const latest = artifacts[artifacts.length - 1];
  if (!latest) return null;
  const older = artifacts.slice(0, -1);

  return (
    // deliver-in：整块（含左侧「产物」二字）一起浮上来。跑完时过程行先淡出、
    // 它再落位，两个动作错开 90ms，才像「这件事做完了」而不是界面上突然多一块。
    <section
      aria-label="本次产物"
      className="deliver-in flex items-start gap-2.5 pl-[2.375rem]"
    >
      <span className="mt-[9px] shrink-0 text-caption leading-5 text-faint">产物</span>

      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <DeliveryCard key={latest.artifact_id} artifact={latest} onAddToChat={onAddToChat} />

        {older.length > 0 ? (
          <div className="mt-0.5">
            <button
              type="button"
              aria-expanded={showOlder}
              onClick={() => setShowOlder((value) => !value)}
              className="inline-flex items-center gap-1 rounded-chip px-1.5 py-1 text-caption text-muted transition-colors hover:bg-surface-hover hover:text-ink-soft"
            >
              <IconChevronDown
                size={12}
                className={`shrink-0 transition-transform ${showOlder ? '' : '-rotate-90'}`}
              />
              更早的产物
              <span className="tabular-nums text-faint">{older.length} 个</span>
            </button>

            {showOlder ? (
              <div className="relative mt-1">
                <div className="flex max-h-[14rem] flex-col gap-1 overflow-y-auto overscroll-contain rounded-control border border-line bg-surface-sunken/50 p-1.5">
                  {[...older].reverse().map((artifact) => (
                    <DeliveryCard
                      key={artifact.artifact_id}
                      artifact={artifact}
                      onAddToChat={onAddToChat}
                    />
                  ))}
                </div>
                {/* 盒子里还能往下翻时给一道渐隐：底部被切断的那一行看起来像坏了 */}
                {older.length > 3 ? (
                  <div
                    aria-hidden
                    className="pointer-events-none absolute inset-x-px bottom-px h-7 rounded-b-control bg-gradient-to-t from-surface to-transparent"
                  />
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function DeliveryCard({
  artifact,
  onAddToChat,
}: {
  artifact: ArtifactItem;
  onAddToChat?: (artifact: ArtifactItem) => Promise<boolean>;
}) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const toast = useToast();
  const style = artifactTypeStyle(artifact.type);
  const Icon = style.icon;
  const ext = (artifact.filename.split('.').pop() ?? artifact.type).toUpperCase();

  /**
   * 下载走「取一份 blob 再存」，不是 <a href download>：
   * 后者在同一地址上点第二次会不会落盘取决于浏览器缓存策略，用户遇到的就是「点了没反应」。
   * 每点一次都给一句可见的反馈，成功失败都不闷着。
   */
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
    <div className="artifact-row artifact-row--card group relative flex items-center gap-2.5 rounded-control border border-line bg-surface py-2 pr-2 pl-2.5">
      <span
        className={`artifact-row__tile grid h-7 w-7 shrink-0 place-items-center rounded-[0.5rem] ${style.tile}`}
        aria-hidden
      >
        <Icon size={14} />
      </span>

      {/* 文件名常被截断：提示里要能读到全名，所以让它换行而不是再截一次 */}
      <Tooltip
        content={<span className="break-all">{artifact.filename}</span>}
        side="top"
        delayMs={400}
        className="min-w-0 flex-1"
      >
        <button
          type="button"
          onClick={() => setPreviewOpen(true)}
          className="block w-full truncate text-left text-mini font-medium text-ink transition-colors hover:text-brand-strong"
        >
          {artifact.filename}
        </button>
      </Tooltip>

      {/* 右侧固定宽度的「信息 ↔ 操作」槽位：hover 时两者原地交换，行高与文件名的宽度都不变 */}
      <span className="relative flex h-6 w-[6rem] shrink-0 items-center justify-end">
        {/* 只有指针压着 / 键盘 focus 时才让位；用 focus-within 的话，
            鼠标点完再移开焦点还在按钮上，操作条会一直亮着 */}
        <span className="pointer-events-none flex items-center gap-1.5 whitespace-nowrap transition-opacity duration-150 group-hover:opacity-0 group-has-[:focus-visible]:opacity-0">
          <span className="shrink-0 text-caption tabular-nums text-faint">
            {formatBytes(artifact.size)}
          </span>
          <span
            className={`rounded-chip px-1.5 py-px text-[calc(10px*var(--font-scale))] font-semibold tracking-wide ${style.chip}`}
          >
            {ext}
          </span>
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
