/** 运行过程卡片（工具 / 子智能体）单元测试：加载态、错误态、正常态与展开交互。 */
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { SubagentCard } from './SubagentCard';
import { ToolCard } from './ToolCard';
import type { SubagentItem, ToolCallItem } from '../../../shared/types/view';

function makeTool(overrides: Partial<ToolCallItem> = {}): ToolCallItem {
  return {
    id: 'tc_1',
    run_id: 'run_1',
    tool: 'file.read',
    ok: true,
    risk: 'low',
    summary: '已读取 1 个文件，共 1,200 字',
    duration_ms: 1200,
    input: { files: ['会议记录.docx'] },
    output: { chars: 1200 },
    created_at: '2026-10-24T10:00:00Z',
    ...overrides,
  };
}

describe('ToolCard', () => {
  it('加载态显示骨架', () => {
    render(<ToolCard tool={makeTool()} loading />);
    expect(screen.getAllByText(/正在调用工具/).length).toBeGreaterThan(0);
  });

  it('错误态显示 CardError', () => {
    render(<ToolCard tool={makeTool()} loadError="工具执行失败" />);
    expect(screen.getByText('工具执行失败')).toBeTruthy();
  });

  it('正常态展示中文工具名与耗时摘要', () => {
    render(<ToolCard tool={makeTool()} />);
    expect(screen.getByText('读取文件')).toBeTruthy();
    expect(screen.getByText(/已读取 1 个文件/)).toBeTruthy();
  });

  it('高风险工具展示风险徽标文案', () => {
    render(<ToolCard tool={makeTool({ tool: 'file.delete', risk: 'high' })} />);
    expect(screen.getByText('删除产物')).toBeTruthy();
  });

  it('点击展开后显示入参/出参 JSON', async () => {
    const user = userEvent.setup();
    render(<ToolCard tool={makeTool()} />);
    const trigger = screen.getByRole('button');
    await user.click(trigger);
    expect(await screen.findByText(/会议记录\.docx/)).toBeTruthy();
  });

  it('工具失败但没有异常对象时，不渲染英文 TOOL_ERROR 空壳', () => {
    // 脚本 exit=1 属于「工具返回 ok:false」，没有 error 字段；
    // 以前这里会补一条红色“TOOL_ERROR 工具执行失败”，既重复又吓人。
    render(
      <ToolCard
        tool={makeTool({ tool: 'code.run_python', ok: false, summary: '脚本执行失败：ValueError' })}
      />,
    );
    expect(screen.queryByText('TOOL_ERROR')).toBeNull();
    expect(screen.queryByText('工具执行失败')).toBeNull();
  });

  it('异常详情收在展开里：外层只留一句「这次没成」', () => {
    render(
      <ToolCard
        tool={makeTool({
          tool: 'code.run_python',
          ok: false,
          summary: '这次没成',
          error: { code: 'TOOL_ERROR', message: '磁盘写满了' },
        })}
      />,
    );
    // 红色调用栈摊在流水里，看着像整轮崩了；现在要点开才看得到
    expect(screen.queryByText('磁盘写满了')).toBeNull();
    fireEvent.click(screen.getByRole('button', { expanded: false }));
    expect(screen.getByText('磁盘写满了')).toBeTruthy();
    expect(screen.getByText('TOOL_ERROR')).toBeTruthy();
  });
});

function makeSubagent(overrides: Partial<SubagentItem> = {}): SubagentItem {
  return {
    id: 'sa_1',
    name: 'doc_agent',
    role: '文档撰写',
    status: 'running',
    summary: '正在整理结构',
    tools: ['file.read', 'doc.generate_report'],
    updated_at: '2026-10-24T10:00:00Z',
    ...overrides,
  };
}

describe('SubagentCard', () => {
  it('加载态', () => {
    render(<SubagentCard subagent={null} loading />);
    expect(screen.getByText(/子智能体启动中/)).toBeTruthy();
  });

  it('错误态', () => {
    render(<SubagentCard subagent={null} error="子智能体不可用" />);
    expect(screen.getByText('子智能体不可用')).toBeTruthy();
  });

  it('运行态展示名称与状态', () => {
    render(<SubagentCard subagent={makeSubagent()} />);
    expect(screen.getByText('doc_agent')).toBeTruthy();
    expect(screen.getByText('运行中')).toBeTruthy();
  });

  it('完成态展示已完成', () => {
    render(<SubagentCard subagent={makeSubagent({ status: 'done', summary: '已完成 3 节' })} />);
    expect(screen.getByText('已完成')).toBeTruthy();
  });

  it('失败态展示失败', () => {
    render(<SubagentCard subagent={makeSubagent({ status: 'failed' })} />);
    expect(screen.getByText('失败')).toBeTruthy();
  });
});
