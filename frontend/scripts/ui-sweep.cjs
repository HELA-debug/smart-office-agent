/**
 * 视觉/布局自动巡检（对应 docs/test-prompts-2026-10-28.md 的 ① 视觉专项 + ③ 对比度）：
 * 6 个路由 × 3 档视口 × 亮暗两主题，逐页抓：横向溢出、越界元素、对比度不足、控制台报错、失败请求。
 * 只读操作：不点删除、不发指令。
 */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('@playwright/test');

const BASE = 'http://127.0.0.1:8000';
const OUT = path.resolve(__dirname, '../../docs/test-evidence-2026-10-28');
const SHOTS = path.join(OUT, 'shots');

const ROUTES = [
  ['工作台', '/'],
  ['产物中心', '/artifacts'],
  ['审计用量', '/audit'],
  ['设置', '/settings'],
  ['知识库', '/knowledge'],
  ['插件与技能', '/skills'],
];

const VIEWPORTS = [
  ['1440x900', 1440, 900],
  ['1024x768', 1024, 768],
  ['390x844', 390, 844],
];

const THEMES = ['dark', 'light'];

function collect(page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;

    /** 元素是否在一个「可以横向滑」的容器里：那种越界是设计好的，不算溢出 */
    const inScroller = (el) => {
      let node = el.parentElement;
      while (node && node !== document.body) {
        const style = getComputedStyle(node);
        if (style.overflowX === 'auto' || style.overflowX === 'scroll') return true;
        node = node.parentElement;
      }
      return false;
    };

    const offenders = [];
    for (const el of document.querySelectorAll('body *')) {
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0')
        continue;
      if (style.position === 'fixed' && style.pointerEvents === 'none') continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (r.right > vw + 2 || r.left < -2) {
        if (inScroller(el)) continue;
        offenders.push({
          tag: el.tagName.toLowerCase(),
          cls: String(el.className).slice(0, 90),
          text: (el.textContent || '').trim().slice(0, 30),
          left: Math.round(r.left),
          right: Math.round(r.right),
        });
      }
    }

    /* ---------- 对比度：正文 4.5:1，大字 3:1 ---------- */
    const parseRgb = (value) => {
      const m = value.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const parts = m[1]
        .split(/[,\s/]+/)
        .filter(Boolean)
        .map(Number);
      if (parts.length < 3) return null;
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    };
    const over = (fg, bg) => ({
      r: fg.r * fg.a + bg.r * (1 - fg.a),
      g: fg.g * fg.a + bg.g * (1 - fg.a),
      b: fg.b * fg.a + bg.b * (1 - fg.a),
      a: 1,
    });
    const lum = (c) => {
      const f = (v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    };
    const ratio = (a, b) => {
      const l1 = lum(a);
      const l2 = lum(b);
      return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    };

    const effectiveBg = (el) => {
      let node = el;
      let acc = null;
      while (node) {
        const style = getComputedStyle(node);
        const rgb = parseRgb(style.backgroundColor);
        if (rgb && rgb.a > 0) {
          acc = acc ? over(acc, rgb) : rgb;
          if (rgb.a === 1) return acc;
        }
        node = node.parentElement;
      }
      // 一路透明：按页面底色兜（html 的背景色一定不透明）
      const rootBg = parseRgb(getComputedStyle(document.documentElement).backgroundColor);
      if (!acc) return rootBg ?? { r: 255, g: 255, b: 255, a: 1 };
      return rootBg && rootBg.a === 1 ? over(acc, rootBg) : acc;
    };

    const lowContrast = [];
    for (const el of document.querySelectorAll('body *')) {
      const hasText = Array.from(el.childNodes).some(
        (node) => node.nodeType === 3 && (node.textContent || '').trim().length > 1,
      );
      if (!hasText) continue;
      const style = getComputedStyle(el);
      if (
        style.display === 'none' ||
        style.visibility === 'hidden' ||
        Number(style.opacity) === 0
      ) {
        continue;
      }
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const fg = parseRgb(style.color);
      if (!fg) continue;
      const bg = effectiveBg(el);
      const color = fg.a < 1 ? over(fg, bg) : fg;
      const value = ratio(color, bg);
      const size = Number.parseFloat(style.fontSize);
      const bold = Number(style.fontWeight) >= 700;
      const large = size >= 24 || (size >= 18.66 && bold);
      const need = large ? 3 : 4.5;
      if (value < need) {
        lowContrast.push({
          text: (el.textContent || '').trim().slice(0, 24),
          cls: String(el.className).slice(0, 70),
          color: style.color,
          size: Math.round(size),
          ratio: Math.round(value * 100) / 100,
          need,
        });
      }
    }

    return {
      vw,
      docScrollW: document.documentElement.scrollWidth,
      bodyScrollW: document.body.scrollWidth,
      offenders: offenders.slice(0, 8),
      offenderCount: offenders.length,
      lowContrast: lowContrast.slice(0, 12),
      lowContrastCount: lowContrast.length,
    };
  });
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge' });
  const results = [];

  for (const [routeName, route] of ROUTES) {
    for (const [vpName, width, height] of VIEWPORTS) {
      for (const theme of THEMES) {
        const context = await browser.newContext({ viewport: { width, height } });
        const page = await context.newPage();
        const consoleErrors = [];
        const pageErrors = [];
        const badResponses = [];
        page.on('console', (msg) => {
          if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 200));
        });
        page.on('pageerror', (err) => pageErrors.push(String(err).slice(0, 200)));
        page.on('response', (res) => {
          if (res.status() >= 400)
            badResponses.push(`${res.status()} ${res.url().replace(BASE, '')}`);
        });

        await page.addInitScript((t) => {
          localStorage.setItem('oa:theme', t);
        }, theme);

        const openErrors = [];
        try {
          await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle', timeout: 20_000 });
          await page.waitForTimeout(700);
        } catch (err) {
          openErrors.push(String(err).slice(0, 200));
        }

        const layout = openErrors.length
          ? {
              vw: width,
              docScrollW: -1,
              bodyScrollW: -1,
              offenders: [],
              offenderCount: -1,
              lowContrast: [],
              lowContrastCount: -1,
            }
          : await collect(page);

        const id = `${route === '/' ? 'workbench' : route.replace(/\//g, '')}-${vpName}-${theme}`;
        const shot = path.join(SHOTS, `${id}.png`);
        try {
          await page.screenshot({ path: shot });
        } catch {
          /* 页面已崩，截图无所谓 */
        }

        results.push({
          route: routeName,
          path: route,
          viewport: vpName,
          theme,
          id,
          shot: path.relative(OUT, shot),
          horizontalOverflow: layout.docScrollW > layout.vw + 1,
          offenderCount: layout.offenderCount,
          offenders: layout.offenders,
          lowContrastCount: layout.lowContrastCount,
          lowContrast: layout.lowContrast,
          consoleErrors,
          pageErrors,
          badResponses: badResponses.filter((item) => !item.includes('/favicon')),
          openErrors,
        });

        await context.close();
      }
    }
  }

  await browser.close();
  fs.writeFileSync(path.join(OUT, 'sweep.json'), JSON.stringify(results, null, 2));

  const failing = results.filter(
    (r) =>
      r.horizontalOverflow ||
      r.pageErrors.length ||
      r.badResponses.length ||
      r.openErrors.length ||
      r.consoleErrors.length,
  );
  const contrast = results.filter((r) => r.lowContrastCount > 0);
  console.log(
    `cases=${results.length} 布局/请求问题=${failing.length} 对比度不足=${contrast.length}`,
  );
  for (const item of failing) {
    console.log('---', item.id);
    if (item.horizontalOverflow) console.log('   横向溢出', item.offenderCount, '个元素');
    for (const o of item.offenders.slice(0, 3))
      console.log('   ·', o.tag, o.cls, `[${o.left},${o.right}]`);
    for (const e of item.pageErrors.slice(0, 2)) console.log('   pageerror:', e);
    for (const e of item.badResponses.slice(0, 3)) console.log('   4xx/5xx:', e);
    for (const e of item.consoleErrors.slice(0, 2)) console.log('   console:', e);
  }
  for (const item of contrast) {
    console.log('=== 对比度', item.id, item.lowContrastCount);
    for (const c of item.lowContrast.slice(0, 3)) {
      console.log(`   ${c.ratio}:1 <${c.need}  ${c.size}px  ${JSON.stringify(c.text)}  ${c.color}`);
    }
  }
})();
