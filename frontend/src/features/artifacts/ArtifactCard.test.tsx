/**
 * 产物卡与预览弹窗。
 * 预览的分支多：docx 走 mammoth 本地转 HTML，文本类拉原文，pdf/xlsx 引导下载，出错给「改为下载」。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { artifactsApi } from './api';
import { ArtifactCard } from './ArtifactCard';
import { ArtifactPreviewModal } from './components/ArtifactPreviewModal';
import type { ArtifactItem } from '../../shared/types/view';

const mammothMock = vi.hoisted(() => ({ convertToHtml: vi.fn() }));

vi.mock('mammoth', () => ({ default: { convertToHtml: mammothMock.convertToHtml } }));

const AT = '2026-10-24T12:00:00.000Z';

function artifact(patch: Partial<ArtifactItem> = {}): ArtifactItem {
  return {
    artifact_id: 'a1',
    type: 'docx',
    filename: '周报_2026-W43.docx',
    size: 18_234,
    download_url: '/api/v1/artifacts/a1/download',
    preview_url: '/api/v1/artifacts/a1/preview',
    created_at: AT,
    meta_status: 'idle',
    meta_error: null,
    meta: null,
    ...patch,
  };
}

const anchorClick = vi.fn();

/** 下载链路：fetch 取 blob → createObjectURL → 点一次 a[download]。 */
function stubDownload() {
  const fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    text: async () => '',
    arrayBuffer: async () => new ArrayBuffer(0),
    blob: async () => new Blob(['bytes']),
  }));
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:fake'),
    revokeObjectURL: vi.fn(),
  });
  anchorClick.mockClear();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => anchorClick());
  return fetchMock;
}

function fetchOk(body: string | ArrayBuffer): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () => (typeof body === 'string' ? body : ''),
      arrayBuffer: async () => (typeof body === 'string' ? new ArrayBuffer(0) : body),
    })),
  );
}

function fetchFail(status = 500): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: false,
      status,
      text: async () => '',
      arrayBuffer: async () => new ArrayBuffer(0),
    })),
  );
}

beforeEach(() => {
  mammothMock.convertToHtml.mockResolvedValue({ value: '<p>正文</p>', messages: [] });
});

/* ------------------------------------------------------------------ */
/* ArtifactCard                                                        */
/* ------------------------------------------------------------------ */

describe('ArtifactCard', () => {
  /** hover 整行才能拿到提示：文件名的父节点就是 Tooltip 的包裹层 */
  async function hoverRow(filename: string): Promise<HTMLElement> {
    fireEvent.mouseEnter(screen.getByText(filename).parentElement as HTMLElement);
    return screen.findByRole('tooltip');
  }

  it('一行只放文件名：类型、大小、时间收进 hover 提示', async () => {
    render(<ArtifactCard artifact={artifact()} />);
    // 列表行里不再有第二行元信息
    expect(screen.queryByText('Word 文档')).toBeNull();
    expect(screen.queryByText('17.8 KB')).toBeNull();

    const tip = await hoverRow('周报_2026-W43');
    expect(tip.textContent).toContain('Word 文档');
    expect(tip.textContent).toContain('17.8 KB');
  });

  it('提示是自绘圆角卡片，不再用浏览器原生 title（原生气泡白底直角）', async () => {
    render(<ArtifactCard artifact={artifact()} />);
    expect(screen.getByText('周报_2026-W43').getAttribute('title')).toBeNull();

    const tip = await hoverRow('周报_2026-W43');
    // portal 到 body，圆角/深色背景跟主题一致
    expect(tip.parentElement).toBe(document.body);
    expect(tip.className).toContain('rounded-control');
    expect(tip.className).toContain('bg-tooltip');
  });

  it('提示条只放文件名和类型/大小/时间，不再罗列素材与花费', async () => {
    // 素材一多，那几行「源自 a、b、c…」会把提示撑到四五步高，
    // 挡住用户真正想确认的那一行；花费在行内右侧本来就有。
    render(
      <ArtifactCard
        artifact={artifact({ sources: ['随笔.docx', '周记.docx'], tokens: 1200, cost_cny: 0.02 })}
      />,
    );
    const tip = await hoverRow('周报_2026-W43');
    expect(tip.textContent).toContain('Word 文档');
    expect(tip.textContent).not.toContain('源自');
    expect(tip.textContent).not.toContain('tokens');
  });

  it('未知类型在 hover 提示里回落展示原始扩展名', async () => {
    render(<ArtifactCard artifact={artifact({ type: 'key' })} />);
    const tip = await hoverRow('周报_2026-W43');
    expect(tip.textContent).toContain('key');
  });

  it('按产物类型区分：DOCX / PDF 各有自己的类型标签与配色', () => {
    render(
      <>
        <ArtifactCard artifact={artifact()} />
        <ArtifactCard
          artifact={artifact({ artifact_id: 'a2', type: 'pdf', filename: '纪要_2026-10-26.pdf' })}
        />
      </>,
    );

    const docx = screen.getByText('DOCX');
    const pdf = screen.getByText('PDF');
    // 类型不同 → 标签底色/字色不同（以前所有产物共用一个蓝色文件图标）
    expect(docx.className).not.toBe(pdf.className);
    // 扩展名交给类型标签，文件名里不再重复一遍
    expect(screen.queryByText('周报_2026-W43.docx')).toBeNull();
    expect(screen.getByText('纪要_2026-10-26')).toBeInTheDocument();
  });

  it('不再展示 SHA256 校验值（用户看不懂那串字符）', () => {
    render(
      <ArtifactCard
        artifact={artifact({ meta: { sha256: '9f2c4a6b8d0e1f3a5c7e9b2d4f6a8c0e' } })}
      />,
    );
    expect(screen.queryByText(/SHA256/)).toBeNull();
  });

  it('运行结束后展示这次消耗的 tokens，并可查看花费明细', async () => {
    render(<ArtifactCard artifact={artifact({ tokens: 1234, cost_cny: 0.0033 })} />);
    expect(screen.getByText('1,234 tokens')).toBeInTheDocument();

    // 提示条只留文件名与类型/大小/时间：行内已经有 tokens，再在气泡里报一次账
    // 只会把提示撑长（用户明确要求收掉）。
    const tip = await hoverRow('周报_2026-W43');
    expect(tip.textContent).not.toContain('tokens');
    expect(tip.textContent).toContain('Word 文档');
  });

  it('历史产物没有用量数据时不显示消耗行', () => {
    render(<ArtifactCard artifact={artifact()} />);
    expect(screen.queryByText(/tokens/)).toBeNull();
  });

  it('打开预览后悬浮提示要收起，不能浮在弹窗上面挡正文', async () => {
    fetchOk(new ArrayBuffer(8));
    render(<ArtifactCard artifact={artifact()} />);

    await hoverRow('周报_2026-W43');
    fireEvent.click(screen.getByText('周报_2026-W43'));

    // 提示 portal 到 body、z-80，比弹窗还高：弹窗一开就必须把它收掉
    await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull());
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('下载按钮取一份文件再存盘，连点两次就下两次', async () => {
    const fetchMock = stubDownload();
    render(<ArtifactCard artifact={artifact()} />);

    const button = screen.getByRole('button', { name: '下载' });
    fireEvent.click(button);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    fireEvent.click(button);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/artifacts/a1/download',
      expect.objectContaining({ cache: 'no-store' }),
    );
    expect(anchorClick).toHaveBeenCalledTimes(2);
    vi.unstubAllGlobals();
  });

  it('鼠标经过时右侧换成操作条：预览 / 添加到对话框 / 下载', async () => {
    render(<ArtifactCard artifact={artifact()} onAddToChat={vi.fn(async () => true)} />);

    const bar = screen.getByRole('toolbar', { name: /的操作/ });
    expect(bar.className).toContain('opacity-0');
    expect(screen.getByRole('button', { name: '预览' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '添加到对话框' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '下载' })).toBeTruthy();
  });

  it('预览按钮打开弹窗，关闭后收起', async () => {
    fetchOk(new ArrayBuffer(8));
    render(<ArtifactCard artifact={artifact()} />);

    fireEvent.click(screen.getByRole('button', { name: '预览' }));
    // 假 fetch 立刻返回，loading 态一闪而过，直接等渲染结果
    expect(await screen.findByText('正文')).toBeInTheDocument();

    // 弹窗里有两个「关闭」：标题栏的图标按钮 + 页脚按钮
    const closeButtons = screen.getAllByRole('button', { name: '关闭' });
    expect(closeButtons).toHaveLength(2);
    fireEvent.click(closeButtons[closeButtons.length - 1] as HTMLElement);
    expect(screen.queryByText('正文')).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/* ArtifactPreviewModal                                                */
/* ------------------------------------------------------------------ */

describe('ArtifactPreviewModal', () => {
  it('正文铺在统一的「纸」容器上：阅读宽度与留白由 .doc-paper 决定，组件不自己写宽度', async () => {
    fetchOk(new ArrayBuffer(8));
    const { container } = render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('正文')).toBeInTheDocument());
    // 要是哪天有人把宽度/内边距写回组件里的 Tailwind 类，这里的断言会先炸
    const article = container.querySelector('[data-testid="preview-doc"]');
    expect(article?.className).toContain('doc-paper');
    expect(article?.className).toContain('prose-docx');
    expect(article?.className).not.toMatch(/\bmax-w-\[/);
  });

  it('docx：下载后用 mammoth 转 HTML 渲染', async () => {
    fetchOk(new ArrayBuffer(8));
    const { container } = render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('正文')).toBeInTheDocument());
    expect(mammothMock.convertToHtml).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.prose-docx')).not.toBeNull();
  });

  it('docx：图和图注包成 figure，预览里能按「图 + 注」排版', async () => {
    fetchOk(new ArrayBuffer(8));
    mammothMock.convertToHtml.mockResolvedValue({
      value:
        '<p><img src="data:image/jpeg;base64,AAA"/></p>' +
        '<p class="doc-caption">图1 杉道晴光</p><p>正文</p>',
      messages: [],
    });
    const { container } = render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('正文')).toBeInTheDocument());
    const figure = container.querySelector('figure');
    expect(figure).not.toBeNull();
    expect(figure?.querySelector('img')).not.toBeNull();
    expect(figure?.querySelector('figcaption')?.textContent).toBe('图1 杉道晴光');
  });

  it('docx：内嵌脚本 / iframe / on* 事件属性被清洗掉', async () => {
    fetchOk(new ArrayBuffer(8));
    mammothMock.convertToHtml.mockResolvedValue({
      value: '<p onclick="alert(1)">安全</p><script>alert(2)</script><iframe src="x"></iframe>',
      messages: [],
    });
    const { container } = render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('安全')).toBeInTheDocument());
    const article = container.querySelector('.prose-docx');
    expect(article?.innerHTML).not.toContain('script');
    expect(article?.innerHTML).not.toContain('iframe');
    expect(article?.innerHTML).not.toContain('onclick');
  });

  it('md：拉原文后按 Markdown 渲染标题，不再是原样 # 号', async () => {
    fetchOk('# 标题\n正文');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'md' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText('标题')).toBeInTheDocument());
    // 文档里的 # 就是一级标题：以前整体降了一级，h1 和正文只差 1px
    expect(container.querySelector('h1')).not.toBeNull();
    expect(screen.queryByText(/# 标题/)).toBeNull();
    expect(mammothMock.convertToHtml).not.toHaveBeenCalled();
  });

  it('txt：按段落排版展示原文', async () => {
    fetchOk('第一段\n第二段');
    render(<ArtifactPreviewModal artifact={artifact({ type: 'txt' })} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/第一段/)).toBeInTheDocument());
  });

  it('txt：文档名字居中且最大，索引节与出处落款不进预览', async () => {
    // 用户 2026-11-09 / 11-10 两次指出：文首被当成普通段落（左对齐、正常字号），
    // 「六、关键文件索引」和「依据《x》整理」这类出处清单还挂在稿子里。
    fetchOk(
      [
        '后端三块核心机制导读',
        'office-agent-mvp：产物预览、智能体回答、最终结果',
        '依据《后端三块核心源码提取.md》整理，代码位置沿用该文件的标注',
        '',
        '一、总览：一次请求走完的链路',
        '一次请求从入口走到产物落盘。',
        '',
        '六、关键文件索引',
        '- services/artifact_service.py：产物预览三分支',
        '- infra/parsing.py：上传文本解析',
        '',
        '七、收尾',
        '结论写在这里。',
      ].join('\n'),
    );
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'txt' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText('后端三块核心机制导读')).toBeInTheDocument());
    expect(container.querySelector('h1.doc-title')?.textContent).toBe('后端三块核心机制导读');
    expect(container.querySelector('p.doc-lead')?.textContent).toContain('office-agent-mvp');
    const body = container.querySelector('[data-testid="preview-doc"]')?.textContent ?? '';
    expect(body).not.toContain('依据《');
    expect(body).not.toContain('关键文件索引');
    expect(body).not.toContain('artifact_service.py');
    expect(body).toContain('结论写在这里');
  });

  it('pdf：用浏览器内置阅读器内嵌，且走 inline=1（否则浏览器会把附件直接下载）', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'pdf' })} onClose={vi.fn()} />,
    );

    // 标题栏的 h2 也带同名 title（长文件名截断时用），这里只认 iframe
    const frame = (await waitFor(() => {
      const element = container.querySelector('iframe');
      expect(element).not.toBeNull();
      return element;
    })) as HTMLIFrameElement;
    expect(frame.tagName).toBe('IFRAME');
    expect(frame.getAttribute('src')).toBe('/api/v1/artifacts/a1/download?inline=1');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('xlsx：走后端表格预览（HTML 表格直接注入）', async () => {
    fetchOk('<table><tbody><tr><td>单元格</td></tr></tbody></table>');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'xlsx' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText('单元格')).toBeInTheDocument());
    expect(container.querySelector('table')).not.toBeNull();
  });

  it('未知类型：只给下载 / 系统程序打开引导', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(
      <ArtifactPreviewModal
        artifact={artifact({ type: 'zip', filename: '归档.zip' })}
        onClose={vi.fn()}
      />,
    );
    expect(await screen.findByText(/该类型暂不支持内嵌预览/)).toBeInTheDocument();
    // 空态里一个、页脚一个：同一句话、同一个动作，两边都给得到
    expect(screen.getAllByRole('button', { name: /用系统程序打开/ }).length).toBeGreaterThan(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('上传的素材按扩展名还原类型：upload + .txt 也能读到正文', async () => {
    fetchOk('第一段\n\n【进展】\n- 打通链路');

    render(
      <ArtifactPreviewModal
        artifact={artifact({ type: 'upload', filename: '周会记录.txt' })}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('第一段')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '进展' })).toBeInTheDocument();
    expect(screen.getByText('打通链路')).toBeInTheDocument();
  });

  it('「用系统程序打开」调接口并在页脚给出结果', async () => {
    fetchOk(new ArrayBuffer(8));
    const openSpy = vi.spyOn(artifactsApi, 'openArtifact').mockResolvedValue({
      data: { artifact_id: 'a1', path: 'C:/x.docx', opened: true, error: null },
      traceId: null,
    });

    render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);
    // 页脚那颗和空态里的按钮同名，取第一个命中即可（页脚在前）
    const openButtons = await screen.findAllByRole('button', { name: /用系统程序打开/ });
    fireEvent.click(openButtons[0] as HTMLElement);

    await waitFor(() => expect(screen.getByText(/已交给系统默认程序打开/)).toBeInTheDocument());
    expect(openSpy).toHaveBeenCalledWith('a1');
    openSpy.mockRestore();
  });

  it('下载失败 → 错误态 + 「改为下载」', async () => {
    fetchFail(404);
    render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);

    expect(await screen.findByText('下载不可用（HTTP 404）')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /改为下载/ })).toBeInTheDocument();
  });

  it('文本预览失败提示的是预览不可用', async () => {
    fetchFail(503);
    render(<ArtifactPreviewModal artifact={artifact({ type: 'txt' })} onClose={vi.fn()} />);
    expect(await screen.findByText('预览不可用（HTTP 503）')).toBeInTheDocument();
  });

  it('下载按钮透传 download_url，并把「已开始下载」告诉用户', async () => {
    const fetchMock = stubDownload();
    render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);
    // 先等 docx 预览那次 fetch 落地，再看下载那次
    await screen.findByText('正文');
    const before = fetchMock.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: /下载/ }));

    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(before + 1));
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v1/artifacts/a1/download',
      expect.objectContaining({ cache: 'no-store' }),
    );
    expect(await screen.findByText(/已开始下载/)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

/* ------------------------------------------------------------------ */
/* 预览排版（第六十轮：阅读版式刻度与纸容器）                          */
/* ------------------------------------------------------------------ */

describe('ArtifactPreviewModal 排版', () => {
  it('标题栏给出类型/大小/时间，「本机预览」只出现一次', async () => {
    fetchOk(new ArrayBuffer(8));
    render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Word 文档');
    expect(dialog).toHaveTextContent('17.8 KB');
    expect(screen.getAllByText('本机预览')).toHaveLength(1);
  });

  it('Markdown：连续正文行合成一段，不再每行撑出一段空白', async () => {
    fetchOk('第一行\n第二行\n\n新的一段');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'md' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText(/第一行/)).toBeInTheDocument());
    const paragraphs = Array.from(container.querySelectorAll('.prose-docx p'));
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]?.querySelectorAll('br')).toHaveLength(1);
  });

  it('Markdown：二级列表挂在父项里，层级不再被抹平', async () => {
    fetchOk('- 一级\n  - 二级\n- 同级');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'md' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText('一级')).toBeInTheDocument());
    const article = container.querySelector('.prose-docx');
    expect(article?.querySelectorAll('ul')).toHaveLength(2);
    expect(article?.querySelector('li > ul > li')?.textContent?.trim()).toBe('二级');
  });

  it('Markdown：有序列表与标题层级照原文走', async () => {
    fetchOk('# 一级标题\n\n## 二级标题\n\n1. 第一步\n2. 第二步');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'md' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText('一级标题')).toBeInTheDocument());
    const article = container.querySelector('.prose-docx');
    expect(article?.querySelector('h1')?.textContent).toBe('一级标题');
    expect(article?.querySelector('h2')?.textContent).toBe('二级标题');
    expect(article?.querySelectorAll('ol li')).toHaveLength(2);
  });

  it('Markdown：项与项之间空一行（松散列表）仍是一个列表，不拆成多个', async () => {
    fetchOk('- 甲\n\n- 乙\n\n- 丙');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'md' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText('甲')).toBeInTheDocument());
    const article = container.querySelector('.prose-docx');
    expect(article?.querySelectorAll('ul')).toHaveLength(1);
    expect(article?.querySelectorAll('ul > li')).toHaveLength(3);
  });

  it('Markdown：列表项的缩进续行并进上一项，不把列表切成两截', async () => {
    fetchOk('- 一级\n  - 二级：说明\n    续行文字\n  - 二级二\n- 同级');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'md' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText('一级')).toBeInTheDocument());
    const article = container.querySelector('.prose-docx');
    expect(article?.querySelectorAll('ul')).toHaveLength(2);
    // 续行留在二级项里，没有变成夹在列表中间的段落
    expect(article?.querySelectorAll('ul > p')).toHaveLength(0);
    expect(article?.querySelector('li > ul > li')?.textContent).toContain('续行文字');
  });

  it('docx：生成时间那段机器信息收成注释块', async () => {
    fetchOk(new ArrayBuffer(8));
    mammothMock.convertToHtml.mockResolvedValue({
      value: '<p>周报</p><p>生成时间：2026-10-28T20:14 | 模式：real</p><h3>摘要</h3>',
      messages: [],
    });
    const { container } = render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/生成时间/)).toBeInTheDocument());
    const metas = container.querySelectorAll('.prose-docx p.doc-meta');
    expect(metas).toHaveLength(1);
    expect(metas[0]?.textContent).toContain('生成时间');
  });

  it('Markdown：竖线表格渲染成 table，不再是两行裸竖线', async () => {
    fetchOk('| 现象 | 根因 |\n| --- | --- |\n| 字小 | 用了 rem |\n| 挤 | 没留白 |');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'md' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText('现象')).toBeInTheDocument());
    const article = container.querySelector('.prose-docx');
    expect(article?.querySelectorAll('table')).toHaveLength(1);
    expect(article?.querySelectorAll('thead th')).toHaveLength(2);
    expect(article?.querySelectorAll('tbody tr')).toHaveLength(2);
    // 分隔行不能漏成正文
    expect(article?.querySelector('td')?.textContent).toBe('字小');
    expect(article?.textContent).not.toContain('---');
  });

  it('纯文本按段落收拢：相邻两行同属一段', async () => {
    fetchOk('第一段第一行\n第一段第二行\n\n第二段');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'txt' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText(/第一段第一行/)).toBeInTheDocument());
    expect(container.querySelectorAll('.prose-docx p')).toHaveLength(2);
  });
});

/* ------------------------------------------------------------------ */
/* 预览窗口尺寸（第六十四轮：默认半窗口，可切全窗口）                   */
/* ------------------------------------------------------------------ */

describe('ArtifactPreviewModal 窗口尺寸', () => {
  it('默认是半窗口：不铺满、纸仍是卡片（全窗口是临时放大，不该成为默认）', async () => {
    fetchOk(new ArrayBuffer(8));
    const { container } = render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('正文')).toBeInTheDocument());
    expect(screen.getByRole('dialog')).not.toHaveAttribute('data-fullscreen');
    const article = container.querySelector('[data-testid="preview-doc"]');
    expect(article?.className).not.toContain('doc-paper--full');
    expect(screen.getByRole('button', { name: '全窗口查看' })).toBeTruthy();
  });

  it('点展开切到全窗口，再点还原回半窗口', async () => {
    fetchOk(new ArrayBuffer(8));
    const { container } = render(<ArtifactPreviewModal artifact={artifact()} onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('正文')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '全窗口查看' }));

    expect(screen.getByRole('dialog')).toHaveAttribute('data-fullscreen', 'true');
    expect(container.querySelector('[data-testid="preview-doc"]')?.className).toContain(
      'doc-paper--full',
    );

    fireEvent.click(screen.getByRole('button', { name: '还原半窗口' }));
    expect(screen.getByRole('dialog')).not.toHaveAttribute('data-fullscreen');
    expect(container.querySelector('[data-testid="preview-doc"]')?.className).not.toContain(
      'doc-paper--full',
    );
  });

  it('全窗口下按 Esc 先退回半窗口（预览不关），再按一次才关', async () => {
    const onClose = vi.fn();
    fetchOk(new ArrayBuffer(8));
    render(<ArtifactPreviewModal artifact={artifact()} onClose={onClose} />);

    await waitFor(() => expect(screen.getByText('正文')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '全窗口查看' }));

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).not.toHaveAttribute('data-fullscreen');

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('表格类在全窗口下换满宽（宽表不被挤成竖条）', async () => {
    fetchOk('<table><tbody><tr><td>单元格</td></tr></tbody></table>');
    const { container } = render(
      <ArtifactPreviewModal artifact={artifact({ type: 'xlsx' })} onClose={vi.fn()} />,
    );

    await waitFor(() => expect(screen.getByText('单元格')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '全窗口查看' }));
    const article = container.querySelector('[data-testid="preview-doc"]');
    expect(article?.className).toContain('doc-paper--table');
    expect(article?.className).toContain('doc-paper--full');
  });
});
