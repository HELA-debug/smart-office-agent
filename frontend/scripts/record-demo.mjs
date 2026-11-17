/**
 * 演示视频录制脚本（Playwright + Edge 内核）
 *
 *   node scripts/record-demo.mjs             # 录制 → docs/media/office-agent-demo.webm
 *   node scripts/record-demo.mjs --probe     # 只走流程不录制（打印时间线）
 *   DEMO_HEADED=1 node scripts/record-demo.mjs   # 有头模式（可肉眼看着它演）
 *
 * 前置：前端 5173、后端 8000 已启动；素材 data/samples/meeting_notes.docx 已生成
 *       （没有就跑：python scripts/make_sample.py）
 *
 * 设计说明：
 * - 单次连续录制，不分段：本机没有 ffmpeg / moviepy，拼不了多段视频，
 *   所以「片头 / 字幕 / 片尾」全部用注入 DOM 的方式画在页面上，随录制一起拍进去。
 * - 字幕层挂在 <body> 下、不受 React 管理，SPA 路由切换（pushState）冲不掉；
 *   每次跳转后仍重新注入，双保险。
 * - 全程真实调用大模型，耗时不可控，所以字幕与等待是配对的：
 *   先亮字幕，再等真实 UI 状态，状态到了才收字幕进入下一镜。
 */

import { chromium } from '@playwright/test';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');

const BASE_URL = process.env.DEMO_BASE_URL || 'http://127.0.0.1:5173';
const OUT_FILE = resolve(ROOT, process.env.DEMO_OUT || 'docs/media/office-agent-demo.webm');
const VIDEO_DIR = resolve(ROOT, 'data/.demo-video');
const SAMPLE = resolve(ROOT, 'data/samples/meeting_notes.docx');
const PROBE = process.argv.includes('--probe');
const HEADED = process.env.DEMO_HEADED === '1';
const VIEWPORT = { width: 1600, height: 900 };

const TASK = process.env.DEMO_TASK || '把这份会议记录整理成一份 600 字左右的周报，输出成 Word 文档';

const OVERLAY_CSS = `
#demo-layer { position: fixed; inset: 0; z-index: 2147483000; pointer-events: none; }
#demo-caption {
  position: absolute; left: 50%; bottom: 40px; transform: translate(-50%, 12px);
  max-width: 74%; background: rgba(11, 14, 20, .9); color: #f5f7fa;
  border: 1px solid rgba(255,255,255,.14); border-radius: 14px;
  padding: 15px 28px; font-size: 21px; line-height: 1.55;
  font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
  box-shadow: 0 16px 40px rgba(0,0,0,.55); text-align: center;
  opacity: 0; transition: opacity .3s ease, transform .3s ease;
}
#demo-caption.show { opacity: 1; transform: translate(-50%, 0); }
#demo-caption b { color: #7dd3fc; font-weight: 700; }
#demo-card {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; text-align: center;
  color: #f5f7fa; font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
  background: radial-gradient(120% 120% at 50% 30%, #16202e 0%, #0a0d13 60%, #070a0f 100%);
  opacity: 0; transition: opacity .45s ease;
}
#demo-card.show { opacity: 1; }
#demo-card .kicker { font-size: 19px; letter-spacing: .3em; color: #7dd3fc; margin-bottom: 18px; }
#demo-card h1 { font-size: 74px; margin: 0 0 18px; letter-spacing: .04em; font-weight: 700; }
#demo-card .sub { font-size: 25px; color: #b6c2d1; margin: 0; line-height: 1.7; }
#demo-card .meta { margin-top: 30px; font-size: 17px; color: #7f8b9c; }
#demo-card .rule { width: 220px; height: 2px; margin: 26px 0 0;
  background: linear-gradient(90deg, transparent, #7dd3fc, transparent); }
`;

const t0 = Date.now();
const stamp = () => `${((Date.now() - t0) / 1000).toFixed(1)}s`;
const log = (step, detail = '') =>
  console.log(`[${stamp().padStart(6)}] ${step}${detail ? ` — ${detail}` : ''}`);

async function ensureOverlay(page) {
  await page.addStyleTag({ content: OVERLAY_CSS });
  await page.evaluate(() => {
    if (document.getElementById('demo-layer')) return;
    const layer = document.createElement('div');
    layer.id = 'demo-layer';
    layer.innerHTML = '<div id="demo-caption"></div><div id="demo-card"></div>';
    document.body.appendChild(layer);
  });
}

const showCaption = (page, html) =>
  page.evaluate((text) => {
    const el = document.getElementById('demo-caption');
    if (!el) return;
    el.innerHTML = text;
    el.classList.add('show');
  }, html);

const hideCaption = (page) =>
  page.evaluate(() => document.getElementById('demo-caption')?.classList.remove('show'));

/** 亮字幕 → 停留 → 收字幕。 */
async function caption(page, html, ms) {
  await showCaption(page, html);
  await page.waitForTimeout(ms);
  await hideCaption(page);
  await page.waitForTimeout(320);
}

async function card(page, { kicker = '', title = '', sub = '', meta = '' }, ms) {
  await page.evaluate(
    (c) => {
      const el = document.getElementById('demo-card');
      if (!el) return;
      el.innerHTML =
        (c.kicker ? `<div class="kicker">${c.kicker}</div>` : '') +
        (c.title ? `<h1>${c.title}</h1>` : '') +
        (c.sub ? `<p class="sub">${c.sub}</p>` : '') +
        '<div class="rule"></div>' +
        (c.meta ? `<div class="meta">${c.meta}</div>` : '');
      el.classList.add('show');
    },
    { kicker, title, sub, meta },
  );
  await page.waitForTimeout(ms);
  await page.evaluate(() => document.getElementById('demo-card')?.classList.remove('show'));
  await page.waitForTimeout(450);
}

/** 鼠标平滑移动，画面里像「有人在用」。 */
async function glide(page, x, y, steps = 22) {
  for (let i = 1; i <= steps; i += 1) {
    const r = i / steps;
    const eased = r < 0.5 ? 2 * r * r : 1 - (-2 * r + 2) ** 2 / 2;
    await page.mouse.move(800 + (x - 800) * eased, 450 + (y - 450) * eased);
    await page.waitForTimeout(12);
  }
}

async function main() {
  mkdirSync(dirname(OUT_FILE), { recursive: true });
  rmSync(VIDEO_DIR, { recursive: true, force: true });
  mkdirSync(VIDEO_DIR, { recursive: true });

  const browser = await chromium.launch({
    channel: 'msedge',
    headless: !HEADED,
    args: ['--force-device-scale-factor=1', '--hide-scrollbars'],
  });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
    locale: 'zh-CN',
    recordVideo: PROBE ? undefined : { dir: VIDEO_DIR, size: VIEWPORT },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);

  try {
    // ------------------------------------------------------------ 片头
    log('打开工作台');
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    await ensureOverlay(page);

    await card(
      page,
      {
        kicker: 'Office Agent',
        title: '会干活的办公智能体',
        sub: '真实大模型调用 · 危险操作先审批 · 产物全程可追溯',
        meta: '本地优先部署 · FastAPI + React · 每一次运行都可审计',
      },
      4200,
    );

    // ------------------------------------------------------------ 总览
    await caption(
      page,
      '工作台三块：<b>左侧会话与项目</b> · <b>中间对话流</b> · <b>右侧产物与用量</b>',
      3800,
    );
    await glide(page, 190, 430);
    await page.waitForTimeout(450);
    await glide(page, 780, 520);
    await page.waitForTimeout(450);
    await glide(page, 1380, 300);
    await page.waitForTimeout(500);

    // ------------------------------------------------------------ 引擎状态
    await glide(page, 800, 870);
    await caption(page, '顶栏写着当前引擎：<b>真实模型 deepseek-flash</b>，不是演示数据', 3400);

    // ------------------------------------------------------------ 新建会话
    await caption(page, '开一个新会话，把活派给它', 2200);
    const created = await page
      .getByText('新建会话', { exact: true })
      .first()
      .click({ timeout: 4000 })
      .then(() => true)
      .catch(() => false);
    log('新建会话', created ? '已点击' : '未找到，沿用当前会话');
    await page.waitForTimeout(1300);

    // ------------------------------------------------------------ 上传素材
    await caption(page, '先给它一份素材：一份会议记录 Word 文档', 2600);
    await page.locator('input[type="file"]').first().setInputFiles(SAMPLE);
    log('素材已上传', SAMPLE);
    await page.waitForTimeout(2400);

    // ------------------------------------------------------------ 下任务
    await showCaption(page, `然后直接说人话：<b>${TASK}</b>`);
    const input = page.locator('textarea[aria-label="任务输入框"]');
    await input.click();
    await input.type(TASK, { delay: 28 });
    await page.waitForTimeout(1400);
    await hideCaption(page);
    await page.waitForTimeout(300);

    await page.locator('button[aria-label="发送"]').click();
    log('任务已发送');

    // ------------------------------------------------------------ 思考过程
    await showCaption(page, '它在<b>边想边输出</b>，你能看着它想，不是干等一个转圈');
    await page.waitForTimeout(6500);

    // -------------------------------------------------- 审批卡（真实触发）
    const approveBtn = page.getByRole('button', { name: '批准并继续' }).first();
    const needApproval = await approveBtn
      .waitFor({ state: 'visible', timeout: 40_000 })
      .then(() => true)
      .catch(() => false);
    log('审批卡', needApproval ? '已出现' : '未出现');

    if (needApproval) {
      await showCaption(page, '要写文件了，它<b>先停下来等你批准</b>——不批准就不动手');
      await page.waitForTimeout(3200);
      await approveBtn.click();
      log('已点击「批准并继续」');
      await hideCaption(page);
      await page.waitForTimeout(400);
      await showCaption(page, '批准后接着跑完剩下的步骤');
    } else {
      await showCaption(page, '它按自己的计划往下执行');
    }

    // ------------------------------------------------------------ 等待完成
    const finished = await page
      .waitForFunction(() => /运行完成/.test(document.body.innerText || ''), null, {
        timeout: 120_000,
      })
      .then(() => true)
      .catch(() => false);
    await hideCaption(page);
    await page.waitForTimeout(400);
    log('任务完成', finished ? '是' : '超时，继续后续镜头');

    const summary = await page
      .evaluate(() => {
        const m = (document.body.innerText || '').match(/运行完成[^\n]*/);
        return m ? m[0].replace(/\s+/g, ' ').trim() : '';
      })
      .catch(() => '');
    log('运行摘要', summary || '(未读到)');

    await caption(page, '跑完直接给结果，<b>过程和结论都留在这一屏</b>', 3400);

    // ------------------------------------------------------------ 产物
    await glide(page, 780, 430);
    await caption(page, '成品是<b>一份真的 Word 文档</b>，就在对话里，点开就能下载', 3600);

    // ------------------------------------------------------------ 用量
    await glide(page, 1380, 210);
    await caption(page, '右侧记着这次真实花了多少：<b>调用次数、token、成本、缓存命中率</b>', 4200);

    // ------------------------------------------------------------ 产物仓库
    await caption(page, '所有成品统一进<b>产物仓库</b>，可预览、可下载、可回溯', 3200);
    await page.goto(`${BASE_URL}/artifacts`, { waitUntil: 'domcontentloaded' });
    await ensureOverlay(page);
    await page.waitForTimeout(2600);
    await caption(page, '每件产物都记着<b>是哪一次运行生的</b>，随时往回查', 2800);

    // ------------------------------------------------------------ 设置页
    await page.goto(`${BASE_URL}/settings`, { waitUntil: 'domcontentloaded' });
    await ensureOverlay(page);
    await page.waitForTimeout(2400);
    await caption(page, '设置里能切<b>执行引擎</b>和演示模式，两者联动，不会各说各话', 3600);
    await page
      .getByText('执行引擎', { exact: false })
      .first()
      .scrollIntoViewIfNeeded()
      .catch(() => {});
    await page.waitForTimeout(1000);
    await caption(page, '思考过程想看多少自己定：<b>完整 / 主要步骤 / 不显示</b>', 3400);
    await page
      .getByText('思考过程', { exact: false })
      .first()
      .scrollIntoViewIfNeeded()
      .catch(() => {});
    await page.waitForTimeout(1200);

    // ------------------------------------------------------------ 片尾
    await card(
      page,
      {
        kicker: 'Office Agent',
        title: '把办公这件事，真的交出去',
        sub: '文档 · 表格 · 材料分析 · 全流程可追溯',
        meta: '技术文档 docs/tech/ · 后端 1454 + 前端 1276 条测试全绿',
      },
      4600,
    );

    log('演示流程结束');
  } catch (error) {
    console.error('!! 录制流程出错：', error?.message || error);
  } finally {
    const video = page.video();
    await context.close();
    await browser.close();

    // 收尾里不能用 return：finally 里的 return 会把 try 里的异常一起吞掉
    if (PROBE) {
      log('探路结束（未录制）');
    } else if (!video) {
      console.error('没有拿到视频对象');
    } else {
      await video.saveAs(OUT_FILE);
      log('视频已保存', OUT_FILE);
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
