/**
 * 特性开关与导航（计划书 6.4 / V2.1 B3）：
 * - real=true 的入口对应已实现页面；false 仍为「即将上线」占位页。
 * - 开关只控制入口是否展示，路由始终注册。
 */
export interface FeatureFlags {
  settings: boolean;
  knowledge: boolean;
  skills: boolean;
  artifacts: boolean;
  audit: boolean;
}

export const FEATURE_FLAGS: FeatureFlags = {
  settings: true,
  knowledge: true,
  skills: true,
  artifacts: true,
  audit: true,
};

export type FeatureKey = keyof FeatureFlags;

export interface NavItem {
  key: FeatureKey;
  label: string;
  /** 左栏图标坞里的短标签：字号 12px 时「产物中心」这类四字会被截断。 */
  short?: string;
  path: string;
  description: string;
  /** true = 已实现页面；false = 占位页 */
  real: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  {
    key: 'artifacts',
    label: '产物中心',
    short: '产物',
    path: '/artifacts',
    description: '跨会话产物、筛选、预览与下载',
    real: true,
  },
  {
    key: 'audit',
    label: '审计用量',
    short: '用量',
    path: '/audit',
    description: '运行审计与用量聚合',
    real: true,
  },
  {
    key: 'settings',
    label: '设置',
    path: '/settings',
    description: '模型、审批与界面设置',
    real: true,
  },
  {
    key: 'skills',
    label: '插件与技能',
    short: '技能',
    path: '/skills',
    // 气泡只补一句做什么：条目本身已经写着「插件与技能」，没必要再复述一遍
    description: '查看插件、添加技能',
    real: true,
  },
  {
    key: 'knowledge',
    label: '知识库',
    short: '知识库',
    path: '/knowledge',
    description: '沉淀常用模板与素材',
    real: false,
  },
];

export const PLACEHOLDER_NAV = NAV_ITEMS.filter((item) => !item.real);

export const PLACEHOLDER_ROUTES = PLACEHOLDER_NAV.map((item) => item.key);

export type PlaceholderRoute = (typeof PLACEHOLDER_ROUTES)[number];
