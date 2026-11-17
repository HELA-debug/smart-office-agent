/**
 * 模型列表：界面用「deepseek harness / WorkBuddy」这类可读名，
 * 但真正传给后端的仍是 provider 标识。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ModelListCard } from './ModelListCard';
import type { ModelOut } from '../api';

function model(overrides: Partial<ModelOut> & Pick<ModelOut, 'provider'>): ModelOut {
  return {
    id: `env:${overrides.provider}`,
    base_url: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    api_key_ref: `env:${overrides.provider.toUpperCase()}_API_KEY`,
    configured: true,
    enabled: true,
    priority: 0,
    builtin: true,
    last_probe: null,
    extra: {},
    ...overrides,
  } as ModelOut;
}

const MODELS: ModelOut[] = [
  model({ provider: 'deepseek' }),
  model({
    provider: 'workbuddy',
    base_url: '',
    model: 'workbuddy-chat',
    configured: false,
    api_key_ref: 'env:WORKBUDDY_API_KEY',
  }),
];

function renderCard(overrides: Partial<Parameters<typeof ModelListCard>[0]> = {}) {
  const props = {
    models: MODELS,
    activeProvider: 'deepseek',
    testing: null,
    testResult: {},
    keyNotice: null,
    onTest: vi.fn(),
    onAddKey: vi.fn(),
    onEditEndpoint: vi.fn(),
    onDisconnect: vi.fn(),
    disconnecting: null,
    ...overrides,
  };
  render(<ModelListCard {...props} />);
  return props;
}

describe('ModelListCard', () => {
  it('按可读名展示供应商，deepseek 显示为 deepseek harness', () => {
    renderCard();
    expect(screen.getByText('deepseek harness')).toBeTruthy();
    expect(screen.getByText('WorkBuddy')).toBeTruthy();
    // 标识本身不再出现在标题行
    expect(screen.queryByText('deepseek')).toBeNull();
  });

  it('WorkBuddy 没填接口时提示的是「缺地址」，并给出填接口入口', () => {
    const props = renderCard();
    expect(screen.getByText('接口地址待填')).toBeTruthy();
    expect(screen.getByText(/还差接口地址/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /设置 WorkBuddy 的接口地址/ }));
    expect(props.onEditEndpoint).toHaveBeenCalledWith(
      expect.objectContaining({ provider: 'workbuddy' }),
    );
  });

  it('已填接口的供应商显示地址本身，按钮变成「改」', () => {
    renderCard();
    expect(screen.getByText('https://api.deepseek.com/v1')).toBeTruthy();
    expect(screen.getByRole('button', { name: /设置 deepseek harness 的接口地址/ })).toBeTruthy();
  });

  it('每行只留「测试连接 / 添加 Key 或 断开」：没有多余的「选择」按钮', () => {
    renderCard();
    // 「选择」重复出现在每一行，跟左边的「模型供应商」下拉做同一件事，已下线
    expect(screen.queryByRole('button', { name: /^选择/ })).toBeNull();
    expect(screen.getAllByRole('button', { name: '测试连接' })).toHaveLength(2);
    // 已配置的行给「断开」，未配置的行给「添加 Key」：一行不会两个都有
    expect(screen.getAllByRole('button', { name: '断开' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: '添加 Key' })).toHaveLength(1);
    // 换主模型的入口写在卡片底部，别让人找不到
    expect(screen.getByText(/在左边「模型供应商」里选/)).toBeTruthy();
  });

  it('已配置的行点「断开」触发回调（分享/部署前把 Key 从本机清掉）', () => {
    const props = renderCard();
    fireEvent.click(screen.getByRole('button', { name: '断开' }));
    expect(props.onDisconnect).toHaveBeenCalledWith(
      expect.objectContaining({ provider: 'deepseek' }),
    );
  });

  it('「当前使用」只挂在真正生效的那一行（内置供应商 priority 全是 0，不能按它判断）', () => {
    renderCard();
    const badges = screen.getAllByText('当前使用');
    expect(badges).toHaveLength(1);
    expect(badges[0]?.closest('div')?.textContent).toContain('deepseek harness');
  });
});
