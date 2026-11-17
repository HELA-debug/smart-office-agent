/**
 * 产物中心：多选与批量删除。
 * 选择集只覆盖当前页——翻页/换筛选要清空，删除要走批量接口而不是逐条打 N 次请求。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sessionsApi } from '../sessions';
import { artifactsApi } from './api';
import { ArtifactsPage } from './ArtifactsPage';
import type { ArtifactOut } from '../../shared/api/types';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    artifactsApi: {
      ...actual.artifactsApi,
      listArtifacts: vi.fn(),
      listTrash: vi.fn(),
      deleteArtifact: vi.fn(),
      deleteArtifacts: vi.fn(),
      restoreArtifact: vi.fn(),
      purgeArtifact: vi.fn(),
    },
  };
});

vi.mock('../sessions', () => ({
  sessionsApi: { listThreads: vi.fn() },
}));

const listMock = vi.mocked(artifactsApi.listArtifacts);
const trashMock = vi.mocked(artifactsApi.listTrash);
const restoreMock = vi.mocked(artifactsApi.restoreArtifact);
const purgeMock = vi.mocked(artifactsApi.purgeArtifact);
const deleteOneMock = vi.mocked(artifactsApi.deleteArtifact);
const deleteManyMock = vi.mocked(artifactsApi.deleteArtifacts);
const threadsMock = vi.mocked(sessionsApi.listThreads);

function artifact(patch: Partial<ArtifactOut> = {}): ArtifactOut {
  return {
    artifact_id: 'a1',
    type: 'txt',
    filename: '报告.txt',
    size: 1024,
    sha256: '',
    content_type: '',
    created_at: '2026-10-24T12:00:00.000Z',
    thread_id: 'th_1',
    run_id: null,
    download_url: '/download',
    preview_url: '/preview',
    extra: {},
    has_preview_file: false,
    has_text: true,
    ...patch,
  };
}

function serve(items: ArtifactOut[]): void {
  listMock.mockResolvedValue({
    data: { artifacts: items, total: items.length, page: 1, page_size: 12 },
    traceId: null,
  });
}

function renderPage(path = '/artifacts') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ArtifactsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  threadsMock.mockResolvedValue({
    data: { trace_id: 'tr_1', threads: [], total: 0, page: 1, page_size: 20 },
    traceId: null,
  });
  deleteOneMock.mockResolvedValue({ data: {}, traceId: null });
  trashMock.mockResolvedValue({
    data: { artifacts: [], total: 0, page: 1, page_size: 100 },
    traceId: null,
  });
  restoreMock.mockResolvedValue({ data: { restored: true }, traceId: null });
  purgeMock.mockResolvedValue({ data: { purged: true }, traceId: null });
  deleteManyMock.mockResolvedValue({
    data: { requested: 0, deleted: 0, failed: [], trashed: [] },
    traceId: null,
  });
  serve([artifact(), artifact({ artifact_id: 'a2', filename: '纪要.txt' })]);
});

describe('ArtifactsPage 多选删除', () => {
  it('勾选后出现已选计数与批量删除按钮', async () => {
    renderPage();
    expect(await screen.findByText('报告.txt')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '删除选中' })).toBeNull();

    fireEvent.click(screen.getByRole('checkbox', { name: '选择 报告.txt' }));
    expect(screen.getByText('已选 1 项')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: '选择 纪要.txt' }));
    expect(screen.getByText('已选 2 项')).toBeInTheDocument();
  });

  it('再次勾选取消该项选择', async () => {
    renderPage();
    const box = await screen.findByRole('checkbox', { name: '选择 报告.txt' });

    fireEvent.click(box);
    expect(screen.getByText('已选 1 项')).toBeInTheDocument();
    fireEvent.click(box);
    expect(screen.queryByText(/已选/)).toBeNull();
  });

  it('全选本页后可一键取消', async () => {
    renderPage();
    // 全选按钮在列表渲染后才有
    const selectAll = await screen.findByRole('checkbox', { name: '全选本页' });

    fireEvent.click(selectAll);
    expect(screen.getByText('已选 2 项')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '选择 报告.txt' })).toBeChecked();

    fireEvent.click(selectAll);
    expect(screen.queryByText(/已选/)).toBeNull();
  });

  it('确认后调用批量接口并刷新列表', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    deleteManyMock.mockResolvedValue({
      data: { requested: 2, deleted: 2, failed: [], trashed: ['/trash/a.txt'] },
      traceId: null,
    });
    renderPage();

    fireEvent.click(await screen.findByRole('checkbox', { name: '全选本页' }));
    fireEvent.click(screen.getByRole('button', { name: '删除选中' }));

    await waitFor(() => expect(deleteManyMock).toHaveBeenCalledWith(['a1', 'a2']));
    expect(confirm).toHaveBeenCalledOnce();
    expect(await screen.findByText('已移入回收站 2 个产物')).toBeInTheDocument();
    // 首次加载 + 删除后刷新
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
    confirm.mockRestore();
  });

  it('取消确认不发起请求', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderPage();

    fireEvent.click(await screen.findByRole('checkbox', { name: '选择 报告.txt' }));
    fireEvent.click(screen.getByRole('button', { name: '删除选中' }));

    await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
    expect(deleteManyMock).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it('部分失败时提示成功数与首个失败原因', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    deleteManyMock.mockResolvedValue({
      data: {
        requested: 2,
        deleted: 1,
        failed: [{ artifact_id: 'a2', deleted: false, message: '产物不存在：a2' }],
        trashed: [],
      },
      traceId: null,
    });
    renderPage();

    fireEvent.click(await screen.findByRole('checkbox', { name: '全选本页' }));
    fireEvent.click(screen.getByRole('button', { name: '删除选中' }));

    expect(await screen.findByText('已删除 1 个，1 个失败：产物不存在：a2')).toBeInTheDocument();
  });

  it('切换类型筛选清空已选项', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('checkbox', { name: '选择 报告.txt' }));
    expect(screen.getByText('已选 1 项')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^类型/ }));
    fireEvent.click(screen.getByRole('button', { name: 'PDF' }));
    await waitFor(() => expect(screen.queryByText(/已选/)).toBeNull());
  });

  it('卡片上不再放单条删除，删除统一走勾选后的「删除选中」', async () => {
    renderPage();
    await screen.findByText('报告.txt');

    const cardDelete = screen
      .queryAllByRole('button', { name: '删除' })
      .filter((button) => button.closest('[data-testid="artifact-card"]'));
    expect(cardDelete).toHaveLength(0);
  });
});

describe('ArtifactsPage 两个分类维度', () => {
  /** 两个维度都收在胶囊里：先点开胶囊，选项才出现在 DOM 里 */
  const openMenu = (label: RegExp) => fireEvent.click(screen.getByRole('button', { name: label }));

  it('维度默认收起成胶囊，点开才展开选项，再点 / Esc 收起', async () => {
    renderPage();
    expect(await screen.findByText('报告.txt')).toBeInTheDocument();

    // 收起时选项根本不渲染：一行只留胶囊，空间全给列表
    expect(screen.queryByRole('button', { name: '全部类型' })).toBeNull();
    const typePill = screen.getByRole('button', { name: /^类型/ });
    expect(typePill).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(typePill);
    expect(typePill).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: '全部类型' })).toBeInTheDocument();

    // 再点一次同一个胶囊就收起
    fireEvent.click(typePill);
    expect(screen.queryByRole('button', { name: '全部类型' })).toBeNull();

    fireEvent.click(typePill);
    expect(screen.getByRole('button', { name: '全部类型' })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('button', { name: '全部类型' })).toBeNull();
  });

  it('类型从下拉改成分类选项：全部类型 / Word / Excel / PDF / PPT / 文本', async () => {
    renderPage();
    expect(await screen.findByText('报告.txt')).toBeInTheDocument();
    openMenu(/^类型/);

    for (const label of ['全部类型', 'Word 文档', 'Excel 表格', 'PDF', 'PPT 演示文稿', '文本']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    // 下拉已经被分类选项取代，不再有 select
    expect(screen.queryByLabelText('按类型筛选')).toBeNull();
  });

  it('面板竖排选项且高度封顶：类型不会空出右侧，会话再多也不会把边框撑长', async () => {
    // 有产物的会话才会进胶囊；给一条，两个维度才都在
    threadsMock.mockResolvedValue({
      data: {
        trace_id: 'tr_1',
        threads: [
          {
            thread_id: 'th_1',
            title: 'W46 周报',
            created_at: '2026-11-06T09:00:00.000Z',
            updated_at: '2026-11-06T10:00:00.000Z',
            pinned: false,
            message_count: 4,
            artifact_count: 3,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
      traceId: null,
    });
    renderPage();
    expect(await screen.findByText('报告.txt')).toBeInTheDocument();

    openMenu(/^类型/);
    // 一行一个、每项撑满面板宽度——换行铺 chip 时短行凑不满，右侧会空出一大块
    for (const label of ['全部类型', 'Word 文档', 'Excel 表格', 'PDF', 'PPT 演示文稿', '文本']) {
      expect(screen.getByRole('button', { name: label })).toHaveClass('w-full');
    }
    const typePanel = screen.getByRole('group', { name: '类型筛选' });
    // 高度按行数算出来封顶（calc）：选项再多也是框内滚，边框不会一节节长下去
    expect(typePanel.style.maxHeight).toMatch(/^calc\(/);

    fireEvent.keyDown(document, { key: 'Escape' });
    openMenu(/^会话/);
    const sessionPanel = screen.getByRole('group', { name: '会话筛选' });
    expect(sessionPanel.style.maxHeight).toMatch(/^calc\(/);
    // 会话会一直攒下去，露的行数比类型少：留的余量不一样，别把两边上限写成一个数
    expect(sessionPanel.style.maxHeight).not.toBe(typePanel.style.maxHeight);
  });

  it('点类型分类就按该类型取数，分页回到第 1 页，胶囊上写着选了什么', async () => {
    renderPage();
    await screen.findByText('报告.txt');
    openMenu(/^类型/);

    fireEvent.click(screen.getByRole('button', { name: 'PDF' }));
    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'pdf', page: 1 })),
    );
    // 选完就收，胶囊上留下当前值——收起状态也知道筛的是 PDF
    expect(screen.queryByRole('button', { name: 'Excel 表格' })).toBeNull();
    expect(screen.getByRole('button', { name: /^类型/ })).toHaveTextContent('PDF');
  });

  it('会话维度按所属对话归类：点会话只列那次对话的产物', async () => {
    threadsMock.mockResolvedValue({
      data: {
        trace_id: 'tr_1',
        threads: [
          {
            thread_id: 'th_1',
            title: 'W46 周报',
            created_at: '2026-11-06T09:00:00.000Z',
            updated_at: '2026-11-06T10:00:00.000Z',
            pinned: false,
            message_count: 4,
            artifact_count: 3,
          },
          {
            thread_id: 'th_2',
            title: '客户合同',
            created_at: '2026-11-05T09:00:00.000Z',
            updated_at: '2026-11-05T10:00:00.000Z',
            pinned: false,
            message_count: 2,
            artifact_count: 1,
          },
          {
            thread_id: 'th_3',
            title: '空会话',
            created_at: '2026-11-04T09:00:00.000Z',
            updated_at: '2026-11-04T10:00:00.000Z',
            pinned: false,
            message_count: 1,
            artifact_count: 0,
          },
        ],
        total: 3,
        page: 1,
        page_size: 100,
      },
      traceId: null,
    });
    renderPage();
    await screen.findByText('报告.txt');
    openMenu(/^会话/);

    // 没有产物的会话不进分类，避免点进去一片空白
    expect(screen.queryByRole('button', { name: /空会话/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '客户合同' }));

    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ threadId: 'th_2', page: 1 }),
      ),
    );
    // 两个维度能叠加
    openMenu(/^类型/);
    // 同一时刻只开一个面板：会话面板让位
    expect(screen.queryByRole('button', { name: '全部对话' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'PDF' }));
    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ threadId: 'th_2', type: 'pdf' }),
      ),
    );
  });

  it('从工作台深链进来：直接定位到该会话，从胶囊里能切回全部对话', async () => {
    threadsMock.mockResolvedValue({
      data: {
        trace_id: 'tr_1',
        threads: [
          {
            thread_id: 'th_2',
            title: '客户合同',
            created_at: '2026-11-05T09:00:00.000Z',
            updated_at: '2026-11-05T10:00:00.000Z',
            pinned: false,
            message_count: 2,
            artifact_count: 1,
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      },
      traceId: null,
    });
    renderPage('/artifacts?thread=th_2');
    await screen.findByText('报告.txt');

    // 取数就带上了会话，不是先全量再在本地筛
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ threadId: 'th_2' }));
    // 定位只靠胶囊本身说清（不再单挂一条「正在查看…」的回执）
    expect(screen.queryByText(/正在查看/)).toBeNull();
    expect(screen.getByRole('button', { name: /^会话/ })).toHaveTextContent('客户合同');

    // 退出定位就点开会话胶囊选「全部对话」
    openMenu(/^会话/);
    fireEvent.click(screen.getByRole('button', { name: '全部对话' }));
    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ threadId: undefined, page: 1 }),
      ),
    );
    expect(screen.getByRole('button', { name: /^会话/ })).toHaveTextContent('全部对话');
  });
});

describe('ArtifactsPage 筛选与回收站', () => {
  it('回收站：列出已删产物并可以恢复', async () => {
    trashMock.mockResolvedValue({
      data: {
        artifacts: [
          {
            ...artifact({ artifact_id: 'a9', filename: '删掉的.txt' }),
            deleted_at: '2026-10-25T02:00:00.000Z',
            restorable: true,
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      },
      traceId: null,
    });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /回收站/ }));

    expect(await screen.findByText('删掉的.txt')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /恢复/ }));

    await waitFor(() => expect(restoreMock).toHaveBeenCalledWith('a9'));
    expect(await screen.findByText('已恢复：删掉的.txt')).toBeInTheDocument();
  });

  it('回收站：彻底删除需要确认，取消则不调用接口', async () => {
    trashMock.mockResolvedValue({
      data: {
        artifacts: [
          {
            ...artifact({ artifact_id: 'a8', filename: '废稿.txt' }),
            deleted_at: '2026-10-25T02:00:00.000Z',
            restorable: true,
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      },
      traceId: null,
    });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /回收站/ }));
    fireEvent.click(await screen.findByRole('button', { name: /彻底删除/ }));

    expect(confirm).toHaveBeenCalled();
    expect(purgeMock).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: /彻底删除/ }));
    await waitFor(() => expect(purgeMock).toHaveBeenCalledWith('a8'));
    confirm.mockRestore();
  });

  it('回收站：全选后可批量恢复', async () => {
    trashMock.mockResolvedValue({
      data: {
        artifacts: [
          {
            ...artifact({ artifact_id: 'a7', filename: '废稿一.txt' }),
            deleted_at: '2026-10-25T02:00:00.000Z',
            restorable: true,
          },
          {
            ...artifact({ artifact_id: 'a9', filename: '废稿二.txt' }),
            deleted_at: '2026-10-25T03:00:00.000Z',
            restorable: true,
          },
        ],
        total: 2,
        page: 1,
        page_size: 100,
      },
      traceId: null,
    });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /回收站/ }));

    // 回收站卡片也带复选框，工具栏有全选
    expect(await screen.findByRole('checkbox', { name: '选择 废稿一.txt' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: '全选本页' }));
    expect(screen.getByText('已选 2 项')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /恢复选中/ }));
    await waitFor(() => expect(restoreMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('已恢复 2 个产物')).toBeInTheDocument();
  });

  it('回收站：全选后批量彻底删除需要确认', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    trashMock.mockResolvedValue({
      data: {
        artifacts: [
          {
            ...artifact({ artifact_id: 'a6', filename: '旧稿.txt' }),
            deleted_at: '2026-10-25T02:00:00.000Z',
            restorable: true,
          },
        ],
        total: 1,
        page: 1,
        page_size: 100,
      },
      traceId: null,
    });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /回收站/ }));
    fireEvent.click(await screen.findByRole('checkbox', { name: '全选本页' }));
    // 选中后工具栏出现「彻底删除」，卡片上的同名按钮也在，取工具栏那个（DOM 在前）
    const purgeButtons = screen.getAllByRole('button', { name: /彻底删除/ });
    fireEvent.click(purgeButtons[0] as HTMLElement);

    await waitFor(() => expect(purgeMock).toHaveBeenCalledWith('a6'));
    expect(confirm).toHaveBeenCalledOnce();
    expect(await screen.findByText('已彻底删除 1 个产物')).toBeInTheDocument();
    confirm.mockRestore();
  });

  it('预览在应用内弹窗打开，不再新开标签页', async () => {
    const open = vi.fn();
    vi.stubGlobal('open', open);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        text: async () => '预览正文',
        arrayBuffer: async () => new ArrayBuffer(0),
      })),
    );

    renderPage();
    fireEvent.click((await screen.findAllByRole('button', { name: /预览/ }))[0] as HTMLElement);

    expect(await screen.findByText('预览正文')).toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe('ArtifactsPage 只列产物', () => {
  it('类型筛选里不再有「上传文件」：上传素材不是产物', async () => {
    listMock.mockResolvedValue({
      data: { artifacts: [artifact()], total: 1, page: 1, page_size: 12 },
      traceId: null,
    } as never);
    trashMock.mockResolvedValue({
      data: { artifacts: [], total: 0, page: 1, page_size: 100 },
      traceId: null,
    } as never);

    renderPage();
    await screen.findByText('报告.txt');

    expect(screen.queryByRole('button', { name: '上传文件' })).toBeNull();
    expect(screen.queryByText('上传文件')).toBeNull();
  });
});
