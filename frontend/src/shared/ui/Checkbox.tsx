import { useEffect, useRef } from 'react';
import { IconCheck } from './Icons';

/**
 * 勾选框。
 *
 * 为什么不用原生 `<input type="checkbox">` 只加 `accent-color`：
 * 未勾选时的底纹由浏览器自己画，而浏览器看的是系统的 color-scheme——用户系统是深色时，
 * 白底卡片里就冒出一个近乎纯黑的方块，跟页面完全不搭（这一版就是被这个坑到的）。
 * 所以这里把外观整个接管：常态是「白底 + 稍微压深一点的边框」，勾上是品牌蓝 + 白勾，
 * 系统深浅色怎么设都不影响。
 *
 * 结构是「透明 input + 覆盖层」：input 仍然是真的 checkbox，键盘、读屏、
 * 表单语义（含 indeterminate）全都保留，只是自己的绘制被 appearance-none 关掉了。
 */
export function Checkbox({
  checked,
  indeterminate = false,
  onChange,
  label,
  /** 给外面 <label htmlFor> 用；外面如果已经有包着它的 label，就不用传 */
  id,
  disabled = false,
  size = 'md',
  className = '',
}: {
  checked: boolean;
  /** 半选（「全选本页」只选了一部分时）：视觉是一条横杠 */
  indeterminate?: boolean;
  onChange: (next: boolean) => void;
  /** 读屏用的名字；外面已经有 <label> 包着时可以不传 */
  label?: string;
  id?: string;
  disabled?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  // indeterminate 只能通过 DOM 属性设置（HTML 没有对应 attribute）
  useEffect(() => {
    if (inputRef.current) inputRef.current.indeterminate = indeterminate && !checked;
  }, [indeterminate, checked]);

  const box = size === 'sm' ? 'h-3.5 w-3.5 rounded-[0.28rem]' : 'h-4 w-4 rounded-[0.32rem]';
  const mark = size === 'sm' ? 9 : 11;
  const active = checked || indeterminate;

  return (
    <span className={`relative inline-grid shrink-0 place-items-center ${className}`}>
      <input
        ref={inputRef}
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => onChange(event.target.checked)}
        className={`${box} cursor-pointer appearance-none border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-line disabled:cursor-not-allowed disabled:opacity-50 ${
          active
            ? 'border-brand-solid bg-brand-solid'
            : // 未勾选：纯白底 + 比 line-strong 再深一档的灰边。
              // line-strong(#cbd5e1) 在白卡片上几乎看不见，14px 的小方框会像「一个缺口」；
              // 用 ink-soft 45% 叠在白底上约 #adb3bb，深浅色主题下都够看。
              'border-ink-soft/45 bg-surface hover:border-brand-border'
        }`}
      />
      {/* 勾 / 横杠画在 input 上面：不拦截点击（pointer-events-none），点哪儿都还是 input */}
      {checked ? (
        <IconCheck size={mark} className="pointer-events-none absolute text-white" />
      ) : indeterminate ? (
        <span
          aria-hidden
          className="pointer-events-none absolute h-[0.1rem] w-2 rounded-full bg-white"
        />
      ) : null}
    </span>
  );
}
