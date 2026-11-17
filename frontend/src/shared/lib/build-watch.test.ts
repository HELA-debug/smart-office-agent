/**
 * 桌面端跟着新构建刷新：只测「能不能认出入口脚本换了」这件事，
 * 刷新本身交给浏览器（jsdom 里 location.reload 不可用，也不值得 mock）。
 */
import { describe, expect, it } from 'vitest';
import { pickEntryScript, watchForRebuild } from './build-watch';

describe('pickEntryScript', () => {
  it('认得出 vite 产物的入口（type 在 src 前）', () => {
    const html = `<!doctype html><html><head></head><body>
      <div id="root"></div>
      <script type="module" crossorigin src="/assets/index-CsFgajK6.js"></script>
    </body></html>`;
    expect(pickEntryScript(html)).toBe('/assets/index-CsFgajK6.js');
  });

  it('属性顺序反过来也认（src 在 type 前）', () => {
    const html = '<script src="/assets/index-abc.js" type="module"></script>';
    expect(pickEntryScript(html)).toBe('/assets/index-abc.js');
  });

  it('没有入口脚本时返回 null，交给调用方保持现状', () => {
    expect(pickEntryScript('<html><body></body></html>')).toBeNull();
    expect(pickEntryScript('<script src="/x.js"></script>')).toBeNull();
  });

  it('开发态的 /src/main.tsx 也能取到（与页面自己一致，不会误刷）', () => {
    const html = '<script type="module" src="/src/main.tsx"></script>';
    expect(pickEntryScript(html)).toBe('/src/main.tsx');
  });
});

describe('watchForRebuild', () => {
  it('页面上没有模块入口时直接放弃，起一个空监听器的代价都不付', () => {
    const stop = watchForRebuild();
    expect(typeof stop).toBe('function');
    stop();
  });
});
