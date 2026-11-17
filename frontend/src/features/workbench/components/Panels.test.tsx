/**
 * 右栏与输入区的辅助面板：运行摘要卡、快捷入口。
 * 快捷入口会打 /usage/summary 与 /models，用假 api 覆盖 loading / ready / error / 重试 四条路径。
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { formatCost } from '../../../shared/lib/format';
import { ComposerQuickAccess } from './ComposerQuickAccess';
import { RunSummaryCard } from './RunSummaryCard';
import type { UsageSummary } from '../state/workbench';

const usageMock = vi.hoisted(() => ({ getUsageSummary: vi.fn() }));
const modelMock = vi.hoisted(() => ({
  listModels: vi.fn(),
  updateSettings: vi.fn(),
  getBalance: vi.fn(),
}));

vi.mock('../../audit', () => ({
  auditApi: { getUsageSummary: usageMock.getUsageSummary },
}));

vi.mock('../../settings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../settings')>();
  return {
    ...actual,
    settingsApi: {
      ...actual.settingsApi,
      listModels: modelMock.listModels,
      updateSettings: modelMock.updateSettings,
      getBalance: modelMock.getBalance,
    },
  };
});

function usageOut(range: string, patch: Record<string, unknown> = {}) {
  return {
    data: {
      trace_id: 'tr',
      range,
      runs: 12,
      real_runs: 9,
      mock_runs: 3,
      tokens: 34_567,
      cost_cny: 1.23,
      cache_hit_tokens: 3_456,
      cache_miss_tokens: 31_111,
      price_note: '按官方闲时价估算：输入未命中 ¥1、命中 ¥0.02、输出 ¥4 每百万 tokens',
      elapsed_ms: 90_000,
      avg_elapsed_ms: 7_500,
      by_status: { completed: 12 },
      by_provider: [{ provider: 'deepseek', runs: 12, tokens: 34_567, cost_cny: 1.23 }],
      // 官方回执里的真实模型名：控制台账单按它归类
      by_model: [{ model: 'deepseek-flash', runs: 12, tokens: 34_567, cost_cny: 1.23 }],
      by_day: [],
      ...patch,
    },
    traceId: 'tr',
  };
}

function summary(patch: Partial<UsageSummary> = {}): UsageSummary {
  return {
    run_id: 'r1',
    status: 'completed',
    tokens: 8123,
    cost_cny: 0.06,
    elapsed_ms: 41_700,
    artifact_ids: ['a1'],
    approvals: [],
    degraded: false,
    ...patch,
  };
}

/* ------------------------------------------------------------------ */
/* RunSummaryCard                                                      */
/* ------------------------------------------------------------------ */

describe('RunSummaryCard', () => {
  it('完成的运行：一行给出产物数与消耗', () => {
    render(
      <RunSummaryCard usage={summary()} artifactCount={2} auditEnabled onOpenAudit={vi.fn()} />,
    );

    expect(screen.getByText('运行完成')).toBeInTheDocument();
    expect(screen.getByText('产物 2 个')).toBeInTheDocument();
    expect(screen.getByText('共消耗 8,123 tokens')).toBeInTheDocument();
    expect(screen.getByText('¥0.06')).toBeInTheDocument();
    // 三栏仪表盘（耗时单列）已删除，不再出现这些字样
    expect(screen.queryByText('耗时')).toBeNull();
  });

  it('审批被拒绝：标题变警示文案', () => {
    render(
      <RunSummaryCard
        usage={summary({ status: 'rejected' })}
        artifactCount={0}
        auditEnabled
        onOpenAudit={vi.fn()}
      />,
    );
    expect(screen.getByText('运行结束（审批被拒绝，产物已保留）')).toBeInTheDocument();
  });

  it('产物数回落 usage.artifact_ids', () => {
    render(
      <RunSummaryCard
        usage={summary()}
        artifactCount={0}
        auditEnabled={false}
        onOpenAudit={vi.fn()}
      />,
    );
    expect(screen.getByText('产物 1 个')).toBeInTheDocument();
  });

  it('审计入口受开关控制', () => {
    const onOpenAudit = vi.fn();
    const { unmount } = render(
      <RunSummaryCard
        usage={summary()}
        artifactCount={1}
        auditEnabled={false}
        onOpenAudit={onOpenAudit}
      />,
    );
    expect(screen.queryByRole('button', { name: /查看审计记录/ })).toBeNull();
    unmount();

    render(
      <RunSummaryCard usage={summary()} artifactCount={1} auditEnabled onOpenAudit={onOpenAudit} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /查看审计记录/ }));
    expect(onOpenAudit).toHaveBeenCalledTimes(1);
  });
});

/* ------------------------------------------------------------------ */
/* ComposerQuickAccess                                                 */
/* ------------------------------------------------------------------ */

const MODEL_ROWS = [
  {
    id: 'env:deepseek',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    api_key_ref: 'env:DEEPSEEK_API_KEY',
    configured: true,
    enabled: true,
    priority: 0,
    builtin: true,
    last_probe: null,
    extra: {},
  },
  {
    id: 'env:qwen',
    provider: 'qwen',
    base_url: '',
    model: 'qwen-plus',
    api_key_ref: 'env:QWEN_API_KEY',
    configured: false,
    enabled: true,
    priority: 0,
    builtin: true,
    last_probe: null,
    extra: {},
  },
];

describe('ComposerQuickAccess', () => {
  beforeEach(() => {
    usageMock.getUsageSummary.mockImplementation((options: { range?: string }) =>
      Promise.resolve(usageOut(options.range ?? '7d')),
    );
    modelMock.listModels.mockResolvedValue({
      data: { trace_id: 'tr', models: MODEL_ROWS },
      traceId: 'tr',
    });
    modelMock.updateSettings.mockResolvedValue({ data: {}, traceId: 'tr' });
    modelMock.getBalance.mockResolvedValue({
      data: {
        trace_id: 'tr',
        supported: true,
        provider: 'deepseek',
        currency: 'CNY',
        total_balance: 6.37,
        granted_balance: 5.48,
        topped_up_balance: 0.89,
        checked_at: '2026-10-31T11:48:00+08:00',
      },
      traceId: 'tr',
    });
  });

  function renderAccess(
    props: { model?: string | null; isMock?: boolean; onModelChanged?: () => void } = {},
  ) {
    return render(
      <MemoryRouter>
        <ComposerQuickAccess
          model={props.model ?? null}
          isMock={props.isMock ?? false}
          onModelChanged={props.onModelChanged}
        />
      </MemoryRouter>,
    );
  }

  const trigger = () => screen.getByRole('button', { name: '模型与用量' });

  it('工具栏只有一个入口：收起时直接写当前模型名', () => {
    renderAccess({ model: 'deepseek-chat' });

    // 以前「当前用量」「模型选择」是两个并排图标，现在合成一个胶囊
    expect(screen.queryByRole('button', { name: '当前用量' })).toBeNull();
    expect(screen.queryByRole('button', { name: '模型选择' })).toBeNull();
    expect(trigger()).toHaveTextContent('deepseek-chat');
    expect(screen.queryByRole('link', { name: /前往设置管理/ })).toBeNull();
  });

  it('展开后模型列表与近 7 天用量在同一处', async () => {
    renderAccess({ model: 'deepseek-chat', isMock: true });
    fireEvent.click(trigger());

    const panel = screen.getByRole('dialog', { name: '模型与用量' });
    expect(await screen.findByText('deepseek-chat')).toBeInTheDocument();
    expect(panel).toHaveTextContent('1 个已配置 / 共 2 个');
    expect(panel).toHaveTextContent('本地 mock');
    expect(panel).toHaveTextContent('qwen-plus');
    expect(panel).toHaveTextContent('未配置');
    expect(panel).toHaveTextContent('近 7 天用量');
    await waitFor(() => expect(panel).toHaveTextContent(formatCost(1.23)));
    expect(panel).toHaveTextContent('34,567');
    // 只有真实调用算费用
    expect(panel).toHaveTextContent('真实调用');
    // 面板正文只留三个数字 + 余额：单价/命中率/实扣模型/mock 次数这些解释性文案
    // 既长又被截断，用户明确要求删掉，改为挂在「成本估算」的悬停提示上
    expect(panel).not.toHaveTextContent('另有本地 mock');
    expect(panel).not.toHaveTextContent('官方实扣模型');
    expect(panel).not.toHaveTextContent('按官方');
    expect(panel).not.toHaveTextContent('输入缓存命中');
    expect(screen.getByRole('link', { name: /前往设置管理/ })).toHaveAttribute('href', '/settings');
  });

  it('花费口径不占正文：悬在成本上才显示单价，余额拆成充值/赠送', async () => {
    renderAccess({ model: 'deepseek-chat' });
    fireEvent.click(trigger());
    const panel = screen.getByRole('dialog', { name: '模型与用量' });

    // 口径挪进 title：正文里一个字都不占，需要时鼠标一停就能看到
    await waitFor(() => expect(panel).toHaveTextContent(formatCost(1.23)));
    const costCell = screen.getByText('成本估算').parentElement;
    expect(costCell?.getAttribute('title')).toContain('每百万 tokens');
    expect(panel).not.toHaveTextContent('每百万 tokens');

    // 余额拆成官网那两项：合计=充值+赠送，数字对得上才敢说「就是同一个账号」
    await waitFor(() => expect(panel).toHaveTextContent('充值 ¥0.89'));
    expect(panel).toHaveTextContent('赠送 ¥5.48');
    expect(panel).toHaveTextContent('¥6.37');
    expect(screen.getByRole('button', { name: '刷新账户余额' })).toBeInTheDocument();
  });

  it('点刷新会重新问一次官方余额（不拿缓存糊弄）', async () => {
    renderAccess({ model: 'deepseek-chat' });
    fireEvent.click(trigger());
    await waitFor(() => expect(modelMock.getBalance).toHaveBeenCalledTimes(1));

    modelMock.getBalance.mockResolvedValueOnce({
      data: {
        trace_id: 'tr',
        supported: true,
        provider: 'deepseek',
        currency: 'CNY',
        total_balance: 6.35,
        granted_balance: 5.46,
        topped_up_balance: 0.89,
        checked_at: '2026-10-31T11:55:00+08:00',
      },
      traceId: 'tr',
    });
    fireEvent.click(screen.getByRole('button', { name: '刷新账户余额' }));
    await waitFor(() => expect(modelMock.getBalance).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: '模型与用量' })).toHaveTextContent('¥6.35'),
    );
  });

  it('当前用的是哪个一眼能看出来：深底色 + 描边，已配置的写绿', async () => {
    renderAccess({ model: 'deepseek-chat' });
    fireEvent.click(trigger());

    // 收起态按钮上也写着模型名，这里只在浮层里找那一行
    const panel = screen.getByRole('dialog', { name: '模型与用量' });
    const currentRow = (await within(panel).findByText('deepseek-chat')).closest('button');
    expect(currentRow).toHaveAttribute('aria-pressed', 'true');
    // 底色比普通行深一档，还多一圈品牌色描边
    expect(currentRow?.className).toContain('bg-brand-soft-strong');
    expect(currentRow?.className).toContain('ring-brand-line');

    expect(within(panel).getByText('未配置').className).toContain('text-faint');
  });

  it('已配置但没在用的写绿色「可用」，跟灰色未配置分开', async () => {
    // 当前模型不在列表里（比如刚改过设置还没刷新），deepseek-chat 就退成「可用」
    renderAccess({ model: 'not-in-list' });
    fireEvent.click(trigger());

    const panel = screen.getByRole('dialog', { name: '模型与用量' });
    expect((await within(panel).findByText('可用')).className).toContain('text-ok');
    expect(within(panel).getByText('未配置').className).toContain('text-faint');
  });

  it('点已配置的模型会写回设置并刷新外层', async () => {
    const onModelChanged = vi.fn();
    renderAccess({ model: 'mock-scripted', onModelChanged });
    fireEvent.click(trigger());

    fireEvent.click(await screen.findByText('deepseek-chat'));

    await waitFor(() =>
      expect(modelMock.updateSettings).toHaveBeenCalledWith({
        model_provider: 'deepseek',
        model_name: 'deepseek-chat',
      }),
    );
    expect(onModelChanged).toHaveBeenCalled();
    expect(await screen.findByText(/已切换到 deepseek-chat/)).toBeInTheDocument();
  });

  it('未配置 Key 的模型是禁用态，点不动', async () => {
    renderAccess();
    fireEvent.click(trigger());

    const row = await screen.findByText('qwen-plus');
    expect(row.closest('button')).toBeDisabled();
    expect(modelMock.updateSettings).not.toHaveBeenCalled();
  });

  it('再次点击同一个按钮收起', () => {
    renderAccess();
    fireEvent.click(trigger());
    expect(screen.getByRole('dialog', { name: '模型与用量' })).toBeInTheDocument();
    fireEvent.click(trigger());
    expect(screen.queryByRole('dialog', { name: '模型与用量' })).toBeNull();
  });

  it('点击面板外部 / 按 Esc 都收起', () => {
    renderAccess();
    fireEvent.click(trigger());
    expect(screen.getByRole('link', { name: /前往设置管理/ })).toBeInTheDocument();

    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole('link', { name: /前往设置管理/ })).toBeNull();

    fireEvent.click(trigger());
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('link', { name: /前往设置管理/ })).toBeNull();
  });

  it('用量接口失败时面板显示错误态', async () => {
    usageMock.getUsageSummary.mockRejectedValue(new Error('挂了'));
    renderAccess();
    fireEvent.click(trigger());
    await waitFor(() => expect(screen.getByText(/加载失败/)).toBeInTheDocument());
  });
});
