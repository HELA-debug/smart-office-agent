/**
 * 扩展页（/skills）：插件 / 技能两个 tab，同一套商店列表。
 *
 * 关键约束：
 * - 已添加的技能不再单开一片区域，就地显示「已添加」，省下来的高度给列表；
 * - 添加按钮自己说结果：点完变成「已添加」，不用去页头找横幅；
 * - 规范包入口在顶部工具条上（之前缩在列表末尾，用户找不到）；
 * - 插件 tab 读的是 runtime 真实注册的工具，按分组展示，只读。
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { promptPacksApi, skillsApi } from './api';
import { SkillsPage } from './SkillsPage';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    skillsApi: {
      list: vi.fn(),
      catalog: vi.fn(),
      install: vi.fn(),
      setEnabled: vi.fn(),
      deleteSkill: vi.fn(),
      importSkill: vi.fn(),
    },
    promptPacksApi: { list: vi.fn() },
  };
});

/** 后端 /tools 的真实工具（描述截断）：插件 tab 按这些分组成插件。 */
const TOOLS = [
  {
    name: 'code.run_python',
    description: '在本机受控目录执行 Python 脚本，用于复杂的文档加工。',
    risk: 'high',
  },
  { name: 'doc.generate_report', description: '根据会话素材与模板生成报告文件。', risk: 'high' },
  { name: 'file.delete', description: '删除当前会话的产物文件（软删）。', risk: 'high' },
  { name: 'file.list', description: '列出当前会话已上传的素材文件。', risk: 'low' },
  { name: 'file.read', description: '读取当前会话素材正文。', risk: 'low' },
  { name: 'todo.list', description: '读取当前任务计划。', risk: 'low' },
  { name: 'todo.write', description: '写入/更新任务计划。', risk: 'low' },
];

function mockSkill(patch: Record<string, unknown> = {}) {
  return {
    name: 'weekly-report',
    title: '周报写作',
    description: '把会议记录整理成结构化周报（DOCX）',
    triggers: ['周报', '周报生成'],
    enabled: true,
    category: '办公文档',
    icon: 'doc',
    badge: '',
    content_chars: 700,
    ...patch,
  };
}

function mockCatalog(patch: Record<string, unknown> = {}) {
  return {
    name: 'meeting-minutes',
    slug: 'meeting-minutes',
    title: '会议纪要',
    description: '把速记压成决议与待办',
    triggers: ['纪要', '会议记录'],
    category: '会议协作',
    icon: 'minutes',
    badge: '必备精选',
    content_chars: 640,
    enabled: true,
    installed: false,
    ...patch,
  };
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ trace_id: 'tr_test', tools: TOOLS }),
      } as unknown as Response;
    }),
  );

  vi.mocked(skillsApi.list).mockResolvedValue({
    data: { skills: [mockSkill()], prompt_chars: 1360 },
    traceId: null,
  });
  vi.mocked(skillsApi.catalog).mockResolvedValue({
    data: {
      skills: [
        mockCatalog(),
        mockCatalog({
          name: 'data-brief',
          slug: 'data-brief',
          title: '数据速览',
          description: '表格读成一页要点',
          triggers: ['汇总', '指标'],
          category: '表格数据',
          icon: 'sheet',
          badge: '新功能推荐',
        }),
        mockCatalog({
          name: 'doc-qc',
          slug: 'doc-qc',
          title: '文档质检',
          description: '成稿前自查',
          triggers: ['校对', '审稿'],
          category: '文件处理',
          icon: 'shield',
          badge: '',
        }),
      ],
      categories: ['会议协作', '表格数据', '文件处理'],
    },
    traceId: null,
  });
  vi.mocked(skillsApi.install).mockResolvedValue({
    data: { name: '会议纪要', slug: 'meeting-minutes', skill: mockSkill() },
    traceId: null,
  });
  vi.mocked(skillsApi.setEnabled).mockResolvedValue({
    data: { name: 'weekly-report', enabled: false, prompt_chars: 660 },
    traceId: null,
  });
  vi.mocked(promptPacksApi.list).mockResolvedValue({
    data: [
      {
        id: 'docx-layout',
        title: '文档排版规范',
        keywords: ['排版', '公文'],
        chars: 520,
        body: '## 文档排版规范\n\n- 标题用黑体三号\n- 正文宋体小四',
      },
      {
        id: 'info-digest',
        title: '信息收敛与要点整理',
        keywords: ['要点'],
        chars: 390,
        body: '## 信息收敛与要点整理\n\n先给结论，再列依据。',
      },
    ],
    traceId: null,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  return render(
    <MemoryRouter>
      <SkillsPage />
    </MemoryRouter>,
  );
}

describe('SkillsPage', () => {
  it('两个 tab：默认在技能，一片网格，添加过的就地标「已添加」', async () => {
    renderPage();
    const grid = await screen.findByTestId('skills-grid');

    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent);
    expect(tabs).toEqual(['插件', '技能']);
    expect(screen.getByRole('tab', { name: '技能' })).toHaveAttribute('aria-selected', 'true');

    // 不再单开一片「已添加」区域：已添加的混在技能库里，用行内状态区分
    expect(screen.queryByRole('heading', { name: '已添加' })).toBeNull();
    expect(grid.className).toContain('auto-fill');

    expect(within(grid).getByText('周报写作')).toBeInTheDocument();
    expect(within(grid).getByText('已添加')).toBeInTheDocument();
    expect(within(grid).getByText('已进提示词')).toBeInTheDocument();
    expect(screen.getByText(/已添加 1 · 可添加 3/)).toBeInTheDocument();
    expect(screen.getByText(/提示词共 1360 字/)).toBeInTheDocument();
    // 两个 tab 共用一行分区标题：技能是「技能库」，插件是「内置插件」
    expect(screen.getByRole('heading', { name: '技能库' })).toBeInTheDocument();
  });

  it('技能库里点「添加」走安装接口（带角标的技能也平铺在网格里，不再有精选位）', async () => {
    renderPage();
    const grid = await screen.findByTestId('skills-grid');
    expect(within(grid).getByText('会议纪要')).toBeInTheDocument();
    expect(screen.queryByTestId('skills-featured')).toBeNull();

    const row = within(grid).getByText('文档质检').closest('article');
    expect(row).not.toBeNull();

    fireEvent.click(within(row as HTMLElement).getByRole('button', { name: '添加' }));
    await waitFor(() => expect(skillsApi.install).toHaveBeenCalledWith('doc-qc'));
  });

  it('分类筛选只留下对应类别，不出现空的「已添加」区块', async () => {
    renderPage();
    const grid = await screen.findByTestId('skills-grid');

    fireEvent.click(screen.getByRole('button', { name: '表格数据' }));
    expect(within(grid).getByText('数据速览')).toBeInTheDocument();
    expect(within(grid).queryByText('会议纪要')).toBeNull();
    expect(screen.queryByText('没有匹配的已添加技能')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '全部' }));
    expect(within(grid).getByText('文档质检')).toBeInTheDocument();
  });

  it('搜索按名称/描述/触发词过滤', async () => {
    renderPage();
    await screen.findByTestId('skills-grid');
    const search = screen.getByLabelText('搜索技能');

    // 触发词也参与匹配：文档质检的名字/描述里没有「校对」
    fireEvent.change(search, { target: { value: '校对' } });
    const grid = screen.getByTestId('skills-grid');
    expect(within(grid).getByText('文档质检')).toBeInTheDocument();
    expect(within(grid).queryByText('会议纪要')).toBeNull();

    fireEvent.change(search, { target: { value: '表格' } });
    expect(within(grid).getByText('数据速览')).toBeInTheDocument();
    expect(within(grid).queryByText('文档质检')).toBeNull();

    fireEvent.change(search, { target: { value: 'zzz-不存在' } });
    expect(screen.getByText(/没有匹配的技能/)).toBeInTheDocument();
  });

  it('技能列表和插件列表同一套排版：没有精选大卡，条目直接用 article 平铺', async () => {
    renderPage();
    const grid = await screen.findByTestId('skills-grid');
    // 一排到底：4 条技能全在同一个网格里，分类只靠上面的 chip 筛
    expect(within(grid).getAllByRole('article')).toHaveLength(4);

    fireEvent.click(screen.getByRole('button', { name: '表格数据' }));
    expect(within(screen.getByTestId('skills-grid')).getAllByRole('article')).toHaveLength(1);
  });

  it('已添加的技能用电源按钮启停', async () => {
    renderPage();
    const button = await screen.findByRole('button', { name: '停用技能 周报写作' });

    fireEvent.click(button);
    await waitFor(() => expect(skillsApi.setEnabled).toHaveBeenCalledWith('weekly-report', false));
  });

  it('停用后的技能给「启用」', async () => {
    vi.mocked(skillsApi.list).mockResolvedValue({
      data: { skills: [mockSkill({ enabled: false })], prompt_chars: 660 },
      traceId: null,
    });
    renderPage();

    const button = await screen.findByRole('button', { name: '启用技能 周报写作' });
    fireEvent.click(button);
    await waitFor(() => expect(skillsApi.setEnabled).toHaveBeenCalledWith('weekly-report', true));
  });

  it('插件 tab：读真实工具，按分组展示，只读且全部启用', async () => {
    renderPage();
    await screen.findByTestId('skills-grid');

    fireEvent.click(screen.getByRole('tab', { name: '插件' }));
    const catalog = await screen.findByTestId('skills-catalog');

    // 7 个工具归成 5 个插件
    for (const title of ['文档生成', '脚本加工', '素材读取', '产物清理', '任务计划']) {
      expect(within(catalog).getByText(title)).toBeInTheDocument();
    }
    expect(within(catalog).getAllByText('2 个工具')).toHaveLength(2);
    expect(within(catalog).getAllByText('1 个工具')).toHaveLength(3);
    expect(within(catalog).getAllByText('已启用').length).toBeGreaterThanOrEqual(5);
    // 插件不提供「添加」：随应用发布，常驻
    expect(within(catalog).queryByRole('button', { name: '添加' })).toBeNull();
    expect(screen.getByText(/内置 5 个插件 · 7 个工具全部启用/)).toBeInTheDocument();
  });

  it('插件 tab 的搜索按插件名与工具名过滤', async () => {
    renderPage();
    await screen.findByTestId('skills-grid');
    fireEvent.click(screen.getByRole('tab', { name: '插件' }));
    const catalog = await screen.findByTestId('skills-catalog');

    fireEvent.change(screen.getByLabelText('搜索插件'), { target: { value: 'file.read' } });
    expect(within(catalog).getByText('素材读取')).toBeInTheDocument();
    expect(within(catalog).queryByText('文档生成')).toBeNull();
  });

  it('规范包入口在顶部工具条上，点开是弹窗阅读器', async () => {
    renderPage();
    const grid = await screen.findByTestId('skills-grid');
    const entry = await screen.findByRole('button', { name: /内置规范包/ });

    // 不再缩在列表最末尾：不在技能网格里，也不在卡片里
    expect(grid.contains(entry)).toBe(false);
    expect(entry.closest('article')).toBeNull();
    expect(screen.queryByText('文档排版规范')).toBeNull();

    fireEvent.click(entry);
    const dialog = await screen.findByRole('dialog', { name: '内置规范包' });
    expect(within(dialog).getByLabelText('规范包目录')).toBeInTheDocument();
    expect(within(dialog).getByText(/共 2 段/)).toBeInTheDocument();
    // 正文按 Markdown 渲染：标题不再带 ##，列表项拆成 li
    expect(within(dialog).getByText('标题用黑体三号')).toBeInTheDocument();
    expect(within(dialog).queryByText(/## 文档排版规范/)).toBeNull();
  });

  it('弹窗里点目录切换正文', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /内置规范包/ }));
    const dialog = await screen.findByRole('dialog', { name: '内置规范包' });
    const nav = within(dialog).getByLabelText('规范包目录');

    fireEvent.click(within(nav).getByText('信息收敛与要点整理'));
    expect(within(dialog).getByText('先给结论，再列依据。')).toBeInTheDocument();
    expect(within(dialog).queryByText('标题用黑体三号')).toBeNull();
  });

  it('弹窗关闭按钮把弹窗收掉', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /内置规范包/ }));
    const dialog = await screen.findByRole('dialog', { name: '内置规范包' });

    // 标题栏的关闭图标和页脚「关闭」同名，点页脚那个（最后一个）
    const closers = within(dialog).getAllByRole('button', { name: '关闭' });
    fireEvent.click(closers[closers.length - 1] as HTMLElement);
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });
});
