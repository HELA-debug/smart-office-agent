/** 模型供应商开放平台入口（充值 / 用量查询均跳转官方，本应用不沉淀支付）。 */
export interface ProviderConsole {
  /** 供应商可读名称 */
  label: string;
  /** 充值 / 账单页 */
  topUp: string;
  /** 用量信息页 */
  usage: string;
  /** API Key 管理页 */
  keys: string;
}

/**
 * 各供应商的展示名。
 *
 * provider 标识（`deepseek` / `qwen`…）是写进配置、接口与数据库的键，永远不改；
 * 这里只负责「界面上怎么称呼它」。WorkBuddy 的接口地址与 Key 都由用户自带，
 * 所以它不在下面那个「开放平台跳转表」里，也不该出现在「去充值」菜单中。
 */
export const PROVIDER_LABELS: Record<string, string> = {
  mock: '演示',
  deepseek: 'deepseek harness',
  // 其余三家保留用户认得出的产品名：把 provider 标识直接摆在界面上（qwen / glm）
  // 等于让用户自己翻译，配置里的键不动、显示名照旧
  qwen: '通义千问',
  glm: '智谱 GLM',
  openai: 'OpenAI',
  workbuddy: 'WorkBuddy',
};

/** 供应商的界面显示名；未登记的（用户自己登记的）原样返回标识。 */
export function providerLabel(provider: string | null | undefined): string {
  if (!provider) return '—';
  return PROVIDER_LABELS[provider] ?? provider;
}

export const PROVIDER_CONSOLES: Record<string, ProviderConsole> = {
  deepseek: {
    label: 'deepseek harness',
    topUp: 'https://platform.deepseek.com/top_up',
    usage: 'https://platform.deepseek.com/usage',
    keys: 'https://platform.deepseek.com/api_keys',
  },
  qwen: {
    label: '通义千问',
    topUp: 'https://bailian.console.aliyun.com/',
    usage: 'https://bailian.console.aliyun.com/',
    keys: 'https://bailian.console.aliyun.com/?tab=app#/api-key',
  },
  glm: {
    label: '智谱 GLM',
    topUp: 'https://open.bigmodel.cn/',
    usage: 'https://open.bigmodel.cn/',
    keys: 'https://open.bigmodel.cn/apiconsole',
  },
  openai: {
    label: 'OpenAI',
    topUp: 'https://platform.openai.com/settings/organization/billing/overview',
    usage: 'https://platform.openai.com/usage',
    keys: 'https://platform.openai.com/api-keys',
  },
};

/** 默认（mock / 未知供应商）跳转 DeepSeek 开放平台。 */
export const DEFAULT_PROVIDER = 'deepseek';

/** 是否带官方开放平台入口：WorkBuddy 这类「自带地址」的供应商没有可跳的页面。 */
export function hasProviderConsole(provider: string | null | undefined): boolean {
  return Boolean(provider && PROVIDER_CONSOLES[provider]);
}

/** 兜底入口：即使 DEFAULT_PROVIDER 键被误删也能返回可用对象（避免运行期 undefined）。 */
const FALLBACK_CONSOLE: ProviderConsole = {
  label: 'deepseek harness',
  topUp: 'https://platform.deepseek.com/top_up',
  usage: 'https://platform.deepseek.com/usage',
  keys: 'https://platform.deepseek.com/api_keys',
};

export function providerConsole(provider: string | null | undefined): ProviderConsole {
  if (provider && PROVIDER_CONSOLES[provider]) return PROVIDER_CONSOLES[provider];
  return PROVIDER_CONSOLES[DEFAULT_PROVIDER] ?? FALLBACK_CONSOLE;
}
