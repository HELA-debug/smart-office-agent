/**
 * 工作台 reducer 的「UI 状态」分支单测（与 workbench.test.ts 的运行事件分支互补）。
 *
 * 这一组覆盖的是：会话列表、上传、产物元信息、审计抽屉、审批生命周期、连接中断。
 * 它们的共同特点是「出错后界面必须仍然可用」——
 * 比如上传失败要保留条目让用户可重试，流中断要把运行标记为 error 而不是卡在 streaming。
 */
import { describe, expect, it } from 'vitest';
import { EVENT_VERSION, parseRunEvent } from '../../../shared/types/events';
import { createInitialState, workbenchReducer } from './workbench';
import type { UploadItem, WorkbenchAction, WorkbenchState } from './workbench';
import type { AuditOut } from '../../../shared/api/types';
import type { ThreadSummary, UploadResponse } from '../../../shared/types/api';
import type { ParsedRunEvent, RunEventMap, RunEventName } from '../../../shared/types/events';
import type { ArtifactItem, ApprovalItem } from '../../../shared/types/view';

const AT = '2026-10-23T10:00:00+08:00';
const RUN_ID = 'r_test_01';

function dispatch(state: WorkbenchState, action: WorkbenchAction): WorkbenchState {
  return workbenchReducer(state, action);
}

function event<T extends RunEventName>(name: T, data: RunEventMap[T]): ParsedRunEvent {
  const parsed = parseRunEvent(name, {
    ...(data as unknown as Record<string, unknown>),
    version: EVENT_VERSION,
    run_id: RUN_ID,
  });
  if (!parsed) throw new Error(`invalid event ${name}`);
  return parsed;
}

function thread(id: string, overrides: Partial<ThreadSummary> = {}): ThreadSummary {
  return {
    thread_id: id,
    title: `会话${id}`,
    created_at: '2026-10-20T09:00:00+08:00',
    updated_at: '2026-10-20T09:00:00+08:00',
    message_count: 0,
    artifact_count: 0,
    ...overrides,
  };
}

function upload(id: string, overrides: Partial<UploadItem> = {}): UploadItem {
  return {
    local_id: id,
    filename: `${id}.txt`,
    size: 100,
    status: 'uploading',
    progress: 0,
    error: null,
    ...overrides,
  };
}

function artifact(id: string, overrides: Partial<ArtifactItem> = {}): ArtifactItem {
  return {
    artifact_id: id,
    type: 'docx',
    filename: `${id}.docx`,
    size: 2048,
    download_url: `/api/v1/artifacts/${id}/download`,
    preview_url: `/api/v1/artifacts/${id}/preview`,
    created_at: AT,
    meta_status: 'idle',
    meta_error: null,
    ...overrides,
  };
}

function approval(id: string, overrides: Partial<ApprovalItem> = {}): ApprovalItem {
  return {
    approval_id: id,
    run_id: RUN_ID,
    tool: 'doc.generate_report',
    risk: 'high',
    message: '生成报告产物（需审批）',
    preview: { kind: 'report', to: 'a@example.com', subject: '周报' },
    created_at: AT,
    decision: null,
    submitting: false,
    error: null,
    ...overrides,
  };
}

/**
 * 取列表首个元素并断言非空。
 * 项目开启了 noUncheckedIndexedAccess，`items[0]` 一律是 `T | undefined`，
 * 测试里逐条写 `?.` 会让断言失效（undefined 也能通过），所以统一在这里抛错。
 */
function first<T>(items: readonly T[]): T {
  const item = items[0];
  if (item === undefined) throw new Error('列表为空，无法取首个元素');
  return item;
}

/* ------------------------------------------------------------------ */
/* 健康检查                                                            */
/* ------------------------------------------------------------------ */

describe('health/checked（健康检查）', () => {
  it('记录状态与版本，首次回填运行模式', () => {
    const next = dispatch(createInitialState(), {
      type: 'health/checked',
      status: 'ok',
      mode: 'real',
      version: '1.2.0',
      at: AT,
    });
    expect(next.health).toEqual({ status: 'ok', mode: 'real', version: '1.2.0', checked_at: AT });
    expect(next.mode).toBe('real');
  });

  it('把后端此刻在用的模型名写进 state.model（界面靠它标「当前」）', () => {
    const next = dispatch(createInitialState(), {
      type: 'health/checked',
      status: 'ok',
      mode: 'real',
      model: 'deepseek-chat',
      at: AT,
    });
    expect(next.model).toBe('deepseek-chat');

    // 后端不可达时清空：不能继续挂着上一次的名字骗人
    const down = dispatch(next, {
      type: 'health/checked',
      status: 'unreachable',
      mode: null,
      model: null,
      at: AT,
    });
    expect(down.model).toBeNull();
  });

  it('后端不可达时保留已有 mode，不覆盖', () => {
    let state = dispatch(createInitialState(), {
      type: 'health/checked',
      status: 'ok',
      mode: 'real',
      version: '1.2.0',
      at: AT,
    });
    state = dispatch(state, {
      type: 'health/checked',
      status: 'unreachable',
      mode: 'mock',
      version: undefined,
      at: '2026-10-23T11:00:00+08:00',
    });
    expect(state.health.status).toBe('unreachable');
    expect(state.mode).toBe('real');
  });
});

/* ------------------------------------------------------------------ */
/* 会话列表                                                            */
/* ------------------------------------------------------------------ */

describe('sessions 列表与排序', () => {
  it('loading 清空上一次错误，loaded 保留服务端顺序、只把置顶提到前面', () => {
    let state = dispatch(createInitialState(), {
      type: 'sessions/error',
      message: '加载失败',
    });
    expect(state.sessionsStatus).toBe('error');

    state = dispatch(state, { type: 'sessions/loading' });
    expect(state.sessionsStatus).toBe('loading');
    expect(state.sessionsError).toBeNull();

    state = dispatch(state, {
      type: 'sessions/loaded',
      sessions: [
        thread('a', { updated_at: '2026-10-01T00:00:00Z' }),
        thread('b', { updated_at: '2026-10-09T00:00:00Z', pinned: true }),
        thread('c', { updated_at: '2026-10-05T00:00:00Z' }),
      ],
      meta: { page: 1, pageSize: 20, total: 3 },
    });
    // 顺序由后端决定（手动排序优先、没排过按最近更新）：前端不再按时间重排，
    // 只负责把置顶的提到最前面，其余保持原样——否则用户拖出来的顺序会被冲掉。
    expect(state.sessions.map((session) => session.thread_id)).toEqual(['b', 'a', 'c']);
    expect(state.sessionsMeta.total).toBe(3);
    expect(state.sessionsStatus).toBe('ready');
  });

  it('reordered 按传入顺序重排，置顶仍在最前', () => {
    let state = dispatch(createInitialState(), {
      type: 'sessions/loaded',
      sessions: [thread('a'), thread('b'), thread('c'), thread('p', { pinned: true })],
    });
    state = dispatch(state, { type: 'sessions/reordered', threadIds: ['c', 'a', 'b'] });
    expect(state.sessions.map((session) => session.thread_id)).toEqual(['p', 'c', 'a', 'b']);
  });

  it('loaded 未传 meta 时保留原有分页信息', () => {
    let state = dispatch(createInitialState(), {
      type: 'sessions/loaded',
      sessions: [],
      meta: { page: 2, pageSize: 10, total: 40 },
    });
    state = dispatch(state, { type: 'sessions/loaded', sessions: [thread('a')] });
    expect(state.sessionsMeta).toEqual({ page: 2, pageSize: 10, total: 40 });
  });

  it('upsert 去重，并在命中当前会话时同步标题', () => {
    let state = dispatch(createInitialState(), {
      type: 'sessions/loaded',
      sessions: [thread('a'), thread('b')],
    });
    state = { ...state, threadId: 'a' };
    state = dispatch(state, {
      type: 'sessions/upsert',
      thread: thread('a', { title: '改名了', updated_at: '2026-12-31T00:00:00Z' }),
    });
    expect(state.sessions).toHaveLength(2);
    expect(state.threadTitle).toBe('改名了');
    expect(first(state.sessions).thread_id).toBe('a');
  });

  it('upsert 非当前会话时不改动标题', () => {
    let state = dispatch(createInitialState(), {
      type: 'sessions/loaded',
      sessions: [thread('a'), thread('b')],
    });
    state = { ...state, threadId: 'a', threadTitle: '原标题' };
    state = dispatch(state, {
      type: 'sessions/upsert',
      thread: thread('b', { title: '别人的会话' }),
    });
    expect(state.threadTitle).toBe('原标题');
  });

  it('removed 删除其它会话时不影响工作台内容', () => {
    let state = dispatch(createInitialState(), {
      type: 'sessions/loaded',
      sessions: [thread('a'), thread('b')],
    });
    state = { ...state, threadId: 'a', timeline: [], artifacts: [artifact('art1')] };
    state = dispatch(state, { type: 'sessions/removed', threadId: 'b' });
    expect(state.sessions.map((session) => session.thread_id)).toEqual(['a']);
    expect(state.artifacts).toHaveLength(1);
    expect(state.threadId).toBe('a');
  });

  it('removed 删除当前会话时重置工作台', () => {
    let state = dispatch(createInitialState(), {
      type: 'sessions/loaded',
      sessions: [thread('a'), thread('b')],
    });
    state = {
      ...state,
      threadId: 'a',
      status: 'done',
      timeline: [],
      plan: null,
      approvals: [approval('ap1')],
      artifacts: [artifact('art1')],
      uploads: [upload('u1')],
      usage: { tokens: 10, cost_cny: 0.1, elapsed_ms: 100 },
    } as unknown as WorkbenchState;
    state = dispatch(state, { type: 'sessions/removed', threadId: 'a' });
    expect(state.threadId).toBeNull();
    expect(state.threadTitle).toBe('新的会话');
    expect(state.status).toBe('idle');
    expect(state.approvals).toEqual([]);
    expect(state.artifacts).toEqual([]);
    expect(state.uploads).toEqual([]);
    expect(state.usage).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/* 会话切换                                                            */
/* ------------------------------------------------------------------ */

describe('thread 新建 / 选择 / 重命名', () => {
  it('thread/new 保留会话列表与健康状态，只重置工作区', () => {
    const base = dispatch(createInitialState(), {
      type: 'sessions/loaded',
      sessions: [thread('a')],
    });
    const withContent = dispatch(base, {
      type: 'run/begin',
      threadId: 'a',
      message: '你好',
      at: AT,
    });
    const next = dispatch(withContent, { type: 'thread/new' });
    expect(next.sessions).toHaveLength(1);
    expect(next.timeline).toEqual([]);
    expect(next.threadId).toBeNull();
    expect(next.status).toBe('idle');
  });

  it('thread/created 把新会话插到列表首位并设为当前', () => {
    let state = dispatch(createInitialState(), {
      type: 'sessions/loaded',
      sessions: [thread('a', { updated_at: '2026-10-01T00:00:00Z' })],
    });
    state = dispatch(state, {
      type: 'thread/created',
      thread: thread('new', { updated_at: '2026-10-30T00:00:00Z' }),
    });
    expect(first(state.sessions).thread_id).toBe('new');
    expect(state.threadId).toBe('new');
    expect(state.threadTitle).toBe('会话new');
    expect(state.sessionsStatus).toBe('ready');
  });

  it('thread/selected 用历史消息重建时间线，素材只进右栏、不挂回输入框', () => {
    const state = dispatch(createInitialState(), {
      type: 'thread/selected',
      threadId: 'a',
      title: '历史会话',
      history: [
        { id: 'm1', role: 'user' as const, content: '问题', created_at: AT, streaming: false },
        { id: 'm2', role: 'assistant' as const, content: '回答', created_at: AT, streaming: false },
      ],
      artifacts: [artifact('art1')],
      approvals: [approval('ap1')],
      threadUploads: [upload('u1')],
    });
    expect(state.threadId).toBe('a');
    expect(state.status).toBe('idle');
    expect(state.timeline).toHaveLength(2);
    expect(first(state.timeline).kind).toBe('message');
    expect(state.artifacts).toHaveLength(1);
    expect(state.approvals).toHaveLength(1);
    // 历史素材归右栏；输入框必须空着，否则跑完一轮后 chip 又挂回来
    expect(state.threadUploads).toHaveLength(1);
    expect(state.uploads).toEqual([]);
  });

  it('thread/selected 缺省集合时为空数组', () => {
    const state = dispatch(createInitialState(), {
      type: 'thread/selected',
      threadId: 'a',
      title: 't',
      history: [],
    });
    expect(state.artifacts).toEqual([]);
    expect(state.approvals).toEqual([]);
    expect(state.uploads).toEqual([]);
  });

  it('thread/title 与 notice 只改各自字段', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'thread/title', title: '新标题' });
    expect(state.threadTitle).toBe('新标题');
    state = dispatch(state, { type: 'notice', notice: { kind: 'error', text: '出错了' } });
    expect(state.notice).toEqual({ kind: 'error', text: '出错了' });
    state = dispatch(state, { type: 'notice', notice: null });
    expect(state.notice).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/* 运行启动与连接                                                      */
/* ------------------------------------------------------------------ */

describe('run/begin 与连接状态', () => {
  it('begin 追加用户消息、重置上一轮残留、关闭审计抽屉', () => {
    let state = dispatch(createInitialState(), {
      type: 'run/begin',
      threadId: 'th_1',
      message: '生成周报',
      at: AT,
    });
    expect(state.status).toBe('streaming');
    expect(state.connection).toBe('connecting');
    expect(state.timeline).toHaveLength(1);
    expect(state.timeline[0]).toMatchObject({ kind: 'message' });
    expect(state.lastUserMessage).toBe('生成周报');
    expect(state.audit.open).toBe(false);

    // 上一轮残留应被清理
    state = {
      ...state,
      status: 'done',
      plan: { todos: [], updated_at: AT },
      usage: { tokens: 1, cost_cny: 0, elapsed_ms: 1 },
      runError: { code: 'X', message: 'y', retryable: false },
      audit: { open: true, status: 'ready', data: null, error: null },
    } as unknown as WorkbenchState;
    state = dispatch(state, {
      type: 'run/begin',
      threadId: 'th_1',
      message: '再来一次',
      at: '2026-10-23T11:00:00+08:00',
    });
    expect(state.plan).toBeNull();
    expect(state.usage).toBeNull();
    expect(state.runError).toBeNull();
    expect(state.audit.open).toBe(false);
  });

  it('run/connection 切换连接状态', () => {
    let state = createInitialState();
    for (const connection of ['connecting', 'open', 'reconnecting', 'closed'] as const) {
      state = dispatch(state, { type: 'run/connection', connection });
      expect(state.connection).toBe(connection);
    }
  });
});

/* ------------------------------------------------------------------ */
/* 中断 / 失败 / 流关闭                                                */
/* ------------------------------------------------------------------ */

describe('运行中断与异常收尾', () => {
  function streamingWithPending(): WorkbenchState {
    let state = dispatch(createInitialState(), {
      type: 'run/begin',
      threadId: 'th_1',
      message: 'x',
      at: AT,
    });
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('run.started', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        thread_id: 'th_1',
        mode: 'mock',
        model: 'm',
      }),
      frameId: '1',
      at: AT,
    });
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('plan.updated', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        todos: [{ id: 't1', content: '读取材料', status: 'in_progress' }],
      }),
      frameId: '2',
      at: AT,
    });
    state = {
      ...state,
      approvals: [approval('ap1')],
    } as unknown as WorkbenchState;
    return state;
  }

  it('run/stopped：回到 idle、保留内容、使待审批失效、追加系统提示', () => {
    const stopped = dispatch(streamingWithPending(), { type: 'run/stopped', at: AT });
    expect(stopped.status).toBe('idle');
    expect(stopped.connection).toBe('closed');
    expect(first(stopped.plan?.todos ?? []).status).toBe('cancelled');
    expect(first(stopped.approvals).error).toBe('运行已停止，审批已失效');
    expect(
      stopped.timeline.some((item) => item.kind === 'message' && item.message.role === 'system'),
    ).toBe(true);
    // 已生成的内容保留
    expect(stopped.timeline.length).toBeGreaterThan(1);
  });

  it('run/failed：进入 error 并记录错误，不追加系统消息', () => {
    const failed = dispatch(streamingWithPending(), {
      type: 'run/failed',
      error: { code: 'MODEL_ERROR', message: '模型调用失败', retryable: true },
      at: AT,
    });
    expect(failed.status).toBe('error');
    expect(failed.runError).toEqual({
      code: 'MODEL_ERROR',
      message: '模型调用失败',
      retryable: true,
    });
    expect(first(failed.plan?.todos ?? []).status).toBe('cancelled');
    expect(first(failed.approvals).error).toBe('运行已结束，审批已失效');
  });

  it('run/streamClosed（streaming 中）：标记为可重试的中断', () => {
    const closed = dispatch(streamingWithPending(), { type: 'run/streamClosed', at: AT });
    expect(closed.status).toBe('error');
    expect(closed.runError).toEqual({
      code: 'STREAM_CLOSED',
      message: '事件流意外中断，未收到运行结束事件',
      retryable: true,
    });
  });

  it('run/streamClosed（等待审批中）：给出审批相关提示', () => {
    const base = streamingWithPending();
    const waiting = { ...base, status: 'waiting_approval' as const } as unknown as WorkbenchState;
    const closed = dispatch(waiting, { type: 'run/streamClosed', at: AT });
    expect(closed.runError?.message).toContain('审批');
    expect(first(closed.approvals).error).toBe('连接已关闭，审批已失效');
  });

  it('run/streamClosed（idle/done 中）：只关连接，不改状态', () => {
    const idle = dispatch(createInitialState(), { type: 'run/streamClosed', at: AT });
    expect(idle.status).toBe('idle');
    expect(idle.connection).toBe('closed');
    expect(idle.runError).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/* 审批生命周期                                                        */
/* ------------------------------------------------------------------ */

describe('approval 生命周期', () => {
  it('submitting → decided → error 的状态流转', () => {
    let state = {
      ...createInitialState(),
      approvals: [approval('ap1')],
    } as unknown as WorkbenchState;

    state = dispatch(state, { type: 'approval/submitting', approvalId: 'ap1' });
    expect(first(state.approvals)).toMatchObject({ submitting: true, error: null });

    state = dispatch(state, {
      type: 'approval/decided',
      approvalId: 'ap1',
      decision: 'approved',
      at: AT,
    });
    expect(first(state.approvals)).toMatchObject({
      submitting: false,
      decision: 'approved',
      decided_at: AT,
      error: null,
    });
    // 审批提交后回到 streaming，连接保持打开
    expect(state.status).toBe('streaming');
    expect(state.connection).toBe('open');

    state = dispatch(state, {
      type: 'approval/error',
      approvalId: 'ap1',
      message: '该审批已处理过',
    });
    expect(first(state.approvals)).toMatchObject({ submitting: false, error: '该审批已处理过' });
  });

  it('只影响指定 approval_id，不波及其它', () => {
    const state = {
      ...createInitialState(),
      approvals: [approval('ap1'), approval('ap2')],
    } as unknown as WorkbenchState;
    const next = dispatch(state, { type: 'approval/submitting', approvalId: 'ap1' });
    expect(first(next.approvals).submitting).toBe(true);
    expect(next.approvals[1]?.submitting).toBe(false);
  });
});

/* ------------------------------------------------------------------ */
/* 上传                                                                */
/* ------------------------------------------------------------------ */

describe('upload 生命周期', () => {
  it('start → progress → preview → success 全链路', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'upload/start', item: upload('u1') });
    expect(state.uploads).toHaveLength(1);

    state = dispatch(state, { type: 'upload/progress', localId: 'u1', progress: 42 });
    expect(first(state.uploads).progress).toBe(42);

    state = dispatch(state, { type: 'upload/preview', localId: 'u1', preview: '前 200 字…' });
    expect(first(state.uploads).preview).toBe('前 200 字…');

    const response = {
      file_id: 'f1',
      filename: 'u1.txt',
      size: 100,
      type: 'txt',
      chars: 500,
      ext: 'txt',
      parsed: true,
    } as UploadResponse;
    state = dispatch(state, { type: 'upload/success', localId: 'u1', response });
    expect(first(state.uploads)).toMatchObject({
      status: 'parsed',
      file_id: 'f1',
      // 后端未返回 artifact_id 时回退 file_id
      artifact_id: 'f1',
      chars: 500,
      ext: 'txt',
      progress: 100,
      error: null,
    });
  });

  it('success 优先使用后端返回的 artifact_id', () => {
    let state = dispatch(createInitialState(), { type: 'upload/start', item: upload('u1') });
    state = dispatch(state, {
      type: 'upload/success',
      localId: 'u1',
      response: { file_id: 'f1', artifact_id: 'art_9' } as UploadResponse,
    });
    expect(first(state.uploads).artifact_id).toBe('art_9');
  });

  it('error 保留条目以便重试，remove 才真正移除', () => {
    let state = dispatch(createInitialState(), { type: 'upload/start', item: upload('u1') });
    state = dispatch(state, { type: 'upload/error', localId: 'u1', message: '文件超过 20MB' });
    expect(state.uploads).toHaveLength(1);
    expect(first(state.uploads)).toMatchObject({ status: 'error', error: '文件超过 20MB' });

    state = dispatch(state, { type: 'upload/remove', localId: 'u1' });
    expect(state.uploads).toHaveLength(0);
  });

  it('按 local_id 精确匹配，不误伤其它上传', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'upload/start', item: upload('u1') });
    state = dispatch(state, { type: 'upload/start', item: upload('u2') });
    state = dispatch(state, { type: 'upload/progress', localId: 'u2', progress: 90 });
    expect(first(state.uploads).progress).toBe(0);
    expect(state.uploads[1]?.progress).toBe(90);
  });
});

/* ------------------------------------------------------------------ */
/* 产物元信息与审计                                                    */
/* ------------------------------------------------------------------ */

describe('artifact 元信息懒加载', () => {
  it('metaLoading → meta → metaError 三态', () => {
    let state = {
      ...createInitialState(),
      artifacts: [artifact('art1')],
    } as unknown as WorkbenchState;

    state = dispatch(state, { type: 'artifact/metaLoading', artifactId: 'art1' });
    expect(first(state.artifacts).meta_status).toBe('loading');

    state = dispatch(state, {
      type: 'artifact/meta',
      artifactId: 'art1',
      sha256: 'abc123',
      createdAt: AT,
    });
    expect(first(state.artifacts)).toMatchObject({
      meta_status: 'ready',
      meta_error: null,
      meta: { sha256: 'abc123', created_at: AT },
    });

    state = dispatch(state, {
      type: 'artifact/metaError',
      artifactId: 'art1',
      message: '元信息加载失败',
    });
    expect(first(state.artifacts)).toMatchObject({
      meta_status: 'error',
      meta_error: '元信息加载失败',
    });
  });
});

describe('audit 抽屉', () => {
  it('open / loading / loaded / error / close 状态流转', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'audit/open' });
    expect(state.audit.open).toBe(true);

    state = dispatch(state, { type: 'audit/loading' });
    expect(state.audit).toMatchObject({ open: true, status: 'loading', error: null });

    const data = { trace_id: 't', thread_id: 'a', runs: [] } as unknown as AuditOut;
    state = dispatch(state, { type: 'audit/loaded', data });
    expect(state.audit).toMatchObject({ status: 'ready', data });

    state = dispatch(state, { type: 'audit/error', message: '审计加载失败' });
    expect(state.audit).toMatchObject({ status: 'error', error: '审计加载失败' });

    state = dispatch(state, { type: 'audit/close' });
    expect(state.audit.open).toBe(false);
  });
});

/* ------------------------------------------------------------------ */
/* 兜底                                                                */
/* ------------------------------------------------------------------ */

describe('reducer 兜底与不可变性', () => {
  it('未知 action 原样返回同一个对象引用', () => {
    const state = createInitialState();
    const next = workbenchReducer(state, {
      type: 'not/a/real/action',
    } as unknown as WorkbenchAction);
    expect(next).toBe(state);
  });

  it('reducer 不修改传入的 state（不可变更新）', () => {
    const state = { ...createInitialState(), uploads: [upload('u1')] } as unknown as WorkbenchState;
    const snapshot = JSON.stringify(state);
    dispatch(state, { type: 'upload/progress', localId: 'u1', progress: 50 });
    expect(JSON.stringify(state)).toBe(snapshot);
  });
});
