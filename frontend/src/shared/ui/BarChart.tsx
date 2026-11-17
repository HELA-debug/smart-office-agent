import { useMemo } from 'react';

export interface BarPoint {
  label: string;
  value: number;
}

/**
 * 轻量柱状图（零依赖）：框架高度固定，柱高只按数值的相对大小变化。
 * 之前用面积图时，某一天突然冒出一个消费尖峰会把整张图拉成「一条平线 + 一个尖」，
 * 改柱状后峰谷对比更容易读，也不会把卡片撑高。
 */
export function BarChart({
  data,
  formatValue,
  height = 132,
  unit = '',
}: {
  data: BarPoint[];
  formatValue: (value: number) => string;
  height?: number;
  unit?: string;
}) {
  const maxValue = useMemo(() => Math.max(...data.map((point) => point.value), 0), [data]);

  if (data.length === 0 || maxValue <= 0) {
    return (
      <div className="flex items-center justify-center text-caption text-faint" style={{ height }}>
        这段时间还没有消费记录
      </div>
    );
  }

  const ticks = [maxValue, maxValue / 2, 0];
  // 标签太多会挤在一起：最多显示 6 个（首、尾各一个，中间均匀取）
  const labelStep = Math.max(1, Math.ceil(data.length / 6));

  return (
    <div className="px-1">
      <div className="flex items-stretch gap-2" style={{ height }} data-chart-frame>
        {/* y 轴刻度：固定宽度，柱子区域宽度不随数值变化 */}
        <div className="flex w-12 shrink-0 flex-col justify-between py-0.5 text-right text-caption text-faint">
          {ticks.map((tick, index) => (
            <span key={index}>{formatValue(tick)}</span>
          ))}
        </div>
        <div className="flex min-w-0 flex-1 items-end gap-[2px]">
          {data.map((point) => {
            const ratio = maxValue > 0 ? point.value / maxValue : 0;
            return (
              <div key={point.label} className="group relative flex h-full flex-1 items-end">
                <div
                  data-bar
                  className="w-full rounded-t-[3px] bg-brand-solid/70 transition-colors duration-150 group-hover:bg-brand-solid"
                  style={{ height: `${Math.max(ratio * 100, point.value > 0 ? 2 : 0)}%` }}
                />
                <span
                  data-bar-tip
                  className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded-chip border border-line bg-tooltip/95 px-1.5 py-0.5 text-caption text-tooltip-ink shadow-card backdrop-blur-[2px] group-hover:block"
                >
                  {point.label} · {formatValue(point.value)}
                  {unit}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="mt-1 flex gap-2">
        <span className="w-12 shrink-0" />
        <div className="flex min-w-0 flex-1 justify-between text-caption text-faint">
          {data
            .filter((_, index) => index % labelStep === 0 || index === data.length - 1)
            .map((point) => (
              <span key={point.label}>{point.label}</span>
            ))}
        </div>
      </div>
    </div>
  );
}
