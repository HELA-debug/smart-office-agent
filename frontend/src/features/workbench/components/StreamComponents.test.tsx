/**
 * 工作台展示组件：Markdown / 气泡 / 思考块 / 流容器 / 状态栏 / 空态。
 *
 * 这些组件没有业务请求，测的是「给定状态渲染成什么样」——
 * 容易写、但恰好是分支最密集的一层（流式中 / 折叠 / 降级 / 断线 / 未连接…）。
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setThinkingView } from '../../../shared/lib/thinking-pref';
import { Markdown } from '../../../shared/ui/Markdown';
import { ChatStream } from './ChatStream';
import { EmptyState } from './EmptyState';
import { MessageBubble } from './MessageBubble';
import { StatusBar } from './StatusBar';
import { ThinkingBlock } from './ThinkingBlock';
import type { ArtifactItem, PlanSnapshot } from '../../../shared/types/view';
import type { ChatMessage, HealthState, ThinkingItem, TimelineItem } from '../state/workbench';

const AT = '2026-10-24T12:00:00.000Z';

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'm1',
    role: 'assistant',
    content: '正文',
    streaming: false,
    created_at: AT,
    ...overrides,
  };
}

function thinking(overrides: Partial<ThinkingItem> = {}): ThinkingItem {
  return {
    id: 'th1',
    content: '先读材料再写文档',
    streaming: false,
    collapsed: true,
    created_at: AT,
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/* Markdown                                                            */
/* ------------------------------------------------------------------ */

describe('Markdown', () => {
  it('标题 / 段落 / 列表 / 引用 / 分割线 / 代码块都能渲染', () => {
    const { container } = render(
      <Markdown
        text={[
          '# 一级标题',
          '',
          '普通段落，含 **加粗**、`行内代码` 与 [链接](https://example.com)。',
          '',
          '- 无序一',
          '- 无序二',
          '',
          '1. 有序一',
          '2. 有序二',
          '',
          '> 引用一段',
          '',
          '---',
          '',
          '```ts',
          'const a = 1;',
          '```',
        ].join('\n')}
      />,
    );

    expect(screen.getByText('一级标题')).toBeInTheDocument();
    expect(screen.getByText('加粗').tagName).toBe('STRONG');
    expect(screen.getByText('行内代码').tagName).toBe('CODE');
    const link = screen.getByRole('link', { name: '链接' });
    expect(link).toHaveAttribute('href', 'https://example.com');
    expect(link).toHaveAttribute('rel', 'noreferrer');

    expect(screen.getByText('无序一').closest('ul')).not.toBeNull();
    expect(screen.getByText('有序一').closest('ol')).not.toBeNull();
    expect(screen.getByText('引用一段').closest('blockquote')).not.toBeNull();
    expect(container.querySelector('hr')).not.toBeNull();
    expect(screen.getByText('const a = 1;')).toBeInTheDocument();
    // 代码块右上角显示语言
    expect(screen.getByText('ts')).toBeInTheDocument();
  });

  it('代码块未标语言时回落展示 code', () => {
    render(<Markdown text={'```\nplain\n```'} />);
    expect(screen.getByText('code')).toBeInTheDocument();
  });

  it('复制代码：成功后按钮变「已复制」', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<Markdown text={'```js\nconst b = 2;\n```'} />);

    fireEvent.click(screen.getByRole('button', { name: '复制' }));

    expect(writeText).toHaveBeenCalledWith('const b = 2;');
    expect(await screen.findByRole('button', { name: '已复制' })).toBeInTheDocument();
  });

  it('剪贴板不可用时不崩，按钮保持「复制」', async () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockRejectedValue(new Error('no permission')),
      },
    });
    render(<Markdown text={'```js\nconst c = 3;\n```'} />);

    fireEvent.click(screen.getByRole('button', { name: '复制' }));
    expect(await screen.findByRole('button', { name: '复制' })).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/* MessageBubble                                                       */
/* ------------------------------------------------------------------ */

describe('MessageBubble', () => {
  it('system 消息渲染为居中的提示条', () => {
    render(<MessageBubble message={message({ role: 'system', content: '会话已新建' })} />);
    expect(screen.getByText('会话已新建')).toBeInTheDocument();
    expect(screen.queryByText('Office Agent')).toBeNull();
  });

  it('user 消息右对齐，带「你 · 时间」角标', () => {
    render(<MessageBubble message={message({ role: 'user', content: '写个周报' })} />);
    expect(screen.getByText('写个周报')).toBeInTheDocument();
    expect(screen.getByText(/^你 · /)).toBeInTheDocument();
  });

  it('assistant 消息走 Markdown 渲染，并有署名与时间', () => {
    render(<MessageBubble message={message({ content: '**要点**：三条' })} />);
    expect(screen.getByText('Office Agent')).toBeInTheDocument();
    expect(screen.getByText('要点').tagName).toBe('STRONG');
    expect(screen.queryByText('正在输出')).toBeNull();
  });

  it('流式中显示「正在输出」', () => {
    render(<MessageBubble message={message({ streaming: true })} />);
    expect(screen.getByText('正在输出')).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/* ThinkingBlock                                                       */
/* ------------------------------------------------------------------ */

describe('ThinkingBlock', () => {
  it('决策行：一行淡字，没有「正在思考 / 已思考」这类壳', () => {
    render(<ThinkingBlock thinking={thinking({ content: '两份表头口径对不上，先按第一份算' })} />);

    expect(screen.getByText('两份表头口径对不上，先按第一份算')).toBeInTheDocument();
    // 以前这里是一块卡片 + 「已思考 3.2 秒」+ 展开按钮，一句话的事被做成了面板
    expect(screen.queryByText(/正在思考|已思考/)).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
    expect(document.querySelector('[data-thinking-kind="decision"]')).not.toBeNull();
  });

  it('某一步没成时用告警语气', () => {
    render(
      <ThinkingBlock thinking={thinking({ kind: 'error', content: '读素材没成（文档加密）' })} />,
    );

    const line = screen.getByText('读素材没成（文档加密）');
    expect(line.className).toContain('text-warn');
    expect(document.querySelector('[data-thinking-kind="error"]')).not.toBeNull();
  });

  it('停下来问你的时候是另一种语气', () => {
    render(<ThinkingBlock thinking={thinking({ kind: 'ask', content: '两份表头按哪个算？' })} />);
    expect(document.querySelector('[data-thinking-kind="ask"]')).not.toBeNull();
  });

  it('流式中带光标、内容实时出现', () => {
    render(<ThinkingBlock thinking={thinking({ streaming: true, content: '先按第一个来' })} />);

    expect(screen.getByText('先按第一个来')).toBeInTheDocument();
    expect(document.querySelector('.caret')).not.toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/* ChatStream                                                          */
/* ------------------------------------------------------------------ */

describe('ChatStream', () => {
  const items: TimelineItem[] = [
    { kind: 'message', id: 'm1', message: message({ role: 'user', content: '写周报' }) },
    { kind: 'thinking', id: 't1', thinking: thinking({ content: '思考中' }) },
    { kind: 'message', id: 'm2', message: message({ content: '好的' }) },
  ];

  it('空列表时渲染空态', () => {
    render(<ChatStream items={[]} status="idle" emptyState={<p>空态占位</p>} />);
    expect(screen.getByText('空态占位')).toBeInTheDocument();
  });

  it('按 kind 分发到对应组件', () => {
    render(<ChatStream items={items} status="idle" emptyState={<p>空态</p>} />);
    const stream = screen.getByTestId('chat-stream');

    expect(within(stream).getByText('写周报')).toBeInTheDocument();
    expect(within(stream).getByText('好的')).toBeInTheDocument();
    // 决策行直接摊在对话里，不再折进「思考过程」那一行
    expect(within(stream).getByText('思考中')).toBeInTheDocument();
    expect(within(stream).queryByText('空态')).toBeNull();
  });

  it('连续的工具 / 计划 / 子智能体默认收成一行「思考过程」', () => {
    const traceItems: TimelineItem[] = [
      {
        kind: 'plan',
        id: 'p1',
        plan: {
          run_id: 'r1',
          todos: [
            { id: '1', content: '读取素材', status: 'completed' },
            { id: '2', content: '生成报告产物', status: 'in_progress' },
          ],
          updated_at: AT,
        },
      },
      {
        kind: 'tool',
        id: 'to1',
        tool: {
          id: 'to1',
          run_id: 'r1',
          tool: 'doc.list_inputs',
          ok: true,
          risk: 'low',
          summary: '共 1 个素材文件',
          duration_ms: 0,
          created_at: AT,
        },
      },
      {
        kind: 'subagent',
        id: 's1',
        subagent: {
          id: 's1',
          name: '文档智能体',
          status: 'running',
          summary: '已读取 1 个文件',
          tools: [],
          updated_at: AT,
        },
      },
    ];

    render(<ChatStream items={traceItems} status="streaming" emptyState={null} />);

    // 默认折叠：只有一个摘要行，具体步骤与工具明细都不出现
    const summary = screen.getByRole('button', { name: /思考过程/ });
    expect(summary).toHaveTextContent('1/2');
    expect(summary).toHaveTextContent('正在：生成报告产物');
    expect(screen.queryByText('共 1 个素材文件')).toBeNull();
    expect(screen.queryByText('文档智能体')).toBeNull();

    // 点开才逐条展开
    fireEvent.click(summary);
    expect(screen.getByText('共 1 个素材文件')).toBeInTheDocument();
    expect(screen.getByText('文档智能体')).toBeInTheDocument();
  });

  /**
   * 产物的时序：这一轮没跑完，产物就不进对话。
   *
   * 以前只压到「开口说第一句」就放出来，于是用户看到的是半成品——脚本还在重跑、
   * 同名文件随时会被覆盖，点预览不是「产物不存在」就是旧内容。结果还没定稿，
   * 不该先摆上桌。
   */
  describe('本轮产物等跑完再现身', () => {
    const doc = (overrides: Partial<ArtifactItem> = {}): ArtifactItem => ({
      artifact_id: 'a1',
      type: 'docx',
      filename: '周报.docx',
      size: 2048,
      download_url: '/api/v1/artifacts/a1/download',
      preview_url: '/api/v1/artifacts/a1/preview',
      run_id: 'r1',
      created_at: AT,
      meta_status: 'idle',
      meta_error: null,
      meta: null,
      ...overrides,
    });

    it('还在跑、且一句思考都没有时，本轮产物先压住', () => {
      render(
        <ChatStream
          items={[]}
          status="streaming"
          artifacts={[doc()]}
          currentRunId="r1"
          emptyState={null}
        />,
      );
      expect(screen.queryByLabelText('本次产物')).toBeNull();
    });

    it('已经说过话了也先压着：脚本还在重跑，同名文件随时会被覆盖', () => {
      render(
        <ChatStream
          items={[{ kind: 'thinking', id: 't1', thinking: thinking({ content: '先定骨架' }) }]}
          status="streaming"
          artifacts={[doc()]}
          currentRunId="r1"
          emptyState={null}
        />,
      );
      expect(screen.queryByLabelText('本次产物')).toBeNull();
    });

    it('等审批时也压着：这一轮还没结束', () => {
      render(
        <ChatStream
          items={[{ kind: 'thinking', id: 't1', thinking: thinking({ content: '要写盘了' }) }]}
          status="waiting_approval"
          artifacts={[doc()]}
          currentRunId="r1"
          emptyState={null}
        />,
      );
      expect(screen.queryByLabelText('本次产物')).toBeNull();
    });

    it('上一轮的旧产物不受影响，不会闪一下再回来', () => {
      render(
        <ChatStream
          items={[]}
          status="streaming"
          artifacts={[doc({ artifact_id: 'old', run_id: 'r0' })]}
          currentRunId="r1"
          emptyState={null}
        />,
      );
      expect(screen.getByLabelText('本次产物')).toBeInTheDocument();
    });

    it('跑完了就直接摆出来（思考被设置隐藏时也一样）', () => {
      render(
        <ChatStream
          items={[]}
          status="done"
          artifacts={[doc()]}
          currentRunId="r1"
          emptyState={null}
        />,
      );
      expect(screen.getByLabelText('本次产物')).toBeInTheDocument();
    });
  });

  it('旁白收进思考过程：对话里只剩一条正式回复，不再每条都挂「Office Agent」抬头', () => {
    const itemsWithNote: TimelineItem[] = [
      { kind: 'message', id: 'u1', message: message({ role: 'user', content: '整理素材' }) },
      { kind: 'thinking', id: 't1', thinking: thinking({ content: '先读素材' }) },
      {
        kind: 'note',
        id: 'n1',
        note: {
          id: 'n1',
          content: '我先把素材读出来，再看它适不适合套周报。',
          streaming: false,
          created_at: AT,
        },
      },
      {
        kind: 'tool',
        id: 'to1',
        tool: {
          id: 'to1',
          run_id: 'r1',
          tool: 'file.list',
          ok: true,
          risk: 'low',
          summary: '共 1 个素材文件',
          duration_ms: 0,
          created_at: AT,
        },
      },
      {
        kind: 'message',
        id: 'm9',
        message: message({ content: '摘要已生成，可在产物中心下载。' }),
      },
    ];

    render(<ChatStream items={itemsWithNote} status="done" emptyState={null} />);

    // 折叠态只看得到一行「思考过程」，旁白不占对话区
    expect(screen.queryByText('我先把素材读出来，再看它适不适合套周报。')).toBeNull();
    expect(screen.getAllByText('Office Agent')).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: /思考过程/ }));
    expect(screen.getByText('我先把素材读出来，再看它适不适合套周报。')).toBeInTheDocument();
  });

  it('决策行在回复之前，执行过程在回复之后', () => {
    const turn: TimelineItem[] = [
      { kind: 'message', id: 'u1', message: message({ role: 'user', content: '把格式调一下' }) },
      { kind: 'thinking', id: 't1', thinking: thinking({ content: '先看它原来是什么结构' }) },
      {
        kind: 'tool',
        id: 'to1',
        tool: {
          id: 'to1',
          run_id: 'r1',
          tool: 'code.run_python',
          ok: true,
          risk: 'high',
          summary: '脚本执行完成，产出 1 个文件',
          duration_ms: 1400,
          created_at: AT,
        },
      },
      { kind: 'message', id: 'm1', message: message({ content: '调好了，文件在下面' }) },
    ];

    const artifacts = [
      {
        artifact_id: 'ar_1',
        type: 'docx',
        filename: '走观秋.docx',
        size: 1024,
        download_url: '/api/v1/artifacts/ar_1/download',
        preview_url: '/api/v1/artifacts/ar_1/preview',
        run_id: 'r1',
        created_at: AT,
        meta_status: 'idle' as const,
        meta_error: null,
        meta: null,
      },
    ];

    const { container } = render(
      <ChatStream items={turn} status="done" artifacts={artifacts} emptyState={null} />,
    );

    const text = container.textContent ?? '';
    const said = text.indexOf('把格式调一下');
    const decided = text.indexOf('先看它原来是什么结构');
    const replied = text.indexOf('调好了，文件在下面');
    const worked = text.indexOf('脚本执行完成，产出 1 个文件');
    // 阅读顺序：你说 → 它怎么定 → 它答什么 → 它做了什么 → 给了什么文件
    expect(said).toBeGreaterThan(-1);
    expect(decided).toBeGreaterThan(said);
    expect(replied).toBeGreaterThan(decided);
    expect(worked).toBeGreaterThan(replied);
    expect(replied).toBeLessThan(text.indexOf('走观秋.docx'));
  });

  it('用户向上翻阅时出现「回到底部」，点击后收起', () => {
    render(<ChatStream items={items} status="idle" emptyState={null} />);
    const stream = screen.getByTestId('chat-stream');
    // jsdom 没实现滚动 API，手动打桩，否则 scrollToBottom 会抛错、pinned 设不回去
    const scrollTo = vi.fn();
    Object.defineProperty(stream, 'scrollTo', { value: scrollTo, configurable: true });
    // jsdom 不做布局，手动给一组尺寸：滚动到中途 → 距离底部超过阈值
    Object.defineProperty(stream, 'scrollHeight', { value: 2000, configurable: true });
    Object.defineProperty(stream, 'clientHeight', { value: 600, configurable: true });
    Object.defineProperty(stream, 'scrollTop', { value: 100, configurable: true, writable: true });

    fireEvent.scroll(stream);
    const backToBottom = screen.getByRole('button', { name: '回到底部' });
    expect(backToBottom).toBeInTheDocument();

    fireEvent.click(backToBottom);
    expect(scrollTo).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: '回到底部' })).toBeNull();
  });

  it('已在底部时不显示「回到底部」', () => {
    render(<ChatStream items={items} status="idle" emptyState={null} />);
    const stream = screen.getByTestId('chat-stream');
    Object.defineProperty(stream, 'scrollHeight', { value: 600, configurable: true });
    Object.defineProperty(stream, 'clientHeight', { value: 600, configurable: true });
    Object.defineProperty(stream, 'scrollTop', { value: 0, configurable: true, writable: true });

    fireEvent.scroll(stream);
    expect(screen.queryByRole('button', { name: '回到底部' })).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/* StatusBar                                                           */
/* ------------------------------------------------------------------ */

describe('StatusBar', () => {
  const health = (status: HealthState['status']): HealthState => ({
    status,
    mode: status === 'ok' ? 'real' : null,
    version: '0.2.0',
    checked_at: AT,
  });

  function renderBar(overrides: Partial<Parameters<typeof StatusBar>[0]> = {}) {
    const props = {
      health: health('ok'),
      mode: null,
      isMockMode: false,
      degraded: false,
      connection: 'idle' as const,
      runError: null,
      notice: null,
      onRetryRun: vi.fn(),
      onRetryHealth: vi.fn(),
      onDismissNotice: vi.fn(),
      rightOpen: true,
      onToggleRightPanel: vi.fn(),
      leftOpen: true,
      onToggleLeftPanel: () => {},
      ...overrides,
    };
    const view = render(<StatusBar {...props} />);
    return { ...props, unmount: view.unmount };
  }

  it('模式徽标：本地 mock 优先，其次 real / mock / 未知', () => {
    const { unmount } = render(
      <StatusBar
        health={health('ok')}
        mode={null}
        isMockMode
        degraded={false}
        connection="idle"
        runError={null}
        notice={null}
        onRetryRun={vi.fn()}
        onRetryHealth={vi.fn()}
        onDismissNotice={vi.fn()}
        rightOpen
        onToggleRightPanel={vi.fn()}
        leftOpen
        onToggleLeftPanel={() => {}}
      />,
    );
    expect(screen.getByText('本地 mock 事件流')).toBeInTheDocument();
    unmount();

    renderBar({});
    expect(screen.getByText('real 模型')).toBeInTheDocument();
  });

  it('模式为 mock 连接器 / 未知时徽标不同', () => {
    const { unmount } = renderBar({ health: health('unknown'), mode: 'mock' });
    expect(screen.getByText('mock 连接器')).toBeInTheDocument();
    unmount();

    renderBar({ health: health('unknown'), mode: null });
    expect(screen.getByText('模式未知')).toBeInTheDocument();
  });

  it('连接状态文案与 idle 不显示', () => {
    const reconnecting = renderBar({ connection: 'reconnecting' });
    expect(screen.getByText('断线重连中')).toBeInTheDocument();
    reconnecting.unmount();

    const open = renderBar({ connection: 'open' });
    expect(screen.getByText('事件流已连接')).toBeInTheDocument();
    open.unmount();

    renderBar({ connection: 'idle' });
    expect(screen.queryByText('事件流已连接')).toBeNull();
    expect(screen.queryByText('断线重连中')).toBeNull();
  });

  it('运行失败条：可重试时给重试按钮，点击回调', () => {
    const props = renderBar({
      runError: { code: 'MODEL_TIMEOUT', message: '模型超时', retryable: true },
    });

    expect(screen.getByText('MODEL_TIMEOUT')).toBeInTheDocument();
    expect(screen.getByText('模型超时')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /重试/ }));
    expect(props.onRetryRun).toHaveBeenCalledTimes(1);
  });

  it('不可重试的错误不显示重试按钮', () => {
    renderBar({ runError: { code: 'INTERNAL', message: '内部错误', retryable: false } });
    expect(screen.queryByRole('button', { name: /重试/ })).toBeNull();
  });

  it('通知条：error 与 info 两种色调，可关闭，带 trace', () => {
    const props = renderBar({
      notice: { kind: 'error', text: '上传失败', traceId: 'tr-1' },
    });

    expect(screen.getByText('上传失败')).toBeInTheDocument();
    expect(screen.getByText('tr-1')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '关闭提示' }));
    expect(props.onDismissNotice).toHaveBeenCalledTimes(1);
  });

  it('后端不可达时给连接指引（mock 模式下不出现）', () => {
    const unreachable = renderBar({ health: health('unreachable') });
    expect(screen.getByText(/还没连上本地服务/)).toBeInTheDocument();
    unreachable.unmount();

    // mock 模式本来就没有后端可连，这条提示不该出现
    const { unmount } = render(
      <StatusBar
        health={health('unreachable')}
        mode={null}
        isMockMode
        degraded={false}
        connection="idle"
        runError={null}
        notice={null}
        onRetryRun={vi.fn()}
        onRetryHealth={vi.fn()}
        onDismissNotice={vi.fn()}
        rightOpen
        onToggleRightPanel={vi.fn()}
        leftOpen
        onToggleLeftPanel={() => {}}
      />,
    );
    expect(screen.queryByText(/还没连上本地服务/)).toBeNull();
    unmount();
  });

  it('mock 模式给出 fixture 说明横幅', () => {
    renderBar({ isMockMode: true, health: health('ok') });
    expect(screen.getByText(/fixture/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '切换到真实后端' })).toBeInTheDocument();
  });

  it('降级运行提示要说清「没调真模型」以及为什么', () => {
    // 以前只写一句「已降级（degraded）」，术语太软，用户根本不知道自己在看本地模拟内容。
    renderBar({ degraded: true, degradedReason: 'deepseek: 模型返回空内容' });
    expect(screen.getByText(/没有调用真实大模型/)).toBeInTheDocument();
    expect(screen.getByText(/本地模拟生成/)).toBeInTheDocument();
    expect(screen.getByText(/模型返回空内容/)).toBeInTheDocument();
  });

  // 顶栏不再放「审计」按钮：一个会话要不要看审计是上下文动作，
  // 已经挂在右栏「产物 / 本次会话」旁边；顶栏再放一个只会跟主题、右栏开关抢位置。
  it('顶栏不再放审计按钮', () => {
    renderBar();
    expect(screen.queryByRole('button', { name: '审计' })).toBeNull();
  });

  it('右栏开关按钮文案随状态切换', () => {
    const props = renderBar({ rightOpen: true });
    fireEvent.click(screen.getByRole('button', { name: '收起右栏' }));
    expect(props.onToggleRightPanel).toHaveBeenCalledTimes(1);
  });
});

/* ------------------------------------------------------------------ */
/* EmptyState                                                          */
/* ------------------------------------------------------------------ */

describe('EmptyState', () => {
  it('只保留上传入口，不再出现模板', () => {
    const onUploadRequest = vi.fn();
    render(<EmptyState mock onUploadRequest={onUploadRequest} />);

    expect(screen.getByText('把一份材料，变成可交付的文档')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /上传素材/ }));
    expect(onUploadRequest).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/或从模板开始/)).toBeNull();
  });

  it('底部那句「会不会外发」跟着引擎走，真实模型下不能还写演示模式', () => {
    const { rerender } = render(<EmptyState mock onUploadRequest={() => {}} />);
    expect(screen.getByText(/演示模式（不联网）/)).toBeInTheDocument();

    rerender(<EmptyState mock={false} onUploadRequest={() => {}} />);
    expect(screen.queryByText(/演示模式（不联网）/)).toBeNull();
    expect(screen.getByText(/素材会发送给模型解析/)).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/* 思考过程显示设置                                                     */
/* ------------------------------------------------------------------ */

describe('思考过程显示设置', () => {
  const trace: TimelineItem[] = [
    { kind: 'message', id: 'u1', message: message({ role: 'user', content: '把行距改成 1.5' }) },
    { kind: 'thinking', id: 'th1', thinking: thinking({ content: '先看看原稿现在的行距是多少' }) },
    {
      kind: 'plan',
      id: 'p1',
      plan: {
        run_id: 'r1',
        todos: [
          { id: '1', content: '看清原稿现在的样子', status: 'completed' },
          { id: '2', content: '定下要动的格式项', status: 'in_progress' },
          { id: '3', content: '改完逐处核对', status: 'pending' },
        ] as PlanSnapshot['todos'],
        updated_at: AT,
      },
    },
    {
      kind: 'tool',
      id: 'to1',
      tool: {
        id: 'to1',
        run_id: 'r1',
        tool: 'code.run_python',
        ok: true,
        risk: 'high',
        summary: '脚本执行完成，产出 1 个文件',
        duration_ms: 12,
        created_at: AT,
      },
    },
    { kind: 'message', id: 'm1', message: message({ content: '行距已经统一成 1.5 了' }) },
  ];

  afterEach(() => {
    act(() => setThinkingView('full'));
  });

  it('默认完全显示：决策行摊在对话里，工具明细收在「思考过程」一行', () => {
    render(<ChatStream items={trace} status="done" emptyState={null} />);
    // 一句话的决策行不值得再点开一层
    expect(screen.getByText('先看看原稿现在的行距是多少')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /思考过程/ }));
    expect(screen.getByText('脚本执行完成，产出 1 个文件')).toBeInTheDocument();
  });

  it('只看主要步骤：留计划主线和决策行，工具明细与旁白不出现', () => {
    setThinkingView('brief');
    render(<ChatStream items={trace} status="done" emptyState={null} />);
    expect(screen.getByText(/定下要动的格式项/)).toBeInTheDocument();
    // 决策行就是「主要步骤」本身，这一档不该把它一起藏掉
    expect(screen.getByText('先看看原稿现在的行距是多少')).toBeInTheDocument();
    expect(screen.queryByText('脚本执行完成，产出 1 个文件')).toBeNull();
  });

  it('不显示：过程整块收走，只剩回复正文', () => {
    setThinkingView('off');
    render(<ChatStream items={trace} status="done" emptyState={null} />);
    expect(screen.getByText('行距已经统一成 1.5 了')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /思考过程/ })).toBeNull();
    expect(screen.queryByText(/定下要动的格式项/)).toBeNull();
    expect(screen.queryByText('先看看原稿现在的行距是多少')).toBeNull();
  });

  it('设置一改就生效，不用刷新页面', () => {
    const { rerender } = render(<ChatStream items={trace} status="done" emptyState={null} />);
    expect(screen.getByRole('button', { name: /思考过程/ })).toBeInTheDocument();

    act(() => setThinkingView('off'));
    rerender(<ChatStream items={trace} status="done" emptyState={null} />);
    expect(screen.queryByRole('button', { name: /思考过程/ })).toBeNull();
  });
});
