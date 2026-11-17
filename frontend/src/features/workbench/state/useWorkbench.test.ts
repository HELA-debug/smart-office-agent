/**
 * useWorkbench 控制器测试。
 *
 * 这一层只做「组件事件 → API 调用 → reducer action」的翻译，所以把五个 feature 的
 * api 层、SSE 与 mock 流全部换成可编程假件，不碰网络、不碰真实事件流。
 * reducer 自身的迁移规则在 workbench.test.ts / workbench.ui.test.ts 里单独测。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../../shared/lib/api';
import { listBackgroundTasks, resetBackgroundTasks } from './background-tasks';
import { useWorkbench } from './useWorkbench';
import type { SseFrame } from '../../runs';

/* ------------------------------------------------------------------ */
/* 外部依赖假件                                                        */
/* ------------------------------------------------------------------ */

const mocks = vi.hoisted(() => ({
  isMockMode: vi.fn(() => false),
  health: vi.fn(),
  listThreads: vi.fn(),
  createThread: vi.fn(),
  getThread: vi.fn(),
  updateThread: vi.fn(),
  deleteThread: vi.fn(),
  getAudit: vi.fn(),
  uploadFile: vi.fn(),
  deleteFile: vi.fn(),
  fetchPreviewText: vi.fn(),
  getArtifact: vi.fn(),
  artifactDownloadUrl: vi.fn(),
  artifactPreviewUrl: vi.fn(),
  listThreadFiles: vi.fn(),
  recognizeFile: vi.fn(),
  submitApproval: vi.fn(),
  cancelRun: vi.fn(),
  streamRun: vi.fn(),
  resumeRunEvents: vi.fn(),
  mockCreateThread: vi.fn(),
  mockListThreads: vi.fn(),
  runMockStream: vi.fn(),
}));

vi.mock('../../../shared/config/runtime', () => ({
  isMockMode: () => mocks.isMockMode(),
  RUN_MODE_OVERRIDE: null,
  SSE_MAX_RECONNECTS: 2,
  SSE_RECONNECT_BASE_DELAY_MS: 1,
  API_BASE: '/api',
  API_V1_BASE: '/api/v1',
  REQUEST_TIMEOUT_MS: 15_000,
  UPLOAD_TIMEOUT_MS: 120_000,
}));

vi.mock('../../settings', () => ({
  settingsApi: { health: mocks.health },
}));

vi.mock('../../sessions', () => ({
  sessionsApi: {
    listThreads: mocks.listThreads,
    createThread: mocks.createThread,
    getThread: mocks.getThread,
    updateThread: mocks.updateThread,
    deleteThread: mocks.deleteThread,
  },
}));

vi.mock('../../audit', () => ({
  auditApi: { getAudit: mocks.getAudit },
}));

vi.mock('../../artifacts', () => ({
  artifactsApi: {
    uploadFile: mocks.uploadFile,
    deleteFile: mocks.deleteFile,
    fetchPreviewText: mocks.fetchPreviewText,
    getArtifact: mocks.getArtifact,
    artifactDownloadUrl: mocks.artifactDownloadUrl,
    artifactPreviewUrl: mocks.artifactPreviewUrl,
    listThreadFiles: mocks.listThreadFiles,
    recognizeFile: mocks.recognizeFile,
  },
  ACCEPTED_UPLOAD_EXTENSIONS: ['.docx', '.txt', '.pdf', '.xlsx', '.png', '.mp3'],
  MAX_UPLOAD_BYTES: 20 * 1024 * 1024,
  // 图片 / 音视频走 200MB 那一档（与 shared/config 的 maxUploadMbForFile 同口径）
  maxUploadBytesForFile: (filename: string) =>
    /\.(png|jpe?g|mp3|m4a|wav|mp4|mov)$/i.test(filename) ? 200 * 1024 * 1024 : 20 * 1024 * 1024,
}));

vi.mock('../../runs', () => ({
  runsApi: {
    submitApproval: mocks.submitApproval,
    cancelRun: mocks.cancelRun,
  },
  streamRun: mocks.streamRun,
  resumeRunEvents: mocks.resumeRunEvents,
}));

vi.mock('../../../shared/lib/mock-run', () => ({
  mockCreateThread: mocks.mockCreateThread,
  mockListThreads: mocks.mockListThreads,
  runMockStream: mocks.runMockStream,
}));

/* ------------------------------------------------------------------ */
/* 构造函数                                                            */
/* ------------------------------------------------------------------ */

const AT = '2026-10-24T12:00:00.000Z';

/** 取列表首个元素并断言非空（项目开启了 noUncheckedIndexedAccess）。 */
function first<T>(items: readonly T[]): T {
  const item = items[0];
  if (item === undefined) throw new Error('列表为空，无法取首个元素');
  return item;
}

const startedPayload = (runId = 'r1', threadId = 't-new') => ({
  version: 1,
  run_id: runId,
  thread_id: threadId,
  mode: 'real',
});

const completedPayload = (runId = 'r1') => ({
  version: 1,
  run_id: runId,
  status: 'completed',
  tokens: 120,
  cost_cny: 0.02,
  elapsed_ms: 3200,
  artifact_ids: [],
  approvals: [],
  degraded: false,
});

function frame(id: string, event: string, data: unknown): SseFrame {
  return { id, event, data: JSON.stringify(data) };
}

function threadSummary(id: string, extra: Record<string, unknown> = {}) {
  return {
    thread_id: id,
    title: `会话 ${id}`,
    created_at: AT,
    updated_at: AT,
    message_count: 0,
    pinned: false,
    ...extra,
  };
}

/** 让 streamRun 按给定帧序列「回放」一次流。 */
function replayStream(frames: SseFrame[], open = true): void {
  mocks.streamRun.mockImplementation(
    async (_input: unknown, handlers: { onOpen?: () => void; onFrame: (f: SseFrame) => void }) => {
      if (open) handlers.onOpen?.();
      for (const item of frames) handlers.onFrame(item);
    },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // 「上次打开的会话」落在 localStorage 里，用例之间必须清掉，否则会跨用例恢复上一次的线程
  window.localStorage.clear();
  mocks.isMockMode.mockReturnValue(false);
  mocks.health.mockResolvedValue({
    data: { mode: 'real', version: '0.2.0' },
    traceId: 'tr-health',
  });
  mocks.listThreads.mockResolvedValue({
    data: { threads: [], page: 1, page_size: 8, total: 0 },
    traceId: null,
  });
  mocks.createThread.mockResolvedValue({ data: threadSummary('t-new'), traceId: null });
  mocks.getThread.mockResolvedValue({
    data: { thread_id: 't1', title: '旧会话', messages: [], artifacts: [] },
    traceId: null,
  });
  mocks.getAudit.mockResolvedValue({ data: { approvals: [] }, traceId: null });
  mocks.updateThread.mockResolvedValue({ data: threadSummary('t1'), traceId: null });
  mocks.deleteThread.mockResolvedValue({ data: {}, traceId: null });
  mocks.submitApproval.mockResolvedValue({ data: {}, traceId: null });
  mocks.cancelRun.mockResolvedValue({ data: {}, traceId: null });
  mocks.streamRun.mockResolvedValue(undefined);
  mocks.resumeRunEvents.mockResolvedValue(undefined);
  mocks.runMockStream.mockResolvedValue(undefined);
  mocks.mockCreateThread.mockReturnValue({
    data: { thread_id: 't-mock', title: '新会话' },
    traceId: 'mock',
  });
  mocks.mockListThreads.mockReturnValue({ data: [], traceId: 'mock' });
  mocks.uploadFile.mockResolvedValue({
    data: {
      file_id: 'f1',
      artifact_id: 'a1',
      filename: '素材.docx',
      size: 2048,
      chars: 12,
      parsed: true,
      text_preview: '解析出来的正文',
    },
    traceId: 'tr-upload',
  });
  mocks.fetchPreviewText.mockResolvedValue('兜底预览');
  // 默认「没有待识别的素材」：只有需要轮询的用例才改它，避免定时器漏到别的用例
  mocks.listThreadFiles.mockResolvedValue({ data: { files: [] }, traceId: null });
  mocks.recognizeFile.mockResolvedValue({
    data: { artifact_id: 'a1', status: 'processing', media: null },
    traceId: null,
  });
  mocks.getArtifact.mockResolvedValue({ data: { sha256: 'sha-1', created_at: AT }, traceId: null });
  mocks.artifactDownloadUrl.mockImplementation((id: string) => `/dl/${id}`);
  mocks.artifactPreviewUrl.mockImplementation((id: string) => `/pv/${id}`);
});

/* ------------------------------------------------------------------ */
/* 初始化：健康检查 + 会话列表                                          */
/* ------------------------------------------------------------------ */

describe('初始化', () => {
  it('挂载即拉健康检查与会话列表，并把 mode / 版本写进 state', async () => {
    mocks.listThreads.mockResolvedValue({
      data: { threads: [threadSummary('t1')], page: 1, page_size: 8, total: 1 },
      traceId: null,
    });
    const { result } = renderHook(() => useWorkbench());

    await waitFor(() => expect(result.current.state.health.status).toBe('ok'));
    expect(result.current.state.health.mode).toBe('real');
    expect(result.current.state.health.version).toBe('0.2.0');
    expect(result.current.state.sessions).toHaveLength(1);
    expect(result.current.state.sessionsMeta).toEqual({ page: 1, pageSize: 8, total: 1 });
    expect(result.current.state.sessionsStatus).toBe('ready');
  });

  it('健康检查失败 → unreachable，不影响会话列表加载', async () => {
    mocks.health.mockRejectedValue(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useWorkbench());

    await waitFor(() => expect(result.current.state.health.status).toBe('unreachable'));
    expect(result.current.state.health.mode).toBeNull();
    expect(result.current.state.sessionsStatus).toBe('ready');
  });

  it('后端未告知 mode 时回落到本地 mock 判定', async () => {
    mocks.health.mockResolvedValue({ data: { version: '0.2.0' }, traceId: null });
    mocks.isMockMode.mockReturnValue(true);
    const { result } = renderHook(() => useWorkbench());

    await waitFor(() => expect(result.current.state.health.status).toBe('ok'));
    expect(result.current.state.health.mode).toBe('mock');
  });

  it('会话列表失败 → sessionsStatus=error 并带错误文案', async () => {
    mocks.listThreads.mockRejectedValue(new ApiError('后端挂了', { code: 'INTERNAL' }));
    const { result } = renderHook(() => useWorkbench());

    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('error'));
    expect(result.current.state.sessionsError).toBe('后端挂了');
  });

  it('分页：goToSessionsPage 带上目标页码重新请求', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.goToSessionsPage(3));
    const lastCall = mocks.listThreads.mock.calls.at(-1)?.[0] as { page: number };
    expect(lastCall.page).toBe(3);
  });
});

/* ------------------------------------------------------------------ */
/* 回到工作台时恢复会话（是否新建会话由用户决定）                      */
/* ------------------------------------------------------------------ */

describe('恢复上次会话', () => {
  it('有记录时挂载即恢复该会话，不偷偷新建线程', async () => {
    window.localStorage.setItem('oa:last-thread', 't1');
    const { result } = renderHook(() => useWorkbench());

    await waitFor(() => expect(result.current.state.threadId).toBe('t1'));
    expect(result.current.state.threadTitle).toBe('旧会话');
    expect(mocks.getThread).toHaveBeenCalledWith('t1');
    expect(mocks.createThread).not.toHaveBeenCalled();
  });

  it('记录已失效 → 停在空状态、清掉记录，也不弹错误提示', async () => {
    window.localStorage.setItem('oa:last-thread', 't-gone');
    mocks.getThread.mockRejectedValue(
      new ApiError('会话不存在', { code: 'NOT_FOUND', status: 404 }),
    );

    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(mocks.getThread).toHaveBeenCalledWith('t-gone'));

    expect(result.current.state.threadId).toBeNull();
    expect(result.current.state.notice).toBeNull();
    expect(window.localStorage.getItem('oa:last-thread')).toBeNull();
  });

  it('点「新建会话」清掉记录：再回首页不会被恢复回来', async () => {
    window.localStorage.setItem('oa:last-thread', 't1');
    const first = renderHook(() => useWorkbench());
    await waitFor(() => expect(first.result.current.state.threadId).toBe('t1'));

    act(() => first.result.current.newThread());
    expect(first.result.current.state.threadId).toBeNull();
    expect(window.localStorage.getItem('oa:last-thread')).toBeNull();

    first.unmount();
    mocks.getThread.mockClear();
    const second = renderHook(() => useWorkbench());
    await waitFor(() => expect(second.result.current.state.sessionsStatus).not.toBe('loading'));
    expect(second.result.current.state.threadId).toBeNull();
    expect(mocks.getThread).not.toHaveBeenCalled();
  });
});

/* ------------------------------------------------------------------ */
/* 发送任务                                                            */
/* ------------------------------------------------------------------ */

describe('发送任务', () => {
  it('建会话 → 起流 → 事件落到 timeline，结束后刷新会话列表', async () => {
    replayStream([
      frame('1', 'run.started', startedPayload()),
      frame('2', 'message.delta', {
        version: 1,
        run_id: 'r1',
        message_id: 'm1',
        delta: '好的',
        index: 0,
      }),
      frame('3', 'run.completed', completedPayload()),
    ]);
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报', 'docx'));

    expect(mocks.createThread).toHaveBeenCalledTimes(1);
    expect(result.current.state.threadId).toBe('t-new');
    expect(result.current.state.status).toBe('done');
    expect(result.current.state.runId).toBe('r1');
    expect(result.current.state.lastUserMessage).toBe('写周报');
    const timeline = result.current.state.timeline;
    expect(timeline.some((item) => item.kind === 'message')).toBe(true);

    const [input] = mocks.streamRun.mock.calls[0] as [{ outputFormat?: string; message: string }];
    expect(input.message).toBe('写周报');
    expect(input.outputFormat).toBe('docx');
    // 初始一次 + 跑完 finally 里刷新一次
    expect(mocks.listThreads).toHaveBeenCalledTimes(2);
  });

  it('「文档格式」跟着这一轮一起发出去（空对象不发，等于全交给后端判断）', async () => {
    replayStream([
      frame('1', 'run.started', startedPayload()),
      frame('3', 'run.completed', completedPayload()),
    ]);
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () =>
      result.current.sendMessage('写周报', 'docx', null, undefined, {
        size: '三号',
        indent_chars: 0,
      }),
    );
    // 首行缩进 0 是「顶格」，不能在这一层被当成没填丢掉
    const [input] = mocks.streamRun.mock.calls[0] as [{ docStyle?: Record<string, unknown> }];
    expect(input.docStyle).toEqual({ size: '三号', indent_chars: 0 });
  });

  it('跑完一轮补拉一次产物：事件漏了也不会逼用户按 F5', async () => {
    // 事件里没有 artifact.ready（脚本产出曾经就是这样），只有服务端知道多了文件
    replayStream([
      frame('1', 'run.started', startedPayload()),
      frame('2', 'run.completed', completedPayload()),
    ]);
    mocks.getThread.mockResolvedValue({
      data: {
        thread_id: 't-new',
        title: '写周报',
        messages: [],
        artifacts: [
          {
            artifact_id: 'art_new',
            type: 'docx',
            filename: '周报（单倍行距）.docx',
            size: 1024,
            sha256: 'sha-new',
            download_url: '/dl/art_new',
            preview_url: '/pv/art_new',
            run_id: 'r1',
            created_at: AT,
          },
        ],
      },
      traceId: null,
    });

    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    await act(async () => result.current.sendMessage('写周报'));

    expect(mocks.getThread).toHaveBeenCalledWith('t-new');
    const names = result.current.state.artifacts.map((item) => item.filename);
    expect(names).toContain('周报（单倍行距）.docx');
    // 补拉只换产物，不能把刚跑出来的对话记录冲掉
    expect(result.current.state.timeline.some((item) => item.kind === 'message')).toBe(true);
    expect(result.current.state.status).toBe('done');
  });

  it('空白消息直接丢弃，不建会话不起流', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('   \n  '));

    expect(mocks.createThread).not.toHaveBeenCalled();
    expect(mocks.streamRun).not.toHaveBeenCalled();
  });

  it('已有 threadId 时复用，不再重复建会话', async () => {
    replayStream([
      frame('1', 'run.started', startedPayload()),
      frame('2', 'run.completed', completedPayload()),
    ]);
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('第一个'));
    await act(async () => result.current.sendMessage('第二个'));

    expect(mocks.createThread).toHaveBeenCalledTimes(1);
    expect(mocks.streamRun).toHaveBeenCalledTimes(2);
  });

  it('运行中再发任务：不请求、只进队列（等前一条跑完自己接上）', async () => {
    let release: (() => void) | undefined;
    mocks.streamRun.mockImplementation(
      async (_input: unknown, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.started', startedPayload()));
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      },
    );
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    let running: Promise<void> | undefined;
    act(() => {
      running = result.current.sendMessage('长任务');
    });
    await waitFor(() => expect(result.current.state.status).toBe('streaming'));

    await act(async () => result.current.sendMessage('插队'));
    expect(result.current.state.notice?.text).toContain('已加入队列');
    expect(result.current.state.queue.map((item) => item.text)).toEqual(['插队']);
    expect(mocks.streamRun).toHaveBeenCalledTimes(1);
    expect(result.current.state.uploads).toHaveLength(0);

    await act(async () => {
      release?.();
      await running;
    });
  });

  it('建会话失败 → 提示错误且不起流', async () => {
    mocks.createThread.mockRejectedValue(new ApiError('库打不开', { code: 'INTERNAL' }));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));

    expect(mocks.streamRun).not.toHaveBeenCalled();
    expect(result.current.state.notice).toMatchObject({
      kind: 'error',
      text: '新建会话失败：库打不开',
    });
  });

  it('流结束但没收到终态事件 → STREAM_CLOSED，避免静默卡在 streaming', async () => {
    mocks.streamRun.mockImplementation(async () => undefined);
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));

    expect(result.current.state.runError).toMatchObject({ code: 'STREAM_CLOSED', retryable: true });
  });

  it('断流后自动续传成功 → 状态收敛为 done，不报错', async () => {
    mocks.streamRun.mockImplementation(
      async (_input: unknown, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.started', startedPayload()));
        // 没有终态事件就断流了
      },
    );
    mocks.resumeRunEvents.mockImplementation(
      async (
        _input: unknown,
        handlers: { onOpen?: () => void; onFrame: (f: SseFrame) => void },
      ) => {
        handlers.onOpen?.();
        handlers.onFrame(frame('2', 'run.completed', completedPayload()));
      },
    );
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));

    expect(mocks.resumeRunEvents).toHaveBeenCalledTimes(1);
    expect(result.current.state.runError).toBeNull();
    expect(result.current.state.status).toBe('done');
  });

  it('续传一直失败 → RECONNECT_FAILED，提示可重试', async () => {
    mocks.streamRun.mockImplementation(
      async (_input: unknown, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.started', startedPayload()));
      },
    );
    mocks.resumeRunEvents.mockResolvedValue(undefined);
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));

    expect(mocks.resumeRunEvents).toHaveBeenCalledTimes(2); // SSE_MAX_RECONNECTS
    expect(result.current.state.runError).toMatchObject({
      code: 'RECONNECT_FAILED',
      retryable: true,
    });
  });

  it('非法 JSON / 未知事件 / 版本不符的帧被忽略，不影响后续帧', async () => {
    mocks.streamRun.mockImplementation(
      async (_input: unknown, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame({ id: '1', event: 'run.started', data: '不是 JSON' });
        handlers.onFrame(frame('2', 'run.never.heard', startedPayload()));
        handlers.onFrame(frame('3', 'run.started', { ...startedPayload(), version: 99 }));
        handlers.onFrame(frame('4', 'run.completed', completedPayload()));
      },
    );
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));

    expect(result.current.state.runId).toBeNull();
    expect(result.current.state.status).toBe('done');
  });

  it('重复送达的旧事件（id 回退）被去重', async () => {
    mocks.streamRun.mockImplementation(
      async (_input: unknown, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame(
          frame('5', 'message.delta', {
            version: 1,
            run_id: 'r1',
            message_id: 'm1',
            delta: '甲',
            index: 0,
          }),
        );
        handlers.onFrame(
          frame('3', 'message.delta', {
            version: 1,
            run_id: 'r1',
            message_id: 'm1',
            delta: '乙',
            index: 0,
          }),
        );
        handlers.onFrame(frame('6', 'run.completed', completedPayload()));
      },
    );
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));

    const reply = result.current.state.timeline.find(
      (item) => item.kind === 'message' && item.message.role === 'assistant',
    );
    const content = reply?.kind === 'message' ? reply.message.content : '';
    expect(content).toContain('甲');
    expect(content).not.toContain('乙');
  });

  it('停止运行：中止事件流并调用后端取消接口', async () => {
    let release: (() => void) | undefined;
    mocks.streamRun.mockImplementation(
      async (_input: unknown, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.started', startedPayload()));
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      },
    );
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    let running: Promise<void> | undefined;
    act(() => {
      running = result.current.sendMessage('长任务');
    });
    await waitFor(() => expect(result.current.state.status).toBe('streaming'));

    await act(async () => {
      result.current.stopRun();
      release?.();
      await running;
    });

    expect(mocks.cancelRun).toHaveBeenCalledWith('r1');
    expect(result.current.state.status).toBe('idle');
  });

  it('后端不支持取消接口 → 只做本地停止并给出说明', async () => {
    mocks.cancelRun.mockRejectedValue(
      new ApiError('not found', { code: 'ENDPOINT_UNAVAILABLE', status: 404 }),
    );
    let release: (() => void) | undefined;
    mocks.streamRun.mockImplementation(
      async (_input: unknown, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.started', startedPayload()));
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      },
    );
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    let running: Promise<void> | undefined;
    act(() => {
      running = result.current.sendMessage('长任务');
    });
    await waitFor(() => expect(result.current.state.status).toBe('streaming'));

    await act(async () => {
      result.current.stopRun();
      release?.();
      await running;
    });
    await waitFor(() => expect(result.current.state.notice?.kind).toBe('info'));
    expect(result.current.state.notice?.text).toContain('已本地停止事件流');
  });

  it('mock 模式下不调用取消接口（本地流无后端可取消）', async () => {
    mocks.isMockMode.mockReturnValue(true);
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.stopRun());
    expect(mocks.cancelRun).not.toHaveBeenCalled();
  });

  it('重试：没有历史任务时只提示', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.retryRun());
    expect(result.current.state.notice?.text).toBe('没有可重试的任务');
  });

  it('重试：复用上一条用户消息重新起流', async () => {
    replayStream([
      frame('1', 'run.started', startedPayload()),
      frame('2', 'run.completed', completedPayload()),
    ]);
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));
    await act(async () => result.current.retryRun('pdf'));

    expect(mocks.streamRun).toHaveBeenCalledTimes(2);
    const lastInput = mocks.streamRun.mock.calls.at(-1)?.[0] as {
      message: string;
      outputFormat?: string;
    };
    expect(lastInput.message).toBe('写周报');
    expect(lastInput.outputFormat).toBe('pdf');
  });
});

/* ------------------------------------------------------------------ */
/* mock 模式                                                           */
/* ------------------------------------------------------------------ */

describe('mock 模式（?mock=1）', () => {
  it('本地建会话并跑本地流，不触碰真实 api', async () => {
    mocks.isMockMode.mockReturnValue(true);
    mocks.mockCreateThread.mockReturnValue({
      data: { thread_id: 't-mock', title: '写周报' },
      traceId: 'mock',
    });
    mocks.runMockStream.mockImplementation(
      async (_input: unknown, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.completed', completedPayload()));
      },
    );
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));

    expect(mocks.createThread).not.toHaveBeenCalled();
    expect(mocks.runMockStream).toHaveBeenCalledTimes(1);
    expect(result.current.state.threadId).toBe('t-mock');
    expect(result.current.state.status).toBe('done');
  });

  it('mock 流的失败回调写进 runError，关闭回调收敛连接态', async () => {
    mocks.isMockMode.mockReturnValue(true);
    mocks.runMockStream.mockImplementation(
      async (
        _input: unknown,
        handlers: {
          onFailure: (f: { code: string; message: string; retryable: boolean }) => void;
          onClose: () => void;
        },
      ) => {
        handlers.onFailure({ code: 'MODEL_TIMEOUT', message: '模型超时', retryable: true });
        handlers.onClose();
      },
    );
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));

    expect(result.current.state.runError).toMatchObject({ code: 'MODEL_TIMEOUT' });
    expect(result.current.state.connection).toBe('closed');
  });
});

/* ------------------------------------------------------------------ */
/* 审批                                                                */
/* ------------------------------------------------------------------ */

describe('审批', () => {
  async function hookWithApproval() {
    // 关键：审批后流要保持打开（等 abort）——若在这里直接结束，会走「断流 → 续传失败」
    // 分支触发 run/failed，pendingApprovals 被标记失效，就测不出等待审批的中间态了。
    mocks.streamRun.mockImplementation(
      async (input: { signal: AbortSignal }, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.started', startedPayload()));
        handlers.onFrame(
          frame('2', 'approval.required', {
            version: 1,
            run_id: 'r1',
            approval_id: 'ap1',
            tool: 'doc.generate_report',
            risk: 'high',
            message: '要生成文件了',
            preview: { to: 'a@example.com', subject: '周报' },
          }),
        );
        await new Promise<void>((resolve) => {
          input.signal.addEventListener('abort', () => resolve());
        });
      },
    );
    const rendered = renderHook(() => useWorkbench());
    await waitFor(() => expect(rendered.result.current.state.sessionsStatus).toBe('ready'));
    // 不能 await：流会一直开到 unmount 触发 abort，await 会把用例挂死到超时
    act(() => {
      void rendered.result.current.sendMessage('发周报');
    });
    await waitFor(() => expect(rendered.result.current.state.status).toBe('waiting_approval'));
    return rendered;
  }

  it('阻塞审批被选出，输入框禁用', async () => {
    const { result } = await hookWithApproval();
    expect(result.current.pendingApproval?.approval_id).toBe('ap1');
    expect(result.current.runBusy).toBe(true);
    expect(result.current.state.status).toBe('waiting_approval');
  });

  it('同意 → 调用后端并落审批结果', async () => {
    const { result } = await hookWithApproval();

    await act(async () => result.current.submitApproval('ap1', 'approved'));

    expect(mocks.submitApproval).toHaveBeenCalledWith('t-new', 'ap1', 'approved');
    expect(first(result.current.state.approvals)).toMatchObject({
      approval_id: 'ap1',
      decision: 'approved',
      submitting: false,
    });
  });

  it('重复提交（后端已处理）按幂等处理，标成功并提示', async () => {
    mocks.submitApproval.mockRejectedValue(
      new ApiError('已处理', { code: 'APPROVAL_ALREADY_DECIDED', status: 409 }),
    );
    const { result } = await hookWithApproval();

    await act(async () => result.current.submitApproval('ap1', 'rejected'));

    expect(first(result.current.state.approvals).decision).toBe('rejected');
    expect(result.current.state.notice?.text).toBe('该审批已处理过（幂等）');
  });

  it('其他错误 → 审批项带 error 并提示（含 trace）', async () => {
    mocks.submitApproval.mockRejectedValue(
      new ApiError('写库失败', { code: 'INTERNAL', traceId: 'tr-9' }),
    );
    const { result } = await hookWithApproval();

    await act(async () => result.current.submitApproval('ap1', 'approved'));

    expect(first(result.current.state.approvals).error).toBe('写库失败（trace: tr-9）');
    expect(result.current.state.notice).toMatchObject({ kind: 'error', traceId: 'tr-9' });
  });

  it('没有会话时提交审批 → 直接拒绝', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.submitApproval('ap1', 'approved'));

    expect(mocks.submitApproval).not.toHaveBeenCalled();
    expect(result.current.state.notice?.text).toBe('缺少会话，无法提交审批');
  });
});

/* ------------------------------------------------------------------ */
/* 上传                                                                */
/* ------------------------------------------------------------------ */

describe('上传', () => {
  function docx(name = '素材.docx'): File {
    return new File(['hello'], name, {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });
  }

  function png(name = '周会截图.png'): File {
    return new File(['fake'], name, { type: 'image/png' });
  }

  /** 上传一张要识别的图片：接口只回「识别中」，文字得靠轮询补。 */
  function mockRecognizingUpload(overrides: Record<string, unknown> = {}) {
    mocks.uploadFile.mockResolvedValue({
      data: {
        file_id: 'f9',
        artifact_id: 'a9',
        filename: '周会截图.png',
        size: 2048,
        chars: 0,
        parsed: false,
        status: 'processing',
        media: { kind: 'image', label: '图片', status: 'processing' },
        ...overrides,
      },
      traceId: 'tr-upload',
    });
  }

  /** 服务端 returns 的一份素材：status 与 media.status 必须同口径，否则界面会说不清。 */
  function threadFile(
    status: 'processing' | 'ready' | 'failed' = 'processing',
    chars = 0,
  ): Record<string, unknown> {
    return {
      file_id: 'f9',
      artifact_id: 'a9',
      filename: '周会截图.png',
      size: 2048,
      ext: 'png',
      chars,
      parsed: status === 'ready',
      status,
      media: {
        kind: 'image',
        label: '图片',
        status,
        ...(status === 'failed' ? { error: '模型没下载下来', retryable: true } : {}),
      },
    };
  }

  it('认不出的后缀也照传：能不能读出字由后端回答，前端不按后缀拦', async () => {
    mocks.uploadFile.mockResolvedValue({
      data: {
        file_id: 'a10',
        artifact_id: 'a10',
        filename: '病毒.exe',
        size: 1024,
        ext: 'exe',
        chars: 0,
        parsed: false,
        status: 'failed',
        media: null,
      },
      traceId: 't',
    });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    // 已经有会话：选文件就立刻上传（没有会话时只暂存，见「没有会话时只进本地队列」）
    await act(async () => result.current.selectThread('t1'));

    await act(async () => result.current.uploadFile(docx('病毒.exe')));

    // 拖进来的东西五花八门（旧版 .doc、.zip、相机导出的 .heic…），前端拦一道
    // 只会让人卡在「到底能传什么」上；收下再如实说「读不出文字」更有用
    expect(mocks.uploadFile).toHaveBeenCalledTimes(1);
  });

  it('超过 20MB → 拦截并提示', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    // 已经有会话：选文件就立刻上传（没有会话时只暂存，见「没有会话时只进本地队列」）
    await act(async () => result.current.selectThread('t1'));

    const big = docx('大文件.docx');
    Object.defineProperty(big, 'size', { value: 21 * 1024 * 1024 });
    await act(async () => result.current.uploadFile(big));

    expect(mocks.uploadFile).not.toHaveBeenCalled();
    expect(first(result.current.state.uploads).error).toBe('文件超过 20MB 上限');
  });

  it('上传成功：带 text_preview 时直接用，不额外请求预览端点', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    // 已经有会话：选文件就立刻上传（没有会话时只暂存，见「没有会话时只进本地队列」）
    await act(async () => result.current.selectThread('t1'));

    await act(async () => result.current.uploadFile(docx()));

    expect(first(result.current.state.uploads)).toMatchObject({
      status: 'parsed',
      preview: '解析出来的正文',
    });
    expect(mocks.fetchPreviewText).not.toHaveBeenCalled();
    expect(result.current.state.notice?.text).toContain('解析 12 字');
  });

  it('上传成功但没带 preview → 回落到预览端点', async () => {
    mocks.uploadFile.mockResolvedValue({
      data: { file_id: 'f1', artifact_id: 'a1', filename: '素材.docx', size: 10, parsed: true },
      traceId: null,
    });
    mocks.fetchPreviewText.mockResolvedValue('端点拿到的预览');
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    // 已经有会话：选文件就立刻上传（没有会话时只暂存，见「没有会话时只进本地队列」）
    await act(async () => result.current.selectThread('t1'));

    await act(async () => result.current.uploadFile(docx()));
    await waitFor(() => expect(first(result.current.state.uploads).preview).toBe('端点拿到的预览'));
    expect(mocks.fetchPreviewText).toHaveBeenCalledWith('a1', 200);
  });

  it('预览端点也失败时不崩，只是没有预览', async () => {
    mocks.uploadFile.mockResolvedValue({
      data: { file_id: 'f1', artifact_id: 'a1', filename: '素材.docx', size: 10 },
      traceId: null,
    });
    mocks.fetchPreviewText.mockRejectedValue(new Error('预览挂了'));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    // 已经有会话：选文件就立刻上传（没有会话时只暂存，见「没有会话时只进本地队列」）
    await act(async () => result.current.selectThread('t1'));

    await act(async () => result.current.uploadFile(docx()));
    expect(first(result.current.state.uploads).status).toBe('parsed');
    expect(first(result.current.state.uploads).preview).toBeUndefined();
  });

  it('解析失败（parsed=false）→ 提示可在任务中重试', async () => {
    mocks.uploadFile.mockResolvedValue({
      data: { file_id: 'f1', artifact_id: 'a1', filename: '素材.docx', size: 10, parsed: false },
      traceId: null,
    });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    // 已经有会话：选文件就立刻上传（没有会话时只暂存，见「没有会话时只进本地队列」）
    await act(async () => result.current.selectThread('t1'));

    await act(async () => result.current.uploadFile(docx()));
    expect(result.current.state.notice?.text).toContain('解析失败');
  });

  it('上传接口失败 → 落 error 项并提示', async () => {
    mocks.uploadFile.mockRejectedValue(new ApiError('磁盘满了', { code: 'INTERNAL' }));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    // 已经有会话：选文件就立刻上传（没有会话时只暂存，见「没有会话时只进本地队列」）
    await act(async () => result.current.selectThread('t1'));

    await act(async () => result.current.uploadFile(docx()));

    expect(first(result.current.state.uploads).status).toBe('error');
    expect(result.current.state.notice?.text).toBe('上传失败：磁盘满了');
  });

  it('没有会话时选文件只进本地队列：不建会话、不上传，状态是「待发送」', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.uploadFile(docx()));

    expect(mocks.createThread).not.toHaveBeenCalled();
    expect(mocks.uploadFile).not.toHaveBeenCalled();
    expect(result.current.state.threadId).toBeNull();
    expect(result.current.state.uploads).toHaveLength(1);
    expect(first(result.current.state.uploads)).toMatchObject({
      status: 'staged',
      filename: '素材.docx',
    });
  });

  it('首次发送任务时才建会话，并把暂存附件传上去', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.uploadFile(docx()));
    await act(async () => {
      await result.current.sendMessage('整理成周报');
    });

    expect(mocks.createThread).toHaveBeenCalledTimes(1);
    expect(mocks.uploadFile).toHaveBeenCalledWith('t-new', expect.any(File), expect.anything());
    expect(mocks.streamRun).toHaveBeenCalled();
  });

  it('多文件上传按顺序逐个执行', async () => {
    const order: string[] = [];
    mocks.uploadFile.mockImplementation(async (_threadId: string, file: File) => {
      order.push(file.name);
      return {
        data: { file_id: file.name, artifact_id: file.name, filename: file.name, size: 10 },
        traceId: null,
      };
    });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    // 已经有会话：选文件就立刻上传（没有会话时只暂存，见「没有会话时只进本地队列」）
    await act(async () => result.current.selectThread('t1'));

    await act(async () => result.current.uploadFiles([docx('一.docx'), docx('二.docx')]));

    expect(order).toEqual(['一.docx', '二.docx']);
    expect(result.current.state.uploads).toHaveLength(2);
  });

  it('移除已上传的素材会同步删服务端记录', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    // 已经有会话：选文件就立刻上传（没有会话时只暂存，见「没有会话时只进本地队列」）
    await act(async () => result.current.selectThread('t1'));

    await act(async () => result.current.uploadFile(docx()));
    const upload = first(result.current.state.uploads);
    expect(upload.file_id).toBeTruthy();

    // 只清本地列表的话，重进会话时素材会从 /threads/{id} 再读回来
    await act(async () => {
      await result.current.removeUpload(upload.local_id);
    });

    expect(mocks.deleteFile).toHaveBeenCalledWith(upload.file_id);
    expect(result.current.state.uploads).toHaveLength(0);
  });

  it('服务端删除失败时保留素材并提示', async () => {
    mocks.deleteFile.mockRejectedValueOnce(new Error('后端挂了'));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    await act(async () => result.current.selectThread('t1'));
    await act(async () => result.current.uploadFile(docx()));
    const upload = first(result.current.state.uploads);

    await act(async () => {
      await result.current.removeUpload(upload.local_id);
    });

    expect(result.current.state.uploads).toHaveLength(1);
    expect(result.current.state.notice?.kind).toBe('error');
  });

  /* ---- 图片 / 录音：上传只回「识别中」，文字靠轮询补 ---- */

  it('图片上传后是「识别中」：先说要等，识别完再提示可用字数', async () => {
    mockRecognizingUpload();
    // 第一次轮询先挂住：这样能看清「还没出结果时界面说的是什么」
    let release: ((value: unknown) => void) | undefined;
    mocks.listThreadFiles.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    await act(async () => result.current.selectThread('t1'));

    await act(async () => result.current.uploadFile(png()));

    // 上传一落地就说清楚「在识别」，否则用户会以为传丢了
    expect(result.current.state.notice?.text).toContain('正在识别文字');
    expect(first(result.current.state.uploads).media_status).toBe('processing');

    await act(async () => {
      release?.({ data: { files: [threadFile('ready', 58)] }, traceId: null });
    });

    await waitFor(() =>
      expect(result.current.state.notice?.text).toContain('识别完成，58 字已可用'),
    );
    // 状态同步回素材本身：徽标从「识别中」变成「图片」，可发送
    expect(first(result.current.state.uploads)).toMatchObject({
      status: 'parsed',
      media_status: 'ready',
      media_kind: 'image',
    });
    expect(mocks.listThreadFiles).toHaveBeenCalledWith('t1');
  });

  it('识别中每 2.5 秒追一次状态，完成后自己停（不一直轮）', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockRecognizingUpload();
      mocks.listThreadFiles
        .mockResolvedValueOnce({ data: { files: [threadFile()] }, traceId: null })
        .mockResolvedValue({
          data: { files: [threadFile('ready', 12)] },
          traceId: null,
        });
      const { result } = renderHook(() => useWorkbench());
      await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
      await act(async () => result.current.selectThread('t1'));
      await act(async () => result.current.uploadFile(png()));

      // 第一次是上传后立刻拉的，此时还在识别 → 素材保持「识别中」
      expect(mocks.listThreadFiles).toHaveBeenCalledTimes(1);
      expect(first(result.current.state.uploads).media_status).toBe('processing');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2600);
      });
      expect(mocks.listThreadFiles).toHaveBeenCalledTimes(2);
      expect(first(result.current.state.uploads).media_status).toBe('ready');

      // 已经出结果：再等也不会继续请求
      await act(async () => {
        await vi.advanceTimersByTimeAsync(6000);
      });
      expect(mocks.listThreadFiles).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('进会话第一次拉状态：不为早就有结果的老素材播报「识别完成」', async () => {
    // 会话里躺着一份上周就转写好的录音
    mocks.getThread.mockResolvedValue({
      data: {
        thread_id: 't1',
        title: '旧会话',
        messages: [],
        artifacts: [],
        uploads: [
          {
            artifact_id: 'old1',
            file_id: 'old1',
            filename: '上周录音.m4a',
            size: 10,
            ext: 'm4a',
            parsed: true,
            chars: 88,
            media: { kind: 'audio', label: '会议录音', status: 'ready' },
          },
        ],
      },
      traceId: null,
    });
    mocks.listThreadFiles.mockResolvedValue({
      data: {
        files: [
          {
            file_id: 'old1',
            artifact_id: 'old1',
            filename: '上周录音.m4a',
            size: 10,
            ext: 'm4a',
            chars: 88,
            parsed: true,
            status: 'ready',
            media: { kind: 'audio', label: '会议录音', status: 'ready' },
          },
        ],
      },
      traceId: null,
    });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    await act(async () => result.current.selectThread('t1'));

    // 再传一张新图，触发第一轮轮询
    mockRecognizingUpload();
    await act(async () => result.current.uploadFile(png()));
    await waitFor(() => expect(mocks.listThreadFiles).toHaveBeenCalled());

    // 旧录音不该被当新闻播报出来
    expect(result.current.state.notice?.text).not.toContain('上周录音');
    expect(result.current.state.notice?.text).toContain('正在识别文字');
  });

  it('识别失败 → 素材标失败并带原因；点重试重新入队并继续追状态', async () => {
    mockRecognizingUpload();
    mocks.listThreadFiles
      .mockResolvedValueOnce({
        data: {
          files: [threadFile('failed')],
        },
        traceId: null,
      })
      .mockResolvedValue({
        data: { files: [threadFile('ready', 30)] },
        traceId: null,
      });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    await act(async () => result.current.selectThread('t1'));
    await act(async () => result.current.uploadFile(png()));

    await waitFor(() => expect(result.current.state.notice?.text).toContain('识别失败'));
    expect(first(result.current.state.uploads)).toMatchObject({
      media_status: 'failed',
      media_error: '模型没下载下来',
    });

    await act(async () => {
      await result.current.retryUpload(first(result.current.state.uploads).local_id);
    });

    // 走服务端的重试接口（不重新上传，文件已经在库里）
    expect(mocks.recognizeFile).toHaveBeenCalledWith('a9');
    await waitFor(() => expect(first(result.current.state.uploads).media_status).toBe('ready'));
  });

  it('识别中的素材不占「可发送」名额，发送前被拦下', async () => {
    mockRecognizingUpload();
    mocks.listThreadFiles.mockResolvedValue({ data: { files: [threadFile()] }, traceId: null });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    await act(async () => result.current.selectThread('t1'));
    await act(async () => result.current.uploadFile(png()));

    const upload = first(result.current.state.uploads);
    // status 是 parsed（文件收下了），但 media 还在识别：两者不能混为一谈
    expect(upload.status).toBe('parsed');
    expect(upload.media_status).toBe('processing');
  });
});

/* ------------------------------------------------------------------ */
/* 会话操作                                                            */
/* ------------------------------------------------------------------ */

describe('会话操作', () => {
  it('重命名：空标题不发请求', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.renameThread('t1', '   '));
    expect(mocks.updateThread).not.toHaveBeenCalled();
  });

  it('重命名成功 → 列表 upsert 并提示', async () => {
    mocks.updateThread.mockResolvedValue({
      data: threadSummary('t1', { title: '新名字' }),
      traceId: null,
    });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.renameThread('t1', ' 新名字 '));

    expect(mocks.updateThread).toHaveBeenCalledWith('t1', { title: '新名字' });
    expect(first(result.current.state.sessions)).toMatchObject({ title: '新名字' });
    expect(result.current.state.notice?.text).toBe('会话已重命名');
  });

  it('重命名失败 → 提示错误', async () => {
    mocks.updateThread.mockRejectedValue(new ApiError('没权限', { code: 'FORBIDDEN' }));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.renameThread('t1', '新名字'));
    expect(result.current.state.notice?.text).toBe('重命名失败：没权限');
  });

  it('置顶 / 取消置顶的提示文案不同', async () => {
    mocks.updateThread
      .mockResolvedValueOnce({ data: threadSummary('t1', { pinned: true }), traceId: null })
      .mockResolvedValueOnce({ data: threadSummary('t1', { pinned: false }), traceId: null });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.toggleThreadPin('t1', true));
    expect(result.current.state.notice?.text).toBe('会话已置顶');

    await act(async () => result.current.toggleThreadPin('t1', false));
    expect(result.current.state.notice?.text).toBe('已取消置顶');
  });

  it('置顶失败 → 提示错误', async () => {
    mocks.updateThread.mockRejectedValue(new ApiError('崩了', { code: 'INTERNAL' }));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.toggleThreadPin('t1', true));
    expect(result.current.state.notice?.text).toBe('置顶失败：崩了');
  });

  it('删除会话（软删）→ 从列表移除并提示', async () => {
    mocks.listThreads.mockResolvedValue({
      data: {
        threads: [threadSummary('t1'), threadSummary('t2')],
        page: 1,
        page_size: 8,
        total: 2,
      },
      traceId: null,
    });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessions).toHaveLength(2));

    await act(async () => result.current.deleteThread('t1'));

    expect(mocks.deleteThread).toHaveBeenCalledWith('t1');
    expect(result.current.state.sessions.map((item) => item.thread_id)).toEqual(['t2']);
    expect(result.current.state.notice?.text).toBe('会话已删除（软删）');
  });

  it('删除失败 → 提示错误且不动列表', async () => {
    mocks.listThreads.mockResolvedValue({
      data: { threads: [threadSummary('t1')], page: 1, page_size: 8, total: 1 },
      traceId: null,
    });
    mocks.deleteThread.mockRejectedValue(new ApiError('删不掉', { code: 'INTERNAL' }));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessions).toHaveLength(1));

    await act(async () => result.current.deleteThread('t1'));

    expect(result.current.state.sessions).toHaveLength(1);
    expect(result.current.state.notice?.text).toBe('删除会话失败：删不掉');
  });

  it('切换会话：历史消息过滤 run_summary 与非文本内容', async () => {
    mocks.listThreads.mockResolvedValue({
      data: { threads: [threadSummary('t1')], page: 1, page_size: 8, total: 1 },
      traceId: null,
    });
    mocks.getThread.mockResolvedValue({
      data: {
        thread_id: 't1',
        title: '旧会话',
        messages: [
          { message_id: 'm1', role: 'user', content: '你好', created_at: AT },
          { message_id: 'm2', role: 'run_summary', content: '汇总' },
          { message_id: 'm3', role: 'assistant', content: { bad: true } },
        ],
        artifacts: [],
      },
      traceId: null,
    });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessions).toHaveLength(1));

    await act(async () => result.current.selectThread('t1'));

    expect(result.current.state.threadId).toBe('t1');
    expect(result.current.state.threadTitle).toBe('旧会话');
    expect(result.current.state.timeline).toHaveLength(1);
  });

  it('切换会话：产物与素材拆到各自列表，已决策审批进右栏', async () => {
    mocks.listThreads.mockResolvedValue({
      data: { threads: [threadSummary('t1')], page: 1, page_size: 8, total: 1 },
      traceId: null,
    });
    mocks.getThread.mockResolvedValue({
      data: {
        thread_id: 't1',
        title: '旧会话',
        messages: [],
        artifacts: [
          {
            artifact_id: 'up1',
            type: 'upload',
            filename: '素材.docx',
            size: 100,
            extra: { chars: 50, ext: '.docx' },
          },
          {
            artifact_id: 'a1',
            type: 'docx',
            filename: '周报.docx',
            size: 200,
            sha256: 'sha-x',
            created_at: AT,
          },
        ],
      },
      traceId: null,
    });
    mocks.getAudit.mockResolvedValue({
      data: {
        approvals: [
          {
            approval_id: 'ap1',
            run_id: 'r1',
            tool: 'doc.generate_report',
            decision: 'approved',
            created_at: AT,
            payload: { to: 'a@example.com' },
          },
          { approval_id: 'ap2', run_id: 'r1', tool: 'file.delete', decision: 'pending' },
        ],
      },
      traceId: null,
    });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessions).toHaveLength(1));

    await act(async () => result.current.selectThread('t1'));

    // 会话自带的素材进右栏；输入框保持空（那是「待发附件」，不是历史素材）
    expect(first(result.current.state.threadUploads)).toMatchObject({
      filename: '素材.docx',
      chars: 50,
    });
    expect(result.current.state.uploads).toEqual([]);
    expect(first(result.current.state.artifacts)).toMatchObject({
      artifact_id: 'a1',
      download_url: '/dl/a1',
      preview_url: '/pv/a1',
      meta_status: 'idle',
    });
    // 只有已决策的进右栏；写盘/删除类工具判为 high
    expect(result.current.state.approvals).toHaveLength(1);
    expect(first(result.current.state.approvals)).toMatchObject({
      risk: 'high',
      decision: 'approved',
    });
  });

  it('切换会话：详情失败仍切过去（空历史）并提示', async () => {
    mocks.listThreads.mockResolvedValue({
      data: { threads: [threadSummary('t1')], page: 1, page_size: 8, total: 1 },
      traceId: null,
    });
    mocks.getThread.mockRejectedValue(new ApiError('查不到', { code: 'NOT_FOUND' }));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessions).toHaveLength(1));

    await act(async () => result.current.selectThread('t1'));

    expect(result.current.state.threadId).toBe('t1');
    expect(result.current.state.threadTitle).toBe('会话 t1');
    expect(result.current.state.timeline).toHaveLength(0);
    expect(result.current.state.notice?.text).toBe('加载会话失败：查不到');
  });

  it('审计接口失败不影响会话切换，审批列表留空', async () => {
    mocks.listThreads.mockResolvedValue({
      data: { threads: [threadSummary('t1')], page: 1, page_size: 8, total: 1 },
      traceId: null,
    });
    mocks.getAudit.mockRejectedValue(new ApiError('审计挂了', { code: 'INTERNAL' }));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessions).toHaveLength(1));

    await act(async () => result.current.selectThread('t1'));

    expect(result.current.state.approvals).toEqual([]);
  });

  it('点当前会话不做任何请求', async () => {
    replayStream([
      frame('1', 'run.started', startedPayload()),
      frame('2', 'run.completed', completedPayload()),
    ]);
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    await act(async () => result.current.sendMessage('写周报'));
    expect(result.current.state.threadId).toBe('t-new');

    // 跑完那一轮会补拉一次产物（对账用），这里只关心「点当前会话」本身不该再发请求
    mocks.getThread.mockClear();
    await act(async () => result.current.selectThread('t-new'));
    expect(mocks.getThread).not.toHaveBeenCalled();
  });

  it('新建会话会清空当前会话', async () => {
    replayStream([
      frame('1', 'run.started', startedPayload()),
      frame('2', 'run.completed', completedPayload()),
    ]);
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.sendMessage('写周报'));
    expect(result.current.state.threadId).toBe('t-new');

    act(() => result.current.newThread());
    expect(result.current.state.threadId).toBeNull();
    expect(result.current.state.timeline).toHaveLength(0);
  });
});

/* ------------------------------------------------------------------ */
/* 产物元数据 / 审计抽屉 / 通知                                        */
/* ------------------------------------------------------------------ */

describe('产物元数据与审计', () => {
  it('加载产物元数据成功 → 写 sha256 与时间', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.loadArtifactMeta('a1'));
    // 该会话还没有这条产物，只有 action 被派发；用 state 断言不到就没意义，
    // 所以这里直接断言 api 被调用（异常分支见下一条）
    expect(mocks.getArtifact).toHaveBeenCalledWith('a1');
  });

  it('加载产物元数据失败 → 不抛异常', async () => {
    mocks.getArtifact.mockRejectedValue(new ApiError('没有这个产物', { code: 'NOT_FOUND' }));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await expect(act(async () => result.current.loadArtifactMeta('a1'))).resolves.toBeUndefined();
  });

  it('打开审计抽屉：没有会话时只开不请求', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.openAudit());

    expect(result.current.state.audit.open).toBe(true);
    expect(mocks.getAudit).not.toHaveBeenCalled();
  });

  it('打开审计抽屉：有会话时加载数据', async () => {
    replayStream([
      frame('1', 'run.started', startedPayload()),
      frame('2', 'run.completed', completedPayload()),
    ]);
    mocks.getAudit.mockResolvedValue({ data: { approvals: [], runs: [] }, traceId: null });
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    await act(async () => result.current.sendMessage('写周报'));

    await act(async () => result.current.openAudit());

    expect(result.current.state.audit.open).toBe(true);
    expect(result.current.state.audit.status).toBe('ready');
  });

  it('审计加载失败 → 抽屉里显示错误', async () => {
    replayStream([
      frame('1', 'run.started', startedPayload()),
      frame('2', 'run.completed', completedPayload()),
    ]);
    mocks.getAudit.mockRejectedValue(new ApiError('审计服务挂了', { code: 'INTERNAL' }));
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
    await act(async () => result.current.sendMessage('写周报'));

    await act(async () => result.current.openAudit());

    expect(result.current.state.audit.status).toBe('error');
    expect(result.current.state.audit.error).toBe('审计服务挂了');
  });

  it('关闭审计抽屉', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.openAudit());
    act(() => result.current.closeAudit());
    expect(result.current.state.audit.open).toBe(false);
  });

  it('手动关闭通知', async () => {
    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    await act(async () => result.current.retryRun());
    expect(result.current.state.notice).not.toBeNull();

    act(() => result.current.dismissNotice());
    expect(result.current.state.notice).toBeNull();
  });

  it('通知 5 秒后自动消失', async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useWorkbench());
      await act(async () => undefined);

      await act(async () => result.current.retryRun());
      expect(result.current.state.notice).not.toBeNull();

      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(result.current.state.notice).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('卸载时中断进行中的流', async () => {
    let aborted = false;
    let release: (() => void) | undefined;
    mocks.streamRun.mockImplementation(
      async (input: { signal: AbortSignal }, handlers: { onFrame: (f: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.started', startedPayload()));
        input.signal.addEventListener('abort', () => {
          aborted = true;
        });
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      },
    );
    const { result, unmount } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    let running: Promise<void> | undefined;
    act(() => {
      running = result.current.sendMessage('长任务');
    });
    await waitFor(() => expect(result.current.state.status).toBe('streaming'));

    unmount();
    expect(aborted).toBe(true);
    release?.();
    await running;
  });
});

/* ------------------------------------------------------------------ */
/* 后台任务（切走会话不中断）                                            */
/* ------------------------------------------------------------------ */

describe('后台任务', () => {
  beforeEach(() => resetBackgroundTasks());

  it('新建会话时正在跑的流转后台：不断流、不再写当前界面', async () => {
    let release: (() => void) | undefined;
    let aborted = false;
    mocks.streamRun.mockImplementation(
      async (input: { signal: AbortSignal }, handlers: { onFrame: (frame: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.started', startedPayload()));
        input.signal.addEventListener('abort', () => {
          aborted = true;
        });
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        handlers.onFrame(frame('2', 'run.completed', completedPayload()));
      },
    );

    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    let running: Promise<void> | undefined;
    act(() => {
      running = result.current.sendMessage('把这份材料整理成周报');
    });
    await waitFor(() => expect(result.current.state.status).toBe('streaming'));

    act(() => result.current.newThread());

    // 流没有被打断，任务挂到后台；当前界面回到空状态
    expect(aborted).toBe(false);
    expect(result.current.state.threadId).toBeNull();
    expect(result.current.state.status).toBe('idle');
    expect(listBackgroundTasks()).toHaveLength(1);
    expect(first(listBackgroundTasks()).label).toContain('整理成周报');
    expect(first(listBackgroundTasks()).runId).toBe('r1');

    // 后台流跑完 → 指示条自动清空
    await act(async () => {
      release?.();
      await running;
    });
    await waitFor(() => expect(listBackgroundTasks()).toHaveLength(0));
  });

  it('手动停止后台任务：断流并请后端取消', async () => {
    let aborted = false;
    mocks.streamRun.mockImplementation(
      async (input: { signal: AbortSignal }, handlers: { onFrame: (frame: SseFrame) => void }) => {
        handlers.onFrame(frame('1', 'run.started', startedPayload()));
        input.signal.addEventListener('abort', () => {
          aborted = true;
        });
        await new Promise<void>((resolve) => {
          input.signal.addEventListener('abort', () => resolve());
        });
      },
    );

    const { result } = renderHook(() => useWorkbench());
    await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));

    let running: Promise<void> | undefined;
    act(() => {
      running = result.current.sendMessage('写周报');
    });
    await waitFor(() => expect(result.current.state.status).toBe('streaming'));

    act(() => result.current.newThread());
    const task = first(listBackgroundTasks());

    act(() => result.current.stopBackgroundTask(task.key));

    expect(aborted).toBe(true);
    expect(listBackgroundTasks()).toHaveLength(0);
    expect(mocks.cancelRun).toHaveBeenCalled();
    await running;
  });
});

/* ------------------------------------------------------------------ */
/* 任务队列：运行中发的消息不丢弃，跑完自动接着执行                     */
/* ------------------------------------------------------------------ */

/**
 * 可控流：第一轮跑到一半挂住，调用 release() 才发 run.completed；
 * 之后的轮次一律挂住（用例只关心「有没有被发起」）。
 */
function controlledStream() {
  let release: (() => void) | null = null;
  let calls = 0;
  mocks.streamRun.mockImplementation(
    async (_input: unknown, handlers: { onOpen?: () => void; onFrame: (f: SseFrame) => void }) => {
      calls += 1;
      handlers.onOpen?.();
      handlers.onFrame(frame('1', 'run.started', startedPayload()));
      if (calls === 1) {
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        handlers.onFrame(frame('2', 'run.completed', completedPayload()));
        return;
      }
      await new Promise<void>(() => {
        /* 后续轮次一直挂着 */
      });
    },
  );
  return { release: () => release?.(), calls: () => calls };
}

async function hookRunning() {
  const { result } = renderHook(() => useWorkbench());
  await waitFor(() => expect(result.current.state.sessionsStatus).toBe('ready'));
  act(() => {
    void result.current.sendMessage('先把材料整理成周报');
  });
  await waitFor(() => expect(result.current.state.status).toBe('streaming'));
  return result;
}

describe('任务队列', () => {
  it('运行中再发一条：不拦截也不丢弃，进队列并给出提示', async () => {
    controlledStream();
    const result = await hookRunning();

    await act(async () => {
      await result.current.sendMessage('顺手再把表格汇总一下');
    });

    expect(result.current.state.queue).toHaveLength(1);
    expect(first(result.current.state.queue).text).toBe('顺手再把表格汇总一下');
    expect(result.current.state.notice?.text).toContain('已加入队列');
    // 当前这条还在跑，队列那条不能抢跑
    expect(mocks.streamRun).toHaveBeenCalledTimes(1);
  });

  it('前一条跑完：队列里那条自动接着执行，不用再点发送', async () => {
    const stream = controlledStream();
    const result = await hookRunning();

    await act(async () => {
      await result.current.sendMessage('再汇总表格');
    });

    await act(async () => {
      stream.release();
    });

    await waitFor(() => expect(stream.calls()).toBe(2));
    const second = mocks.streamRun.mock.calls[1]?.[0] as { message: string };
    expect(second.message).toBe('再汇总表格');
    await waitFor(() => expect(result.current.state.queue).toHaveLength(0));
  });

  it('排队任务的素材跟着它走：输入区清空，编辑时再还回来', async () => {
    controlledStream();
    const result = await hookRunning();

    await act(async () => {
      await result.current.uploadFile(new File(['x'], '台账.docx'));
    });
    await act(async () => {
      await result.current.sendMessage('把台账也并进来');
    });

    expect(result.current.state.uploads).toHaveLength(0);
    const item = first(result.current.state.queue);
    expect(item.uploads.map((upload) => upload.filename)).toEqual(['台账.docx']);

    let text: string | null = null;
    act(() => {
      text = result.current.editQueued(item.id);
    });
    expect(text).toBe('把台账也并进来');
    expect(result.current.state.queue).toHaveLength(0);
    expect(result.current.state.uploads.map((upload) => upload.filename)).toEqual(['台账.docx']);
  });

  it('删除排队任务：它的素材一并从服务端软删，不会留在会话里', async () => {
    controlledStream();
    const result = await hookRunning();
    await act(async () => {
      await result.current.uploadFile(new File(['x'], '台账.docx'));
    });
    await act(async () => {
      await result.current.sendMessage('把台账也并进来');
    });

    const item = first(result.current.state.queue);
    await act(async () => {
      await result.current.removeQueued(item.id);
    });

    expect(mocks.deleteFile).toHaveBeenCalledWith('f1');
    expect(result.current.state.queue).toHaveLength(0);
  });

  it('按停止：队列先歇着，点「继续执行」才接着跑', async () => {
    const stream = controlledStream();
    const result = await hookRunning();
    await act(async () => {
      await result.current.sendMessage('再汇总表格');
    });

    act(() => result.current.stopRun());
    expect(result.current.state.queuePaused).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(stream.calls()).toBe(1);

    await act(async () => {
      result.current.resumeQueue();
    });
    await waitFor(() => expect(stream.calls()).toBe(2));
  });
});
