/**
 * 工作台 reducer 的纯辅助函数：timeline 增改、审批/子代理收尾、会话排序。
 *
 * 从 workbench.ts 拆出（P2-14），行为不变；只做「给定旧状态 → 返回新数组/新对象」。
 */

import type {
  ApprovalItem,
  ChatMessage,
  NoteItem,
  PlanSnapshot,
  ThinkingItem,
  TimelineItem,
  WorkbenchState,
} from './types';
import type { ThreadSummary } from '../../../shared/types/api';
import type { SubagentInfo } from '../../../shared/types/events';

export function upsertTimeline(state: WorkbenchState, item: TimelineItem): TimelineItem[] {
  const index = state.timeline.findIndex((existing) => existing.id === item.id);
  if (index === -1) return [...state.timeline, item];
  const next = state.timeline.slice();
  next[index] = item;
  return next;
}

export function updateMessage(
  state: WorkbenchState,
  messageId: string,
  update: (message: ChatMessage) => ChatMessage,
  fallback: ChatMessage,
): TimelineItem[] {
  const index = state.timeline.findIndex(
    (item) => item.kind === 'message' && item.id === messageId,
  );
  if (index === -1) {
    return [...state.timeline, { kind: 'message', id: messageId, message: fallback }];
  }
  const current = state.timeline[index];
  if (!current || current.kind !== 'message') return state.timeline;
  const next = state.timeline.slice();
  next[index] = { kind: 'message', id: messageId, message: update(current.message) };
  return next;
}

/**
 * 旁白（channel=process）的增量更新：跟消息一样按 message_id 定位，
 * 只是落在 `note` 条目上——它属于「执行过程」，不属于对话气泡。
 */
export function updateNote(
  state: WorkbenchState,
  noteId: string,
  update: (note: NoteItem) => NoteItem,
  fallback: NoteItem,
): TimelineItem[] {
  const index = state.timeline.findIndex((item) => item.kind === 'note' && item.id === noteId);
  if (index === -1) {
    return [...state.timeline, { kind: 'note', id: noteId, note: fallback }];
  }
  const current = state.timeline[index];
  if (!current || current.kind !== 'note') return state.timeline;
  const next = state.timeline.slice();
  next[index] = { kind: 'note', id: noteId, note: update(current.note) };
  return next;
}

export function markMessagesSettled(timeline: TimelineItem[]): TimelineItem[] {
  return timeline.map((item) => {
    if (item.kind === 'message' && item.message.streaming) {
      return { ...item, message: { ...item.message, streaming: false } };
    }
    if (item.kind === 'note' && item.note.streaming) {
      return { ...item, note: { ...item.note, streaming: false } };
    }
    // 思考流收尾：停止流式态并自动折叠
    if (item.kind === 'thinking' && item.thinking.streaming) {
      return {
        ...item,
        thinking: { ...item.thinking, streaming: false, collapsed: true },
      };
    }
    return item;
  });
}

export function updateThinking(
  state: WorkbenchState,
  thinkingId: string,
  update: (thinking: ThinkingItem) => ThinkingItem,
  fallback: ThinkingItem,
): TimelineItem[] {
  const index = state.timeline.findIndex(
    (item) => item.kind === 'thinking' && item.id === thinkingId,
  );
  if (index === -1) {
    return [...state.timeline, { kind: 'thinking', id: thinkingId, thinking: fallback }];
  }
  const current = state.timeline[index];
  if (!current || current.kind !== 'thinking') return state.timeline;
  const next = state.timeline.slice();
  next[index] = { kind: 'thinking', id: thinkingId, thinking: update(current.thinking) };
  return next;
}

export function upsertSubagent(
  state: WorkbenchState,
  info: SubagentInfo,
  tool: string,
  summary: string,
  at: string,
): TimelineItem[] {
  const id = `subagent_${info.id}`;
  const existing = state.timeline.find(
    (item): item is Extract<TimelineItem, { kind: 'subagent' }> =>
      item.kind === 'subagent' && item.id === id,
  );
  const status = info.status ?? 'running';
  const item: TimelineItem = {
    kind: 'subagent',
    id,
    subagent: {
      id: info.id,
      name: info.name,
      role: info.role,
      status,
      summary,
      tools: existing ? Array.from(new Set([...existing.subagent.tools, tool])) : [tool],
      updated_at: at,
    },
  };
  return upsertTimeline(state, item);
}

export function settleSubagents(timeline: TimelineItem[], at: string): TimelineItem[] {
  return timeline.map((item) =>
    item.kind === 'subagent' && item.subagent.status === 'running'
      ? { ...item, subagent: { ...item.subagent, status: 'done', updated_at: at } }
      : item,
  );
}

export function settlePendingApprovals(approvals: ApprovalItem[], reason: string): ApprovalItem[] {
  return approvals.map((approval) =>
    approval.decision === null && !approval.error
      ? { ...approval, error: reason, submitting: false }
      : approval,
  );
}

/** 停止/失败时把「进行中」的 todo 标为已取消，避免界面停在运行中的假象。 */
export function cancelPlanProgress(plan: PlanSnapshot | null, at: string): PlanSnapshot | null {
  if (!plan) return null;
  return {
    ...plan,
    updated_at: at,
    todos: plan.todos.map((todo) =>
      todo.status === 'in_progress' ? { ...todo, status: 'cancelled' as const } : todo,
    ),
  };
}

export function cancelTimelinePlan(timeline: TimelineItem[], at: string): TimelineItem[] {
  return timeline.map((item) =>
    item.kind === 'plan' ? { ...item, plan: cancelPlanProgress(item.plan, at) ?? item.plan } : item,
  );
}

export function addSystemMessage(state: WorkbenchState, text: string, at: string): TimelineItem[] {
  const id = `sys_${at}_${state.timeline.length}`;
  return [
    ...state.timeline,
    {
      kind: 'message',
      id,
      message: { id, role: 'system', content: text, streaming: false, created_at: at },
    },
  ];
}

/**
 * 会话排序：只保证「置顶的在前面」，其余保持传入顺序。
 *
 * 顺序本身由后端决定（threads.sort_index 优先、没排过的按 updated_at），
 * 前端再按时间排一遍会把用户拖出来的顺序冲掉——刚拖完、一刷新又回去了。
 * Array.prototype.sort 是稳定排序，所以同组内的相对顺序原样保留。
 */
export function sortSessions(sessions: ThreadSummary[]): ThreadSummary[] {
  return [...sessions].sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)));
}
