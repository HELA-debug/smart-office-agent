/**
 * 导入技能引导：不能只弹系统文件框，得先把「文件长什么样」交给用户。
 * 文案目标是「照做就行」——所以断言的是步骤与示例，不锁具体措辞以外的术语。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SkillImportGuide } from './SkillImportGuide';

describe('SkillImportGuide', () => {
  it('三步流程与示例都在，主操作不藏在底部工具条', () => {
    render(
      <SkillImportGuide onClose={() => {}} onImport={() => {}} importing={false} notice={null} />,
    );

    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByText('下一张空便签')).toBeTruthy();
    expect(screen.getByText('照着高亮的三行，改成你自己的话')).toBeTruthy();
    expect(screen.getByText('把这个文件选进来')).toBeTruthy();
    expect(screen.getByRole('button', { name: /下载便签/ })).toBeTruthy();
    // 第 3 步的主按钮就在正文里，读完不用再往下找
    expect(screen.getByRole('button', { name: /选文件导入/ })).toBeTruthy();
    // 示例里给出可以直接照抄的写法
    expect(screen.getByText('title: 周报小助手')).toBeTruthy();
  });

  it('不讲实现细节：术语收进「进阶」折叠区', () => {
    render(
      <SkillImportGuide onClose={() => {}} onImport={() => {}} importing={false} notice={null} />,
    );

    // 主流程不提 frontmatter / Markdown
    expect(screen.queryByText(/frontmatter/i)).toBeNull();
    expect(screen.queryByText(/Markdown/)).toBeNull();
    // 可选项默认折叠着
    const details = document.querySelector('details');
    expect(details?.open).toBe(false);
    expect(details?.textContent).toContain('category');
  });

  it('选中文件就把文件交给导入流程', () => {
    const onImport = vi.fn();
    render(
      <SkillImportGuide onClose={() => {}} onImport={onImport} importing={false} notice={null} />,
    );

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['# skill'], 'SKILL.md', { type: 'text/markdown' });
    fireEvent.change(input, { target: { files: [file] } });

    expect(onImport).toHaveBeenCalledWith(file);
    expect(screen.getByText('SKILL.md')).toBeTruthy();
  });

  it('导入结果就地显示：成功给技能名，失败给原因', () => {
    const { unmount } = render(
      <SkillImportGuide
        onClose={() => {}}
        onImport={() => {}}
        importing={false}
        notice="已导入「周报助手」"
      />,
    );
    expect(screen.getByText('已导入「周报助手」')).toBeTruthy();
    unmount();

    render(
      <SkillImportGuide
        onClose={() => {}}
        onImport={() => {}}
        importing={false}
        notice="导入失败：已有同名技能"
      />,
    );
    expect(screen.getByText(/导入失败：已有同名技能/)).toBeTruthy();
  });

  it('接了模型就有「说一句就写」：先给预览，点「就用这张」才导入', async () => {
    const onDraft = vi.fn().mockResolvedValue({
      markdown: '---\nname: demo\ntitle: 演示技能\n---\n\n# 怎么做\n\n1. 读材料',
      name: 'demo',
      title: '演示技能',
      description: '演示用',
      triggers: ['演示'],
      model: 'fake-model',
      source: 'model' as const,
      note: '核对一下步骤对不对',
    });
    const onUseDraft = vi.fn();
    const onImport = vi.fn();

    render(
      <SkillImportGuide
        onClose={() => {}}
        onImport={onImport}
        importing={false}
        notice={null}
        onDraft={onDraft}
        onUseDraft={onUseDraft}
      />,
    );

    fireEvent.change(screen.getByLabelText('一句话说清你要什么'), {
      target: { value: '整理会议纪要' },
    });
    fireEvent.click(screen.getByRole('button', { name: /让模型写一张/ }));

    await waitFor(() => expect(onDraft).toHaveBeenCalledWith('整理会议纪要'));
    expect(await screen.findByText('演示技能')).toBeTruthy();
    // 预览阶段不写盘：此时还没有导入动作
    expect(onImport).not.toHaveBeenCalled();
    expect(screen.getByText(/由 fake-model 写/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /就用这张/ }));
    expect(onUseDraft).toHaveBeenCalledWith(expect.objectContaining({ name: 'demo' }));
  });

  it('没接模型时整块入口不出现（三步流程保持不变）', () => {
    render(
      <SkillImportGuide onClose={() => {}} onImport={() => {}} importing={false} notice={null} />,
    );
    expect(screen.queryByRole('button', { name: /让模型写一张/ })).toBeNull();
    expect(screen.queryByLabelText('一句话说清你要什么')).toBeNull();
  });

  it('模型报错时就地给原因，不弹窗也不清空输入', () => {
    render(
      <SkillImportGuide
        onClose={() => {}}
        onImport={() => {}}
        importing={false}
        notice={null}
        onDraft={async () => null}
        draftError="模型这次没写出内容，换句话再说一次试试"
      />,
    );
    expect(screen.getByText(/换句话再说一次/)).toBeTruthy();
  });
});
