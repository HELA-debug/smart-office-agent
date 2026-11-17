import { describe, expect, it } from 'vitest';

import { renderTextDoc } from './ArtifactPreviewModal';

/**
 * TXT 预览的结构还原。
 *
 * 这份样例抄的是真实产物 `后端三块核心机制导读(3).txt` 的开头：大标题、空行、
 * 一行副标题、一行「依据《…》整理」的落款，然后是小节标题与按 76 宽硬折过行的正文。
 * 用户当时贴的截图里，副标题被当成正文（左对齐 + 空两格），正文每行都是一句半截话、
 * 右缘参差不齐——两端对齐根本没生效。
 */
const SAMPLE = [
  '后端三块核心机制导读',
  '',
  'office-agent-mvp：产物预览、智能体回答、最终结果',
  '依据《后端三块核心源码提取.md》整理，代码位置沿用该文件的标注',
  '',
  '【一、总览：一次请求走完的链路】',
  '',
  '入口是 POST /api/v1/runs/stream，RunService.start 在这里建 Run、建用户消息、组',
  'RunContext，然后把活交给 RealEngine.run。引擎在 ReAct 循环里反复「调模型、执行工具、回填',
  '观察」；工具产出文件后由 doc.generate_report 落盘 DOCX 和同名 preview.html；循环结束，',
  'SummaryService 生成运行摘要，RUN_COMPLETED 事件交给 RunService 落库。',
  '',
  '三块各自的落点：',
  '',
  '- 产物预览效果：ArtifactService.preview() 三分支渲染，配上上传时的 infra/parsing.py',
  '  与生成时的 doc.py render_preview_html()',
].join('\n');

describe('renderTextDoc', () => {
  const html = renderTextDoc(SAMPLE);

  it('第一行是文档大标题，跨空行的那行也算副标题', () => {
    expect(html).toContain('<h1 class="doc-title">后端三块核心机制导读</h1>');
    // 标题和副标题之间隔着一个空行：不能只看「第一个空行之前」
    expect(html).toContain(
      '<p class="doc-lead">office-agent-mvp：产物预览、智能体回答、最终结果</p>',
    );
  });

  it('标题块分三档：大标题 / 副标题 / 信息行', () => {
    // 用户在截图里点过这个：大标题和两行「实验名称：…」「姓名：…」都按副标题排，
    // 三行一样大一样粗，看着像三个并列的标题。信息行要退回正文字号、不加粗。
    const report = [
      '实验二　光照自适应调光（2026 年第 47 周，工作周报）',
      '',
      '实验名称：光照自适应调光　　实验方式：Wokwi 在线仿真',
      '姓名：敬一博　　学号：202416320112　　专业：智慧能源　　日期：2026-11-11',
      '',
      '【一、本周结论】',
      '本周完成四档照度的 PWM 标定。',
    ].join('\n');
    const reportHtml = renderTextDoc(report);
    expect(reportHtml).toContain('<h1 class="doc-title">实验二　光照自适应调光（2026 年第 47 周，工作周报）</h1>');
    expect(reportHtml).toContain(
      '<p class="doc-byline">实验名称：光照自适应调光　　实验方式：Wokwi 在线仿真</p>',
    );
    expect(reportHtml).toContain(
      '<p class="doc-byline">姓名：敬一博　　学号：202416320112　　专业：智慧能源　　日期：2026-11-11</p>',
    );
    // 一行说明（不带「字段：值」）仍是副标题
    const brief = ['标题', '', '基于 Wokwi 的 ESP32 物联网仿真实验', '', '【一、实验设备】', '正文。'].join('\n');
    expect(renderTextDoc(brief)).toContain(
      '<p class="doc-lead">基于 Wokwi 的 ESP32 物联网仿真实验</p>',
    );
  });

  it('落款行不进预览，也不会被当成副标题', () => {
    expect(html).not.toContain('依据《后端三块核心源码提取.md》');
  });

  it('【】小节标题单独成行', () => {
    expect(html).toContain('<h3>一、总览：一次请求走完的链路</h3>');
  });

  it('硬折行的正文并回一段，段落里不留 <br/>', () => {
    const paragraph = /<p>([\s\S]*?)<\/p>/.exec(html)?.[1] ?? '';
    expect(paragraph).toContain('建用户消息、组 RunContext');
    expect(paragraph).toContain('循环里反复「调模型、执行工具、回填观察」');
    expect(paragraph).not.toContain('<br/>');
    // 折行工具是在空格处断出来的，断完那个空格就没了：接回来要补上，别粘成一个词
    expect(paragraph).not.toContain('组RunContext');
    // 中文之间不补空格：补了就成了「回填 观察」那种断字
    expect(paragraph).toContain('执行工具、回填观察」');
  });

  it('真正的分段仍然分开：句末标点、单独一行的引导语', () => {
    const paragraphs = html.match(/<p>/g) ?? [];
    // 正文一段 + 「三块各自的落点：」一段（副标题是 doc-lead，不算）
    expect(paragraphs.length).toBe(2);
    expect(html).toContain('<p>三块各自的落点：</p>');
  });

  it('列表项的缩进续行并进同一项，折行处不硬断', () => {
    expect(html).toContain(
      '<li>产物预览效果：ArtifactService.preview() 三分支渲染，配上上传时的 infra/parsing.py 与生成时的 doc.py render_preview_html()</li>',
    );
  });

  it('一行一条的短行不合并（日志、落款、地址）', () => {
    const log = ['标题', '', '【一、记录】', '2026-11-07 14:02  INFO 退款率口径切到下单时间', '2026-11-07 15:40  WARN 第三方通道超时 3 次'].join('\n');
    const logHtml = renderTextDoc(log);
    // 每条各自成段、不带首行缩进：日志靠行首对齐读，并进一段就废了
    expect(logHtml).toContain(
      '<p class="doc-flat">2026-11-07 14:02  INFO 退款率口径切到下单时间</p>',
    );
    expect(logHtml).toContain(
      '<p class="doc-flat">2026-11-07 15:40  WARN 第三方通道超时 3 次</p>',
    );
  });

  it('不带【】的中文编号也认成小节标题', () => {
    const plain = ['标题', '', '一、背景', '这段是正文，说明这一节要讲什么。'].join('\n');
    expect(renderTextDoc(plain)).toContain('<h3>一、背景</h3>');
  });
});
