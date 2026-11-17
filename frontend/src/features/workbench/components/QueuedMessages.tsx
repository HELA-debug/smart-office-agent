import {
  IconClock,
  IconFile,
  IconGrip,
  IconPause,
  IconPencil,
  IconPlay,
  IconSend,
  IconTrash,
} from '../../../shared/ui/Icons';
import { IconButton } from '../../../shared/ui/primitives';
import type { QueuedMessage } from '../state/workbench';

/**
 * 输入框上方的「排队消息」。
 *
 * 上一轮还在跑时发出的消息不丢弃、也不拦人，先在这儿排着；
 * 当前任务一结束就自动按顺序执行。
 *
 * 形态对齐聊天工具里熟悉的队列：上面一枚**胶囊**只说「现在有几条在等」，
 * 下面每条各占一张**卡片**（抓手 + 正文 + 右侧三个动作）。
 * 之前是一张带表头的大卡里塞轨道节点——表头占了半屏却只讲一件事，
 * 多条消息挤在一起也分不清边界；拆成「一枚计数 + 若干卡片」后，
 * 一眼看得出几条在等、每条是什么、想动哪条就动哪条。
 */
export function QueuedMessages({
  items,
  paused,
  onEdit,
  onRemove,
  onPromote,
  onResume,
}: {
  items: QueuedMessage[];
  paused: boolean;
  onEdit: (id: string) => void;
  onRemove: (id: string) => void;
  /** 优先执行：把这条提到队首（暂停中会顺手解除暂停） */
  onPromote: (id: string) => void;
  onResume: () => void;
}) {
  if (items.length === 0) return null;

  return (
    <section aria-label="排队中的任务" className="mb-2">
      <div className="mb-1.5 flex items-center gap-2">
        <span
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-caption ${
            paused
              ? 'border-warn-line bg-warn-soft text-warn'
              : 'border-line bg-surface-sunken/70 text-muted'
          }`}
        >
          {paused ? <IconPause size={11} /> : <IconClock size={11} />}
          {items.length} 条排队中
        </span>
        {paused ? (
          <>
            <span className="hidden text-caption text-warn/90 sm:inline">已暂停，不会自己跑</span>
            <button
              type="button"
              onClick={onResume}
              className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-full border border-warn-line bg-surface px-2.5 py-1 text-caption font-medium text-warn transition-colors hover:bg-warn-soft"
            >
              <IconPlay size={10} />
              继续执行
            </button>
          </>
        ) : (
          <span className="hidden text-caption text-faint sm:inline">
            当前任务结束后自动接着执行
          </span>
        )}
      </div>

      <ol className="space-y-1.5">
        {items.map((item, index) => {
          /** 队首：下一个就轮到它（暂停时谁都不算「下一个」） */
          const isNext = index === 0 && !paused;
          return (
            <li
              key={item.id}
              data-testid="queued-message"
              className={`group flex items-start gap-1.5 rounded-xl border bg-surface py-2 pr-1.5 pl-0.5 transition-colors ${
                isNext ? 'border-line-strong' : 'border-line'
              } hover:border-line-strong`}
            >
              {/* 抓手：告诉用户这几条是按顺序排的，不是同时跑 */}
              <span aria-hidden className="mt-1.5 shrink-0 pl-1 text-faint">
                <IconGrip size={13} />
              </span>

              <div className="min-w-0 flex-1 py-0.5">
                <div className="flex items-start gap-1.5">
                  <p className="line-clamp-2 min-w-0 text-regular leading-relaxed break-words text-ink">
                    {item.text}
                  </p>
                  {isNext ? (
                    <span className="mt-1 shrink-0 rounded-chip bg-brand-soft px-1.5 py-px text-[calc(10px*var(--font-scale))] font-medium text-brand-strong">
                      下一个
                    </span>
                  ) : null}
                </div>
                {item.uploads.length > 0 ? (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {item.uploads.map((upload) => (
                      <span
                        key={upload.local_id}
                        className="inline-flex max-w-[12rem] items-center gap-1 rounded-chip bg-surface-sunken px-1.5 py-px text-[calc(10px*var(--font-scale))] text-muted"
                      >
                        <IconFile size={9} className="shrink-0" />
                        <span className="truncate">{upload.filename}</span>
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>

              <div className="flex shrink-0 items-center gap-0.5 text-faint opacity-60 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 max-sm:opacity-100">
                <IconButton
                  label="优先执行这条排队任务"
                  className="h-7 w-7"
                  onClick={() => onPromote(item.id)}
                >
                  <IconSend size={13} />
                </IconButton>
                <IconButton
                  label="编辑这条排队任务"
                  className="h-7 w-7"
                  onClick={() => onEdit(item.id)}
                >
                  <IconPencil size={13} />
                </IconButton>
                {/* 删除平时是灰的、只在 hover 变红：三条一模一样的红垃圾桶太抢眼睛，
                    排在队里最常做的是「看/改」，不是「删」 */}
                <IconButton
                  label="删除这条排队任务"
                  className="h-7 w-7 hover:bg-danger-soft! hover:text-danger!"
                  onClick={() => onRemove(item.id)}
                >
                  <IconTrash size={13} />
                </IconButton>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
