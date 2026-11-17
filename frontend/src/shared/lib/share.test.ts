/**
 * 会话导出工具单测。
 *
 * 重点不在字符串长什么样，而在两条容易静默失败的路：
 *   - 剪贴板：https 之外没有 clipboard API，必须退回 execCommand（否则「点了没反应」）
 *   - 下载：Blob + a[download] 的链路必须真的触发点击，否则用户拿到空文件
 *
 * 曾经的 threadLink / shareText 已随假分享渠道一起删掉：应用里没有 /threads/:id 路由，
 * 链接发出去对方只会落到首页。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildThreadMarkdown, copyText, downloadTextFile, safeFilename } from './share';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('buildThreadMarkdown', () => {
  it('带上时间、消息数、产物数', () => {
    const md = buildThreadMarkdown({
      title: '周报',
      updatedAt: '10/26 15:11',
      messageCount: 3,
      artifactCount: 1,
    });
    expect(md).toContain('# 周报');
    expect(md).toContain('最近更新：10/26 15:11');
    expect(md).toContain('消息数：3');
    expect(md).toContain('产物数：1');
  });

  it('没有产物时不写产物行', () => {
    const md = buildThreadMarkdown({ title: 't', artifactCount: 0 });
    expect(md).not.toContain('产物数');
  });

  it('空标题兜底，不再写死链', () => {
    const md = buildThreadMarkdown({ title: '' });
    expect(md).toContain('# 未命名会话');
    expect(md).not.toContain('/threads/');
  });
});

describe('safeFilename', () => {
  it('去掉文件名里不能出现的字符', () => {
    expect(safeFilename('a/b:c*d?"e"<f>|g')).toBe('a-b-c-d-e-f-g');
  });

  it('全是非法字符/空白时给兜底名', () => {
    expect(safeFilename('   ')).toBe('会话');
  });
});

describe('copyText', () => {
  it('优先用 clipboard API', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    await expect(copyText('hi')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('hi');
  });

  it('clipboard 被拒时退回 execCommand，仍算成功', async () => {
    vi.stubGlobal('navigator', {
      ...navigator,
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    });
    const exec = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true });

    await expect(copyText('hi')).resolves.toBe(true);
    expect(exec).toHaveBeenCalledWith('copy');
    // 临时 textarea 不能留在 DOM 里
    expect(document.querySelector('textarea')).toBeNull();
  });

  it('两条路都失败时返回 false', async () => {
    vi.stubGlobal('navigator', {
      ...navigator,
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    });
    Object.defineProperty(document, 'execCommand', {
      value: vi.fn().mockReturnValue(false),
      configurable: true,
    });
    await expect(copyText('hi')).resolves.toBe(false);
  });
});

describe('downloadTextFile', () => {
  it('创建 Blob 链接并真的点一次 a[download]', () => {
    const createObjectURL = vi.fn().mockReturnValue('blob:fake');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    downloadTextFile('周报.md', '# 周报');

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    // 下载完成后要清掉临时节点，否则每导一次多一个 a
    expect(document.querySelector('a[download]')).toBeNull();
  });
});
