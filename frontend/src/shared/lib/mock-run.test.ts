/**
 * mock-run 测试：`?mock=1` 时的本地 fixture（不是假后端，是演示兜底）。
 *
 * 这段脚本按真实事件契约吐 11 类事件，节奏靠 setTimeout 撑着，
 * 所以整组用假定时器推进——真等下来一条完整流要 7 秒。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EVENT_VERSION } from '../types/events';
import {
  mockCreateThread,
  mockGetArtifact,
  mockGetAudit,
  mockGetThread,
  mockHealth,
  mockListFiles,
  mockListThreads,
  mockSubmitApproval,
  mockUploadFile,
  runMockStream,
} from './mock-run';
import type { SseFrame, StreamFailure } from './sse';

/**
 * 收集帧 + 记录回调。
 * 这里给 vi.fn 显式标注签名（而不是裸 vi.fn()），否则 Mock<Procedure> 与
 * RunStreamHandlers 的（可能为 undefined 的）回调类型对不上，tsc 会报 TS2322。
 */
function collector() {
  const frames: SseFrame[] = [];
  const onOpen = vi.fn<() => void>();
  const onClose = vi.fn<() => void>();
  const onAbort = vi.fn<() => void>();
  const onFailure = vi.fn<(failure: StreamFailure) => void>();
  return { frames, onOpen, onClose, onAbort, onFailure };
}

type Collected = ReturnType<typeof collector>;

function payload(frame: SseFrame): Record<string, unknown> {
  return JSON.parse(frame.data) as Record<string, unknown>;
}

function eventsOf(frames: SseFrame[]): string[] {
  return frames.map((frame) => frame.event);
}

function framesNamed(frames: SseFrame[], name: string): SseFrame[] {
  return frames.filter((frame) => frame.event === name);
}

/** 把整条 mock 流跑完（假定时器一次性推到底，真实耗时约 7s）。 */
async function runScript(outputFormat: string | undefined): Promise<Collected> {
  const spy = collector();
  const promise = runMockStream(
    { threadId: 'th_mock_001', message: '写周报', outputFormat },
    {
      onFrame: (frame) => spy.frames.push(frame),
      onOpen: spy.onOpen,
      onClose: spy.onClose,
      onAbort: spy.onAbort,
      onFailure: spy.onFailure,
    },
  );
  await vi.advanceTimersByTimeAsync(30_000);
  await promise;
  return spy;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/* ------------------------------------------------------------------ */
/* 非流式 fixture                                                     */
/* ------------------------------------------------------------------ */

describe('非流式 fixture', () => {
  it('mockHealth 固定返回 ok + mock 模式', () => {
    const response = mockHealth();
    expect(response.data).toMatchObject({ status: 'ok', mode: 'mock' });
    expect(response.traceId).toMatch(/^mock-trace-/);
  });

  it('mockCreateThread 生成递增 id，标题为空时回落默认值', () => {
    const firstThread = mockCreateThread('  写周报  ').data;
    const secondThread = mockCreateThread('   ').data;

    expect(firstThread.title).toBe('写周报');
    expect(secondThread.title).toBe('新的会话');
    expect(firstThread.thread_id).toMatch(/^th_mock_\d{3}$/);
    expect(secondThread.thread_id).not.toBe(firstThread.thread_id);
  });

  it('mockListThreads 按 updated_at 倒序，新建的排在最前', () => {
    const created = mockCreateThread('最新的').data;
    const list = mockListThreads().data;
    expect(list[0]?.thread_id).toBe(created.thread_id);

    const times = list.map((thread) => thread.updated_at);
    expect([...times].sort((a, b) => b.localeCompare(a))).toEqual(times);
  });

  it('mockGetThread 查不到时现造一个会话，保证深链不白屏', () => {
    const existing = mockCreateThread('存在的').data;
    expect(mockGetThread(existing.thread_id).data.thread_id).toBe(existing.thread_id);
    expect(mockGetThread(existing.thread_id).data.messages).toEqual([]);

    const missing = mockGetThread('th_not_exist').data;
    expect(missing.thread_id).toMatch(/^th_mock_/);
    expect(missing.messages).toEqual([]);
  });

  it('mockListFiles 返回空数组（上传记录走产物接口）', () => {
    expect(mockListFiles().data).toEqual([]);
  });

  it('mockUploadFile：文本类文件统计字数，二进制不给 chars', async () => {
    const textual = new File(['一二三四五'], '素材.txt', { type: 'text/plain' });
    const pendingText = mockUploadFile('th_mock_001', textual);
    await vi.advanceTimersByTimeAsync(300);
    const textResult = await pendingText;
    expect(textResult.data).toMatchObject({ filename: '素材.txt', ext: 'txt', chars: 5 });

    const binary = new File(['PK'], '会议记录.docx');
    const pendingBinary = mockUploadFile('th_mock_001', binary);
    await vi.advanceTimersByTimeAsync(300);
    const binaryResult = await pendingBinary;
    expect(binaryResult.data.chars).toBeUndefined();
    expect(binaryResult.data.file_id).toMatch(/^art_upload_mock_/);
  });

  it('mockSubmitApproval：没有待审批项时抛 APPROVAL_ALREADY_DECIDED', () => {
    expect(() => mockSubmitApproval('th_mock_001', 'a_not_exist', 'approved')).toThrow(
      'APPROVAL_ALREADY_DECIDED',
    );
  });

  it('mockGetArtifact：查不到时给一份可预览的兜底产物', () => {
    const fallback = mockGetArtifact('art_unknown').data;
    expect(fallback.artifact_id).toBe('art_unknown');
    expect(fallback.preview_url).toContain('data:text/html');
  });

  it('mockGetAudit 没有跑过任务时 runs 为空', () => {
    const response = mockGetAudit('th_never_run');
    expect(response.data.thread_id).toBe('th_never_run');
    expect(response.data.runs).toEqual([]);
  });
});

/* ------------------------------------------------------------------ */
/* 事件脚本                                                            */
/* ------------------------------------------------------------------ */

describe('runMockStream', () => {
  it('一次跑到底：中途不停、终态 completed 并关流', async () => {
    const spy = await runScript('docx');
    const events = eventsOf(spy.frames);

    expect(spy.onOpen).toHaveBeenCalledTimes(1);
    expect(spy.onClose).toHaveBeenCalledTimes(1);
    expect(spy.onAbort).not.toHaveBeenCalled();
    expect(spy.onFailure).not.toHaveBeenCalled();

    for (const name of [
      'run.started',
      'thinking.delta',
      'thinking.completed',
      'message.delta',
      'message.completed',
      'plan.updated',
      'tool.finished',
      'artifact.ready',
      'run.completed',
    ]) {
      expect(events).toContain(name);
    }
    // 审批卡已经拿掉了：演示流里也不该再出现这个事件，否则前端会卡在一个
    // 没人能给出的决议上。
    expect(events).not.toContain('approval.required');

    const started = payload(spy.frames[0] as SseFrame);
    expect(started).toMatchObject({
      version: EVENT_VERSION,
      thread_id: 'th_mock_001',
      mode: 'mock',
    });

    const completed = payload(framesNamed(spy.frames, 'run.completed')[0] as SseFrame);
    expect(completed).toMatchObject({
      status: 'completed',
      artifact_ids: ['art_01'],
      approvals: [],
    });

    // 计划推了 4 次，最后一次全部完成
    const plans = framesNamed(spy.frames, 'plan.updated').map(payload);
    expect(plans).toHaveLength(4);
    expect(
      (plans.at(-1)?.todos as Array<{ status: string }>).every(
        (todo) => todo.status === 'completed',
      ),
    ).toBe(true);

    const tools = framesNamed(spy.frames, 'tool.finished').map(payload);
    expect(tools.map((tool) => tool.tool)).toEqual([
      'file.list',
      'file.read',
      'doc.generate_report',
    ]);
    expect(tools.at(-1)).toMatchObject({ ok: true, risk: 'high' });
    // 一轮只留一句决策行：不再有「开工前念方法论」和「生成后二次思考」那两段仪式
    const thinks = framesNamed(spy.frames, 'thinking.completed').map(payload);
    expect(thinks).toHaveLength(1);
    expect(thinks[0]).toMatchObject({ kind: 'decision' });
  });

  it('产物格式 → 事件类型与文件名跟着变', async () => {
    const cases: Array<[string, string]> = [
      ['pdf', 'pdf'],
      ['xlsx', 'xlsx'],
      ['txt', 'txt'],
    ];
    for (const [format, expectedType] of cases) {
      const spy = await runScript(format);
      const artifact = payload(framesNamed(spy.frames, 'artifact.ready')[0] as SseFrame);
      expect(artifact.type).toBe(expectedType);
      expect(artifact.filename).toBe(`周报_2026-W43.${format}`);
    }
  });

  it('非法 / 缺省格式回落 docx', async () => {
    for (const format of [undefined, 'zip']) {
      const spy = await runScript(format);
      const artifact = payload(framesNamed(spy.frames, 'artifact.ready')[0] as SseFrame);
      expect(artifact.type).toBe('docx');
      expect(artifact.filename).toBe('周报_2026-W43.docx');
    }
  });

  it('产物写入内存，产物详情与审计都能查到这一轮', async () => {
    const spy = await runScript('pdf');
    const artifact = mockGetArtifact('art_01').data;
    expect(artifact).toMatchObject({ type: 'pdf', filename: '周报_2026-W43.pdf' });

    const audit = mockGetAudit('th_mock_001').data;
    expect(audit.runs).toHaveLength(1);
    expect(audit.runs[0]).toMatchObject({ status: 'completed', approvals: [] });
    expect(spy.onClose).toHaveBeenCalled();
  });

  it('中途 abort：只回调 onAbort，不发终态事件', async () => {
    const spy = collector();
    const controller = new AbortController();
    const promise = runMockStream(
      { threadId: 'th_mock_002', message: '写周报', signal: controller.signal },
      {
        onFrame: (frame) => spy.frames.push(frame),
        onOpen: spy.onOpen,
        onClose: spy.onClose,
        onAbort: spy.onAbort,
      },
    );

    await vi.advanceTimersByTimeAsync(1200);
    controller.abort();
    await vi.advanceTimersByTimeAsync(1000);
    await promise;

    expect(spy.onAbort).toHaveBeenCalledTimes(1);
    expect(spy.onClose).not.toHaveBeenCalled();
    expect(eventsOf(spy.frames)).not.toContain('run.completed');
  });

  it('调用前已 abort：run.started 之后立刻停，不进入正文', async () => {
    const spy = collector();
    const controller = new AbortController();
    controller.abort();

    await runMockStream(
      { threadId: 'th_mock_003', message: '写周报', signal: controller.signal },
      {
        onFrame: (frame) => spy.frames.push(frame),
        onOpen: spy.onOpen,
        onAbort: spy.onAbort,
      },
    );

    // run.started 在第一次 sleep 之前发出，所以逃不掉；正文与思考一律不出现
    expect(eventsOf(spy.frames)).toEqual(['run.started']);
    expect(spy.onAbort).toHaveBeenCalledTimes(1);
  });

  it('生成中途 abort：按取消处理，不写终态', async () => {
    const spy = collector();
    const controller = new AbortController();
    const promise = runMockStream(
      { threadId: 'th_mock_004', message: '写周报', signal: controller.signal },
      {
        onFrame: (frame) => spy.frames.push(frame),
        onOpen: spy.onOpen,
        onClose: spy.onClose,
        onAbort: spy.onAbort,
      },
    );

    // 推到「正在生成」那一步（已过读取与提炼，还没发 artifact.ready）
    await vi.advanceTimersByTimeAsync(3000);
    expect(eventsOf(spy.frames)).toContain('tool.finished');
    expect(eventsOf(spy.frames)).not.toContain('run.completed');

    controller.abort();
    await vi.advanceTimersByTimeAsync(1000);
    await promise;

    expect(spy.onAbort).toHaveBeenCalledTimes(1);
    expect(spy.onClose).not.toHaveBeenCalled();
  });
});
