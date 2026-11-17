import { IconChevronDown, IconFile, IconInbox, IconShield } from '../../../shared/ui/Icons';
import { Badge, IconButton, Tooltip } from '../../../shared/ui/primitives';
import { ArtifactCard } from '../../artifacts';
import { DesktopAppCard } from './DesktopAppCard';
import type { ArtifactItem } from '../state/workbench';

/**
 * 右栏：本会话的产物仓库。
 *
 * 交付物在对话里已经给了卡片（能预览、能下载），这一栏是「仓库」视角：
 * 这个会话一共产出过哪些文件，一行一个，方便回头翻。
 *
 * 底部「本次素材」已撤掉：素材在输入框和对话里都看得见，这里再列一遍只是重复；
 * 空出来的高度留给产物列表，仓库才装得下更多文件。
 */
export function RightPanel({
  artifacts,
  canAudit,
  onOpenAudit,
  onOpenAllArtifacts,
  onAddArtifact,
}: {
  artifacts: ArtifactItem[];
  /** 有可审计的运行时才给入口（没有就灰掉，避免点了没反应）。 */
  canAudit: boolean;
  onOpenAudit: () => void;
  onOpenAllArtifacts: () => void;
  /** 把仓库里的旧产物放回对话框：翻到一份上周的稿子，接着说「照这个再改一版」 */
  onAddArtifact?: (artifact: ArtifactItem) => Promise<boolean>;
}) {
  return (
    <div className="flex h-full min-w-0 flex-col bg-surface">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
        <IconFile size={15} className="shrink-0 text-muted" />
        <span className="text-regular font-semibold text-ink">产物仓库</span>
        <Badge tone={artifacts.length > 0 ? 'brand' : 'neutral'}>{artifacts.length}</Badge>
        <span className="ml-auto flex items-center gap-1">
          <span className="text-caption text-faint">本次会话</span>
          <IconButton
            label="打开审计用量"
            className="h-6 w-6"
            disabled={!canAudit}
            onClick={onOpenAudit}
          >
            <IconShield size={13} />
          </IconButton>
        </span>
      </div>

      {/*
        产物区：只吃掉「剩下的高度」。
        空态只要一句话说明这里会出现什么——起步示例属于输入框的活儿，
        放在产物栏里既占高度又抢注意力。
      */}
      <div className="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto overscroll-contain px-1.5 py-1.5 [&>*]:shrink-0">
        {artifacts.length === 0 ? (
          <div className="flex flex-1 flex-col justify-center px-2 pb-6">
            <div className="mx-auto w-full max-w-[16.5rem]">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-surface-sunken text-faint">
                <IconInbox size={16} />
              </span>
              <p className="mt-2.5 text-caption leading-snug text-faint">
                这个会话还没有文件。跑完一轮，产出会先出现在对话里，同时归档到这里。
              </p>
            </div>
          </div>
        ) : (
          artifacts.map((artifact) => (
            <ArtifactCard
              key={artifact.artifact_id}
              artifact={artifact}
              onAddToChat={onAddArtifact}
            />
          ))
        )}

        {artifacts.length > 0 ? (
          /*
           * 悬停提示走统一的 Tooltip，不用原生 title：
           * 系统气泡是方角白框，跟这一栏的圆角卡片完全不是一个体系。
           * 外层 span 必须 block w-full，否则按钮宽度会缩到文字那么长，
           * 鼠标划过时的底色短一截（「框那么宽、背景那么短」）。
           */
          <Tooltip
            label="打开产物中心，并定位到本会话的产物"
            side="top"
            delayMs={200}
            className="mt-1 block w-full shrink-0"
          >
            <button
              type="button"
              onClick={onOpenAllArtifacts}
              // 文案不说「全部产物」：进了产物页只看到本会话（那才是用户点它的意图），
              // 跨会话浏览在左栏「产物中心」，别用一个词指两件事。
              className="inline-flex w-full items-center justify-center gap-1 rounded-control px-2 py-1.5 text-caption text-faint transition-colors hover:bg-surface-hover hover:text-ink"
            >
              查看本会话全部产物
              <IconChevronDown size={11} className="-rotate-90" />
            </button>
          </Tooltip>
        ) : null}
      </div>

      {/* 桌面端入口贴在最底下：它是「换一种更顺手的方式用这个产品」，
          不是本轮任务的一部分，所以不跟产物抢上面的位置。 */}
      <DesktopAppCard />
    </div>
  );
}
