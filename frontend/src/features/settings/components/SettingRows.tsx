/**
 * 设置页的行式骨架（参照桌面端设置面板）：
 * - 分区卡片：标题 + 说明在顶栏，行与行之间用细分割线；
 * - 每一行左侧是「名称 + 一句说明」，右侧是控件（下拉 / 输入 / 开关 / 滑块）；
 * - 全区统一 8px 圆角、无重描边，视觉上比表单更安静。
 */
import type { ReactNode } from 'react';

export function SettingSection({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-card border border-line bg-surface shadow-card">
      <div className="flex items-start gap-3 border-b border-line px-5 py-3.5">
        <div className="min-w-0 flex-1">
          <h2 className="text-regular font-semibold text-ink">{title}</h2>
          {description ? (
            <p className="mt-1 text-body leading-relaxed text-muted">{description}</p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div>{children}</div>
    </section>
  );
}

export function SettingRow({
  title,
  description,
  error,
  children,
  stacked = false,
  controlWidth = 'w-[15rem]',
}: {
  title: string;
  description?: ReactNode;
  error?: string;
  /** 右侧控件；默认靠右单行，`stacked` 时换行放到说明下面（宽控件用） */
  children?: ReactNode;
  stacked?: boolean;
  /** 右侧控件的宽度类；滑块这类需要更宽的给 w-[16rem] */
  controlWidth?: string;
}) {
  return (
    <div className="border-b border-line px-5 py-3.5 last:border-b-0">
      <div
        className={
          stacked ? 'space-y-2' : 'flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-6'
        }
      >
        <div className="min-w-0 flex-1">
          <div className="text-regular font-medium text-ink">{title}</div>
          {description ? (
            <div className="mt-1 text-body leading-relaxed text-muted">{description}</div>
          ) : null}
          {error ? <div className="mt-1 text-mini text-danger">{error}</div> : null}
        </div>
        {children ? (
          <div
            className={
              stacked
                ? ''
                : `flex shrink-0 items-center justify-end gap-2 max-sm:w-full ${controlWidth}`
            }
          >
            {children}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * 带刻度说明的滑杆（参照桌面端「字体大小 · 小 / 默认 / 大」那种写法）。
 *
 * 刻度不是均匀排的：例如界面缩放 85%~110% 的「默认 90%」落在 20% 处，
 * 硬按三等分摆会在视觉上骗人（拖到中间以为回了默认）。这里按真实数值定位。
 */
export function ScaleSlider({
  value,
  min,
  max,
  step,
  onChange,
  label,
  ticks,
  valueText,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (next: number) => void;
  label: string;
  ticks: { label: string; value: number }[];
  valueText?: string;
}) {
  const span = max - min || 1;
  return (
    <div className="w-full">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-label={label}
        aria-valuetext={valueText}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-sunken accent-brand"
      />
      <div className="relative mt-1.5 h-4 select-none" aria-hidden="true">
        {ticks.map((tick) => {
          const at = Math.min(100, Math.max(0, ((tick.value - min) / span) * 100));
          const shift = at <= 0 ? '' : at >= 100 ? '-translate-x-full' : '-translate-x-1/2';
          return (
            <span
              key={tick.label}
              className={`absolute top-0 whitespace-nowrap text-caption text-faint ${shift}`}
              style={{ left: `${at}%` }}
            >
              {tick.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        checked ? 'bg-brand' : 'bg-line-strong'
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform ${
          checked ? 'translate-x-[1.15rem]' : 'translate-x-[0.2rem]'
        }`}
      />
    </button>
  );
}

/** 主题二选一：太阳 / 月亮（与顶栏开关联动）。 */
export function ThemeSwitch({
  value,
  onChange,
  lightIcon,
  darkIcon,
}: {
  value: 'light' | 'dark';
  onChange: (next: 'light' | 'dark') => void;
  lightIcon: ReactNode;
  darkIcon: ReactNode;
}) {
  const options = [
    { key: 'light' as const, label: '浅色', icon: lightIcon },
    { key: 'dark' as const, label: '深色', icon: darkIcon },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="主题"
      className="inline-flex items-center gap-0.5 rounded-full border border-line bg-surface-sunken p-0.5"
    >
      {options.map((option) => {
        const active = option.key === value;
        return (
          <button
            key={option.key}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={option.label}
            onClick={() => onChange(option.key)}
            className={`inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-mini transition-colors ${
              active ? 'bg-brand-soft text-brand-strong' : 'text-muted hover:text-ink'
            }`}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
