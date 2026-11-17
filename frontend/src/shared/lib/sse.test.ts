/**
 * SSE 帧解析（shared/lib/sse.ts）单元测试。
 *
 * 这是前后端契约的解析入口，出错会直接表现为「对话流不更新」，
 * 且全是纯函数，最适合做高密度覆盖（LF/CRLF、多行 data、注释心跳、未知字段）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseSseFrame, resumeRunEvents, streamRun, type SseFrame } from './sse';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('parseSseFrame', () => {
  it('解析 id / event / data 三字段', () => {
    const frame = parseSseFrame('id: 12\nevent: run.started\ndata: {"a":1}');
    expect(frame).toEqual({ id: '12', event: 'run.started', data: '{"a":1}' });
  });

  it('缺省 event 时回退为 message', () => {
    const frame = parseSseFrame('data: hello');
    expect(frame?.event).toBe('message');
    expect(frame?.data).toBe('hello');
  });

  it('缺省 id 时为 null', () => {
    expect(parseSseFrame('event: ping\ndata: {}')?.id).toBeNull();
  });

  it('支持多行 data 拼接为换行文本', () => {
    const frame = parseSseFrame('event: text\ndata: line1\ndata: line2\ndata: line3');
    expect(frame?.data).toBe('line1\nline2\nline3');
  });

  it('忽略注释行（心跳）与空行', () => {
    const frame = parseSseFrame(': keep-alive\n\ndata: payload');
    expect(frame?.data).toBe('payload');
  });

  it('兼容 CRLF 换行', () => {
    const frame = parseSseFrame('id: 3\r\nevent: run.completed\r\ndata: {"ok":true}');
    expect(frame).toEqual({ id: '3', event: 'run.completed', data: '{"ok":true}' });
  });

  it('data 后仅一个空格才被剥离（保留正文前导空格语义）', () => {
    expect(parseSseFrame('data:  two-spaces')?.data).toBe(' two-spaces');
  });

  it('字段冒号后的空值也算有效字段', () => {
    expect(parseSseFrame('id:\ndata: x')?.id).toBe('');
  });

  it('忽略 retry 等未知字段', () => {
    const frame = parseSseFrame('retry: 3000\nevent: tick\ndata: 1');
    expect(frame?.event).toBe('tick');
    expect(frame?.data).toBe('1');
  });

  it('没有 data 行时返回 null（无法构造事件）', () => {
    expect(parseSseFrame('event: run.started\nid: 1')).toBeNull();
    expect(parseSseFrame('')).toBeNull();
    expect(parseSseFrame(': only comment')).toBeNull();
  });

  it('data 为非法 JSON 时仍原样返回（交给上层处理）', () => {
    expect(parseSseFrame('data: {broken')?.data).toBe('{broken');
  });

  it('无冒号的 data 等价于空 data 行（SSE 规范）', () => {
    const frame = parseSseFrame('data');
    expect(frame).not.toBeNull();
    expect(frame?.data).toBe('');
  });

  it('UTF-8 中文内容不被破坏', () => {
    const frame = parseSseFrame('event: text.delta\ndata: {"text":"周报生成中"}');
    expect(frame).not.toBeNull();
    expect(JSON.parse(frame?.data ?? '{}').text).toBe('周报生成中');
  });
});

/* ------------------------------------------------------------------ */
/* 流式连接（streamRun / resumeRunEvents）                              */
/* ------------------------------------------------------------------ */

/** 构造 SSE 响应：chunks 会按数组顺序依次投递，模拟网络分片。 */
function sseResponse(
  chunks: string[],
  options: { contentType?: string; body?: unknown } = {},
): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return {
    ok: true,
    status: 200,
    headers: { get: () => options.contentType ?? 'text/event-stream' },
    text: async () => JSON.stringify(options.body ?? {}),
    body: options.body === undefined ? stream : null,
  } as unknown as Response;
}

function errorResponse(status: number, body: string, contentType = 'application/json'): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => contentType },
    text: async () => body,
    body: null,
  } as unknown as Response;
}

function frame(id: string, event: string, data: string): string {
  return `id: ${id}\nevent: ${event}\ndata: ${data}\n\n`;
}

describe('streamRun 正常流', () => {
  it('按序投递帧，终态事件后关流并触发 onClose', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          frame('1', 'run.started', '{"run_id":"r1"}'),
          frame('2', 'message.delta', '{"delta":"你好"}'),
          frame('3', 'run.completed', '{"status":"completed"}'),
        ]),
      ),
    );
    const events: string[] = [];
    const onOpen = vi.fn();
    const onClose = vi.fn();
    await streamRun(
      { threadId: 't1', message: '写周报' },
      {
        onFrame: (f) => events.push(f.event),
        onOpen,
        onClose,
      },
    );
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(events).toEqual(['run.started', 'message.delta', 'run.completed']);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('未知事件照常投递（由上层忽略）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([frame('1', 'something.new', '{"x":1}'), frame('2', 'run.completed', '{}')]),
      ),
    );
    const events: string[] = [];
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: (f) => events.push(f.event) });
    expect(events).toContain('something.new');
  });

  it('跨 chunk 的半包帧会被缓冲后再拼出（网络分片场景）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          'id: 1\nevent: run.star',
          'ted\ndata: {"run_',
          'id":"r1"}\n\n',
          frame('2', 'run.completed', '{}'),
        ]),
      ),
    );
    const frames: SseFrame[] = [];
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: (f) => frames.push(f) });
    expect(frames[0]).toEqual({ id: '1', event: 'run.started', data: '{"run_id":"r1"}' });
    expect(frames).toHaveLength(2);
  });

  it('CRLF 分隔的帧也能正确切分', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          'id: 1\r\nevent: run.started\r\ndata: {"run_id":"r1"}\r\n\r\n',
          'id: 2\r\nevent: run.completed\r\ndata: {}\r\n\r\n',
        ]),
      ),
    );
    const events: string[] = [];
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: (f) => events.push(f.event) });
    expect(events).toEqual(['run.started', 'run.completed']);
  });

  it('无 data 的坏帧被忽略，不中断后续帧', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse(['id: 1\nevent: heartbeat\n\n', frame('2', 'run.completed', '{}')]),
      ),
    );
    const events: string[] = [];
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: (f) => events.push(f.event) });
    expect(events).toEqual(['run.completed']);
  });

  it('服务端关流（无终态事件）也触发 onClose', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([frame('1', 'message.delta', '{"delta":"a"}')])),
    );
    const onClose = vi.fn();
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: () => undefined, onClose });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('请求体含 message / mode / output_format，并对 threadId 编码', async () => {
    const fetchMock = vi.fn(async () => sseResponse([frame('1', 'run.completed', '{}')]));
    vi.stubGlobal('fetch', fetchMock);
    await streamRun(
      { threadId: 't 1/2', message: '写周报', mode: 'mock', outputFormat: 'pdf' },
      { onFrame: () => undefined },
    );
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/threads/t%201%2F2/runs/stream');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      message: '写周报',
      mode: 'mock',
      output_format: 'pdf',
    });
    expect((init.headers as Record<string, string>).Accept).toBe('text/event-stream');
  });

  it('省略 mode / outputFormat 时不发送这两个字段', async () => {
    const fetchMock = vi.fn(async () => sseResponse([frame('1', 'run.completed', '{}')]));
    vi.stubGlobal('fetch', fetchMock);
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: () => undefined });
    expect(
      JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string),
    ).toEqual({
      message: 'x',
    });
  });
});

describe('streamRun 失败路径', () => {
  it('HTTP 非 2xx + 标准错误体 → onFailure（带 code/status/traceId）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        errorResponse(
          400,
          JSON.stringify({
            trace_id: 't-9',
            error: { code: 'INVALID_ARGUMENT', message: '消息为空' },
          }),
        ),
      ),
    );
    const onFailure = vi.fn();
    await streamRun({ threadId: 't1', message: '' }, { onFrame: () => undefined, onFailure });
    expect(onFailure).toHaveBeenCalledWith({
      code: 'INVALID_ARGUMENT',
      message: '消息为空',
      retryable: false,
      traceId: 't-9',
      status: 400,
    });
  });

  it('422 + detail 数组 → 提示「请求参数有误」', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse(422, JSON.stringify({ detail: [{ loc: ['body'] }] }))),
    );
    const onFailure = vi.fn();
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: () => undefined, onFailure });
    expect(onFailure.mock.calls[0]?.[0]).toMatchObject({
      code: 'HTTP_422',
      message: '请求参数有误',
    });
  });

  it('detail 为字符串时直接作为消息', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse(403, JSON.stringify({ detail: '没有权限' }))),
    );
    const onFailure = vi.fn();
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: () => undefined, onFailure });
    expect(onFailure.mock.calls[0]?.[0]).toMatchObject({ message: '没有权限', status: 403 });
  });

  it('5xx / 429 标记为可重试', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse(503, '')),
    );
    const onFailure = vi.fn();
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: () => undefined, onFailure });
    expect(onFailure.mock.calls[0]?.[0]).toMatchObject({
      code: 'HTTP_503',
      message: '请求失败（HTTP 503）',
      retryable: true,
    });
  });

  it('2xx 但返回 JSON（代理把 SSE 吞了）→ 视为失败且可重试', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse(200, JSON.stringify({ detail: 'nginx 缓冲了响应' }))),
    );
    const onFailure = vi.fn();
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: () => undefined, onFailure });
    expect(onFailure.mock.calls[0]?.[0]).toMatchObject({
      message: 'nginx 缓冲了响应',
      retryable: true,
      status: 200,
    });
  });

  it('响应无 body → STREAM_UNAVAILABLE', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([], { body: {} })),
    );
    const onFailure = vi.fn();
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: () => undefined, onFailure });
    expect(onFailure).toHaveBeenCalledWith({
      code: 'STREAM_UNAVAILABLE',
      message: '当前浏览器不支持流式响应',
      retryable: false,
      traceId: null,
    });
  });

  it('网络异常 → NETWORK_ERROR（提示检查代理）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const onFailure = vi.fn();
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: () => undefined, onFailure });
    expect(onFailure.mock.calls[0]?.[0]).toMatchObject({
      code: 'NETWORK_ERROR',
      retryable: true,
      message: '无法连接后端（/api 代理未通或服务未启动）',
    });
  });

  it('非 TypeError 异常透出其 message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('代理配置错误');
      }),
    );
    const onFailure = vi.fn();
    await streamRun({ threadId: 't1', message: 'x' }, { onFrame: () => undefined, onFailure });
    expect(onFailure.mock.calls[0]?.[0]).toMatchObject({ message: '代理配置错误' });
  });

  it('调用前已 abort → 直接 onAbort，不发请求', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    controller.abort();
    const onAbort = vi.fn();
    await streamRun(
      { threadId: 't1', message: 'x', signal: controller.signal },
      { onFrame: () => undefined, onAbort },
    );
    expect(onAbort).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('流途中 abort → onAbort，且不触发 onFailure', async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            );
          }),
      ),
    );
    const onAbort = vi.fn();
    const onFailure = vi.fn();
    const promise = streamRun(
      { threadId: 't1', message: 'x', signal: controller.signal },
      { onFrame: () => undefined, onAbort, onFailure },
    );
    controller.abort();
    await promise;
    expect(onAbort).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();
  });
});

describe('resumeRunEvents 断线续传', () => {
  it('携带 Last-Event-ID 续传，并按终态事件关流', async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse([
        frame('5', 'message.delta', '{"delta":"续"}'),
        frame('6', 'run.completed', '{}'),
      ]),
    );
    vi.stubGlobal('fetch', fetchMock);
    const events: string[] = [];
    await resumeRunEvents(
      { runId: 'r 1', lastEventId: '4' },
      { onFrame: (f) => events.push(f.event) },
    );
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/runs/r%201/events/stream');
    expect(init.method).toBe('GET');
    expect((init.headers as Record<string, string>)['Last-Event-ID']).toBe('4');
    expect(events).toEqual(['message.delta', 'run.completed']);
  });

  it('无 lastEventId 时不发送 Last-Event-ID 头', async () => {
    const fetchMock = vi.fn(async () => sseResponse([frame('1', 'run.completed', '{}')]));
    vi.stubGlobal('fetch', fetchMock);
    await resumeRunEvents({ runId: 'r1', lastEventId: null }, { onFrame: () => undefined });
    const headers = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1]
      .headers as Record<string, string>;
    expect(headers['Last-Event-ID']).toBeUndefined();
    expect(headers.Accept).toBe('text/event-stream');
  });

  it('后端未实现（404）→ onFailure（上层据此降级）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse(404, '')),
    );
    const onFailure = vi.fn();
    await resumeRunEvents(
      { runId: 'r1', lastEventId: null },
      { onFrame: () => undefined, onFailure },
    );
    expect(onFailure.mock.calls[0]?.[0]).toMatchObject({ code: 'HTTP_404', status: 404 });
  });

  it('resume 期间 abort → onAbort', async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            );
          }),
      ),
    );
    const onAbort = vi.fn();
    const promise = resumeRunEvents(
      { runId: 'r1', lastEventId: '1', signal: controller.signal },
      { onFrame: () => undefined, onAbort },
    );
    controller.abort();
    await promise;
    expect(onAbort).toHaveBeenCalledTimes(1);
  });

  it('网络异常 → NETWORK_ERROR', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const onFailure = vi.fn();
    await resumeRunEvents(
      { runId: 'r1', lastEventId: null },
      { onFrame: () => undefined, onFailure },
    );
    expect(onFailure.mock.calls[0]?.[0]).toMatchObject({ code: 'NETWORK_ERROR', retryable: true });
  });
});
