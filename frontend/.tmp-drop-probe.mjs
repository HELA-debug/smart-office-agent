/**
 * 临时诊断脚本（不进仓库）：用 CDP 的 Input.dispatchDragEvent 模拟「从资源管理器拖文件进来」，
 * 复现真实 drop 里 dataTransfer 到底是什么。用完即删。
 */
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const dir = join(tmpdir(), 'drop-probe');
mkdirSync(dir, { recursive: true });
const filePath = join(dir, '周会纪要.txt');
writeFileSync(filePath, '这是一份测试素材，用来验证拖拽上传。\n', 'utf8');

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on('console', (m) => console.log('[console]', m.type(), m.text().slice(0, 200)));
page.on('pageerror', (e) => console.log('[pageerror]', e.message));

await page.goto('http://127.0.0.1:5173', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(2500);

// 把 dataTransfer 的真实内容打印出来：看 drop 到页面时到底有没有 files
await page.evaluate(() => {
  window.__dropLog = [];
  for (const type of ['dragenter', 'dragover', 'drop']) {
    window.addEventListener(
      type,
      (e) => {
        const dt = e.dataTransfer;
        window.__dropLog.push({
          type,
          defaultPrevented: e.defaultPrevented,
          target: e.target?.tagName + '.' + (e.target?.className || '').toString().slice(0, 40),
          types: dt ? Array.from(dt.types) : null,
          files: dt ? dt.files.length : null,
          fileNames: dt ? Array.from(dt.files).map((f) => f.name) : null,
          items: dt ? Array.from(dt.items).map((i) => `${i.kind}:${i.type}`) : null,
          hasEntry: dt
            ? Array.from(dt.items).map((i) => typeof i.webkitGetAsEntry === 'function' && !!i.webkitGetAsEntry())
            : null,
        });
      },
      true, // 捕获阶段：比 React 更早看到，defaultPrevented 反映的是「之前」的状态
    );
  }
});

const box = await page.locator('textarea').first().boundingBox();
if (!box) throw new Error('找不到输入框');
const x = Math.round(box.x + box.width / 2);
const y = Math.round(box.y + box.height / 2);

const cdp = await page.context().newCDPSession(page);
const dragData = {
  items: [],
  files: [filePath],
  dragOperationsMask: 1,
};
for (const type of ['dragEnter', 'dragOver', 'drop']) {
  await cdp.send('Input.dispatchDragEvent', { type, x, y, data: dragData });
  await page.waitForTimeout(300);
}
await page.waitForTimeout(1200);

console.log('\n=== 页面里捕获到的事件 ===');
console.log(JSON.stringify(await page.evaluate(() => window.__dropLog), null, 1));

console.log('\n=== 界面上的提示 ===');
const hint = await page.evaluate(() => {
  const hit = Array.from(document.querySelectorAll('p,span,div'))
    .map((el) => el.textContent?.trim() || '')
    .filter((t) => t.includes('没读到') || t.includes('上传') || t.includes('素材'));
  return Array.from(new Set(hit)).slice(0, 6);
});
console.log(hint);

await page.screenshot({ path: join(dir, 'after-drop.png') });
console.log('\n截图:', join(dir, 'after-drop.png'));
await browser.close();
