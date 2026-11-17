/**
 * 产物下载工具单测。
 *
 * 这条链路的失败方式很隐蔽：文件「第一次能下、第二次点了没反应」。
 * 原因是老实现直接 `window.open(url)`——浏览器把它当弹窗，连续点几次就被拦掉，
 * 用户除了「没反应」什么也看不到。所以这里锁住三件事：
 *   1. 每点一次都要重新取一份 blob（不复用上一次的 objectURL）；
 *   2. 每次都真的点一次 a[download]，文件名跟着走；
 *   3. objectURL 用完要回收，临时节点不能留在 DOM 里。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { saveRemoteFile } from './download';

const URL_PATH = '/api/v1/artifacts/art_1/download';

function stubFetch() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    blob: async () => new Blob(['docx-bytes']),
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function stubObjectUrl() {
  let seq = 0;
  const createObjectURL = vi.fn(() => {
    seq += 1;
    return `blob:fake-${seq}`;
  });
  const revokeObjectURL = vi.fn();
  vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
  return { createObjectURL, revokeObjectURL };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('saveRemoteFile', () => {
  it('每次调用都重新取一份文件、点一次 a[download]，文件名跟着走', async () => {
    const fetchMock = stubFetch();
    const { createObjectURL } = stubObjectUrl();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    await saveRemoteFile(URL_PATH, '周报.docx');
    await saveRemoteFile(URL_PATH, '周报.docx');
    await saveRemoteFile(URL_PATH, '周报.docx');

    // 三次点击 = 三次请求 + 三次点击 + 三个新地址（不复用上一次已回收的那个）
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(click).toHaveBeenCalledTimes(3);
    expect(createObjectURL).toHaveBeenCalledTimes(3);
    expect(new Set(createObjectURL.mock.results.map((r) => r.value)).size).toBe(3);
  });

  it('请求带 no-store：同一地址重复下载不能吃缓存', async () => {
    const fetchMock = stubFetch();
    stubObjectUrl();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    await saveRemoteFile(URL_PATH, '周报.docx');

    expect(fetchMock).toHaveBeenCalledWith(
      URL_PATH,
      expect.objectContaining({ cache: 'no-store' }),
    );
  });

  it('文件名写进 download 属性，点完把临时节点清掉', async () => {
    stubFetch();
    stubObjectUrl();
    let downloaded = '';
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloaded = this.download;
    });

    await saveRemoteFile(URL_PATH, '24级软件工程_工作周报_2026-W44.docx');

    expect(downloaded).toBe('24级软件工程_工作周报_2026-W44.docx');
    // 每下完一次都留一个 a 节点的话，点十次页面里就躺着十个
    expect(document.querySelector('a[download]')).toBeNull();
  });

  it('objectURL 一秒后回收，不把整份文件长期挂在内存里', async () => {
    stubFetch();
    const { revokeObjectURL } = stubObjectUrl();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.useFakeTimers();

    await saveRemoteFile(URL_PATH, '周报.docx');
    // 立刻回收在部分浏览器里会下到空文件，所以必须等一会儿
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake-1');
  });

  it('服务端报错时抛出来，不要假装下载成功', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 404, blob: async () => new Blob([]) }),
    );
    const { createObjectURL } = stubObjectUrl();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    await expect(saveRemoteFile(URL_PATH, '周报.docx')).rejects.toThrow('下载失败（HTTP 404）');
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
  });
});
