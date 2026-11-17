/**
 * SSE 事件 → 状态迁移（`run/event` 分支）。
 *
 * 从 workbench.ts 拆出（P2-14）。每个事件只负责「把这一帧的影响写进 state」，
 * 跨事件共用的整理动作（收尾/取消/排序）留在 ./helpers，避免这里继续膨胀。
 */

import {
  cancelPlanProgress,
  cancelTimelinePlan,
  markMessagesSettled,
  settlePendingApprovals,
  settleSubagents,
  updateMessage,
  updateNote,
  updateThinking,
  upsertSubagent,
  upsertTimeline,
} from './helpers';
import type {
  ApprovalItem,
  PlanSnapshot,
  ToolCallItem,
  WorkbenchAction,
  WorkbenchState,
} from './types';

export function applyRunEvent(
  state: WorkbenchState,
  action: Extract<WorkbenchAction, { type: 'run/event' }>,
): WorkbenchState {
  const { parsed, frameId, at } = action;
  const { name, event } = parsed;

  switch (name) {
    case 'run.started':
      return {
        ...state,
        status: 'streaming',
        connection: 'open',
        runId: event.run_id,
        mode: event.mode,
        model: event.model ?? null,
        degraded: event.degraded ?? false,
        runError: null,
      };

    case 'message.delta': {
      const delta = event.delta;
      const streaming = state.status === 'waiting_approval' ? 'waiting_approval' : 'streaming';
      // 中间旁白（channel=process）收进「执行过程」，不再单独起一个带头像的气泡
      if (event.channel === 'process') {
        return {
          ...state,
          status: streaming,
          timeline: updateNote(
            state,
            event.message_id,
            (note) => ({ ...note, content: note.content + delta, streaming: true }),
            {
              id: event.message_id,
              content: delta,
              streaming: true,
              created_at: at,
            },
          ),
        };
      }
      return {
        ...state,
        status: streaming,
        timeline: updateMessage(
          state,
          event.message_id,
          (message) => ({ ...message, content: message.content + delta, streaming: true }),
          {
            id: event.message_id,
            role: 'assistant',
            content: delta,
            streaming: true,
            created_at: at,
          },
        ),
      };
    }

    case 'message.completed':
      if (event.channel === 'process') {
        return {
          ...state,
          timeline: updateNote(
            state,
            event.message_id,
            (note) => ({ ...note, content: event.content, streaming: false }),
            {
              id: event.message_id,
              content: event.content,
              streaming: false,
              created_at: at,
            },
          ),
        };
      }
      return {
        ...state,
        timeline: updateMessage(
          state,
          event.message_id,
          (message) => ({ ...message, content: event.content, streaming: false }),
          {
            id: event.message_id,
            role: 'assistant',
            content: event.content,
            streaming: false,
            created_at: at,
          },
        ),
      };

    case 'thinking.delta':
      return {
        ...state,
        status: state.status === 'waiting_approval' ? 'waiting_approval' : 'streaming',
        timeline: updateThinking(
          state,
          event.message_id,
          (thinking) => ({ ...thinking, content: thinking.content + event.delta, streaming: true }),
          {
            id: event.message_id,
            content: event.delta,
            streaming: true,
            collapsed: false,
            kind: event.kind,
            created_at: at,
          },
        ),
      };

    case 'thinking.completed':
      return {
        ...state,
        timeline: updateThinking(
          state,
          event.message_id,
          (thinking) => ({
            ...thinking,
            content: event.content,
            streaming: false,
            collapsed: true,
            kind: event.kind ?? thinking.kind,
            elapsed_ms: event.elapsed_ms,
          }),
          {
            id: event.message_id,
            content: event.content,
            streaming: false,
            collapsed: true,
            kind: event.kind,
            elapsed_ms: event.elapsed_ms,
            created_at: at,
          },
        ),
      };

    case 'plan.updated': {
      const plan: PlanSnapshot = { run_id: event.run_id, todos: event.todos, updated_at: at };
      return {
        ...state,
        plan,
        timeline: upsertTimeline(state, { kind: 'plan', id: `plan_${event.run_id}`, plan }),
      };
    }

    case 'tool.finished': {
      const tool: ToolCallItem = {
        id: frameId
          ? `tool_${event.run_id}_${frameId}`
          : `tool_${event.run_id}_${state.timeline.length}`,
        run_id: event.run_id,
        tool: event.tool,
        ok: event.ok,
        skipped: event.output?.skipped === true,
        risk: event.risk,
        summary: event.summary,
        duration_ms: event.duration_ms,
        input: event.input,
        output: event.output,
        artifact_id: event.artifact_id,
        error: event.error,
        subagent: event.subagent,
        created_at: at,
      };
      let timeline = [...state.timeline, { kind: 'tool' as const, id: tool.id, tool }];
      if (event.subagent) {
        timeline = upsertSubagent(
          { ...state, timeline },
          event.subagent,
          event.tool,
          event.summary,
          at,
        );
      }
      return { ...state, timeline };
    }

    case 'approval.required': {
      const exists = state.approvals.some((approval) => approval.approval_id === event.approval_id);
      const approval: ApprovalItem = {
        approval_id: event.approval_id,
        run_id: event.run_id,
        tool: event.tool,
        risk: event.risk,
        message: event.message,
        preview: event.preview,
        created_at: at,
        decision: null,
        submitting: false,
        error: null,
      };
      return {
        ...state,
        status: 'waiting_approval',
        approvals: exists
          ? state.approvals.map((item) =>
              item.approval_id === event.approval_id
                ? { ...approval, decision: item.decision }
                : item,
            )
          : [...state.approvals, approval],
      };
    }

    case 'artifact.ready': {
      const exists = state.artifacts.some((artifact) => artifact.artifact_id === event.artifact_id);
      if (exists) {
        return {
          ...state,
          artifacts: state.artifacts.map((artifact) =>
            artifact.artifact_id === event.artifact_id
              ? {
                  ...artifact,
                  type: event.type,
                  filename: event.filename,
                  size: event.size,
                  download_url: event.download_url,
                  preview_url: event.preview_url,
                  run_id: event.run_id,
                  sources: event.sources ?? artifact.sources,
                }
              : artifact,
          ),
        };
      }
      return {
        ...state,
        artifacts: [
          ...state.artifacts,
          {
            artifact_id: event.artifact_id,
            type: event.type,
            filename: event.filename,
            size: event.size,
            download_url: event.download_url,
            preview_url: event.preview_url,
            run_id: event.run_id,
            created_at: at,
            meta_status: 'idle',
            meta_error: null,
            meta: null,
            sources: event.sources ?? [],
          },
        ],
      };
    }

    case 'run.completed':
      return {
        ...state,
        status: 'done',
        connection: 'closed',
        degraded: event.degraded,
        runError: null,
        // 任务结束了，发给这一轮的附件完成了它的使命：从输入框收走。
        // 只收「已经传上去（parsed）」的——运行期间用户新挑的文件还是 staged，不能连坐清掉。
        uploads: state.uploads.filter((upload) => upload.status !== 'parsed'),
        // 产物卡要显示这一轮花了多少（token / 钱），只有运行结束才知道
        artifacts: state.artifacts.map((artifact) =>
          artifact.run_id === event.run_id
            ? { ...artifact, tokens: event.tokens, cost_cny: event.cost_cny }
            : artifact,
        ),
        usage: {
          run_id: event.run_id,
          status: event.status,
          tokens: event.tokens,
          cost_cny: event.cost_cny,
          elapsed_ms: event.elapsed_ms,
          artifact_ids: event.artifact_ids,
          approvals: event.approvals,
          degraded: event.degraded,
        },
        timeline: markMessagesSettled(settleSubagents(state.timeline, at)),
        approvals: state.approvals.map((approval) => {
          if (approval.decision !== null || approval.error) return approval;
          return {
            ...approval,
            error: '运行已结束，审批未提交',
            submitting: false,
          };
        }),
      };

    case 'run.failed':
      return {
        ...state,
        status: 'error',
        connection: 'closed',
        runError: event.error,
        degraded: event.degraded ?? state.degraded,
        plan: cancelPlanProgress(state.plan, at),
        timeline: markMessagesSettled(cancelTimelinePlan(settleSubagents(state.timeline, at), at)),
        approvals: settlePendingApprovals(state.approvals, '运行已结束，审批已失效'),
      };

    default:
      // 未知事件（未来追加的事件类型）必须忽略
      return state;
  }
}
