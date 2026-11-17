/** 供应商 Key 的展示与默认命名规则（设置页与「添加 Key」弹窗共用）。 */

/** 各供应商默认环境变量名；与后端读取 Key 的名字保持一致。 */
export const DEFAULT_ENV_NAME: Record<string, string> = {
  deepseek: 'DEEPSEEK_API_KEY',
  qwen: 'DASHSCOPE_API_KEY',
  glm: 'GLM_API_KEY',
  openai: 'OPENAI_API_KEY',
  workbuddy: 'WORKBUDDY_API_KEY',
};

/** WorkBuddy 之类的「自带接口」供应商：没有默认端点，得先填地址。 */
export const NEEDS_ENDPOINT: Record<string, boolean> = {
  workbuddy: true,
};

/** 掩码展示：sk-****abcd（与后端 masked_secret 口径一致）。 */
export function maskedKey(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '****';
  if (trimmed.length <= 8) return '****';
  return `${trimmed.slice(0, 3)}****${trimmed.slice(-4)}`;
}
