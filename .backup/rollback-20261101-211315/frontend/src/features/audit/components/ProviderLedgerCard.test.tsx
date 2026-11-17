/**
 * 官方账单对账卡。
 *
 * 这张卡的存在理由是「别让人怀疑系统在编数据」，所以测试锁的是三件事：
 * 拿到数据时要把差额算清楚、拿不到时要说明白原因、token 输入不能悄悄漏出去。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ProviderUsageOut } from '../../../shared/api/types';
import { ProviderLedgerCard } from './ProviderLedgerCard';

const BASE: ProviderUsageOut = {
  trace_id: 't',
  provider: 'deepseek',
  available: true,
  has_token: true,
  token_preview: 'abcd…wxyz',
  month: '2026-11',
  source: 'https://platform.deepseek.com/api/v0/usage/amount',
  requests: 398,
  tokens: 1_904_847,
  cost_cny: 0.69,
  cache_hit_tokens: 1_500_000,
  cache_miss_tokens: 300_000,
  output_tokens: 104_847,
  days: [],
  fetched_at: '2026-11-01T13:30:00+08:00',
  note: '官方口径：按平台账单统计。',
};

const LOCAL = { cost: 0.05, calls: 16, tokens: 119_524 };

function renderCard(data: ProviderUsageOut | null = BASE, local = LOCAL) {
  return render(
    <ProviderLedgerCard
      data={data}
      loading={false}
      local={local}
      onRefresh={() => {}}
      onSaveToken={async () => {}}
    />,
  );
}

describe('ProviderLedgerCard', () => {
  it('拿官方和本地两本账并排显示，差额单独点出来', () => {
    renderCard();
    expect(screen.getByText('官方账单')).toBeTruthy();
    expect(screen.getByText('¥0.69')).toBeTruthy();
    expect(screen.getByText('398')).toBeTruthy();
    // 差额 = 官方 0.69 - 本地 0.05；文案和数字在同一段里，用正则定位
    expect(screen.getByText(/差额\s*¥0\.64/)).toBeTruthy();
    expect(screen.getByText(/本应用之外的消耗/)).toBeTruthy();
  });

  it('没填 token 时给出输入口，并说明官方接口不认 API Key', () => {
    renderCard({
      trace_id: 't',
      provider: 'deepseek',
      available: false,
      has_token: false,
      error: { code: 'NO_TOKEN', message: '还没有填写官方 token。' },
    });
    expect(screen.getByLabelText('官方用量 token')).toBeTruthy();
    expect(screen.getByText(/不接受 API Key/)).toBeTruthy();
  });

  it('token 过期时提示重新获取，而不是静默显示 0', () => {
    renderCard({
      trace_id: 't',
      provider: 'deepseek',
      available: false,
      has_token: true,
      error: { code: 'TOKEN_EXPIRED', message: '官方 token 已失效（返回 40002/40003）。' },
    });
    expect(screen.getByText('token 已失效')).toBeTruthy();
    expect(screen.getByLabelText('官方用量 token')).toBeTruthy();
  });

  it('保存 token 走回调，输入框只提交用户粘贴的值', async () => {
    const onSaveToken = vi.fn().mockResolvedValue(undefined);
    render(
      <ProviderLedgerCard
        data={{
          trace_id: 't',
          provider: 'deepseek',
          available: false,
          has_token: false,
          error: { code: 'NO_TOKEN', message: '' },
        }}
        loading={false}
        local={LOCAL}
        onRefresh={() => {}}
        onSaveToken={onSaveToken}
      />,
    );

    fireEvent.change(screen.getByLabelText('官方用量 token'), {
      target: { value: '  my-user-token-value  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => expect(onSaveToken).toHaveBeenCalledWith('my-user-token-value'));
  });

  it('两边一致时不再硬造一个差额', () => {
    renderCard(BASE, { cost: 0.69, calls: 398, tokens: 1_904_847 });
    expect(screen.getByText(/两边一致/)).toBeTruthy();
  });
});
