/** 展示层格式化工具（纯函数）单元测试：边界值 + 中文单位 + 空值兜底。 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  formatBytes,
  formatClock,
  formatCost,
  formatDateTime,
  formatDuration,
  formatNumber,
  shortJson,
  timeAgo,
  toolLabel,
  truncate,
} from './format';

describe('formatBytes', () => {
  it('按量级切换单位', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.00 MB');
  });

  it('空值与 NaN 显示破折号', () => {
    expect(formatBytes(null)).toBe('—');
    expect(formatBytes(undefined)).toBe('—');
    expect(formatBytes(Number.NaN)).toBe('—');
  });
});

describe('formatDuration', () => {
  it('毫秒 / 秒 / 分秒三种形态', () => {
    expect(formatDuration(320)).toBe('320 ms');
    expect(formatDuration(1500)).toBe('1.5 s');
    expect(formatDuration(65_000)).toBe('1 分 5 秒');
  });

  it('空值兜底', () => {
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(Number.NaN)).toBe('—');
  });
});

describe('formatCost', () => {
  it('零 / 小额 / 常规分别保留 2 或 4 位小数', () => {
    expect(formatCost(0)).toBe('¥0.00');
    expect(formatCost(0.0034)).toBe('¥0.0034');
    expect(formatCost(1.239)).toBe('¥1.24');
  });

  it('空值兜底', () => {
    expect(formatCost(null)).toBe('—');
  });
});

describe('formatNumber', () => {
  it('千分位', () => {
    expect(formatNumber(8123)).toBe('8,123');
    expect(formatNumber(0)).toBe('0');
  });

  it('空值兜底', () => {
    expect(formatNumber(undefined)).toBe('—');
  });
});

describe('时间格式化', () => {
  it('非法日期返回破折号', () => {
    expect(formatClock('not-a-date')).toBe('—');
    expect(formatDateTime('not-a-date')).toBe('—');
    expect(formatClock(null)).toBe('—');
    expect(formatDateTime(undefined)).toBe('—');
  });

  it('合法时间输出非空字符串', () => {
    const iso = new Date('2026-10-24T09:30:00+08:00').toISOString();
    expect(formatClock(iso)).not.toBe('—');
    expect(formatDateTime(iso)).not.toBe('—');
  });
});

describe('timeAgo', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-24T12:00:00+08:00'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('按时间差输出中文相对时间', () => {
    const base = new Date('2026-10-24T12:00:00+08:00').getTime();
    expect(timeAgo(new Date(base - 10_000).toISOString())).toBe('刚刚');
    expect(timeAgo(new Date(base - 5 * 60_000).toISOString())).toBe('5 分钟前');
    expect(timeAgo(new Date(base - 3 * 3600_000).toISOString())).toBe('3 小时前');
    expect(timeAgo(new Date(base - 2 * 86400_000).toISOString())).toBe('2 天前');
  });

  it('超过 7 天回退到日期时间', () => {
    const old = new Date('2026-10-01T09:00:00+08:00').toISOString();
    expect(timeAgo(old)).not.toContain('前');
  });

  it('空值与非法日期返回空串', () => {
    expect(timeAgo(null)).toBe('');
    expect(timeAgo('bad')).toBe('');
  });
});

describe('toolLabel', () => {
  it('已知工具映射为中文', () => {
    expect(toolLabel('file.delete')).toBe('删除产物');
    expect(toolLabel('doc.generate_report')).toBe('生成文档');
    // 检索和「又读了一遍」在过程里要能分开：前者是按问题取片段
    expect(toolLabel('file.search')).toBe('检索素材');
  });

  it('未知工具原样返回', () => {
    expect(toolLabel('custom.step')).toBe('custom.step');
  });
});

describe('truncate', () => {
  it('短文本原样返回', () => {
    expect(truncate('abc', 5)).toBe('abc');
  });

  it('超长文本保留 max-1 个字符并补省略号', () => {
    expect(truncate('abcdefgh', 5)).toBe('abcd…');
  });
});

describe('shortJson', () => {
  it('null 显示破折号', () => {
    expect(shortJson(null)).toBe('—');
    expect(shortJson(undefined)).toBe('—');
  });

  it('字符串直接截断', () => {
    expect(shortJson('hello', 10)).toBe('hello');
  });

  it('对象序列化为一行 JSON', () => {
    expect(shortJson({ a: 1 })).toBe('{"a":1}');
  });

  it('循环引用不抛异常', () => {
    const loop: Record<string, unknown> = {};
    loop.self = loop;
    expect(typeof shortJson(loop)).toBe('string');
  });
});
