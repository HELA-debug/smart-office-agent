/**
 * 图标组件单测。
 *
 * 图标本身没有逻辑，但它们是「无障碍」和「尺寸契约」的薄弱环节：
 *   - 装饰性图标必须对读屏隐藏（aria-hidden），否则读屏会念出无意义的图形；
 *   - viewBox / stroke 由 base() 统一注入，被覆盖就会破坏整套图标的视觉一致性。
 * 因此这里批量渲染全部图标并校验公共契约，避免新增图标时漏掉约定。
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import * as Icons from './Icons';
import type { IconProps } from './Icons';
import type { ReactElement } from 'react';

const ICON_EXPORTS = Object.entries(Icons).filter(
  ([name, value]) => name.startsWith('Icon') && typeof value === 'function',
) as Array<[string, (props: IconProps) => ReactElement]>;

describe('图标清单', () => {
  it('数量符合预期（新增/删除图标时需同步更新这里）', () => {
    expect(ICON_EXPORTS.length).toBe(68);
  });
});

describe('图标公共契约', () => {
  it.each(ICON_EXPORTS)('%s 渲染为 svg 且对读屏隐藏', (_name, Icon) => {
    const { container } = render(<Icon />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });

  it.each(ICON_EXPORTS)('%s 默认尺寸 16，可通过 size 覆盖', (_name, Icon) => {
    const { container, rerender } = render(<Icon />);
    const svg = container.querySelector('svg') as SVGSVGElement;
    const defaults = Icon.name === 'IconLogo' ? 20 : 16;
    expect(svg.getAttribute('width')).toBe(String(defaults));
    expect(svg.getAttribute('height')).toBe(String(defaults));

    rerender(<Icon size={32} />);
    expect(container.querySelector('svg')?.getAttribute('width')).toBe('32');
    expect(container.querySelector('svg')?.getAttribute('height')).toBe('32');
  });

  // IconLogo 是品牌标识，直接沿用应用图标的 512 viewBox（见下面的专项断言）
  it.each(ICON_EXPORTS.filter(([name]) => name !== 'IconLogo'))(
    '%s 使用统一的 24x24 viewBox',
    (_name, Icon) => {
      const { container } = render(<Icon />);
      expect(container.querySelector('svg')?.getAttribute('viewBox')).toBe('0 0 24 24');
    },
  );

  it.each(ICON_EXPORTS)('%s 允许外部覆盖 className 与事件', (_name, Icon) => {
    const onClick = { current: 0 };
    const { container } = render(
      <Icon className="text-danger" onClick={() => (onClick.current += 1)} />,
    );
    const svg = container.querySelector('svg') as SVGSVGElement;
    expect(svg.getAttribute('class')).toContain('text-danger');
    svg.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onClick.current).toBe(1);
  });
});

describe('描边类图标的统一样式', () => {
  // Logo 是纯填充的品牌图形，不参与描边约定
  const strokedIcons = ICON_EXPORTS.filter(([name]) => name !== 'IconLogo');

  it.each(strokedIcons)('%s 采用 currentColor 描边（跟随文字颜色）', (_name, Icon) => {
    const { container } = render(<Icon />);
    const svg = container.querySelector('svg') as SVGSVGElement;
    expect(svg.getAttribute('stroke')).toBe('currentColor');
    expect(svg.getAttribute('fill')).toBe('none');
    expect(svg.getAttribute('stroke-width')).toBe('1.8');
  });

  it.each(strokedIcons)('%s 描边端点与连接为圆角', (_name, Icon) => {
    const { container } = render(<Icon />);
    const svg = container.querySelector('svg') as SVGSVGElement;
    expect(svg.getAttribute('stroke-linecap')).toBe('round');
    expect(svg.getAttribute('stroke-linejoin')).toBe('round');
  });
});

describe('IconLogo 品牌图形', () => {
  it('与桌面端应用图标同源：深墨底板 + 白色文档 + 蓝色星，且不参与描边约定', () => {
    const { container } = render(<Icons.IconLogo />);
    const svg = container.querySelector('svg') as SVGSVGElement;
    // 直接复用 512 的 viewBox，改图标时两边不会走偏
    expect(svg.getAttribute('viewBox')).toBe('0 0 512 512');
    expect(svg.getAttribute('stroke')).toBeNull();
    // 底板 / 文档 / 星：三个填充色必须都在
    const fills = Array.from(svg.querySelectorAll('rect, path')).map((el) =>
      el.getAttribute('fill'),
    );
    expect(fills).toContain('#0d1526');
    expect(fills).toContain('#ffffff');
    expect(fills).toContain('#2563eb');
    // 21px 下只留两条文字行，多了会糊
    expect(svg.querySelectorAll('rect[height="30"]')).toHaveLength(2);
  });
});

describe('IconSpinner 加载态', () => {
  it('带旋转动画与弧形路径，尺寸可定制（按钮 loading 用 13/15）', () => {
    const { container, rerender } = render(<Icons.IconSpinner size={13} />);
    const svg = container.querySelector('svg') as SVGSVGElement;
    expect(svg.getAttribute('class')).toContain('animate-spin');
    expect(svg.querySelector('path')?.getAttribute('d')).toBe('M12 3a9 9 0 1 0 9 9');
    expect(svg.getAttribute('width')).toBe('13');
    rerender(<Icons.IconSpinner size={15} />);
    expect(container.querySelector('svg')?.getAttribute('width')).toBe('15');
  });

  it('自定义 className 追加而非覆盖动画类', () => {
    const { container } = render(<Icons.IconSpinner className="text-brand" />);
    const svgClass = container.querySelector('svg')?.getAttribute('class') ?? '';
    expect(svgClass).toContain('animate-spin');
    expect(svgClass).toContain('text-brand');
  });
});
