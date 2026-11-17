/**
 * 展示层脱敏：密钥类字段打码、邮箱保留首字母。
 * 工具卡入参/出参渲染前统一走这里（后端已脱敏，这是前端兜底）。
 */

const SENSITIVE_KEY =
  /token|secret|password|passwd|api[_-]?key|authorization|cookie|session|credential/i;
const EMAIL_PATTERN = /([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/g;

export function redactValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactValue);
  if (value && typeof value === 'object') {
    const result: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      result[key] = SENSITIVE_KEY.test(key) ? '••••••' : redactValue(item);
    }
    return result;
  }
  if (typeof value === 'string') {
    return value.replace(
      EMAIL_PATTERN,
      (_match, first: string, domain: string) => `${first}***${domain}`,
    );
  }
  return value;
}
