import { useId, useState } from 'react';

export interface AreaPoint {
  label: string;
  value: number;
  /** tooltip 附加明细（如 tokens 拆分） */
  detail?: string;
}

/**
 * 轻量面积图（零依赖 SVG）：hover 显示十字线 + 深色 tooltip。
 * 用于审计用量的按日趋势（消费金额 / 请求次数 / tokens）。
 */
export function AreaChart({
  data,
  formatValue,
  color = 'var(--color-brand)',
  height = 120,
  unit = '',
}: {
  data: AreaPoint[];
  formatValue: (value: number) => string;
  color?: string;
  height?: number;
  unit?: string;
}) {
  const gradientId = useId();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center text-caption text-faint" style={{ height }}>
        暂无数据
      </div>
    );
  }

  const width = 600;
  const padding = { top: 12, right: 8, bottom: 20, left: 8 };
  const maxValue = Math.max(...data.map((point) => point.value), 0);
  const niceMax = maxValue > 0 ? maxValue * 1.15 : 1;
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;

  const xOf = (index: number) =>
    padding.left + (data.length === 1 ? innerWidth / 2 : (index / (data.length - 1)) * innerWidth);
  const yOf = (value: number) => padding.top + innerHeight - (value / niceMax) * innerHeight;

  const linePath = data
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${xOf(index)},${yOf(point.value)}`)
    .join(' ');
  const areaPath = `${linePath} L${xOf(data.length - 1)},${padding.top + innerHeight} L${xOf(0)},${
    padding.top + innerHeight
  } Z`;

  const hovered = hoverIndex != null ? (data[hoverIndex] ?? null) : null;
  const hoverX = hoverIndex != null ? xOf(hoverIndex) : 0;
  const hoverY = hovered ? yOf(hovered.value) : 0;

  const onMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    const index = Math.round(ratio * (data.length - 1));
    setHoverIndex(Math.min(data.length - 1, Math.max(0, index)));
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        role="img"
        onMouseMove={onMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {/* 顶部最大值参考线 */}
        <text
          x={padding.left}
          y={padding.top - 3}
          className="fill-[var(--color-faint)] text-[calc(9px*var(--font-scale))]"
        >
          {formatValue(maxValue)}
          {unit}
        </text>
        <path d={areaPath} fill={`url(#${gradientId})`} />
        <path d={linePath} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
        {hoverIndex != null ? (
          <>
            <line
              x1={hoverX}
              y1={padding.top}
              x2={hoverX}
              y2={padding.top + innerHeight}
              stroke="var(--color-line-strong)"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
            <circle cx={hoverX} cy={hoverY} r="3" fill={color} stroke="#fff" strokeWidth="1.5" />
          </>
        ) : null}
        {/* x 轴：首/中/末三个标签 */}
        {[0, Math.floor((data.length - 1) / 2), data.length - 1].map((index, position) => (
          <text
            key={index}
            x={xOf(index)}
            y={height - 5}
            textAnchor={position === 0 ? 'start' : position === 2 ? 'end' : 'middle'}
            className="fill-[var(--color-faint)] text-[calc(9px*var(--font-scale))]"
          >
            {data[index]?.label ?? ''}
          </text>
        ))}
      </svg>
      {hovered ? (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-control border border-line bg-tooltip/95 px-2 py-1 text-caption text-tooltip-ink shadow-pop backdrop-blur-[2px]"
          style={{
            left: `${(hoverX / width) * 100}%`,
            top: 0,
          }}
        >
          <div className="font-medium">
            {hovered.label} · {formatValue(hovered.value)}
            {unit}
          </div>
          {hovered.detail ? <div className="mt-0.5 text-faint">{hovered.detail}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
