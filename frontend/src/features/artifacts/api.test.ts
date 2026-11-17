/**
 * 产物接口单测。
 *
 * 上传走的是 XHR（为了进度条），与其余接口的 fetch 路径不同，
 * 因此这里额外用 FakeXhr 覆盖：进度回调、成功解析、错误体映射、网络失败、abort。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MEDIA_UPLOAD_EXTENSIONS, mediaKindOf } from '../../shared/config/output-formats';

const state = vi.hoisted(() => ({ mockMode: false }));

vi.mock('../../shared/config/runtime', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/config/runtime')>();
  return { ...actual, isMockMode: () => state.mockMode };
});

/* ------------------------------------------------------------------ */
/* 假 XHR                                                              */
/* ------------------------------------------------------------------ */

interface ProgressEventLike {
  lengthComputable: boolean;
  loaded: number;
  total: number;
}

class FakeXhr {
  static instances: FakeXhr[] = [];

  status = 0;
  responseText = '';
  responseType = '';
  timeout = 0;
  method = '';
  url = '';
  body: unknown = null;
  aborted = false;
  upload: { onprogress: ((event: ProgressEventLike) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;

  constructor() {
    FakeXhr.instances.push(this);
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(): void {
    // 无需实现
  }

  send(body: unknown): void {
    this.body = body;
  }

  abort(): void {
    this.aborted = true;
  }
}

function lastXhr(): FakeXhr {
  const xhr = FakeXhr.instances[FakeXhr.instances.length - 1];
  if (!xhr) throw new Error('还没有创建任何 XMLHttpRequest');
  return xhr;
}

/* ------------------------------------------------------------------ */
/* 辅助                                                                */
/* ------------------------------------------------------------------ */

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function textResponse(status: number, text: string): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => text,
  } as unknown as Response;
}

async function freshArtifactsApi() {
  vi.resetModules();
  return (await import('./api')).artifactsApi;
}

function stubFetch(impl: () => Promise<Response>): void {
  vi.stubGlobal('fetch', vi.fn(impl));
}

function fetchMock(): ReturnType<typeof vi.fn> {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

function lastFetchUrl(): string {
  const mock = fetchMock();
  const call = mock.mock.calls[mock.mock.calls.length - 1] as [string] | undefined;
  if (!call) throw new Error('还没有发生任何 fetch 调用');
  return call[0];
}

function makeFile(name: string, content = 'hello'): File {
  return new File([content], name, { type: 'text/plain' });
}

beforeEach(() => {
  state.mockMode = false;
  FakeXhr.instances = [];
  vi.stubGlobal('XMLHttpRequest', FakeXhr as unknown as typeof XMLHttpRequest);
  stubFetch(async () => jsonResponse(200, {}));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

/* ------------------------------------------------------------------ */
/* 纯函数                                                              */
/* ------------------------------------------------------------------ */

describe('产物类型常量与映射', () => {
  it('文档扩展名与产物类型标签一一对应，媒体另有自己的标签', async () => {
    const { ACCEPTED_UPLOAD_EXTENSIONS, ARTIFACT_TYPE_LABELS, ARTIFACT_TYPES } =
      await import('./api');
    for (const ext of ACCEPTED_UPLOAD_EXTENSIONS) {
      // 图片 / 录音 / 视频不是产物类型，走 mediaKindOf 那条路（见 uploadTypeLabel 用例）
      if (mediaKindOf(`x${ext}`)) continue;
      expect(ARTIFACT_TYPE_LABELS[ext.replace('.', '')]).toBeTruthy();
    }
    // 媒体扩展名一个都不能漏在两张表之外：漏了拖进来就是「不支持的类型」
    for (const exts of Object.values(MEDIA_UPLOAD_EXTENSIONS)) {
      for (const ext of exts) expect(ACCEPTED_UPLOAD_EXTENSIONS).toContain(ext);
    }
    for (const type of ARTIFACT_TYPES) {
      expect(ARTIFACT_TYPE_LABELS[type]).toBeTruthy();
    }
  });

  it('artifactTypeTone 按类型分组着色', async () => {
    const { artifactTypeTone } = await import('./api');
    expect(artifactTypeTone('docx')).toBe('brand');
    expect(artifactTypeTone('html')).toBe('brand');
    expect(artifactTypeTone('xlsx')).toBe('ok');
    expect(artifactTypeTone('csv')).toBe('ok');
    expect(artifactTypeTone('pdf')).toBe('warn');
    expect(artifactTypeTone('pptx')).toBe('warn');
    expect(artifactTypeTone('md')).toBe('accent');
    expect(artifactTypeTone('txt')).toBe('neutral');
    expect(artifactTypeTone('未知类型')).toBe('neutral');
  });

  it('uploadTypeLabel 优先按扩展名，未知名回退大写扩展名', async () => {
    const { uploadTypeLabel } = await import('./api');
    expect(uploadTypeLabel('a.docx')).toBe('Word 文档');
    expect(uploadTypeLabel('a.pdf')).toBe('PDF');
    expect(uploadTypeLabel('a.csv')).toBe('CSV 表格');
    expect(uploadTypeLabel('a.pptx')).toBe('PPT 演示文稿');
    // 媒体报「是哪一类素材」而不是后缀：用户要知道它还要等识别
    expect(uploadTypeLabel('周会截图.png')).toBe('图片');
    expect(uploadTypeLabel('例会.mp4')).toBe('会议视频');
    expect(uploadTypeLabel('录音.m4a')).toBe('会议录音');
    expect(uploadTypeLabel('转写稿.srt')).toBe('会议记录');
    // 没登记的扩展名仍按大写展示，不至于只剩一个点
    expect(uploadTypeLabel('a.key')).toBe('KEY');
    // 无后缀时 split('.').pop() 拿到整个文件名，仍按大写扩展名展示
    expect(uploadTypeLabel('noext')).toBe('NOEXT');
    // 真正的空扩展名才回退「文件」
    expect(uploadTypeLabel('a.docx', '')).toBe('文件');
    // 显式传入 ext 时以 ext 为准
    expect(uploadTypeLabel('a.docx', 'PDF')).toBe('PDF');
  });

  it('MAX_UPLOAD_BYTES 与后端默认 20MB 一致', async () => {
    const { MAX_UPLOAD_BYTES } = await import('./api');
    expect(MAX_UPLOAD_BYTES).toBe(20 * 1024 * 1024);
  });
});

/* ------------------------------------------------------------------ */
/* mock 模式                                                           */
/* ------------------------------------------------------------------ */

describe('artifactsApi（mock 模式）', () => {
  beforeEach(() => {
    state.mockMode = true;
  });

  it('listArtifacts 返回内置演示产物', async () => {
    const api = await freshArtifactsApi();
    const result = await api.listArtifacts();
    expect(result.data.artifacts).toHaveLength(1);
    expect(result.data.page_size).toBe(20);
    expect(result.data.artifacts[0]).toMatchObject({
      artifact_id: 'art_01',
      has_text: true,
      has_preview_file: false,
    });
  });

  it('getArtifact 对未知 id 回退到内置产物', async () => {
    const api = await freshArtifactsApi();
    const result = await api.getArtifact('不存在的id');
    expect(result.data.artifact_id).toBeTruthy();
  });

  it('uploadFile 走 mock 通道，返回文件元信息', async () => {
    const api = await freshArtifactsApi();
    const result = await api.uploadFile('t1', makeFile('笔记.txt', '标题：周报'));
    expect(result.data).toMatchObject({ filename: '笔记.txt', type: 'txt', parsed: true });
    expect(result.data.chars ?? 0).toBeGreaterThan(0);
  });

  it('fetchPreviewText 在 mock 下返回文件名（截断到 limit）', async () => {
    const api = await freshArtifactsApi();
    const text = await api.fetchPreviewText('art_01', 4);
    expect(text).toBe('周报_2');
    // limit 足够大时返回完整文件名
    expect(await api.fetchPreviewText('art_01', 200)).toContain('.docx');
  });

  it('deleteArtifacts 在 mock 下直接返回全成功，不发请求', async () => {
    const api = await freshArtifactsApi();
    const result = await api.deleteArtifacts(['art_01', 'art_02']);
    expect(result.data).toEqual({ requested: 2, deleted: 2, failed: [], trashed: [] });
    expect(fetchMock().mock.calls.some((call) => String(call[0]).includes('batch-delete'))).toBe(
      false,
    );
  });
});

/* ------------------------------------------------------------------ */
/* 真实请求路径                                                        */
/* ------------------------------------------------------------------ */

describe('artifactsApi（真实请求）', () => {
  it('listArtifacts 总是带上分页参数，并拼装过滤条件', async () => {
    const api = await freshArtifactsApi();
    await api.listArtifacts({ threadId: 't1', runId: 'r1', type: 'docx', page: 2, pageSize: 5 });
    const params = new URLSearchParams(lastFetchUrl().split('?')[1]);
    expect(params.get('thread_id')).toBe('t1');
    expect(params.get('run_id')).toBe('r1');
    expect(params.get('type')).toBe('docx');
    expect(params.get('page')).toBe('2');
    expect(params.get('page_size')).toBe('5');
  });

  it('listArtifacts 无参数时用默认 page=1 / page_size=20', async () => {
    const api = await freshArtifactsApi();
    await api.listArtifacts();
    const params = new URLSearchParams(lastFetchUrl().split('?')[1]);
    expect(params.get('page')).toBe('1');
    expect(params.get('page_size')).toBe('20');
  });

  it('getArtifact / deleteArtifact 对 id 编码', async () => {
    const api = await freshArtifactsApi();
    await api.getArtifact('a b');
    expect(lastFetchUrl()).toBe('/api/v1/artifacts/a%20b');
    await api.deleteArtifact('a/b');
    expect(lastFetchUrl()).toBe('/api/v1/artifacts/a%2Fb');
    expect((fetchMock().mock.calls.at(-1) as [unknown, { method: string }])[1].method).toBe(
      'DELETE',
    );
  });

  it('下载 / 预览地址带 v1 前缀并编码 id', async () => {
    const api = await freshArtifactsApi();
    expect(api.artifactDownloadUrl('a b')).toBe('/api/v1/artifacts/a%20b/download');
    expect(api.artifactPreviewUrl('a/b')).toBe('/api/v1/artifacts/a%2Fb/preview');
  });

  it('deleteArtifacts 走批量接口，POST id 数组', async () => {
    const api = await freshArtifactsApi();
    stubFetch(async () =>
      jsonResponse(200, { trace_id: 'tr_1', requested: 2, deleted: 2, failed: [], trashed: [] }),
    );

    const result = await api.deleteArtifacts(['a1', 'a2']);

    expect(lastFetchUrl()).toBe('/api/v1/artifacts/batch-delete');
    const [, init] = fetchMock().mock.calls.at(-1) as [string, RequestInit];
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ artifact_ids: ['a1', 'a2'] });
    expect(result.data.deleted).toBe(2);
    expect(result.traceId).toBe('tr_1');
  });

  it('fetchPreviewText 从 <pre> 中提取文本并反转义', async () => {
    const api = await freshArtifactsApi();
    stubFetch(async () =>
      textResponse(200, '<html><pre>摘要 &amp; 要点 &lt;标签&gt;</pre></html>'),
    );
    expect(await api.fetchPreviewText('a1')).toBe('摘要 & 要点 <标签>');
  });

  it('fetchPreviewText 无 <pre> 时剥掉标签再取文本', async () => {
    const api = await freshArtifactsApi();
    stubFetch(async () => textResponse(200, '<div><p>第一段</p><p>第二段</p></div>'));
    expect(await api.fetchPreviewText('a1', 3)).toBe('第一段');
  });

  it('fetchPreviewText 失败时抛出带状态码的错误', async () => {
    const api = await freshArtifactsApi();
    stubFetch(async () => textResponse(404, 'not found'));
    await expect(api.fetchPreviewText('a1')).rejects.toThrow('预览不可用（HTTP 404）');
  });
});

describe('artifactsApi.uploadFile（XHR 路径）', () => {
  it('以 POST 提交 FormData，并对 id 编码', async () => {
    const api = await freshArtifactsApi();
    const promise = api.uploadFile('t 1', makeFile('a.txt'));
    const xhr = lastXhr();
    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe('/api/v1/threads/t%201/files');
    expect(xhr.body).toBeInstanceOf(FormData);
    expect(xhr.timeout).toBe(120_000);
    xhr.status = 200;
    xhr.responseText = JSON.stringify({ file_id: 'f1', trace_id: 't-1' });
    xhr.onload?.();
    await expect(promise).resolves.toEqual({
      data: { file_id: 'f1', trace_id: 't-1' },
      traceId: 't-1',
    });
  });

  it('lengthComputable 时回调上传进度（四舍五入到整数）', async () => {
    const api = await freshArtifactsApi();
    const onProgress = vi.fn();
    const promise = api.uploadFile('t1', makeFile('a.txt'), { onProgress });
    const xhr = lastXhr();
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 3 });
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 1, total: 3 });
    expect(onProgress).toHaveBeenCalledTimes(1);
    expect(onProgress).toHaveBeenCalledWith(33);
    xhr.status = 200;
    xhr.responseText = '{}';
    xhr.onload?.();
    await promise;
  });

  it('响应缺少 trace_id 时 traceId 为 null', async () => {
    const api = await freshArtifactsApi();
    const promise = api.uploadFile('t1', makeFile('a.txt'));
    const xhr = lastXhr();
    xhr.status = 201;
    xhr.responseText = JSON.stringify({ file_id: 'f1' });
    xhr.onload?.();
    await expect(promise).resolves.toEqual({ data: { file_id: 'f1' }, traceId: null });
  });

  it('响应体非 JSON 时不抛错，data 为 null', async () => {
    const api = await freshArtifactsApi();
    const promise = api.uploadFile('t1', makeFile('a.txt'));
    const xhr = lastXhr();
    xhr.status = 200;
    xhr.responseText = 'not-json';
    xhr.onload?.();
    await expect(promise).resolves.toEqual({ data: null, traceId: null });
  });

  it('HTTP 错误时用后端 error.message，并附上 code / status / traceId', async () => {
    const api = await freshArtifactsApi();
    const promise = api.uploadFile('t1', makeFile('a.txt'));
    const xhr = lastXhr();
    xhr.status = 413;
    xhr.responseText = JSON.stringify({
      trace_id: 't-9',
      error: { code: 'FILE_TOO_LARGE', message: '文件超过 20MB 上限' },
    });
    xhr.onload?.();
    await expect(promise).rejects.toMatchObject({
      message: '文件超过 20MB 上限',
      code: 'FILE_TOO_LARGE',
      status: 413,
      traceId: 't-9',
    });
  });

  it('HTTP 错误且无错误体时用状态码兜底文案', async () => {
    const api = await freshArtifactsApi();
    const promise = api.uploadFile('t1', makeFile('a.txt'));
    const xhr = lastXhr();
    xhr.status = 500;
    xhr.responseText = '';
    xhr.onload?.();
    await expect(promise).rejects.toMatchObject({
      message: '上传失败（HTTP 500）',
      code: 'HTTP_500',
      status: 500,
    });
  });

  it('网络失败与超时分别给出不同提示', async () => {
    const api = await freshArtifactsApi();
    const failed = api.uploadFile('t1', makeFile('a.txt'));
    lastXhr().onerror?.();
    await expect(failed).rejects.toThrow('无法连接后端');

    const timedOut = api.uploadFile('t1', makeFile('a.txt'));
    lastXhr().ontimeout?.();
    await expect(timedOut).rejects.toThrow('上传超时');
  });

  it('调用方 abort 时中断 XHR', async () => {
    const api = await freshArtifactsApi();
    const controller = new AbortController();
    void api.uploadFile('t1', makeFile('a.txt'), { signal: controller.signal });
    expect(lastXhr().aborted).toBe(false);
    controller.abort();
    expect(lastXhr().aborted).toBe(true);
  });
});
