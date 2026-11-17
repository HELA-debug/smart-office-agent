/**
 * 柱状图：框架高度固定，柱高只按数值相对大小变化（不能按绝对值撑高卡片）。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BarChart } from './BarChart';

const data = [
  { label: '10-01', value: 0 },
  { label: '10-02', value: 5 },
  { label: '10-03', value: 1 },
  { label: '10-04', value: 2.5 },
];

function barHeights(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll<HTMLElement>('[data-bar]')).map(
    (node) => node.style.height,
  );
}

describe('BarChart', () => {
  it('没有任何数值时给空态文案', () => {
    render(<BarChart data={[{ label: '10-01', value: 0 }]} formatValue={(v) => `¥${v}`} />);
    expect(screen.getByText('这段时间还没有消费记录')).toBeInTheDocument();
  });

  it('柱高按最大值归一：最大的一根 100%，零值不出现柱子', () => {
    const { container } = render(
      <BarChart data={data} formatValue={(value) => `¥${value.toFixed(2)}`} />,
    );
    const heights = barHeights(container);
    expect(heights).toHaveLength(4);
    expect(heights[1]).toBe('100%');
    expect(heights[0]).toBe('0%');
    // 1 / 5 = 20%
    expect(heights[2]).toBe('20%');
  });

  it('高度写死在容器上，不随数据条数或数值变大', () => {
    const { container } = render(
      <BarChart data={data} formatValue={(value) => `${value}`} height={140} />,
    );
    const frame = container.querySelector<HTMLElement>('[data-chart-frame]');
    expect(frame?.style.height).toBe('140px');
  });

  it('y 轴刻度从最大值到 0，鼠标悬停显示具体金额（不用原生 title）', () => {
    const { container } = render(<BarChart data={data} formatValue={(value) => `¥${value}`} />);
    expect(container.textContent).toContain('¥5');
    expect(container.textContent).toContain('¥0');
    const tips = Array.from(container.querySelectorAll('[data-bar-tip]')).map(
      (node) => node.textContent ?? '',
    );
    expect(tips).toHaveLength(4);
    expect(tips[1]).toContain('10-02');
    expect(container.querySelector('[title]')).toBeNull();
  });
});
