import { IconAlertTriangle, IconInfo, IconSparkle } from '../../../shared/ui/Icons';
import type { ThinkingItem } from '../state/workbench';

/**
 * 决策行（v1.5，沿用 thinking.* 事件）：一行淡字，不再是「思考过程」面板。
 *
 * 为什么改：以前每轮开工都先摊开一大段推演（固定的四个维度、固定的篇幅），
 * 读起来像模板在演，还把正文顶下去。现在后端只在真的需要判断时给一句话——
 * 它挑了哪个方向、停下来问你、还是某一步没成——所以这里也不该再给卡片、
 * 边框和「已思考 3.2 秒」。安静地干活，比先把方法论念一遍更像人。
 */
export function ThinkingBlock({ thinking }: { thinking: ThinkingItem }) {
  const kind = thinking.kind ?? 'decision';
  const failed = kind === 'error';
  const Icon = failed ? IconAlertTriangle : kind === 'ask' ? IconInfo : IconSparkle;
  const iconTone = failed ? 'text-warn' : kind === 'ask' ? 'text-brand' : 'text-faint';
  const textTone = failed ? 'text-warn' : 'text-ink-soft';

  return (
    <div className="flex items-start gap-1.5 px-2.5" data-thinking-kind={kind}>
      <Icon
        size={12}
        className={`mt-[0.3rem] shrink-0 ${iconTone} ${thinking.streaming ? 'animate-pulse' : ''}`}
      />
      <p
        className={`min-w-0 whitespace-pre-wrap break-words text-mini leading-relaxed ${textTone}`}
      >
        {thinking.content}
        {thinking.streaming ? <span className="caret" aria-hidden /> : null}
      </p>
    </div>
  );
}
