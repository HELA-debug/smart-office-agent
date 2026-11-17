/**
 * 输入区交互测试。
 *
 * 重点锁住一条观感规则：主发送按钮任何状态下都要有反应 —— 没写内容时点它是把焦点送回
 * 输入框（而不是实色按钮点不动、hover 也没反馈）；运行中才是真正禁用。
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../../shared/lib/api';
import { DROP_FILES_EVENT } from '../../../shared/lib/drop-guard';
import { promptsApi } from '../api/prompts';
import { Composer } from './Composer';
import type { DocStyle } from '../../../shared/config/doc-style';
import type { OutputFormat } from '../../../shared/config/output-formats';
import type { QueuedMessage, UploadItem } from '../state/workbench';

vi.mock('../../settings', () => ({
  settingsApi: {
    listModels: vi.fn().mockResolvedValue({ data: { models: [] }, traceId: null }),
    updateSettings: vi.fn().mockResolvedValue({ data: {}, traceId: null }),
  },
}));
vi.mock('../../audit', () => ({
  auditApi: { getUsageSummary: vi.fn().mockResolvedValue({ data: null, traceId: null }) },
}));
vi.mock('../api/prompts', () => ({
  promptsApi: { enhance: vi.fn() },
}));

function upload(patch: Partial<UploadItem> = {}): UploadItem {
  return {
    local_id: 'u1',
    filename: '周会记录.txt',
    size: 2048,
    status: 'parsed',
    chars: 453,
    preview: '这是正文预览，界面上不应该再出现这一行',
    error: null,
    ext: '.txt',
    ...patch,
  };
}

function renderComposer(
  patch: {
    value?: string;
    disabled?: boolean;
    uploads?: UploadItem[];
    isStreaming?: boolean;
    waitingApproval?: boolean;
    onOpenApproval?: () => void;
    queue?: QueuedMessage[];
    queuePaused?: boolean;
    onEditQueued?: (id: string) => void;
    onRemoveQueued?: (id: string) => void;
    onPromoteQueued?: (id: string) => void;
    onResumeQueue?: () => void;
    onRetryUpload?: (localId: string) => void;
    modelBlocked?: boolean;
    modelHint?: string;
  } = {},
) {
  const onSubmit = vi.fn();
  const onChange = vi.fn();
  const onUploadFiles = vi.fn();
  const view = render(
    <MemoryRouter>
      <Composer
        value={patch.value ?? ''}
        onChange={onChange}
        onSubmit={onSubmit}
        onStop={vi.fn()}
        onUploadFiles={onUploadFiles}
        uploads={patch.uploads ?? []}
        onRemoveUpload={vi.fn()}
        disabled={patch.disabled ?? false}
        isStreaming={patch.isStreaming ?? false}
        waitingApproval={patch.waitingApproval ?? false}
        onOpenApproval={patch.onOpenApproval ?? vi.fn()}
        outputFormat={'docx' as OutputFormat}
        onOutputFormatChange={vi.fn()}
        model="mock-scripted"
        isMock
        modelBlocked={patch.modelBlocked ?? false}
        modelHint={patch.modelHint}
        queue={patch.queue ?? []}
        queuePaused={patch.queuePaused ?? false}
        {...(patch.onEditQueued ? { onEditQueued: patch.onEditQueued } : {})}
        {...(patch.onRemoveQueued ? { onRemoveQueued: patch.onRemoveQueued } : {})}
        {...(patch.onPromoteQueued ? { onPromoteQueued: patch.onPromoteQueued } : {})}
        {...(patch.onResumeQueue ? { onResumeQueue: patch.onResumeQueue } : {})}
        {...(patch.onRetryUpload ? { onRetryUpload: patch.onRetryUpload } : {})}
      />
    </MemoryRouter>,
  );
  return { onSubmit, onChange, onUploadFiles, ...view };
}

describe('Composer 发送按钮', () => {
  it('没写内容时按钮仍可点：点它只把焦点送回输入框，不提交', () => {
    const { onSubmit } = renderComposer();
    const send = screen.getByRole('button', { name: /发送/ });
    expect(send).not.toBeDisabled();

    fireEvent.click(send);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole('textbox'));
  });

  it('有内容时正常提交', () => {
    const { onSubmit } = renderComposer({ value: '把这份纪要整理成周报' });
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('没有可用模型（modelBlocked）：写了内容也拦住，提示怎么把模型配上', () => {
    const { onSubmit } = renderComposer({
      value: '把这份纪要整理成周报',
      modelBlocked: true,
      modelHint: '还没有可用的模型：点输入框左侧的「选择模型」挑一家，或到设置页添加 Key',
    });
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent(/还没有可用的模型/);
    expect(document.activeElement).toBe(screen.getByRole('textbox'));
  });

  it('没有可用模型时门禁排在最前：哪怕一个字没写，提示的也是「缺模型」不是「缺内容」', () => {
    const { onSubmit } = renderComposer({ modelBlocked: true });
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent(/选择模型|添加 Key/);
  });

  it('只加了附件没写需求：点发送给出明确提示，不提交', () => {
    const { onSubmit } = renderComposer({ uploads: [upload()] });
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent(/请再写一句需求/);
    expect(document.activeElement).toBe(screen.getByRole('textbox'));
  });

  it('完全没有内容时提示「请先输入需求」', () => {
    const { onSubmit } = renderComposer();
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('请先输入需求');
  });

  it('附件下方不再重复展示「预览：…」大段文本', () => {
    renderComposer({ uploads: [upload()] });
    expect(screen.queryByText(/预览：/)).toBeNull();
    expect(screen.getByText('周会记录.txt')).toBeInTheDocument();
    expect(screen.getByText('453 字')).toBeInTheDocument();
  });

  it('开始输入后提示自动消失', () => {
    renderComposer();
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));
    expect(screen.getByRole('status')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox'), { target: { value: '写周报' } });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('运行中（disabled）才是真禁用', () => {
    const { onSubmit } = renderComposer({ value: '再补一版', disabled: true });
    const send = screen.getByRole('button', { name: /发送/ });
    expect(send).toBeDisabled();
    fireEvent.click(send);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  /* 空输入时这颗按钮曾经是「浅底浅图标」，在白卡上只差 1.09:1，基本看不见；
     hover 又只深了 0.02 明度。这里锁住新规则：静息实心深底，悬停转柔和浅底。 */
  it('空输入：静息是实心深底，悬停转柔和浅底并同步压淡图标', () => {
    renderComposer();
    const send = screen.getByRole('button', { name: /发送/ });
    expect(send.className).toContain('bg-send-face');
    expect(send.className).toContain('hover:bg-send-face-hover');
    expect(send.className).toContain('hover:text-send-ink-hover');
    expect(send.className).not.toContain('bg-surface-sunken');
  });

  it('有内容：切到 ink 主按钮，悬停改用 ink-soft（不再只靠 opacity）', () => {
    renderComposer({ value: '把这份纪要整理成周报' });
    const send = screen.getByRole('button', { name: /发送/ });
    expect(send.className).toContain('bg-ink text-canvas');
    expect(send.className).toContain('hover:bg-ink-soft');
    expect(send.className).not.toContain('hover:opacity-90');
  });
});

/* ------------------------------------------------------------------ */
/* 审批策略与技能入口（第十二轮：两样都放进了输入框工具条）              */
/* ------------------------------------------------------------------ */

describe('Composer 审批策略与技能', () => {
  function renderWithToolbar(onApprovalModeChange = vi.fn()) {
    render(
      <MemoryRouter>
        <Composer
          value=""
          onChange={vi.fn()}
          onSubmit={vi.fn()}
          onStop={vi.fn()}
          onUploadFiles={vi.fn()}
          uploads={[]}
          onRemoveUpload={vi.fn()}
          disabled={false}
          isStreaming={false}
          waitingApproval={false}
          onOpenApproval={vi.fn()}
          outputFormat={'docx' as OutputFormat}
          onOutputFormatChange={vi.fn()}
          approvalMode="risky"
          onApprovalModeChange={onApprovalModeChange}
          skillsPanel={<span data-testid="skills-panel">技能面板</span>}
          skillsSummary="2/2 启用"
        />
      </MemoryRouter>,
    );
    return onApprovalModeChange;
  }

  it('信任档位显示当前档位，改选后回调', () => {
    const onApprovalModeChange = renderWithToolbar();
    const trigger = screen.getByLabelText('信任档位');
    expect(trigger).toHaveTextContent('标准');

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('option', { name: /放手/ }));
    expect(onApprovalModeChange).toHaveBeenCalledWith('all_allow');
  });

  it('技能不再占工具栏：收进加号菜单的第二级', () => {
    renderWithToolbar();
    // 工具栏上看不到技能（连隐藏的节点都不该有）
    expect(screen.queryByTestId('skills-panel')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /更多输入选项/ }));
    const group = screen.getByRole('menuitem', { name: /技能/ });
    expect(group).toHaveAttribute('aria-expanded', 'false');
    expect(group).toHaveTextContent('2/2 启用');
    // 收起状态下二级面板不进无障碍树，菜单才够紧凑
    expect(screen.queryByRole('menu', { name: '技能' })).toBeNull();

    fireEvent.pointerOver(group);
    const flyout = screen.getByRole('menu', { name: '技能' });
    expect(within(flyout).getByTestId('skills-panel')).toBeInTheDocument();
  });

  it('文件名不再挂跟随鼠标的提示（只有失败原因才有）', () => {
    renderComposer({ uploads: [upload()] });
    // 正常素材卡片只显示文件名，不渲染 tooltip 文本节点
    expect(screen.getByText('周会记录.txt')).toBeInTheDocument();
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});

describe('Composer 排队', () => {
  /** 取第 index 个元素并断言存在（项目开启了 noUncheckedIndexedAccess）。 */
  function pick(items: HTMLElement[], index: number): HTMLElement {
    const element = items[index];
    if (!element) throw new Error(`第 ${index} 个按钮不存在`);
    return element;
  }

  function queued(patch: Partial<QueuedMessage> = {}): QueuedMessage {
    return {
      id: 'q1',
      threadId: 't1',
      text: '再把表格汇总成台账',
      uploads: [],
      created_at: '2026-10-25T10:00:00.000Z',
      ...patch,
    };
  }

  it('没有排队任务时不占位置', () => {
    renderComposer();
    expect(screen.queryByLabelText('排队中的任务')).toBeNull();
  });

  it('运行中：主按钮变「排队」，停止按钮同时在场', () => {
    renderComposer({ value: '再补一版', isStreaming: true });
    expect(screen.getByRole('button', { name: /排队/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /停止/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /发送/ })).toBeNull();
  });

  it('队列卡片：一枚计数胶囊 + 每条一张卡，正文与素材名都在，三个动作带对 id', () => {
    const onEditQueued = vi.fn();
    const onRemoveQueued = vi.fn();
    const onPromoteQueued = vi.fn();
    renderComposer({
      queue: [
        queued({ uploads: [upload({ local_id: 'u9', filename: '台账.xlsx' })] }),
        queued({ id: 'q2', text: '顺手再画个饼图' }),
      ],
      onEditQueued,
      onRemoveQueued,
      onPromoteQueued,
    });

    expect(screen.getByLabelText('排队中的任务')).toBeInTheDocument();
    // 计数胶囊只说「几条在等」，不再是大卡片的表头
    expect(screen.getByText('2 条排队中')).toBeInTheDocument();
    // 每条排队消息各占一张卡
    expect(screen.getAllByTestId('queued-message')).toHaveLength(2);
    expect(screen.getByText('再把表格汇总成台账')).toBeInTheDocument();
    expect(screen.getByText('台账.xlsx')).toBeInTheDocument();
    expect(screen.getByText('顺手再画个饼图')).toBeInTheDocument();
    expect(screen.getByText('下一个')).toBeInTheDocument();

    fireEvent.click(pick(screen.getAllByRole('button', { name: '优先执行这条排队任务' }), 1));
    expect(onPromoteQueued).toHaveBeenCalledWith('q2');
    fireEvent.click(pick(screen.getAllByRole('button', { name: '编辑这条排队任务' }), 0));
    expect(onEditQueued).toHaveBeenCalledWith('q1');
    fireEvent.click(pick(screen.getAllByRole('button', { name: '删除这条排队任务' }), 1));
    expect(onRemoveQueued).toHaveBeenCalledWith('q2');
  });

  it('队列暂停时给「继续执行」出口', () => {
    const onResumeQueue = vi.fn();
    renderComposer({ queue: [queued()], queuePaused: true, onResumeQueue });

    expect(screen.getByText(/已暂停/)).toBeInTheDocument();
    // 暂停时没有「下一个」：谁都不算马上要跑
    expect(screen.queryByText('下一个')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /继续执行/ }));
    expect(onResumeQueue).toHaveBeenCalled();
  });
});

/* ------------------------------------------------------------------ */
/* 加号菜单：产物格式折叠成悬停展开一行（第五十三轮）                     */
/* ------------------------------------------------------------------ */

describe('Composer 加号菜单', () => {
  function renderMenu(
    patch: { uploads?: UploadItem[]; outputFormat?: OutputFormat; docStyle?: DocStyle } = {},
  ) {
    const onOutputFormatChange = vi.fn();
    const onApprovalModeChange = vi.fn();
    const onDocStyleChange = vi.fn();
    render(
      <MemoryRouter>
        <Composer
          value=""
          onChange={vi.fn()}
          onSubmit={vi.fn()}
          onStop={vi.fn()}
          onUploadFiles={vi.fn()}
          uploads={patch.uploads ?? []}
          onRemoveUpload={vi.fn()}
          disabled={false}
          isStreaming={false}
          waitingApproval={false}
          onOpenApproval={vi.fn()}
          outputFormat={patch.outputFormat ?? 'docx'}
          onOutputFormatChange={onOutputFormatChange}
          approvalMode="risky"
          onApprovalModeChange={onApprovalModeChange}
          docStyle={patch.docStyle ?? {}}
          onDocStyleChange={onDocStyleChange}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: /更多输入选项/ }));
    return { onOutputFormatChange, onApprovalModeChange, onDocStyleChange };
  }

  /** 悬停分组行：React 的 onPointerEnter 由 pointerover 合成，测试里用 pointerOver 触发 */
  function hoverFormatGroup() {
    fireEvent.pointerOver(screen.getByRole('menuitem', { name: /产物格式/ }));
  }

  /**
   * 菜单的「文档格式」分组：原来这里摆的是「产物中心」「审计用量」两个页面入口。
   * 那两个是「回头翻」的地方，天天挂在输入框旁边却几乎没人点；位置让给了发稿前
   * 真会调的一排（字体/字号/字形/行距/缩进/对齐），抄的是 WPS 的工具栏。
   */
  it('菜单里有「文档格式」，没有「产物中心」「审计用量」', () => {
    renderMenu();
    expect(screen.getByRole('menuitem', { name: /文档格式/ })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /产物中心/ })).toBeNull();
    expect(screen.queryByRole('menuitem', { name: /审计用量/ })).toBeNull();
  });

  it('点字号就把这一项交给上层，面板不跟着收起来（常常要连着改三项）', () => {
    const { onDocStyleChange } = renderMenu();
    fireEvent.pointerOver(screen.getByRole('menuitem', { name: /文档格式/ }));

    fireEvent.click(screen.getByRole('button', { name: '三号' }));
    expect(onDocStyleChange).toHaveBeenCalledWith({ size: '三号' });
    // 面板还在：连续改字体 / 行距不用重新展开
    expect(screen.getByRole('button', { name: '楷体' })).toBeInTheDocument();
  });

  it('再点一次同一项就是取消（回到「交给 Agent 判断」）', () => {
    const { onDocStyleChange } = renderMenu({ docStyle: { size: '三号' } });
    fireEvent.pointerOver(screen.getByRole('menuitem', { name: /文档格式/ }));

    fireEvent.click(screen.getByRole('button', { name: '三号' }));
    expect(onDocStyleChange).toHaveBeenCalledWith({});
  });

  it('默认值用浅底标出来，蓝底才代表「这一轮我定了」', () => {
    renderMenu();
    fireEvent.pointerOver(screen.getByRole('menuitem', { name: /文档格式/ }));

    // 什么都不选时：宋体 / 小四 / 1.5 倍 / 2 字符 / 两端对齐 是预设默认——淡底色，不是选中。
    // 选中意味着「别改」，默认意味着「不出声就按这个来，但公文还能换仿宋三号」。
    // 上一版给默认项画的是虚线，白卡片上几乎看不出，改成只深一档的底色。
    for (const label of ['宋体', '小四', '1.5 倍', '2 字符', '两端对齐']) {
      const chip = screen.getByRole('button', { name: label });
      expect(chip).toHaveClass('bg-surface-sunken');
      expect(chip).not.toHaveClass('border-dashed');
      expect(chip).toHaveAttribute('aria-pressed', 'false');
    }
    // 不是默认值的项保持白底，三种状态（默认 / 选中 / 普通）不能糊成一片
    expect(screen.getByRole('button', { name: '黑体' })).not.toHaveClass('bg-surface-sunken');
    // 底部把整份默认摆出来（五项全在），用户不用点开一层层猜
    const receipt = screen.getByTestId('doc-style-receipt');
    expect(receipt).toHaveAttribute('title', '默认 宋体 · 小四 · 1.5 倍 · 2 字符 · 两端对齐');
    expect((receipt.textContent ?? '').replace(/\s+/g, '')).toBe(
      '默认宋体·小四·1.5倍·2字符·两端对齐',
    );
    // 没设值时按钮也在，只是置灰——它是这个面板唯一的退路，不能藏起来
    expect(screen.getByRole('button', { name: '恢复默认' })).toBeDisabled();
  });

  it('底部始终是完整的一份样式，改哪项就替换哪一项', () => {
    renderMenu({ docStyle: { indent_chars: '1' } });
    fireEvent.pointerOver(screen.getByRole('menuitem', { name: /文档格式/ }));

    // 只动了首行缩进：其余四项照默认显示，用户仍能一眼看全整份样式
    const receipt = screen.getByTestId('doc-style-receipt');
    expect(receipt).toHaveAttribute('title', '宋体 · 小四 · 1.5 倍 · 1 字符 · 两端对齐');
    expect((receipt.textContent ?? '').replace(/\s+/g, '')).toBe('宋体·小四·1.5倍·1字符·两端对齐');
    // 改过之后不再是「默认」，那两个字跟着去掉
    expect(receipt).not.toHaveTextContent('默认');
  });

  it('底部替换的是文字，不是把整行缩成一项', () => {
    renderMenu({ docStyle: { size: '三号', align: 'center' } });
    fireEvent.pointerOver(screen.getByRole('menuitem', { name: /文档格式/ }));

    const receipt = screen.getByTestId('doc-style-receipt');
    expect(receipt).toHaveAttribute('title', '宋体 · 三号 · 1.5 倍 · 2 字符 · 居中');
    // 字体 / 行距 / 缩进没动过，仍然在行里
    for (const kept of ['宋体', '1.5 倍', '2 字符']) {
      expect(receipt).toHaveTextContent(kept);
    }

    // 选了居中之后，两端对齐就不再是「本轮默认」，浅底跟着撤掉
    expect(screen.getByRole('button', { name: '居中' })).toHaveClass('bg-brand-soft');
    expect(screen.getByRole('button', { name: '两端对齐' })).not.toHaveClass('bg-surface-sunken');
  });

  it('「恢复默认」始终在场，点了就把这一轮设的全清掉', () => {
    const { onDocStyleChange } = renderMenu({ docStyle: { size: '三号' } });
    fireEvent.pointerOver(screen.getByRole('menuitem', { name: /文档格式/ }));

    const reset = screen.getByRole('button', { name: '恢复默认' });
    expect(reset).toBeEnabled();
    fireEvent.click(reset);
    expect(onDocStyleChange).toHaveBeenCalledWith({});
  });

  it('默认收起：产物格式只占一行，收起时也看得到当前值', () => {
    renderMenu({ outputFormat: 'docx' });
    const group = screen.getByRole('menuitem', { name: /产物格式/ });

    expect(group).toHaveAttribute('aria-expanded', 'false');
    // 收起时右侧显示当前值（用中等长度标签，窄行里不会把分组名挤掉）
    expect(group).toHaveTextContent('产物格式Word 文档');
    // 折叠状态下四项不渲染在无障碍树里，菜单才够紧凑
    expect(screen.queryByRole('menuitemradio', { name: /PDF 文档（pdf）/ })).toBeNull();
  });

  it('悬停才展开全部产物格式，并勾出当前选中的那一项', () => {
    renderMenu({ outputFormat: 'docx' });
    hoverFormatGroup();

    expect(screen.getByRole('menuitem', { name: /产物格式/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByRole('menuitemradio', { name: /Word 文档（docx）/ })).toBeChecked();
    expect(screen.getByRole('menuitemradio', { name: /PDF 文档（pdf）/ })).not.toBeChecked();
    expect(screen.getByRole('menuitemradio', { name: /Excel 表格（xlsx）/ })).not.toBeChecked();
    expect(screen.getByRole('menuitemradio', { name: /PPT 演示文稿（pptx）/ })).not.toBeChecked();
    expect(screen.getByRole('menuitemradio', { name: /纯文本（txt）/ })).not.toBeChecked();
  });

  it('在展开的分组里换格式：回调正确的类型并收起菜单', () => {
    const { onOutputFormatChange } = renderMenu();
    hoverFormatGroup();
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Excel 表格（xlsx）/ }));

    expect(onOutputFormatChange).toHaveBeenCalledWith('xlsx');
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('和素材同格式的那一项标出「同素材」', () => {
    renderMenu({ uploads: [upload({ filename: '台账.xlsx', ext: '.xlsx' })] });
    hoverFormatGroup();
    const xlsx = screen.getByRole('menuitemradio', { name: /Excel 表格（xlsx）/ });
    expect(xlsx).toHaveTextContent('同素材');
    expect(screen.getByRole('menuitemradio', { name: /Word 文档（docx）/ })).not.toHaveTextContent(
      '同素材',
    );
  });

  it('面板里不再有信任档位：外部胶囊是唯一入口', () => {
    const { onApprovalModeChange } = renderMenu();
    hoverFormatGroup();

    expect(screen.queryByRole('menuitemradio', { name: /按需确认/ })).toBeNull();
    expect(screen.queryByRole('menuitemradio', { name: /全部允许/ })).toBeNull();
    // 外部胶囊仍在，且没有被菜单改动过
    fireEvent.click(screen.getByLabelText('信任档位'));
    fireEvent.click(screen.getByRole('option', { name: /放手/ }));
    expect(onApprovalModeChange).toHaveBeenCalledWith('all_allow');
  });

  it('Esc 先收二级面板，再按一次才收整张菜单', () => {
    renderMenu();
    hoverFormatGroup();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menuitemradio', { name: /PDF 文档（pdf）/ })).toBeNull();
    expect(screen.getByRole('menu', { name: '更多输入选项' })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('面板底色跟主题走，不再是那块突兀的纯黑浮层', () => {
    renderMenu();
    const menu = screen.getByRole('menu', { name: '更多输入选项' });
    expect(menu).toHaveClass('bg-surface');
    expect(menu).not.toHaveClass('bg-black');
  });

  it('产物格式不再有独立入口，信任档位胶囊仍在并排在加号后面', () => {
    renderMenu();
    fireEvent.keyDown(document, { key: 'Escape' });

    // 独立入口已移除：工具栏上找不到「产物格式」控件
    expect(screen.queryByLabelText('产物格式')).toBeNull();
    // 审批胶囊保留（安全设置要一眼看得见），且在 DOM 里位于加号之后
    const plus = screen.getByRole('button', { name: /更多输入选项/ });
    const approval = screen.getByLabelText('信任档位');
    expect(plus.compareDocumentPosition(approval) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

/* ------------------------------------------------------------------ */
/* 增强提示词（第五十一轮）                                             */
/* ------------------------------------------------------------------ */

describe('Composer 增强提示词', () => {
  function renderEnhance(patch: { value?: string } = {}) {
    const view = renderComposer({ value: patch.value ?? '' });
    return { ...view, button: screen.getByRole('button', { name: '增强提示词' }) };
  }

  it('没写需求就点：把焦点送回输入框并说清缺什么', () => {
    const { button, onChange } = renderEnhance();
    fireEvent.click(button);

    expect(screen.getByRole('status')).toHaveTextContent('先写一句需求');
    expect(document.activeElement).toBe(screen.getByRole('textbox'));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('增强成功：输入框内容被替换，并用 info 语气说明来源', async () => {
    vi.mocked(promptsApi.enhance).mockResolvedValue({
      data: {
        text: '任务：把会议记录整理成周报\n输出格式：Word 文档（docx）',
        source: 'model',
        model: 'deepseek-chat',
        note: '',
      },
      traceId: 'tr_1',
    });
    const { button, onChange } = renderEnhance({ value: '整理成周报' });

    fireEvent.click(button);

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange.mock.calls[0]?.[0]).toContain('任务：把会议记录整理成周报');
    expect(screen.getByRole('status')).toHaveTextContent('可直接修改后发送');
    // 请求带上了当前格式，后端才能按产物类型补结构
    expect(vi.mocked(promptsApi.enhance).mock.calls[0]?.[0]).toMatchObject({
      text: '整理成周报',
      outputFormat: 'docx',
    });
  });

  it('本地规则补全时把「为什么」带给用户', async () => {
    vi.mocked(promptsApi.enhance).mockResolvedValue({
      data: {
        text: '任务：整理成周报\n要求：先结论后依据',
        source: 'rules',
        model: '',
        note: '现在没有可用的模型（演示模式或还没配 Key），已按通用结构补全',
      },
      traceId: 'tr_2',
    });
    const { button, onChange } = renderEnhance({ value: '整理成周报' });

    fireEvent.click(button);

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(screen.getByRole('status')).toHaveTextContent('已按通用结构补全');
  });

  it('失败时原文保留，并说清是哪一步没成', async () => {
    vi.mocked(promptsApi.enhance).mockRejectedValue(new ApiError('模型超时', { code: 'TIMEOUT' }));
    const { button, onChange } = renderEnhance({ value: '整理成周报' });

    fireEvent.click(button);

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('增强失败'));
    expect(screen.getByRole('status')).toHaveTextContent('模型超时');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('请求在飞时标记 aria-busy，避免重复点击', async () => {
    let release: (value: unknown) => void = () => {};
    vi.mocked(promptsApi.enhance).mockReturnValue(
      new Promise((resolve) => {
        release = resolve as (value: unknown) => void;
      }) as ReturnType<typeof promptsApi.enhance>,
    );
    const { button } = renderEnhance({ value: '整理成周报' });

    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-busy', 'true');

    await act(async () => {
      release({
        data: {
          text: '任务：整理成周报\n要求：先结论后依据',
          source: 'model',
          model: 'm',
          note: '',
        },
        traceId: 'tr_3',
      });
    });
    await waitFor(() => expect(button).toHaveAttribute('aria-busy', 'false'));
  });
});

describe('Composer 等确认状态', () => {
  it('等确认时说明「在等什么」，点「去确认」能把卡片滚进视野', () => {
    const onOpenApproval = vi.fn();
    renderComposer({ waitingApproval: true, onOpenApproval });

    // 「在跑」和「停住了等你点一下」是两种状态：文案不能混
    expect(screen.getByText('有一步要你确认，点了才接着做')).toBeInTheDocument();
    expect(screen.getByLabelText('任务输入框')).toHaveAttribute(
      'placeholder',
      '先确认上一步操作，我再接着做…',
    );

    fireEvent.click(screen.getByRole('button', { name: '去确认' }));
    expect(onOpenApproval).toHaveBeenCalledTimes(1);
  });

  it('平时不显示这条提示', () => {
    renderComposer();
    expect(screen.queryByText('有一步要你确认，点了才接着做')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '去确认' })).not.toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/* 图片 / 会议记录 / 录音 / 视频                                        */
/* ------------------------------------------------------------------ */

describe('Composer 添加媒体素材', () => {
  /** 点开加号菜单：只是一行「添加文件」，不再有类型分支。 */
  function openPlusMenu() {
    renderComposer();
    fireEvent.click(screen.getByRole('button', { name: /更多输入选项/ }));
    return document.querySelector('input[type="file"]') as HTMLInputElement;
  }

  it('「添加文件」直接开系统选择器，不再先问「加什么类型」', () => {
    // 磁盘对话框永远开在同一个位置，分五类也定位不到具体文件夹，
    // 多一层选择只是多一次点击——这条测试就是钉住「别再长回来」。
    const input = openPlusMenu();
    expect(screen.getByRole('menuitem', { name: /添加文件/ })).toBeInTheDocument();
    expect(screen.queryByText('要加什么素材？')).toBeNull();
    expect(screen.queryByRole('menuitem', { name: /^图片/ })).toBeNull();
    expect(screen.queryByRole('menuitem', { name: /^会议录音/ })).toBeNull();

    const click = vi.spyOn(input, 'click').mockImplementation(() => undefined);
    fireEvent.click(screen.getByRole('menuitem', { name: /添加文件/ }));

    expect(click).toHaveBeenCalledTimes(1);
    // 一次给全：文档 + 图片 + 录音 + 视频都在同一个 accept 里，选完再识别
    for (const ext of ['.docx', '.pdf', '.png', '.mp3', '.mp4', '.srt']) {
      expect(input.accept).toContain(ext);
    }
    // 点完菜单要收起，别压在系统对话框后面
    expect(screen.queryByRole('menu', { name: '更多输入选项' })).toBeNull();
  });

  it('拖进来：任何后缀都收下，交给后端判断（不再在前端筛一遍）', async () => {
    const { onUploadFiles } = renderComposer();
    const shot = new File(['x'], '周会截图.png', { type: 'image/png' });
    const doc = new File(['x'], '旧合同.doc', { type: 'application/msword' });
    const apk = new File(['x'], '安装包.apk', { type: 'application/vnd.android.package-archive' });

    fireEvent.drop(screen.getByLabelText('任务输入框'), {
      dataTransfer: { files: [shot, doc, apk], types: ['Files'] },
    });

    // 认不出的格式也进上传：后端收下并说明「读不出文字」，比在前端拦掉有用
    await waitFor(() => expect(onUploadFiles).toHaveBeenCalledTimes(1));
    expect(onUploadFiles.mock.calls[0]?.[0]).toEqual([shot, doc, apk]);
    expect(screen.queryByText(/暂不支持/)).toBeNull();
  });

  it('拖的是文件但浏览器没给内容：说清楚，并直接把选择框打开', async () => {
    const { onUploadFiles } = renderComposer();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const picker = vi.spyOn(input, 'click').mockImplementation(() => undefined);

    fireEvent.drop(screen.getByLabelText('任务输入框'), {
      dataTransfer: { files: [], items: [], types: ['Files'] },
    });

    expect(await screen.findByText(/没带文件内容/)).toBeInTheDocument();
    // 死路变活路：弹选择框，用户选一下同一个文件就进去了
    expect(picker).toHaveBeenCalledTimes(1);
    expect(onUploadFiles).not.toHaveBeenCalled();
  });

  it('拖的根本不是文件（页面上的文字/图片）：说清楚，不乱弹选择框', async () => {
    const { onUploadFiles } = renderComposer();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const picker = vi.spyOn(input, 'click').mockImplementation(() => undefined);

    fireEvent.drop(screen.getByLabelText('任务输入框'), {
      dataTransfer: { files: [], items: [], types: ['text/plain'] },
    });

    expect(await screen.findByText(/拖的是页面上的内容/)).toBeInTheDocument();
    expect(picker).not.toHaveBeenCalled();
    expect(onUploadFiles).not.toHaveBeenCalled();
  });

  it('拖到输入框以外也能加：窗口兜底转过来的 drop 走同一条路', async () => {
    const { onUploadFiles } = renderComposer();
    const file = new File(['x'], '投标材料.zip', { type: 'application/zip' });

    // 用户在左栏 / 对话区松手时，drop-guard 拦下导航，把 dataTransfer 转到这里
    act(() => {
      window.dispatchEvent(
        new CustomEvent(DROP_FILES_EVENT, {
          detail: { dataTransfer: { files: [file], types: ['Files'] } },
        }),
      );
    });

    await waitFor(() => expect(onUploadFiles).toHaveBeenCalledTimes(1));
    expect(onUploadFiles.mock.calls[0]?.[0]).toEqual([file]);
  });

  it('收下但读不出文字：写「读不出文字」，不当成失败标红', () => {
    renderComposer({
      uploads: [
        upload({
          filename: '旧合同.doc',
          ext: '.doc',
          chars: 0,
          preview: undefined,
          note: '这是旧版 Word 格式（.doc），里面的文字读不出来；用 Word/WPS 另存为 .docx 后再传就能读',
        }),
      ],
    });
    const label = screen.getByText('读不出文字');
    expect(label).toBeInTheDocument();
    // 文件确实收下了，不是「失败」——红框会让人以为要重传
    expect(screen.queryByText('失败')).toBeNull();
  });

  it('识别中：徽标报类别、转圈并写「识别中…」（不是「失败」也不是空转）', () => {
    renderComposer({
      uploads: [
        upload({
          filename: '周会截图.png',
          ext: '.png',
          media_kind: 'image',
          media_status: 'processing',
          chars: undefined,
          preview: undefined,
        }),
      ],
    });
    expect(screen.getByText('图片')).toBeInTheDocument();
    expect(screen.getByText('识别中…')).toBeInTheDocument();
    expect(screen.queryByText('失败')).toBeNull();
  });

  it('识别失败：标红、给原因、带「重试」，点它只重跑识别不重传文件', () => {
    const onRetryUpload = vi.fn();
    renderComposer({
      uploads: [
        upload({
          filename: '会议录音.m4a',
          ext: '.m4a',
          media_kind: 'audio',
          media_status: 'failed',
          media_error: '语音识别模型加载失败',
          chars: undefined,
          preview: undefined,
        }),
      ],
      onRetryUpload,
    });
    expect(screen.getByText('会议录音')).toBeInTheDocument();
    expect(screen.getByText('识别失败')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(onRetryUpload).toHaveBeenCalledWith('u1');
  });

  it('识别没完就发送：拦下来并说清「不用重传」', () => {
    const { onSubmit } = renderComposer({
      value: '把这份截图整理成会议纪要',
      uploads: [
        upload({
          filename: '周会截图.png',
          ext: '.png',
          media_kind: 'image',
          media_status: 'processing',
        }),
      ],
    });
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/还在识别文字/)).toBeInTheDocument();
    expect(screen.getByText(/不用重传/)).toBeInTheDocument();
  });

  it('识别完成后同一份素材可以正常发送', () => {
    const { onSubmit } = renderComposer({
      value: '把这份截图整理成会议纪要',
      uploads: [
        upload({
          filename: '周会截图.png',
          ext: '.png',
          media_kind: 'image',
          media_status: 'ready',
          chars: 58,
        }),
      ],
    });
    fireEvent.click(screen.getByRole('button', { name: /发送/ }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
