/**
 * 真实任务节奏探测：发送一条任务，每 2 秒采样一次 UI 状态，把时间线写进日志文件。
 * 目的是在正式录制前摸清真实调用要多久、会不会触发工具卡与审批卡。
 *
 *   node scripts/probe-run.mjs
 */

import { chromium } from '@playwright/test';
import { appendFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');
const LOG = resolve(ROOT, 'data/probe-run.log');
const BASE_URL = 'http://127.0.0.1:5173';
const SAMPLE = resolve(ROOT, 'data/samples/meeting_notes.docx');
const TASK = process.env.DEMO_TASK || '把这份会议记录整理成一份 600 字左右的周报，输出成 Word 文档';

const t0 = Date.now();
const secs = () => ((Date.now() - t0) / 1000).toFixed(1);
writeFileSync(LOG, '');
const say = (line) => {
  const text = `[${secs().padStart(6)}s] ${line}`;
  console.log(text);
  appendFileSync(LOG, `${text}\n`);
};

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    locale: 'zh-CN',
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);

  say(`打开 ${BASE_URL}`);
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);

  say('新建会话');
  try {
    await page.getByText('新建会话', { exact: true }).first().click({ timeout: 4000 });
    say('  已点击新建会话');
  } catch {
    say('  未找到新建会话按钮，沿用当前会话');
  }
  await page.waitForTimeout(1200);

  say(`上传素材：${SAMPLE}`);
  await page.locator('input[type="file"]').first().setInputFiles(SAMPLE);
  await page.waitForTimeout(2600);
  say('  上传完成');

  say(`输入任务：${TASK}`);
  const input = page.locator('textarea[aria-label="任务输入框"]');
  await input.click();
  await input.fill(TASK);
  await page.waitForTimeout(600);

  say('点击发送');
  await page.locator('button[aria-label="发送"]').click();

  let sawThinking = false;
  let sawTool = false;
  let sawApproval = false;
  let lastLen = 0;

  for (let i = 0; i < 90; i += 1) {
    await page.waitForTimeout(2000);

    const state = await page.evaluate(() => {
      const body = document.body.innerText || '';
      const hasSend = !!document.querySelector('button[aria-label="发送"]');
      const hasStop = !!document.querySelector('button[aria-label="停止"]');
      const approve = Array.from(document.querySelectorAll('button'))
        .map((b) => (b.textContent || '').trim())
        .filter((t) => /批准|同意|允许|拒绝/.test(t));
      return {
        hasSend,
        hasStop,
        approve: approve.slice(0, 3),
        len: body.length,
        hasTool: /file\.list|工具|调用/.test(body),
        tail: body.slice(-160).replace(/\s+/g, ' '),
        done: /运行完成/.test(body),
        artifacts: (body.match(/产物\s*(\d+)\s*个/) || [])[1] ?? null,
        paused: /运行暂停中/.test(body),
      };
    });

    if (state.paused) say('  ⏸ 暂停等待审批');

    if (!sawThinking && state.hasStop) {
      sawThinking = true;
      say('  ▶ 开始运行（出现停止按钮）');
    }
    if (!sawTool && state.hasTool) {
      sawTool = true;
      say('  ▶ 出现工具调用痕迹');
    }
    if (!sawApproval && state.approve.length) {
      sawApproval = true;
      say(`  ▶ 出现审批按钮：${state.approve.join(' / ')}`);
      try {
        await page.getByRole('button', { name: state.approve[0] }).first().click({ timeout: 3000 });
        say(`  ▶ 已点击「${state.approve[0]}」`);
      } catch (e) {
        say(`  ▶ 点击审批失败：${e.message}`);
      }
    }
    if (state.len !== lastLen) {
      lastLen = state.len;
      if (i % 3 === 0) say(`  文本长度 ${state.len}`);
    }

    if (state.done) {
      say(`✅ 任务完成（出现「运行完成」）产物=${state.artifacts ?? '未知'}`);
      say(`   最终文本长度 ${state.len}`);
      say(`   结尾：${state.tail}`);
      break;
    }
  }

  say(`采样结束：思考=${sawThinking} 工具=${sawTool} 审批=${sawApproval}`);
  await page.screenshot({ path: resolve(ROOT, 'data/probe-after.png'), fullPage: false });
  await context.close();
  await browser.close();
  say('done');
}

main().catch((e) => {
  say(`ERROR ${e?.message || e}`);
  process.exit(1);
});
