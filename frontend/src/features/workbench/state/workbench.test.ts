import { describe, expect, it } from 'vitest';
import { EVENT_VERSION } from '../../../shared/types/events';
import { parseRunEvent } from '../../../shared/types/events';
import {
  createInitialState,
  selectBlockingApproval,
  selectRunBusy,
  workbenchReducer,
} from './workbench';
import type { WorkbenchAction, WorkbenchState } from './workbench';
import type { ParsedRunEvent, RunEventMap, RunEventName } from '../../../shared/types/events';

const AT = '2026-10-23T10:00:00+08:00';
const RUN_ID = 'r_test_01';

function event<T extends RunEventName>(name: T, data: RunEventMap[T]): ParsedRunEvent {
  const parsed = parseRunEvent(name, {
    ...(data as unknown as Record<string, unknown>),
    version: EVENT_VERSION,
    run_id: RUN_ID,
  });
  if (!parsed) throw new Error(`invalid event ${name}`);
  return parsed;
}

function dispatch(state: WorkbenchState, action: WorkbenchAction): WorkbenchState {
  return workbenchReducer(state, action);
}

function startStreaming(): WorkbenchState {
  let state = createInitialState();
  state = dispatch(state, { type: 'run/begin', threadId: 'th_1', message: '生成周报', at: AT });
  state = dispatch(state, {
    type: 'run/event',
    parsed: event('run.started', {
      version: EVENT_VERSION,
      run_id: RUN_ID,
      thread_id: 'th_1',
      mode: 'mock',
      model: 'mock-scripted',
    }),
    frameId: '1',
    at: AT,
  });
  return state;
}

describe('workbench reducer 状态机', () => {
  it('初始为 idle：输入可用、没有待审批', () => {
    const state = createInitialState();
    expect(state.status).toBe('idle');
    expect(selectRunBusy(state)).toBe(false);
    expect(selectBlockingApproval(state)).toBeNull();
    expect(state.timeline).toHaveLength(0);
  });

  it('run.started 进入 streaming，message.delta 增量追加并在 completed 固化', () => {
    let state = startStreaming();
    expect(state.status).toBe('streaming');
    expect(selectRunBusy(state)).toBe(true);

    state = dispatch(state, {
      type: 'run/event',
      parsed: event('message.delta', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        message_id: 'm_1',
        delta: '我先读取',
        index: 0,
      }),
      frameId: '2',
      at: AT,
    });
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('message.delta', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        message_id: 'm_1',
        delta: '素材。',
        index: 1,
      }),
      frameId: '3',
      at: AT,
    });

    const streamingMessage = state.timeline.find((item) => item.id === 'm_1');
    expect(streamingMessage?.kind).toBe('message');
    if (streamingMessage?.kind !== 'message') throw new Error('message missing');
    expect(streamingMessage.message.content).toBe('我先读取素材。');
    expect(streamingMessage.message.streaming).toBe(true);

    state = dispatch(state, {
      type: 'run/event',
      parsed: event('message.completed', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        message_id: 'm_1',
        content: '我先读取素材。',
      }),
      frameId: '4',
      at: AT,
    });
    const completed = state.timeline.find((item) => item.id === 'm_1');
    if (completed?.kind !== 'message') throw new Error('message missing');
    expect(completed.message.streaming).toBe(false);
  });

  it('thinking.delta 追加思考流，completed 后折叠', () => {
    let state = startStreaming();

    state = dispatch(state, {
      type: 'run/event',
      parsed: event('thinking.delta', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        message_id: 'm_think',
        delta: '我先理解任务',
        index: 0,
      }),
      frameId: '2',
      at: AT,
    });
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('thinking.delta', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        message_id: 'm_think',
        delta: '目标与约束。',
        index: 1,
      }),
      frameId: '3',
      at: AT,
    });

    const streaming = state.timeline.find((item) => item.id === 'm_think');
    expect(streaming?.kind).toBe('thinking');
    if (streaming?.kind !== 'thinking') throw new Error('thinking missing');
    expect(streaming.thinking.content).toBe('我先理解任务目标与约束。');
    expect(streaming.thinking.streaming).toBe(true);
    expect(streaming.thinking.collapsed).toBe(false);

    state = dispatch(state, {
      type: 'run/event',
      parsed: event('thinking.completed', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        message_id: 'm_think',
        content: '我先理解任务目标与约束。',
      }),
      frameId: '4',
      at: AT,
    });
    const done = state.timeline.find((item) => item.id === 'm_think');
    if (done?.kind !== 'thinking') throw new Error('thinking missing');
    expect(done.thinking.streaming).toBe(false);
    expect(done.thinking.collapsed).toBe(true);
  });

  it('plan.updated 整体替换 todos，tool.finished 追加工具卡与子智能体', () => {
    let state = startStreaming();
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('plan.updated', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        todos: [
          { id: 't1', content: '读取材料', status: 'in_progress' },
          { id: 't2', content: '生成文档', status: 'pending' },
        ],
      }),
      frameId: '2',
      at: AT,
    });
    expect(state.plan?.todos).toHaveLength(2);

    state = dispatch(state, {
      type: 'run/event',
      parsed: event('tool.finished', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        tool: 'file.read',
        ok: true,
        risk: 'low',
        summary: '已读取 2 个文件',
        duration_ms: 120,
        input: { files: ['a.txt'] },
        output: { chars: 1240 },
        artifact_id: null,
        subagent: { id: 'doc_agent', name: '文档智能体', role: '成文', status: 'running' },
      }),
      frameId: '3',
      at: AT,
    });
    expect(state.timeline.filter((item) => item.kind === 'tool')).toHaveLength(1);
    expect(state.timeline.filter((item) => item.kind === 'subagent')).toHaveLength(1);
  });

  it('approval.required 阻塞输入，审批通过后回到 streaming', () => {
    let state = startStreaming();
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('approval.required', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        approval_id: 'a_1',
        tool: 'doc.generate_report',
        risk: 'high',
        message: '即将生成报告文件，请确认',
        preview: { to: 'me@example.com', impact: '写入产物目录' },
      }),
      frameId: '7',
      at: AT,
    });

    expect(state.status).toBe('waiting_approval');
    expect(selectBlockingApproval(state)?.approval_id).toBe('a_1');
    expect(selectRunBusy(state)).toBe(true);

    state = dispatch(state, {
      type: 'approval/decided',
      approvalId: 'a_1',
      decision: 'approved',
      at: AT,
    });
    expect(state.status).toBe('streaming');
    expect(selectBlockingApproval(state)).toBeNull();
  });

  it('run.completed 进入 done 并记录用量，消息结束打字态', () => {
    let state = startStreaming();
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('run.completed', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        status: 'completed',
        tokens: 8123,
        cost_cny: 0.06,
        elapsed_ms: 41700,
        artifact_ids: ['art_1'],
        approvals: [{ approval_id: 'a_1', tool: 'doc.generate_report', decision: 'approved' }],
        degraded: false,
      }),
      frameId: '9',
      at: AT,
    });

    expect(state.status).toBe('done');
    expect(state.usage?.tokens).toBe(8123);
    expect(state.usage?.status).toBe('completed');
    expect(selectRunBusy(state)).toBe(false);
  });

  it('run.completed 且出了产物：附件自动清掉，消耗写到产物卡上', () => {
    let state = startStreaming();
    state = dispatch(state, {
      type: 'upload/start',
      item: {
        local_id: 'u1',
        filename: 'cet4成绩.pdf',
        size: 1024,
        status: 'parsed',
        error: null,
      },
    });
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('artifact.ready', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        artifact_id: 'art_1',
        type: 'pdf',
        filename: '周报.pdf',
        size: 2048,
        download_url: '/api/v1/artifacts/art_1/download',
        preview_url: '/api/v1/artifacts/art_1/preview',
      }),
      frameId: '2',
      at: AT,
    });

    state = dispatch(state, {
      type: 'run/event',
      parsed: event('run.completed', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        status: 'completed',
        tokens: 8123,
        cost_cny: 0.06,
        elapsed_ms: 41700,
        artifact_ids: ['art_1'],
        approvals: [],
        degraded: false,
      }),
      frameId: '3',
      at: AT,
    });

    // 附件完成了它的使命，不再挂在输入框上
    expect(state.uploads).toHaveLength(0);
    expect(state.artifacts[0]?.tokens).toBe(8123);
    expect(state.artifacts[0]?.cost_cny).toBe(0.06);
  });

  it('run.completed 只收走已发出的附件，运行期间新挑的文件留着', () => {
    let state = startStreaming();
    // 这一轮已经发出去的（parsed）
    state = dispatch(state, {
      type: 'upload/start',
      item: { local_id: 'u1', filename: '已发出.docx', size: 1024, status: 'parsed', error: null },
    });
    // 运行中用户又挑了一个，还没发（staged）
    state = dispatch(state, {
      type: 'upload/start',
      item: { local_id: 'u2', filename: '下一轮.pdf', size: 2048, status: 'staged', error: null },
    });

    state = dispatch(state, {
      type: 'run/event',
      parsed: event('run.completed', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        status: 'completed',
        tokens: 100,
        cost_cny: 0.001,
        elapsed_ms: 1000,
        artifact_ids: [],
        approvals: [],
        degraded: false,
      }),
      frameId: '2',
      at: AT,
    });

    expect(state.uploads.map((item) => item.local_id)).toEqual(['u2']);
  });

  it('run.failed 进入 error，并把进行中的 todo 与待审批标记失效', () => {
    let state = startStreaming();
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
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('approval.required', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        approval_id: 'a_1',
        tool: 'doc.generate_report',
        risk: 'high',
        message: '请确认',
        preview: {},
      }),
      frameId: '3',
      at: AT,
    });
    state = dispatch(state, {
      type: 'run/event',
      parsed: event('run.failed', {
        version: EVENT_VERSION,
        run_id: RUN_ID,
        error: { code: 'APPROVAL_TIMEOUT', message: '审批超时', retryable: true },
        degraded: true,
      }),
      frameId: '4',
      at: AT,
    });

    expect(state.status).toBe('error');
    expect(state.runError?.code).toBe('APPROVAL_TIMEOUT');
    expect(state.degraded).toBe(true);
    expect(state.plan?.todos[0]?.status).toBe('cancelled');
    expect(selectBlockingApproval(state)).toBeNull();
  });

  it('停止运行回到 idle 并保留已生成内容', () => {
    let state = startStreaming();
    state = dispatch(state, { type: 'run/stopped', at: AT });
    expect(state.status).toBe('idle');
    expect(state.connection).toBe('closed');
    const systemNote = state.timeline.find(
      (item) => item.kind === 'message' && item.message.role === 'system',
    );
    expect(systemNote).toBeDefined();
  });

  it('未知事件在解析层被忽略', () => {
    expect(parseRunEvent('subagent.magic', { version: 1, run_id: RUN_ID })).toBeNull();
    expect(parseRunEvent('run.started', { version: 2, run_id: RUN_ID })).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/* 素材识别状态（图片 OCR / 录音转写）                                   */
/* ------------------------------------------------------------------ */

describe('上传素材的识别状态', () => {
  /** 上传完一张要识别的图片：接口只回「识别中」，文字还没出来。 */
  function recognizingImage(): WorkbenchState {
    let state = createInitialState();
    state = dispatch(state, {
      type: 'upload/start',
      item: { local_id: 'u1', filename: '周会截图.png', size: 2048, status: 'staged', error: null },
    });
    return dispatch(state, {
      type: 'upload/success',
      localId: 'u1',
      response: {
        file_id: 'f9',
        artifact_id: 'a9',
        filename: '周会截图.png',
        size: 2048,
        parsed: false,
        status: 'processing',
        media: { kind: 'image', label: '图片', status: 'processing' },
      },
    });
  }

  it('上传成功但还在识别：parsed 为 false 不代表失败，卡片要显示「识别中」', () => {
    const state = recognizingImage();
    const upload = state.uploads[0];
    expect(upload?.media_kind).toBe('image');
    expect(upload?.media_status).toBe('processing');
    // 关键回归：以前 parsed=false 一律当 error，图片会被标红成「解析失败」
    expect(upload?.status).toBe('parsed');
    expect(upload?.error).toBeNull();
  });

  it('同步识别结果：补上字数与预览，状态转 ready', () => {
    let state = recognizingImage();
    state = dispatch(state, {
      type: 'upload/sync',
      files: [
        {
          file_id: 'f9',
          artifact_id: 'a9',
          filename: '周会截图.png',
          size: 2048,
          chars: 58,
          parsed: true,
          status: 'ready',
          text_preview: '会议纪要：本周完成 3 项',
          media: { kind: 'image', label: '图片', status: 'ready', meta: { lines: 4 } },
        },
      ],
    });
    const upload = state.uploads[0];
    expect(upload?.media_status).toBe('ready');
    expect(upload?.chars).toBe(58);
    expect(upload?.preview).toContain('本周完成 3 项');
    expect(upload?.media_meta).toEqual({ lines: 4 });
    expect(upload?.media_error).toBeUndefined();
  });

  it('同步识别失败：带原因，不吞掉（用户才知道能不能重试）', () => {
    let state = recognizingImage();
    state = dispatch(state, {
      type: 'upload/sync',
      files: [
        {
          file_id: 'f9',
          artifact_id: 'a9',
          filename: '周会截图.png',
          size: 2048,
          parsed: false,
          status: 'failed',
          media: {
            kind: 'image',
            label: '图片',
            status: 'failed',
            error: '这张图里没有识别到文字',
            retryable: false,
          },
        },
      ],
    });
    expect(state.uploads[0]?.media_status).toBe('failed');
    expect(state.uploads[0]?.media_error).toBe('这张图里没有识别到文字');
  });

  it('同步只认自己的文件：别的会话/别的文件的记录不影响本地卡片', () => {
    let state = recognizingImage();
    state = dispatch(state, {
      type: 'upload/sync',
      files: [
        {
          file_id: 'other',
          artifact_id: 'other',
          filename: '别人的.pdf',
          size: 10,
          parsed: true,
          status: 'ready',
          media: null,
        },
      ],
    });
    expect(state.uploads[0]?.media_status).toBe('processing');
    expect(state.uploads[0]?.filename).toBe('周会截图.png');
  });

  it('点重试：卡片先回到识别中并清掉上次的错误', () => {
    let state = recognizingImage();
    state = dispatch(state, {
      type: 'upload/sync',
      files: [
        {
          file_id: 'f9',
          artifact_id: 'a9',
          filename: '周会截图.png',
          size: 2048,
          parsed: false,
          status: 'failed',
          media: { kind: 'image', label: '图片', status: 'failed', error: '模型没下载下来' },
        },
      ],
    });
    state = dispatch(state, { type: 'upload/retry', localId: 'u1' });
    expect(state.uploads[0]?.media_status).toBe('processing');
    expect(state.uploads[0]?.media_error).toBeUndefined();
  });
});
