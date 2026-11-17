/**
 * 对话里的交付区（ArtifactDelivery）。
 *
 * 守护的产品约束：
 * 1. 一轮跑完后，产物直接摆在对话里，且像一份「附件清单」：类型图块、
 *    文件名（带扩展名）、大小、预览与下载都在一行里；
 * 2. 对话里只铺**最新一份**，其余（哪怕同一轮出的）一律进「更早的产物」折叠区：
 *    翻旧会话时历史产物不能铺满一屏，同轮出两张 PDF 时也不能一起铺；
 * 3. 折叠区默认收起（一行「更早的产物 · N 个」），点一下展开成可滚动的小盒子。
 *
 * 下载是颗按钮而不是 `<a href download>`：同一份文件点第二次会不会落盘，
 * 各家浏览器策略不同（老实现用 window.open，第二次直接被当弹窗拦掉）。
 * 现在每点一次都重新取一份文件，所以「连点两次」必须是「下载两次」。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ArtifactDelivery } from './ArtifactDelivery';
import type { ArtifactItem } from '../../../shared/types/view';

function makeArtifact(overrides: Partial<ArtifactItem> = {}): ArtifactItem {
  return {
    artifact_id: 'ar_1',
    type: 'docx',
    filename: '24级软件工程_文件摘要_2026-10-27.docx',
    size: 2048,
    download_url: '/api/v1/artifacts/ar_1/download',
    preview_url: '/api/v1/artifacts/ar_1/preview',
    created_at: '2026-10-27T08:55:00Z',
    run_id: 'r_old',
    meta_status: 'idle',
    meta_error: null,
    meta: null,
    ...overrides,
  };
}

function stubDownload() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    blob: async () => new Blob(['bytes']),
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:fake'),
    revokeObjectURL: vi.fn(),
  });
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  return { fetchMock, click };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('ArtifactDelivery 版式与折叠', () => {
  it('没有产物时整块不渲染', () => {
    const { container } = render(<ArtifactDelivery artifacts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('产物像附件一样列出：文件名带扩展名、大小、预览与下载', () => {
    render(<ArtifactDelivery artifacts={[makeArtifact()]} />);

    expect(screen.getByLabelText('本次产物')).toBeTruthy();
    expect(screen.getByText('产物')).toBeTruthy();
    expect(screen.getByText('24级软件工程_文件摘要_2026-10-27.docx')).toBeTruthy();
    expect(screen.getByText('2.0 KB')).toBeTruthy();
    expect(screen.getByRole('button', { name: /下载/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /预览/ })).toBeTruthy();
    // 三个操作都收在一条悬浮操作条里（角色是 toolbar），而不是散在行尾
    expect(screen.getByRole('toolbar', { name: /的操作/ })).toBeTruthy();
  });

  it('产物数大于 1 就折叠：只铺最新的那份，其余进「更早的产物」', () => {
    render(
      <ArtifactDelivery
        artifacts={[
          makeArtifact({ artifact_id: 'ar_old', run_id: 'r_old' }),
          makeArtifact({
            artifact_id: 'ar_new',
            filename: '秋景速查材料.docx',
            run_id: 'r_new',
          }),
        ]}
      />,
    );

    expect(screen.getByText('秋景速查材料.docx')).toBeTruthy();
    expect(screen.queryByText('24级软件工程_文件摘要_2026-10-27.docx')).toBeNull();

    // 折叠行只说「更早的产物 1 个」，默认收起
    const fold = screen.getByRole('button', { name: /更早的产物/ });
    expect(fold).toHaveAttribute('aria-expanded', 'false');
    expect(fold).toHaveTextContent('1 个');

    fireEvent.click(fold);
    expect(fold).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('24级软件工程_文件摘要_2026-10-27.docx')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /下载/ })).toHaveLength(2);

    // 再点一次收起：历史产物不该长期占着一屏
    fireEvent.click(fold);
    expect(screen.queryByText('24级软件工程_文件摘要_2026-10-27.docx')).toBeNull();
  });

  it('同一轮里出两份 PDF 也只铺最后一份，另一份进折叠区', () => {
    render(
      <ArtifactDelivery
        artifacts={[
          makeArtifact({ artifact_id: 'ar_a', filename: '实验报告.pdf', run_id: 'r_now' }),
          makeArtifact({ artifact_id: 'ar_b', filename: '工作周报_2026-W45.pdf', run_id: 'r_now' }),
        ]}
      />,
    );

    // 两张都是同一轮出的：以前会一起铺开（这就是用户看到的那个 bug）
    expect(screen.getByText('工作周报_2026-W45.pdf')).toBeTruthy();
    expect(screen.queryByText('实验报告.pdf')).toBeNull();
    expect(screen.getByRole('button', { name: /更早的产物/ })).toHaveTextContent('1 个');
  });

  it('出 7 份也只铺最新一份，其余 6 份全在折叠区里', () => {
    const many = Array.from({ length: 7 }, (_, index) =>
      makeArtifact({
        artifact_id: `ar_${index}`,
        filename: `第${index + 1}份.docx`,
        run_id: 'r_now',
      }),
    );
    render(<ArtifactDelivery artifacts={many} />);

    // 只有最新生成的那份是平铺的
    expect(screen.getByText('第7份.docx')).toBeTruthy();
    expect(screen.queryByText('第6份.docx')).toBeNull();
    expect(screen.queryByText('第1份.docx')).toBeNull();

    const fold = screen.getByRole('button', { name: /更早的产物/ });
    expect(fold).toHaveTextContent('6 个');

    fireEvent.click(fold);
    expect(screen.getByText('第1份.docx')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /下载/ })).toHaveLength(7);
  });

  it('新的一轮产出之后，上一轮自动归入折叠区（刷新页面也一样）', () => {
    const { rerender } = render(<ArtifactDelivery artifacts={[makeArtifact({ run_id: 'r_1' })]} />);
    expect(screen.getByText('24级软件工程_文件摘要_2026-10-27.docx')).toBeTruthy();

    rerender(
      <ArtifactDelivery
        artifacts={[
          makeArtifact({ artifact_id: 'ar_1', run_id: 'r_1' }),
          makeArtifact({ artifact_id: 'ar_2', filename: '第二轮.docx', run_id: 'r_2' }),
        ]}
      />,
    );

    expect(screen.getByText('第二轮.docx')).toBeTruthy();
    expect(screen.queryByText('24级软件工程_文件摘要_2026-10-27.docx')).toBeNull();
  });
});

describe('ArtifactDelivery 下载', () => {
  it('同一份文件连点两次，就要下两次', async () => {
    const { fetchMock, click } = stubDownload();
    render(<ArtifactDelivery artifacts={[makeArtifact()]} />);

    const button = screen.getByRole('button', { name: /下载/ });
    fireEvent.click(button);
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(button).toBeEnabled());

    fireEvent.click(button);
    await waitFor(() => expect(click).toHaveBeenCalledTimes(2));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/artifacts/ar_1/download',
      expect.objectContaining({ cache: 'no-store' }),
    );
  });

  it('下载失败时说明原因，按钮回到可点状态（不能一次失败就卡死）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500, blob: async () => new Blob([]) }),
    );
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(), revokeObjectURL: vi.fn() });
    render(<ArtifactDelivery artifacts={[makeArtifact()]} />);

    const button = screen.getByRole('button', { name: /下载/ });
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeEnabled());
    expect(button).toHaveAccessibleName('下载');
  });
});

describe('ArtifactDelivery 添加到对话框', () => {
  it('把整份产物交给工作台，成功后图标变成勾（有反馈才敢连点）', async () => {
    const handed: ArtifactItem[] = [];
    const onAdd = vi.fn(async (item: ArtifactItem) => {
      handed.push(item);
      return true;
    });
    render(<ArtifactDelivery artifacts={[makeArtifact()]} onAddToChat={onAdd} />);

    fireEvent.click(screen.getByRole('button', { name: '添加到对话框' }));

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(handed[0]?.artifact_id).toBe('ar_1');
    expect(await screen.findByRole('button', { name: '已加入对话框' })).toBeTruthy();
  });

  it('没接回调时不给这颗按钮：点了没反应的入口比没有更糟', () => {
    render(<ArtifactDelivery artifacts={[makeArtifact()]} />);
    expect(screen.queryByRole('button', { name: '添加到对话框' })).toBeNull();
  });

  it('工作台报失败时保持原样，不假装成功', async () => {
    const onAdd = vi.fn(async () => false);
    render(<ArtifactDelivery artifacts={[makeArtifact()]} onAddToChat={onAdd} />);

    fireEvent.click(screen.getByRole('button', { name: '添加到对话框' }));

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: '添加到对话框' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '已加入对话框' })).toBeNull();
  });
});
