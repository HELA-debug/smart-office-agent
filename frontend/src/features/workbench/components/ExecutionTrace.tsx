import { useMemo, useRef, useState } from 'react';
import { IconChevronDown, IconSparkle, IconX } from '../../../shared/ui/Icons';
import { selectRetriedIds } from '../state/selectors';
import type { TimelineItem } from '../state/workbench';
import type { ReactNode } from 'react';

/**
 * 执行过程：把「计划 / 工具调用 / 子智能体 / 旁白」收成一行。
 *
 * v1.5 起决策行（thinking）不再收进来：它一次只有一句话、一轮最多两三条，
 * 是这一轮里唯一一句「它在想什么」，折进这里就白说了——那一行直接摊在对话里。
 *
 * 一次运行会刷出四五条流水，用户要滚半天才看到正文。这里默认只留一行
 * （在干什么、走了几步、有没有失败），想看细节再点开。
 */
export function ExecutionTrace({
  items,
  active = false,
  children,
}: {
  items: TimelineItem[];
  /** 这一轮还在跑：图标呼吸、文案说「正在…」，让等待有落点 */
  active?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);

  const summary = useMemo(() => {
    const plan = [...items].reverse().find((item) => item.kind === 'plan');
    const todos = plan?.kind === 'plan' ? (plan.plan?.todos ?? []) : [];
    const done = todos.filter((todo) => todo.status === 'completed').length;
    const currentTodo = todos.find((todo) => todo.status === 'in_progress');

    const tools = items.filter((item) => item.kind === 'tool');
    // 两样都不计入失败：跳过（门控没放行）不是出错；重试后成了的那次只是草稿。
    const covered = selectRetriedIds(items);
    const failed =
      tools.filter(
        (item) =>
          item.kind === 'tool' && !item.tool.ok && !item.tool.skipped && !covered.has(item.id),
      ).length +
      items.filter((item) => item.kind === 'subagent' && item.subagent?.status === 'failed').length;

    const runningAgent = items.find(
      (item) => item.kind === 'subagent' && item.subagent?.status === 'running',
    );
    const lastTool = tools[tools.length - 1];

    const current = currentTodo
      ? currentTodo.content
      : runningAgent?.kind === 'subagent' && runningAgent.subagent
        ? runningAgent.subagent.summary || `${runningAgent.subagent.name} 运行中`
        : lastTool?.kind === 'tool'
          ? lastTool.tool.summary
          : '';

    return { done, total: todos.length, failed, current };
  }, [items]);

  // 运行中只说「正在做什么」；跑完什么都不说。
  // **不报步数**：走几步是我们自己的工程参数，用户关心的是「东西做出来了没有」。
  // 何况「共 6 步」这种数字只会让人替我们担心——他并不知道 6 步够不够、上限在哪，
  // 只会以为「是不是快用完了」。有计划时右边已经有「3/5」那一格，够表示进度了。
  const headline = active ? (summary.current ? `正在：${summary.current}` : '正在处理…') : '';
  // 跑完那一刻不能把这句话「删掉」——文字从有到无是硬切，和产物卡片插进来撞在同一帧，
  // 看起来就是界面猛地换了一块。留着上一句、只把透明度收到 0，它会自己淡下去。
  // ref 在这里只是「记住上一帧渲染的值」，写入幂等、不触发渲染。
  const lastHeadline = useRef('');
  if (headline) lastHeadline.current = headline;
  const shownHeadline = headline || lastHeadline.current;

  return (
    // 不加边框：它是一行「说明」，不是一张卡片。卡片会和下面的产物区连成一摞盒子，
    // 而这一行本来就该退到背景里——想看细节再点开。
    <div className={open ? 'rounded-control bg-surface-sunken/40 p-1' : ''}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-control px-2.5 py-1 text-left transition-colors hover:bg-surface-hover"
      >
        <IconSparkle
          size={13}
          className={`shrink-0 transition-colors duration-200 ${active ? 'animate-pulse text-brand' : 'text-faint'}`}
        />
        <span
          className={`shrink-0 text-mini transition-colors duration-200 ${active ? 'font-medium text-ink-soft' : 'text-muted'}`}
        >
          思考过程
        </span>
        {summary.failed > 0 ? (
          <span className="inline-flex shrink-0 items-center gap-0.5 text-mini text-danger">
            <IconX size={11} />
            {summary.failed} 处没走通
          </span>
        ) : null}
        {/* flex-1 保留占位：文案淡出后右侧的「3/5」不会跟着弹回左边 */}
        <span
          className={`min-w-0 flex-1 truncate text-mini text-muted transition-opacity duration-200 ${
            active ? 'opacity-100' : 'opacity-0'
          }`}
          aria-hidden={!active}
        >
          {shownHeadline}
        </span>
        {summary.total > 0 ? (
          <span className="shrink-0 text-caption tabular-nums text-faint">
            {summary.done}/{summary.total}
          </span>
        ) : null}
        <IconChevronDown
          size={13}
          className={`shrink-0 text-faint transition-transform ${open ? '' : '-rotate-90'}`}
        />
      </button>

      {open ? <div className="mt-1 flex flex-col gap-1.5">{children}</div> : null}
    </div>
  );
}
