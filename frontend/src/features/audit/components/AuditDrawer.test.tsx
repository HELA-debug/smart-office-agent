/**
 * 审计抽屉：每轮运行要能说清「这次到底调没调外部模型」。
 *
 * 真实调用要把供应商给的请求 id 摆出来（拿去控制台对账），
 * 没拿到回执的要明说，本地 mock 的直接写「不调用外部模型」——
 * 三种情况混成一句「已完成」，用户就分不清是真花钱还是本地演的。
 */
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AuditDrawer } from './AuditDrawer';
import type { AuditViewState } from '../../../shared/types/view';

function drawer(run: Record<string, unknown>): AuditViewState {
  return {
    open: true,
    status: 'ready',
    error: null,
    data: {
      trace_id: 'tr_test',
      thread_id: 'th_1',
      thread_title: '调用凭据自检',
      runs: [
        {
          run_id: 'r_1',
          started_at: '2026-10-31T10:00:00+08:00',
          finished_at: '2026-10-31T10:00:10+08:00',
          status: 'completed',
          mode: 'real',
          engine: 'real',
          provider: 'deepseek',
          model: 'deepseek-chat',
          tokens: 6200,
          cost_cny: 0.02,
          elapsed_ms: 10_000,
          error_code: null,
          degraded: false,
          request_ids: [],
          calls: 0,
          verified_calls: 0,
          approvals: [],
          artifacts: [],
          ...run,
        },
      ],
      approvals: [],
      artifacts: [],
    },
  } as AuditViewState;
}

const noop = vi.fn();

describe('AuditDrawer 调用回执', () => {
  it('真实调用摆出供应商请求 id，并标注几次带回执', () => {
    render(
      <AuditDrawer
        audit={drawer({
          request_ids: ['db7bcb64-d901-4e91-a749-0abd8a32dff5'],
          calls: 2,
          verified_calls: 2,
        })}
        onClose={noop}
        onRetry={noop}
      />,
    );

    expect(screen.getByText('请求 id')).toBeTruthy();
    // 只露前 8 位，完整值放在 title 里，不把一眼看不完的 uuid 糊一屏
    const chip = screen.getByTitle('db7bcb64-d901-4e91-a749-0abd8a32dff5');
    expect(chip).toHaveTextContent('db7bcb64…');
    expect(screen.getByText('2/2 次带回执')).toBeTruthy();
  });

  it('没拿到回执就说清楚，不假装是真实调用', () => {
    render(
      <AuditDrawer
        audit={drawer({ request_ids: [], calls: 1, verified_calls: 0 })}
        onClose={noop}
        onRetry={noop}
      />,
    );

    expect(screen.getByText(/没拿到回执/)).toBeTruthy();
    expect(screen.getByText('0/1 次带回执')).toBeTruthy();
  });

  it('配置名与官方回执名不同时，说清按哪个名字计费', () => {
    render(
      <AuditDrawer
        audit={drawer({
          model: 'deepseek-chat',
          provider_model: 'deepseek-flash',
          request_ids: ['01a415c0-5af7-4689-96ea-609d40675176'],
          calls: 2,
          verified_calls: 2,
        })}
        onClose={noop}
        onRetry={noop}
      />,
    );

    expect(screen.getByText(/官方按/)).toBeTruthy();
    expect(screen.getByText('deepseek-flash')).toBeTruthy();
  });

  it('mock 运行不冒充外部调用', () => {
    render(
      <AuditDrawer
        audit={drawer({
          mode: 'mock',
          engine: 'mock',
          provider: 'mock',
          model: 'mock-scripted',
          request_ids: [],
          calls: 0,
          verified_calls: 0,
        })}
        onClose={noop}
        onRetry={noop}
      />,
    );

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('本地 mock 运行：不调用外部模型')).toBeTruthy();
  });
});
