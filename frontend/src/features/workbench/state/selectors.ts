/** 工作台选择器：从 state 派生视图用的少量布尔/引用查询。 */

import type { ApprovalItem, TimelineItem, WorkbenchState } from './types';

/* ------------------------------------------------------------------ */
/* 选择器                                                              */
/* ------------------------------------------------------------------ */

/** 当前阻塞输入的审批（未决议且未失效）。 */
export function selectBlockingApproval(state: WorkbenchState): ApprovalItem | null {
  return state.approvals.find((approval) => approval.decision === null && !approval.error) ?? null;
}

/** 当前是否「忙」：运行中或等审批。忙的时候发送不丢弃，而是进队列。 */
export function selectRunBusy(state: WorkbenchState): boolean {
  return state.status === 'streaming' || state.status === 'waiting_approval';
}

/** 是否正在流式运行（停止按钮可见）。 */
export function selectIsStreaming(state: WorkbenchState): boolean {
  return state.status === 'streaming';
}

export function selectHasContent(state: WorkbenchState): boolean {
  return state.timeline.length > 0;
}

/**
 * 「这一步没跑通、但后面换了个写法成了」的那些调用。
 *
 * 用户关心的是「东西做出来了没有」，不是「我们中间试错了几次」。同一件工具在
 * 本轮里后面成功过，前面那次失败就只是一次草稿——画红框、计进「×N 步失败」，
 * 等于把返工摊到他脸上。
 */
export function selectRetriedIds(items: TimelineItem[]): Set<string> {
  const okTools = new Set(
    items
      .filter((item) => item.kind === 'tool' && item.tool.ok)
      .map((item) => (item.kind === 'tool' ? item.tool.tool : '')),
  );
  const ids = new Set<string>();
  for (const item of items) {
    if (item.kind !== 'tool' || item.tool.ok || item.tool.skipped) continue;
    if (okTools.has(item.tool.tool)) ids.add(item.id);
  }
  return ids;
}
