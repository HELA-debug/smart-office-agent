/**
 * 加号菜单里的技能面板：勾选启用 / 删除二次确认 / 导入引导入口。
 * 这些动作都会改后端状态，交互上要防手滑（删除必须点两下）。
 * 开关与 Esc 由外层菜单负责（见 Composer 的「加号菜单」用例），这里只测面板内容。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SkillsPanel } from './SkillsPanel';
import type { SkillItem } from '../api';

function makeSkill(overrides: Partial<SkillItem> = {}): SkillItem {
  return {
    name: '周报助手',
    title: '周报助手',
    description: '按周报骨架整理材料',
    triggers: ['周报'],
    enabled: true,
    category: '办公文档',
    icon: 'doc',
    badge: '',
    content_chars: 320,
    ...overrides,
  };
}

function renderPanel(props: Partial<React.ComponentProps<typeof SkillsPanel>> = {}) {
  const handlers = {
    onToggle: vi.fn(),
    onRemove: vi.fn(),
    onImportGuide: vi.fn(),
  };
  render(
    <MemoryRouter>
      <SkillsPanel
        items={[makeSkill()]}
        status="ready"
        promptChars={1360}
        busyName={null}
        notice={null}
        {...handlers}
        {...props}
      />
    </MemoryRouter>,
  );
  return handlers;
}

describe('SkillsPanel', () => {
  it('显示已启用数量、提示词字数与技能条目', () => {
    renderPanel();

    expect(screen.getByText('周报助手')).toBeTruthy();
    expect(screen.getByText(/1\/1 启用 · 提示词 1360 字/)).toBeTruthy();
    expect(screen.getByRole('link', { name: /管理/ })).toBeTruthy();
    expect(screen.getByText('按周报骨架整理材料')).toBeTruthy();
  });

  it('勾选复选框立刻回调启停', () => {
    const { onToggle } = renderPanel();

    fireEvent.click(screen.getByLabelText('启用技能 周报助手'));
    expect(onToggle).toHaveBeenCalledWith('周报助手', false);
  });

  it('删除要点两下：先确认再删', () => {
    const { onRemove } = renderPanel();

    fireEvent.click(screen.getByRole('button', { name: '删除技能 周报助手' }));
    expect(onRemove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    expect(onRemove).toHaveBeenCalledWith('周报助手');
  });

  it('取消删除不会回调', () => {
    const { onRemove } = renderPanel();

    fireEvent.click(screen.getByRole('button', { name: '删除技能 周报助手' }));
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(onRemove).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '删除技能 周报助手' })).toBeTruthy();
  });

  it('点「导入技能」走引导，不在这里直接弹系统文件框', () => {
    const { onImportGuide } = renderPanel();

    // 直接弹文件框等于把「文件该长什么样」的门槛留给了用户，导入要先给引导
    expect(document.querySelector('input[type="file"]')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '导入技能' }));
    expect(onImportGuide).toHaveBeenCalledTimes(1);
  });

  it('没有技能时给导入提示', () => {
    renderPanel({ items: [] });
    expect(screen.getByText(/还没有技能，点下面「导入技能」建一个试试/)).toBeTruthy();
  });

  it('读取失败时说明后端没在跑，而不是留一片空白', () => {
    renderPanel({ status: 'error' });
    expect(screen.getByText(/读不到技能列表/)).toBeTruthy();
  });

  it('导入结果就地显示在页脚', () => {
    renderPanel({ notice: '已导入：演示技能' });
    expect(screen.getByText('已导入：演示技能')).toBeTruthy();
  });
});
