import { chromium } from 'playwright';

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage();
const errors = [];
const apiCalls = [];

page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`));
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`[console] ${m.text()}`);
});
page.on('request', (r) => {
  if (r.url().includes('/api/')) apiCalls.push(r.url().replace('http://127.0.0.1:5174', ''));
});

await page.goto(process.env.PROBE_URL, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(2500);

const shot = await page.evaluate(() => {
  const root = document.querySelector('#root');
  const text = document.body.innerText.trim();
  return {
    rootChildren: root?.children.length ?? -1,
    textLen: text.length,
    head: text.slice(0, 140),
    // 首屏是不是「空壳」：有没有会话行
    hasSessions: /产物|小时前|分钟前/.test(text),
  };
});

console.log(JSON.stringify({ shot, apiCalls: [...new Set(apiCalls)].slice(0, 10), errors: errors.slice(0, 6) }, null, 1));
await browser.close();
