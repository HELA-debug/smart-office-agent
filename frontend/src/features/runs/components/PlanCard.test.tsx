import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { PlanCard } from './PlanCard';
import type { PlanSnapshot } from '../../../shared/types/view';

const plan: PlanSnapshot = {
  run_id: 'r_1',
  updated_at: '2026-10-23T10:00:00+08:00',
  todos: [
    { id: 't1', content: '读取上传材料', status: 'completed' },
    { id: 't2', content: '提炼周报要点', status: 'in_progress' },
    { id: 't3', content: '生成 DOCX 周报', status: 'pending' },
    { id: 't4', content: '生成报告产物（需审批）', status: 'pending' },
  ],
};

describe('PlanCard', () => {
  it('默认收起：一行显示进度与当前步骤', () => {
    render(<PlanCard plan={plan} />);

    expect(screen.getByText('执行计划')).toBeInTheDocument();
    expect(screen.getByText('1/4 已完成')).toBeInTheDocument();
    // 收起态只留当前在做什么，不铺开全部步骤
    expect(screen.getByText(/正在：提炼周报要点/)).toBeInTheDocument();
    expect(screen.queryByText('读取上传材料')).not.toBeInTheDocument();
  });

  it('点开后展开全部步骤，进行中高亮', async () => {
    const user = userEvent.setup();
    render(<PlanCard plan={plan} />);

    await user.click(screen.getByRole('button', { name: /执行计划/ }));
    expect(screen.getByText('读取上传材料')).toBeInTheDocument();
    expect(screen.getByText('进行中')).toBeInTheDocument();
    expect(screen.getByText('生成 DOCX 周报')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /执行计划/ }));
    expect(screen.queryByText('读取上传材料')).not.toBeInTheDocument();
  });

  it('空计划与加载态有三态兜底', () => {
    render(<PlanCard plan={null} />);
    expect(screen.getByText('计划尚未生成')).toBeInTheDocument();
  });

  it('全部完成时收成一行淡字，点开才看步骤', async () => {
    const user = userEvent.setup();
    render(
      <PlanCard
        plan={{
          ...plan,
          todos: plan.todos.map((todo) => ({ ...todo, status: 'completed' as const })),
        }}
      />,
    );

    // 结束后不再占一整块卡片，只剩一行摘要
    // 步数不进界面：完成就该只说「完成」
    expect(screen.getByText('执行计划已完成')).toBeInTheDocument();
    expect(screen.queryByText('全部步骤已完成')).not.toBeInTheDocument();
    expect(screen.queryByText('读取上传材料')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /执行计划已完成/ }));
    expect(screen.getByText('读取上传材料')).toBeInTheDocument();
  });
});
