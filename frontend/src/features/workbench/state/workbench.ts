/**
 * 工作台状态机入口（计划书 6.3 / api.md 第 4 节）。
 *
 * 状态：idle → streaming → waiting_approval → done / error
 * 规则：只有 reducer 能改状态；组件只读 state，不自行猜测运行进度。
 * 事件驱动的迁移：
 *   run.started        → streaming
 *   approval.required  → waiting_approval
 *   run.completed      → done
 *   run.failed         → error
 *   审批 POST 成功      → streaming（connection 始终保持打开）
 *
 * P2-14 拆分（行为不变）：类型与初始状态在 ./types，纯辅助函数在 ./helpers，
 * SSE 事件分支在 ./run-events，派生状态选择器在 ./selectors。
 * 本文件只保留 action 分发，并 `export *` 维持原有导入路径可用。
 */
import {
  addSystemMessage,
  cancelPlanProgress,
  cancelTimelinePlan,
  markMessagesSettled,
  settlePendingApprovals,
  settleSubagents,
  sortSessions,
} from './helpers';
import { applyRunEvent } from './run-events';
import { createInitialState } from './types';
import type { WorkbenchAction, WorkbenchState } from './types';

export * from './selectors';
export * from './types';

export function workbenchReducer(state: WorkbenchState, action: WorkbenchAction): WorkbenchState {
  switch (action.type) {
    case 'health/checked':
      return {
        ...state,
        health: {
          status: action.status,
          mode: action.mode,
          version: action.version,
          checked_at: action.at,
          engine: action.engine,
          engineEffective: action.engineEffective,
          engineReason: action.engineReason,
          modelReady: action.modelReady,
          modelHint: action.modelHint,
        },
        degraded: action.degraded ?? state.degraded,
        degradedReason: action.degradedReason ?? (action.degraded ? state.degradedReason : ''),
        mode: state.mode ?? action.mode,
        // 健康检查是唯一知道「现在跑哪个模型」的地方；以前只取了 mode，
        // model 一直是 null，于是输入框永远写着「选择模型」、面板也无从高亮
        model: action.model ?? null,
      };

    case 'sessions/loading':
      return { ...state, sessionsStatus: 'loading', sessionsError: null };

    case 'sessions/loaded':
      return {
        ...state,
        sessionsStatus: 'ready',
        sessions: sortSessions(action.sessions),
        sessionsMeta: action.meta ?? state.sessionsMeta,
        sessionsError: null,
      };

    case 'sessions/upsert': {
      const known = state.sessions.some((session) => session.thread_id === action.thread.thread_id);
      // 已有的会话只更新字段、位置不动：用户拖好的顺序不该被一条新消息顶走；
      // 新会话才插到最前面。
      const next = sortSessions(
        known
          ? state.sessions.map((session) =>
              session.thread_id === action.thread.thread_id ? action.thread : session,
            )
          : [action.thread, ...state.sessions],
      );
      return {
        ...state,
        sessions: next,
        threadTitle:
          state.threadId === action.thread.thread_id ? action.thread.title : state.threadTitle,
      };
    }

    /**
     * 拖动排序：拿传来的顺序重排当前这一页。
     * 只动顺序、不碰计数；落库失败时上层会再拉一次列表把顺序纠正回来。
     */
    case 'sessions/reordered': {
      const order = new Map(action.threadIds.map((id, index) => [id, index]));
      const next = [...state.sessions].sort((a, b) => {
        // 置顶的永远在最前，置顶组内部也认这次拖出来的顺序
        const byPin = Number(Boolean(b.pinned)) - Number(Boolean(a.pinned));
        if (byPin !== 0) return byPin;
        const ia = order.get(a.thread_id) ?? Number.MAX_SAFE_INTEGER;
        const ib = order.get(b.thread_id) ?? Number.MAX_SAFE_INTEGER;
        return ia - ib;
      });
      return { ...state, sessions: next };
    }

    case 'sessions/removed':
      return {
        ...state,
        sessions: state.sessions.filter((session) => session.thread_id !== action.threadId),
        // 侧栏「最近会话 N」要立刻减一：之前只删列表项，数字要等下一次刷新才变
        sessionsMeta: {
          ...state.sessionsMeta,
          total: Math.max(0, state.sessionsMeta.total - 1),
        },
        // 会话被删了，它的排队任务也没地方跑了
        queue: state.queue.filter((item) => item.threadId !== action.threadId),
        ...(state.threadId === action.threadId
          ? {
              threadId: null,
              threadTitle: '新的会话',
              status: 'idle' as const,
              timeline: [],
              plan: null,
              approvals: [],
              artifacts: [],
              uploads: [],
              threadUploads: [],
              subagents: [],
              usage: null,
              runError: null,
            }
          : {}),
      };

    /**
     * 批量清理：一次进来一串 ID。total 只减「真的从列表里消失的那几条」，
     * 否则跨页选中后页面已刷新过的会话会把计数越减越小。
     */
    case 'sessions/removedMany': {
      const ids = new Set(action.threadIds);
      const remaining = state.sessions.filter((session) => !ids.has(session.thread_id));
      const removedCount = state.sessions.length - remaining.length;
      const activeRemoved = state.threadId !== null && ids.has(state.threadId);
      return {
        ...state,
        sessions: remaining,
        sessionsMeta: {
          ...state.sessionsMeta,
          total: Math.max(0, state.sessionsMeta.total - removedCount),
        },
        queue: state.queue.filter((item) => !ids.has(item.threadId)),
        ...(activeRemoved
          ? {
              threadId: null,
              threadTitle: '新的会话',
              status: 'idle' as const,
              timeline: [],
              plan: null,
              approvals: [],
              artifacts: [],
              uploads: [],
              threadUploads: [],
              subagents: [],
              usage: null,
              runError: null,
            }
          : {}),
      };
    }

    case 'sessions/error':
      return { ...state, sessionsStatus: 'error', sessionsError: action.message };

    case 'thread/new':
      return {
        ...createInitialState(),
        sessions: state.sessions,
        sessionsMeta: state.sessionsMeta,
        sessionsStatus: state.sessionsStatus,
        sessionsError: state.sessionsError,
        health: state.health,
        mode: state.mode,
        notice: state.notice,
        // 排队任务是用户亲手写的，换会话不能丢：它记着自己的会话，切回去还能接着跑
        queue: state.queue,
        queuePaused: state.queuePaused,
      };

    case 'thread/created':
      return {
        ...state,
        threadId: action.thread.thread_id,
        threadTitle: action.thread.title,
        sessions: sortSessions([
          action.thread,
          ...state.sessions.filter((session) => session.thread_id !== action.thread.thread_id),
        ]),
        sessionsMeta: state.sessions.some(
          (session) => session.thread_id === action.thread.thread_id,
        )
          ? state.sessionsMeta
          : { ...state.sessionsMeta, total: state.sessionsMeta.total + 1 },
        sessionsStatus: 'ready',
      };

    case 'thread/selected': {
      const base = createInitialState();
      return {
        ...base,
        sessions: state.sessions,
        sessionsMeta: state.sessionsMeta,
        sessionsStatus: state.sessionsStatus,
        sessionsError: state.sessionsError,
        health: state.health,
        mode: state.mode,
        threadId: action.threadId,
        threadTitle: action.title,
        artifacts: action.artifacts ?? [],
        approvals: action.approvals ?? [],
        // 输入框只放「还没发出去」的文件：历史素材进 threadUploads 给右栏用，
        // 不能挂回输入框——那会让用户以为素材还没发、占着地方
        uploads: [],
        threadUploads: action.threadUploads ?? [],
        timeline: action.history.map((message) => ({
          kind: 'message' as const,
          id: message.id,
          message,
        })),
        status: 'idle',
        queue: state.queue,
        queuePaused: state.queuePaused,
      };
    }

    case 'thread/title':
      return { ...state, threadTitle: action.title };

    case 'thread/assets':
      return {
        ...state,
        artifacts: action.artifacts,
        threadUploads: action.threadUploads ?? state.threadUploads,
      };

    case 'notice':
      return { ...state, notice: action.notice };

    case 'run/begin':
      return {
        ...state,
        status: 'streaming',
        connection: 'connecting',
        threadId: action.threadId,
        timeline: [
          ...state.timeline,
          {
            kind: 'message',
            id: `user_${action.at}_${state.timeline.length}`,
            message: {
              id: `user_${action.at}_${state.timeline.length}`,
              role: 'user',
              content: action.message,
              streaming: false,
              created_at: action.at,
            },
          },
        ],
        plan: null,
        subagents: [],
        runId: null,
        runError: null,
        usage: null,
        degraded: false,
        degradedReason: '',
        audit: { ...state.audit, open: false },
        lastUserMessage: action.message,
      };

    case 'run/connection':
      return { ...state, connection: action.connection };

    case 'run/event':
      return applyRunEvent(state, action);

    case 'run/stopped':
      return {
        ...state,
        status: 'idle',
        connection: 'closed',
        plan: cancelPlanProgress(state.plan, action.at),
        timeline: addSystemMessage(
          {
            ...state,
            timeline: markMessagesSettled(
              cancelTimelinePlan(settleSubagents(state.timeline, action.at), action.at),
            ),
          },
          '已停止本次运行。已生成的内容保留。',
          action.at,
        ),
        approvals: settlePendingApprovals(state.approvals, '运行已停止，审批已失效'),
      };

    case 'run/failed':
      return {
        ...state,
        status: 'error',
        connection: 'closed',
        runError: action.error,
        plan: cancelPlanProgress(state.plan, action.at),
        timeline: markMessagesSettled(
          cancelTimelinePlan(settleSubagents(state.timeline, action.at), action.at),
        ),
        approvals: settlePendingApprovals(state.approvals, '运行已结束，审批已失效'),
      };

    case 'run/streamClosed':
      if (state.status === 'streaming') {
        return {
          ...state,
          status: 'error',
          connection: 'closed',
          runError: {
            code: 'STREAM_CLOSED',
            message: '事件流意外中断，未收到运行结束事件',
            retryable: true,
          },
          timeline: markMessagesSettled(settleSubagents(state.timeline, action.at)),
        };
      }
      if (state.status === 'waiting_approval') {
        return {
          ...state,
          status: 'error',
          connection: 'closed',
          runError: {
            code: 'STREAM_CLOSED',
            message: '审批期间事件流被关闭，无法继续运行',
            retryable: true,
          },
          approvals: settlePendingApprovals(state.approvals, '连接已关闭，审批已失效'),
        };
      }
      return { ...state, connection: 'closed' };

    case 'approval/submitting':
      return {
        ...state,
        approvals: state.approvals.map((approval) =>
          approval.approval_id === action.approvalId
            ? { ...approval, submitting: true, error: null }
            : approval,
        ),
      };

    case 'approval/decided':
      return {
        ...state,
        status: 'streaming', // 审批提交后回到 streaming，后续事件继续在本流推送
        connection: 'open',
        approvals: state.approvals.map((approval) =>
          approval.approval_id === action.approvalId
            ? {
                ...approval,
                submitting: false,
                decision: action.decision,
                decided_at: action.at,
                error: null,
              }
            : approval,
        ),
      };

    case 'approval/error':
      return {
        ...state,
        approvals: state.approvals.map((approval) =>
          approval.approval_id === action.approvalId
            ? { ...approval, submitting: false, error: action.message }
            : approval,
        ),
      };

    case 'upload/start':
      return { ...state, uploads: [...state.uploads, action.item] };

    case 'upload/begin':
      // 本地暂存（staged）→ 真正开始上传
      return {
        ...state,
        uploads: state.uploads.map((upload) =>
          upload.local_id === action.localId
            ? { ...upload, status: 'uploading', progress: 0, error: null }
            : upload,
        ),
      };

    case 'upload/progress':
      return {
        ...state,
        uploads: state.uploads.map((upload) =>
          upload.local_id === action.localId ? { ...upload, progress: action.progress } : upload,
        ),
      };

    case 'upload/preview':
      return {
        ...state,
        uploads: state.uploads.map((upload) =>
          upload.local_id === action.localId ? { ...upload, preview: action.preview } : upload,
        ),
      };

    case 'upload/success':
      return {
        ...state,
        uploads: state.uploads.map((upload) =>
          upload.local_id === action.localId
            ? {
                ...upload,
                // 图片 / 录音 / 视频上传完只是「收到了」，文字还在识别：卡片上要
                // 继续显示识别中，等轮询把结果带回来；标成 parsed 会让人以为能发了
                status: 'parsed',
                file_id: action.response.file_id,
                artifact_id: action.response.artifact_id ?? action.response.file_id,
                chars: action.response.chars,
                ext: action.response.ext,
                media_kind: action.response.media?.kind ?? upload.media_kind,
                media_status: action.response.media?.status ?? upload.media_status,
                media_error: action.response.media?.error,
                media_meta: action.response.media?.meta,
                note: action.response.note ?? null,
                progress: 100,
                error: null,
              }
            : upload,
        ),
      };

    case 'upload/sync': {
      // 以服务端为准合并：识别完成的补字数与状态，失败带原因。
      // 只更新「这一份文件」的字段，别把上传中/本地的 progress 覆盖掉。
      const byId = new Map(action.files.map((file) => [file.artifact_id ?? file.file_id, file]));
      return {
        ...state,
        uploads: state.uploads.map((upload) => {
          const remote = byId.get(upload.artifact_id ?? upload.file_id ?? '');
          if (!remote) return upload;
          const media = remote.media;
          return {
            ...upload,
            chars: remote.chars ?? upload.chars,
            preview: remote.text_preview || upload.preview,
            media_kind: media?.kind ?? upload.media_kind,
            media_status: media?.status ?? (remote.parsed ? 'ready' : upload.media_status),
            media_error: media?.error,
            media_meta: media?.meta,
            note: remote.note ?? upload.note,
          };
        }),
      };
    }

    case 'upload/retry':
      return {
        ...state,
        uploads: state.uploads.map((upload) =>
          upload.local_id === action.localId
            ? { ...upload, media_status: 'processing', media_error: undefined, error: null }
            : upload,
        ),
      };

    case 'upload/error':
      return {
        ...state,
        uploads: state.uploads.map((upload) =>
          upload.local_id === action.localId
            ? { ...upload, status: 'error', error: action.message }
            : upload,
        ),
      };

    case 'upload/remove':
      return {
        ...state,
        uploads: state.uploads.filter((upload) => upload.local_id !== action.localId),
      };

    case 'queue/add': {
      // 素材跟着这条消息走：从输入区摘掉，下一条消息不会再误带上去
      const moved = new Set(action.item.uploads.map((upload) => upload.local_id));
      return {
        ...state,
        queue: [...state.queue, action.item],
        // 用户又写了一条：说明他想让它跑，顺手解除「停止」造成的暂停
        queuePaused: false,
        uploads: state.uploads.filter((upload) => !moved.has(upload.local_id)),
      };
    }

    case 'queue/remove':
      return { ...state, queue: state.queue.filter((item) => item.id !== action.id) };

    case 'queue/promote': {
      // 挪到最前面：出队按「本会话最早的一条」取，排第一就等于「下一个跑它」。
      // 顺手解除暂停——用户点了「优先执行」显然是想让活儿跑起来。
      const item = state.queue.find((entry) => entry.id === action.id);
      if (!item) return state;
      return {
        ...state,
        queue: [item, ...state.queue.filter((entry) => entry.id !== action.id)],
        queuePaused: false,
      };
    }

    case 'queue/returnUploads': {
      const existing = new Set(state.uploads.map((upload) => upload.local_id));
      const back = action.uploads.filter((upload) => !existing.has(upload.local_id));
      // 接在后面：多次编辑同一条任务时素材顺序不会来回颠倒
      return { ...state, uploads: [...state.uploads, ...back] };
    }

    case 'queue/pause':
      return { ...state, queuePaused: true };

    case 'queue/resume':
      return { ...state, queuePaused: false };

    case 'artifact/metaLoading':
      return {
        ...state,
        artifacts: state.artifacts.map((artifact) =>
          artifact.artifact_id === action.artifactId
            ? { ...artifact, meta_status: 'loading' }
            : artifact,
        ),
      };

    case 'artifact/meta':
      return {
        ...state,
        artifacts: state.artifacts.map((artifact) =>
          artifact.artifact_id === action.artifactId
            ? {
                ...artifact,
                meta_status: 'ready',
                meta_error: null,
                meta: { sha256: action.sha256, created_at: action.createdAt },
              }
            : artifact,
        ),
      };

    case 'artifact/metaError':
      return {
        ...state,
        artifacts: state.artifacts.map((artifact) =>
          artifact.artifact_id === action.artifactId
            ? { ...artifact, meta_status: 'error', meta_error: action.message }
            : artifact,
        ),
      };

    case 'audit/open':
      return { ...state, audit: { ...state.audit, open: true } };

    case 'audit/loading':
      return { ...state, audit: { ...state.audit, open: true, status: 'loading', error: null } };

    case 'audit/loaded':
      return { ...state, audit: { open: true, status: 'ready', data: action.data, error: null } };

    case 'audit/error':
      return { ...state, audit: { ...state.audit, status: 'error', error: action.message } };

    case 'audit/close':
      return { ...state, audit: { ...state.audit, open: false } };

    default:
      return state;
  }
}
