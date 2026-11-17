/**
 * 审批策略（approval mode）：把「这个 Agent 能自己干到什么程度」交给用户选。
 *
 * 三种档位对应三种信任程度，和输入框里选的档位一起随本轮请求发出去：
 * 卡片这一层已经删掉了，档位现在调的是**门控的放行线**：拿不准的时候，是宁可
 * 先不做，还是照着你的意思直接做。
 * - always_ask 谨慎：把握不到 0.85 就不动手，模棱两可时会先问一句；
 * - risky 标准（默认）：说出口就算数，「你让我改」就改；
 * - all_allow 放手：只保留「先别 / 算了」这两道否决，其余都按你的意思做。
 *
 * 存 localStorage：用户选过一次，下个会话沿用，不用每次重选。
 */

export const APPROVAL_MODES = ['always_ask', 'risky', 'all_allow'] as const;

export type ApprovalMode = (typeof APPROVAL_MODES)[number];

export const DEFAULT_APPROVAL_MODE: ApprovalMode = 'risky';

export const APPROVAL_MODE_LABELS: Record<ApprovalMode, string> = {
  always_ask: '谨慎',
  risky: '标准',
  all_allow: '放手',
};

export const APPROVAL_MODE_HINTS: Record<ApprovalMode, string> = {
  always_ask: '拿不准就先不做，等你把话说死',
  risky: '你说清楚了就做，删东西才拦一下',
  all_allow: '按你的意思来，尽量不拦',
};

export const APPROVAL_MODE_STORAGE_KEY = 'oa.approval-mode';

export function isApprovalMode(value: unknown): value is ApprovalMode {
  return typeof value === 'string' && (APPROVAL_MODES as readonly string[]).includes(value);
}

/** 读本地偏好：读不到或值非法都回退默认档（宁可多问一句）。 */
export function readApprovalMode(): ApprovalMode {
  if (typeof window === 'undefined') return DEFAULT_APPROVAL_MODE;
  try {
    const stored = window.localStorage.getItem(APPROVAL_MODE_STORAGE_KEY);
    return isApprovalMode(stored) ? stored : DEFAULT_APPROVAL_MODE;
  } catch {
    return DEFAULT_APPROVAL_MODE;
  }
}

export function writeApprovalMode(mode: ApprovalMode): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(APPROVAL_MODE_STORAGE_KEY, mode);
  } catch {
    // 隐私模式下 localStorage 可能不可写：偏好丢了不影响功能
  }
}
