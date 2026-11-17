import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AreaChart } from './AreaChart';

const data = [
  { label: '10-01', value: 10, detail: '3 次运行' },
  { label: '10-02', value: 40 },
  { label: '10-03', value: 20 },
];

describe('AreaChart', () => {
  it('空数据给占位文案', () => {
    render(<AreaChart data={[]} formatValue={(value) => String(value)} />);
    expect(screen.getByText('暂无数据')).toBeInTheDocument();
  });

  it('渲染折线、面积与首中末三个横轴标签', () => {
    const { container } = render(
      <AreaChart data={data} formatValue={(value) => `¥${value.toFixed(2)}`} unit=" 元" />,
    );

    expect(screen.getByRole('img')).toBeInTheDocument();
    expect(container.querySelectorAll('path')).toHaveLength(2); // 面积 + 折线
    expect(screen.getByText('10-01')).toBeInTheDocument();
    expect(screen.getByText('10-02')).toBeInTheDocument();
    expect(screen.getByText('10-03')).toBeInTheDocument();
    // 顶部最大值参考线取数据里的最大值（不是 niceMax）
    expect(screen.getByText('¥40.00 元')).toBeInTheDocument();
  });

  it('单点数据不会把横坐标算成 0/0', () => {
    const { container } = render(
      <AreaChart data={[{ label: '只有一天', value: 5 }]} formatValue={String} />,
    );
    expect(container.querySelector('path')?.getAttribute('d')).toContain('M');
    // 只有一个点时首/中/末三个标签是同一个，会渲染三份
    expect(screen.getAllByText('只有一天')).toHaveLength(3);
  });

  it('全 0 数据用 1 兜底，不出现 NaN 坐标', () => {
    const { container } = render(
      <AreaChart
        data={[
          { label: 'a', value: 0 },
          { label: 'b', value: 0 },
        ]}
        formatValue={String}
      />,
    );
    expect(container.querySelector('path')?.getAttribute('d')).not.toContain('NaN');
  });

  it('hover 显示十字线 + tooltip（含明细），移出后收起', () => {
    const { container } = render(
      <AreaChart data={data} formatValue={(value) => `¥${value}`} unit=" 元" />,
    );
    const svg = screen.getByRole('img');
    Object.defineProperty(svg, 'getBoundingClientRect', {
      value: () => ({
        left: 0,
        width: 600,
        top: 0,
        height: 120,
        right: 600,
        bottom: 120,
        x: 0,
        y: 0,
      }),
      configurable: true,
    });

    // clientX=300 → 比例 0.5 → 第 2 个点（索引 1）
    fireEvent.mouseMove(svg, { clientX: 300 });
    expect(screen.getByText('10-02 · ¥40 元')).toBeInTheDocument();
    expect(container.querySelector('circle')).not.toBeNull();
    expect(container.querySelector('line[stroke-dasharray]')).not.toBeNull();

    // 第 1 个点带 detail
    fireEvent.mouseMove(svg, { clientX: 0 });
    expect(screen.getByText('10-01 · ¥10 元')).toBeInTheDocument();
    expect(screen.getByText('3 次运行')).toBeInTheDocument();

    fireEvent.mouseLeave(svg);
    expect(screen.queryByText(/10-01 · /)).toBeNull();
    expect(container.querySelector('circle')).toBeNull();
  });

  it('越界坐标被夹到端点，不会取到 undefined', () => {
    render(<AreaChart data={data} formatValue={String} />);
    const svg = screen.getByRole('img');
    Object.defineProperty(svg, 'getBoundingClientRect', {
      value: () => ({
        left: 0,
        width: 600,
        top: 0,
        height: 120,
        right: 600,
        bottom: 120,
        x: 0,
        y: 0,
      }),
      configurable: true,
    });

    fireEvent.mouseMove(svg, { clientX: 9999 });
    expect(screen.getByText('10-03 · 20')).toBeInTheDocument();

    fireEvent.mouseMove(svg, { clientX: -9999 });
    expect(screen.getByText('10-01 · 10')).toBeInTheDocument();
  });
});

describe('AreaChart 自定义样式', () => {
  it('颜色与高度可覆盖', () => {
    const { container } = render(
      <AreaChart data={data} formatValue={String} color="var(--color-ok)" height={80} />,
    );
    const svg = screen.getByRole('img');
    expect(svg).toHaveAttribute('viewBox', '0 0 600 80');
    const stroke = container.querySelector('path[stroke]');
    expect(stroke?.getAttribute('stroke')).toBe('var(--color-ok)');
  });
});
