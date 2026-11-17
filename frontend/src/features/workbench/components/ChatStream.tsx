import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useThinkingView } from '../../../shared/lib/thinking-pref';
import { IconChevronDown } from '../../../shared/ui/Icons';
import { Button } from '../../../shared/ui/primitives';
import { PlanCard } from '../../runs';
import { ToolCard } from '../../runs';
import { SubagentCard } from '../../runs';
import { selectRetriedIds } from '../state/selectors';
import { ArtifactDelivery } from './ArtifactDelivery';
import { ExecutionTrace } from './ExecutionTrace';
import { MessageBubble } from './MessageBubble';
import { ThinkingBlock } from './ThinkingBlock';
import type { ThinkingView } from '../../../shared/lib/thinking-pref';
import type { ArtifactItem } from '../../../shared/types/view';
import type { NoteItem, TimelineItem, WorkbenchStatus } from '../state/workbench';
import type { ReactNode } from 'react';

const PIN_THRESHOLD_PX = 140;

/**
 * 中间旁白（channel=process）：不带头像、不起气泡，只在思考过程里当一行说明。
 *
 * 以前每次「读素材 / 过结构 / 换模板」都发一条 assistant 消息，每条都带一遍
 * 「Office Agent + 时间」抬头，一次运行下来对话区几乎被抬头占满。
 */
function TraceNote({ note }: { note: NoteItem }) {
  return (
    <div className="flex gap-2 px-2.5 text-caption leading-relaxed text-muted">
      <span className="mt-[0.55rem] h-1 w-1 shrink-0 rounded-full bg-faint" />
      <p className="min-w-0 whitespace-pre-wrap break-words">
        {note.content}
        {note.streaming ? <span className="caret" aria-hidden /> : null}
      </p>
    </div>
  );
}

/**
 * 哪些时间线条目属于「中间过程」：计划、工具调用、子智能体、旁白。
 *
 * 决策行（thinking）不在里面：它现在只有一句话、一次运行最多出现两三次，
 * 收进折叠条就白说了——那正是用户最该看见的一行。
 */
function isTraceItem(item: TimelineItem): boolean {
  return (
    item.kind === 'plan' || item.kind === 'tool' || item.kind === 'subagent' || item.kind === 'note'
  );
}

/**
 * 一轮对话：用户说过一句话之后、下一句之前的所有东西。
 *
 * 为什么要按轮切：中间过程（计划、工具、思考）以前按到达顺序插在对话里，
 * 于是「执行过程」那一坨永远压在 Office Agent 头像上方——看起来像上一轮的尾巴，
 * 正文被它顶下去。切轮之后，一轮里的过程统一收到该轮正文下面、产物上面，
 * 阅读顺序变成「你说了什么 → 它答了什么 → 它怎么想的 → 给了什么文件」。
 */
type Turn = { key: string; items: TimelineItem[] };

function splitTurns(items: TimelineItem[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;
  for (const item of items) {
    const startsTurn = item.kind === 'message' && item.message.role === 'user';
    if (!current || startsTurn) {
      current = { key: item.id, items: [] };
      turns.push(current);
    }
    current.items.push(item);
  }
  return turns;
}

function renderTraceItem(item: TimelineItem, superseded?: Set<string>): ReactNode {
  switch (item.kind) {
    case 'plan':
      return <PlanCard key={item.id} plan={item.plan} />;
    case 'tool':
      return <ToolCard key={item.id} tool={item.tool} retried={superseded?.has(item.id)} />;
    case 'subagent':
      return <SubagentCard key={item.id} subagent={item.subagent} />;
    case 'thinking':
      return <ThinkingBlock key={item.id} thinking={item.thinking} />;
    case 'note':
      return <TraceNote key={item.id} note={item.note} />;
    default:
      return null;
  }
}

/** 一条中间过程不值得收成一组（本来就是一行流水），两条以上才折叠。 */
function renderTraces(traces: TimelineItem[], active: boolean): ReactNode {
  if (traces.length === 0) return null;
  const superseded = selectRetriedIds(traces);
  if (traces.length === 1) {
    const only = traces[0];
    return only ? renderTraceItem(only, superseded) : null;
  }
  return (
    <ExecutionTrace items={traces} active={active}>
      {traces.map((item) => renderTraceItem(item, superseded))}
    </ExecutionTrace>
  );
}

/**
 * 按设置裁剪「过程」的可见度。
 * - full：原样全给；
 * - brief：只留计划主线，工具调用、旁白、推理全文都收走；
 * - off：一条都不留，对话里只剩回复与产物。
 */
function filterTraces(traces: TimelineItem[], view: ThinkingView): TimelineItem[] {
  if (view === 'off') return [];
  if (view === 'brief') return traces.filter((item) => item.kind === 'plan');
  return traces;
}

export function ChatStream({
  items,
  status,
  artifacts = [],
  currentRunId,
  emptyState,
  onAddArtifact,
}: {
  items: TimelineItem[];
  status: WorkbenchStatus;
  /** 本轮/本会话生成的文件：直接摆在对话末尾，能预览能下载 */
  artifacts?: ArtifactItem[];
  /** 当前正在跑的 run id：用来把「本轮的产物」和「上一轮的旧产物」分开处理 */
  currentRunId?: string | null;
  emptyState: ReactNode;
  /** 把交付区里的某份产物放回对话框（作为下一轮素材） */
  onAddArtifact?: (artifact: ArtifactItem) => Promise<boolean>;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  // 「思考过程显示多少」是本地偏好：设置里一改，这里立刻跟着变
  const thinkingView = useThinkingView();

  // 自动滚动：只有用户已经在底部附近时才跟随，避免打断向上翻阅。
  // 正文输出中跟着「正在输出的那条气泡」的末尾走，而不是容器底部——
  // 过程行和产物都排在正文后面，贴底会让刚打出来的字跑到屏幕外。
  useEffect(() => {
    const element = scrollRef.current;
    if (!element || !pinned || items.length === 0) return;
    const max = element.scrollHeight - element.clientHeight;
    const streaming = element.querySelector<HTMLElement>('[data-streaming="true"]');
    if (streaming) {
      const bottom =
        streaming.getBoundingClientRect().bottom -
        element.getBoundingClientRect().top +
        element.scrollTop;
      element.scrollTop = Math.max(0, Math.min(max, bottom - element.clientHeight + 24));
      return;
    }
    element.scrollTop = max;
    // artifacts.length 也算一次「内容变化」：产物是跑完才插入的，那一刻 items 早已不动，
    // 不跟着滚就会整块落在视口外——用户只看到对话停住，还以为没生成。
  }, [items, pinned, artifacts.length]);

  const turns = useMemo(() => splitTurns(items), [items]);
  const activeTurnKey = status === 'streaming' ? turns[turns.length - 1]?.key : undefined;

  /**
   * 本轮产物等这一轮跑完再现身。
   *
   * 以前只压到「开口说第一句」就放出来，于是用户看到的是半成品：脚本还在重跑、
   * 同名文件随时会被覆盖，点预览不是「产物不存在」就是旧内容。这不是加载慢，是
   * 「结果还没定稿就先摆上桌」。现在整轮（含等待审批）都压住，收尾时一次性露出。
   *
   * 只压本轮：上一轮的旧产物早就亮在屏幕上了，跟着一起压会闪一下再回来。
   */
  const deliveryArtifacts = useMemo(() => {
    const running = status === 'streaming' || status === 'waiting_approval';
    if (!running || !currentRunId) return artifacts;
    return artifacts.filter((artifact) => artifact.run_id !== currentRunId);
  }, [artifacts, currentRunId, status]);

  const onScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    setPinned(distance < PIN_THRESHOLD_PX);
  };

  const scrollToBottom = () => {
    const element = scrollRef.current;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' });
    setPinned(true);
  };

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="h-full overflow-y-auto overscroll-contain px-gutter pt-[clamp(0.75rem,2.4vh,1.5rem)] pb-[clamp(0.5rem,1.6vh,1rem)]"
        data-testid="chat-stream"
      >
        {/* 一轮一个块：正文在上、思考过程在下，条目间距同步收紧，一屏能看到更多上下文 */}
        <div className="mx-auto flex min-h-full w-full max-w-[52rem] flex-col gap-3">
          {items.length === 0 ? emptyState : null}
          {turns.map((turn) => {
            const traces = filterTraces(turn.items.filter(isTraceItem), thinkingView);
            return (
              <Fragment key={turn.key}>
                {turn.items
                  .filter((item) => !isTraceItem(item))
                  // 「不显示过程」时连决策行一起收走；其余档位都留着——
                  // 它已经不是流水账，而是这一轮唯一一句「我在想什么」。
                  .filter((item) => thinkingView !== 'off' || item.kind !== 'thinking')
                  .map((item) =>
                    item.kind === 'message' ? (
                      <MessageBubble key={item.id} message={item.message} />
                    ) : item.kind === 'thinking' ? (
                      <ThinkingBlock key={item.id} thinking={item.thinking} />
                    ) : null,
                  )}
                {renderTraces(traces, turn.key === activeTurnKey)}
              </Fragment>
            );
          })}
          {/* 交付物跟在回复后面：跑完就能点开看、点一下下载，不用再跑去右栏找。
              key 跟着最新一份产物走：新产物落桌时整块重新挂载，deliver-in 才会重播一次
              （只改内容不换 key 的话，CSS 动画只在首次挂载时跑，后面几轮又变成硬插入）。 */}
          <ArtifactDelivery
            key={deliveryArtifacts[deliveryArtifacts.length - 1]?.artifact_id ?? 'empty'}
            artifacts={deliveryArtifacts}
            onAddToChat={onAddArtifact}
          />
        </div>
      </div>

      {!pinned && items.length > 0 ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center">
          <Button
            variant="secondary"
            size="sm"
            onClick={scrollToBottom}
            leading={<IconChevronDown size={14} />}
            className="pointer-events-auto shadow-pop"
          >
            回到底部
          </Button>
        </div>
      ) : null}
    </div>
  );
}
