/** 展示层格式化工具（纯函数，便于单测）。 */

export function formatBytes(bytes: number | undefined | null): string {
  if (bytes == null || Number.isNaN(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export function formatDuration(ms: number | undefined | null): string {
  if (ms == null || Number.isNaN(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes} 分 ${seconds} 秒`;
}

export function formatCost(cny: number | undefined | null): string {
  if (cny == null || Number.isNaN(cny)) return '—';
  if (cny === 0) return '¥0.00';
  if (cny < 0.01) return `¥${cny.toFixed(4)}`;
  return `¥${cny.toFixed(2)}`;
}

/** 比率 → 百分比文案（0.0034 → "0.3%"）；用于「缓存命中率」这类小比例 */
export function formatPercent(rate: number | undefined | null, digits = 1): string {
  if (rate == null || Number.isNaN(rate)) return '—';
  return `${(rate * 100).toFixed(digits)}%`;
}

export function formatNumber(value: number | undefined | null): string {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toLocaleString('zh-CN');
}

export function formatClock(iso: string | undefined | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

export function formatDateTime(iso: string | undefined | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function timeAgo(iso: string | undefined | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return '刚刚';
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`;
  if (diff < 7 * 86400_000) return `${Math.floor(diff / 86400_000)} 天前`;
  return formatDateTime(iso);
}

/** 工具名 → 中文短名（找不到就原样展示）。 */
const TOOL_LABELS: Record<string, string> = {
  'file.list': '列出素材',
  'file.read': '读取文件',
  // 和执行过程里其他动作区分开：搜素材不是又读了一遍，是「按问题取片段」
  'file.search': '检索素材',
  'doc.analyze_material': '脚本解析素材',
  'doc.generate_report': '生成文档',
  'doc.generate': '生成文档',
  'file.delete': '删除产物',
  'code.run_python': '执行 Python',
  'web.search': '检索资料',
  'knowledge.search': '检索知识库',
};

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool;
}

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

/** 把任意值渲染成一行摘要（用于工具入参/出参折叠区）。 */
export function shortJson(value: unknown, max = 120): string {
  if (value == null) return '—';
  if (typeof value === 'string') return truncate(value, max);
  try {
    return truncate(JSON.stringify(value), max);
  } catch {
    return String(value);
  }
}
