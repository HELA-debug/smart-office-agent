import { expect, test } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';

async function backendReady(request: APIRequestContext) {
  try {
    const response = await request.get('http://127.0.0.1:8000/api/v1/health', { timeout: 3000 });
    return response.ok();
  } catch {
    return false;
  }
}

test.describe('冒烟：页面可达', () => {
  test('工作台空状态三区可见', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByText('Office Agent', { exact: false }).first()).toBeVisible();
    await expect(page.getByRole('heading', { name: /把一份材料/ })).toBeVisible();
    await expect(page.getByRole('button', { name: '新建会话' })).toBeVisible();
    await expect(page.getByLabel('任务输入框')).toBeVisible();
    await expect(page.getByRole('button', { name: '发送' })).toBeVisible();
    await expect(page.getByRole('button', { name: /上传素材/ }).first()).toBeVisible();
  });

  test('知识库占位页可达', async ({ page }) => {
    await page.goto('/knowledge');
    await expect(page.getByText('即将上线').first()).toBeVisible();
    await expect(page.getByRole('link', { name: /返回首页/ }).first()).toBeVisible();
  });

  test('右栏默认收起，展开后是产物仓库（素材区已删）', async ({ page }) => {
    await page.goto('/?mock=1');

    // 交付物已经摆在对话里，右栏是「回头翻」的次要视图，默认不占宽度
    await expect(page.getByRole('button', { name: '展开右栏' })).toBeVisible();
    await expect(page.locator('aside')).toHaveCount(1); // 只有左栏

    await page.getByRole('button', { name: '展开右栏' }).click();
    await expect(page.getByText('产物仓库')).toBeVisible();
    await expect(page.getByText('本次素材')).toHaveCount(0);
    // 审批已内联进对话流，右栏不再有独立审批区
    await expect(page.getByText('审批', { exact: true })).toHaveCount(0);
  });

  test('顶栏 hover 提示不被视口裁切', async ({ page }) => {
    await page.goto('/?mock=1');

    // 顶栏紧贴视口上边缘：提示气泡必须自动翻到下方且完整可见
    const toggle = page.getByRole('button', { name: /收起右栏|展开右栏/ });
    await toggle.hover();

    const tip = page.getByRole('tooltip');
    await expect(tip).toBeVisible();
    const box = await tip.boundingBox();
    const viewport = page.viewportSize();
    expect(box).not.toBeNull();
    if (box && viewport) {
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    }
    // 气泡文案与按钮语义一致
    await expect(tip).toHaveText(/收起右栏|展开右栏/);
  });
});

test.describe('Mock 模式：新交互', () => {
  test('右栏只放产物（审批已搬进对话流）', async ({ page }) => {
    await page.goto('/?mock=1');
    await page.getByRole('button', { name: '展开右栏' }).click();

    await expect(page.getByText('产物仓库')).toBeVisible();
    // 审批独立面板与「无待办」徽标都从右栏撤掉，审批卡只在对话流里出现
    await expect(page.getByText('审批', { exact: true })).toHaveCount(0);
    await expect(page.getByText('当前无待审批动作')).toHaveCount(0);
    // 用量与额度早已下线，充值入口也一并移除
    await expect(page.getByText('用量与额度')).toBeHidden();
    await expect(page.getByRole('button', { name: '充值', exact: true })).toHaveCount(0);
  });

  test('产物仓库：空态一句话，不再有「本次素材」', async ({ page }) => {
    await page.goto('/?mock=1');
    await page.getByRole('button', { name: '展开右栏' }).click();
    const rail = page.locator('aside').last();

    // 产物空态：一行说明就够，起步示例已经撤掉（那是输入框的活儿）
    await expect(rail.getByText(/这个会话还没有文件/)).toBeVisible();
    await expect(rail.getByText('可以先让我做这些')).toHaveCount(0);
    // 底部「本次素材」已按需求删除：素材在输入框和对话里都看得见
    await expect(rail.getByText('本次素材')).toHaveCount(0);
    await expect(rail.getByText('本次运行')).toHaveCount(0);
  });

  test('默认深色，对话区标题行的太阳/月亮可来回切', async ({ page }) => {
    await page.goto('/?mock=1');
    const html = page.locator('html');

    // 没存过偏好：默认深色（白底整片刺眼，办公界面给暗底）
    await expect(html).toHaveClass(/dark/);
    // 主题是标题行右侧的一枚图标，不是左栏底部那颗带文字的入口
    await expect(page.getByRole('button', { name: '切换到浅色主题' })).toBeVisible();

    await page.getByRole('button', { name: '切换到浅色主题' }).click();
    await expect(html).not.toHaveClass(/dark/);
    await page.getByRole('button', { name: '切换到深色主题' }).click();
    await expect(html).toHaveClass(/dark/);
  });

  test('顶栏不再放审计入口，审计回到右栏「本次会话」', async ({ page }) => {
    await page.goto('/?mock=1');
    // 顶栏那个「审计」按钮已删：它跟主题、右栏开关挤在一起，且右栏本来就有按会话的入口
    await expect(page.getByRole('button', { name: '审计', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '展开右栏' }).click();
    await expect(page.getByRole('button', { name: '打开审计用量' })).toBeVisible();
  });

  test('左栏：品牌 + 新建 + 搜索 + 导航 + 项目 + 会话（模板区已移除）', async ({ page }) => {
    await page.goto('/?mock=1');
    const rail = page.locator('aside').first();

    // 品牌区：名称 + 版本 + 收起按钮（参照桌面端侧栏的顶部排版）
    await expect(rail.getByText('Office Agent', { exact: true })).toBeVisible();
    await expect(rail.getByText(/V0\.2\.0/)).toBeVisible();
    await expect(rail.getByRole('button', { name: '收起侧边栏' })).toBeVisible();

    await expect(rail.getByRole('button', { name: '新建会话' })).toBeVisible();
    await expect(rail.getByLabel('搜索会话')).toBeVisible();

    // 导航是「图标 + 文字」一行一个，不再收进底部小图标条
    const nav = rail.getByRole('navigation', { name: '功能导航' });
    for (const label of ['产物中心', '审计用量', '设置', '插件与技能', '知识库']) {
      await expect(nav.getByRole('link', { name: label })).toBeVisible();
    }

    // 模板整块删除：文案与入口都不该再出现
    await expect(rail.getByText('模板', { exact: true })).toHaveCount(0);
    await expect(rail.getByRole('button', { name: '添加个人模板' })).toHaveCount(0);
    for (const label of ['周报', '会议纪要', '文件摘要']) {
      await expect(rail.getByRole('button', { name: new RegExp(`^${label}`) })).toHaveCount(0);
    }

    // 项目区常驻
    await expect(rail.getByRole('button', { name: '添加项目' })).toBeVisible();
    // 底部身份卡已删（第五十四轮）：那块高度直接交给会话列表，列表铺到面板底沿
    await expect(rail.getByText('本机 · 演示环境')).toHaveCount(0);
    const railBox = await rail.boundingBox();
    const listBox = await page.getByTestId('session-list').boundingBox();
    expect(
      railBox && listBox && railBox.y + railBox.height - (listBox.y + listBox.height),
    ).toBeLessThan(12);
    // 主题开关不在左栏（在对话区标题行）
    await expect(rail.getByRole('button', { name: /切换到(浅色|深色)主题/ })).toHaveCount(0);
  });

  test('左栏高度：矮窗口自动收起项目区，会话列表始终占满剩余且能滚', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 600 });
    await page.goto('/?mock=1');
    const rail = page.locator('aside').first();
    const toggle = rail.getByRole('button', { name: /^项目/ }).first();

    // 矮窗口：项目区自动收起（内容退出无障碍树，添加入口仍留在标题行）
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(rail.getByRole('button', { name: '添加项目' })).toBeVisible();

    const list = page.getByTestId('session-list');
    const listBox = await list.boundingBox();
    // min-h-[7rem] 且根字号 90%：会话区拿到的高度不会低于 ~100px
    expect(listBox?.height ?? 0).toBeGreaterThan(96);
    // 会话列内部自己滚，不靠整栏滚动
    const scrolls = await list.evaluate((node) => ({
      overflowY: getComputedStyle(node).overflowY,
      railOverflow: (() => {
        const aside = node.closest('aside');
        return aside ? aside.scrollHeight - aside.clientHeight : 0;
      })(),
    }));
    expect(scrolls.overflowY).toBe('auto');
    expect(scrolls.railOverflow).toBe(0);

    // 窗口拉高：项目区回来，会话列表跟着变高（谁也没被裁）
    await page.setViewportSize({ width: 1280, height: 860 });
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const taller = await list.boundingBox();
    expect(taller?.height ?? 0).toBeGreaterThan((listBox?.height ?? 0) + 120);

    // 手动收起后仍能点开：折叠只是收纳，不是删功能
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  test('卡片式外壳：三块面板各自浮在画布上，靠圆角 + 描边 + 投影分区', async ({ page }) => {
    await page.goto('/?mock=1');

    const shell = page.getByTestId('workbench-shell');
    const shellPadding = await shell.evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        top: Number.parseFloat(style.paddingTop),
        left: Number.parseFloat(style.paddingLeft),
      };
    });
    // 外壳留一圈内边距：面板不贴窗口边缘，才浮得起来
    expect(shellPadding.top).toBeGreaterThan(6);
    expect(shellPadding.left).toBeGreaterThan(6);

    const rail = page.locator('aside').first();
    const railBox = await rail.boundingBox();
    const mainBox = await page.locator('main').first().boundingBox();
    expect(railBox?.x ?? -1).toBe(shellPadding.left);
    expect(railBox?.y ?? -1).toBe(shellPadding.top);
    // 左栏和对话区之间留缝（gap），两块不是描边贴描边
    const gap = (mainBox?.x ?? 0) - ((railBox?.x ?? 0) + (railBox?.width ?? 0));
    expect(gap).toBeGreaterThan(6);

    // 分区靠的是「圆角 + 描边 + 投影」，三块面板各是一张卡片
    const card = async (locator: typeof rail) =>
      locator.evaluate((node) => {
        const style = getComputedStyle(node);
        return {
          radius: Number.parseFloat(style.borderTopLeftRadius),
          border: Number.parseFloat(style.borderTopWidth),
          shadow: style.boxShadow,
        };
      });
    const railCard = await card(rail);
    const mainCard = await card(page.locator('main').first());
    expect(railCard.radius).toBeGreaterThanOrEqual(12);
    expect(mainCard.radius).toBeGreaterThanOrEqual(12);
    expect(railCard.border).toBeGreaterThan(0);
    expect(mainCard.border).toBeGreaterThan(0);
    expect(railCard.shadow).not.toBe('none');
    expect(mainCard.shadow).not.toBe('none');
  });

  test('左栏可收起为图标条，悬停浮现名称', async ({ page }) => {
    await page.goto('/?mock=1');
    const shell = page.getByTestId('workbench-shell');
    const rail = page.locator('aside').first();

    const widthOfRail = async () => {
      const box = await rail.boundingBox();
      return Math.round(box?.width ?? 0);
    };
    const expandedWidth = await widthOfRail();
    expect(expandedWidth).toBeGreaterThan(200);

    // 收起入口有两处（品牌行 + 对话区标题行），这里走左栏自己那颗
    await rail.getByRole('button', { name: '收起侧边栏' }).click();
    // 收起成 3.25rem 的图标条：宽度变了，但栏还在
    await expect.poll(widthOfRail).toBeLessThan(80);
    await expect(rail.getByRole('button', { name: '展开侧边栏' })).toBeVisible();
    // 对话区标题行的那颗跟着换文案，两个入口永远一致
    await expect(page.getByRole('main').getByRole('button', { name: '展开侧边栏' })).toBeVisible();
    // 收起态不显示文字导航，只留图标（靠 aria-label / 悬停浮层说清是什么）
    await expect(page.getByLabel('搜索会话')).toHaveCount(0);
    await expect(page.getByText('Office Agent', { exact: true })).toHaveCount(0);
    // 会话条目不进收起态（第五十七轮）：窄条里认不出是哪条，还平白拖出一条滚动条
    await expect(page.getByTestId('session-list')).toHaveCount(0);
    const scrollers = await rail.evaluate(
      (node) =>
        [...node.querySelectorAll('*')].filter((el) =>
          ['auto', 'scroll'].includes(getComputedStyle(el).overflowY),
        ).length,
    );
    expect(scrollers).toBe(0);

    // 悬停浮出名称 + 一句说明：浮层是 fixed 的，不会被宽度动画容器裁掉
    const artifacts = shell.getByRole('link', { name: '产物中心' });
    await artifacts.hover();
    const flyout = page.getByText('跨会话产物、筛选、预览与下载');
    await expect(flyout).toBeVisible();
    const box = await flyout.boundingBox();
    const railBox = await rail.boundingBox();
    // 浮在图标条右侧，且整块在视口内
    expect(box?.x ?? 0).toBeGreaterThanOrEqual((railBox?.x ?? 0) + (railBox?.width ?? 0));
    const viewport = page.viewportSize();
    if (box && viewport) {
      expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    }

    // 展开回去：宽度恢复，文字导航回来
    await rail.getByRole('button', { name: '展开侧边栏' }).click();
    await expect.poll(widthOfRail).toBe(expandedWidth);
    await expect(page.getByLabel('搜索会话')).toBeVisible();
  });

  test('左右两条侧边栏各自独立收起：都收起时只剩对话区', async ({ page }) => {
    await page.goto('/?mock=1');
    const rail = page.locator('aside').first();

    await rail.getByRole('button', { name: '收起侧边栏' }).click();
    await page.getByRole('button', { name: '展开右栏' }).click();

    // 左栏成图标条、右栏展开：两块都在
    await expect(rail.getByRole('button', { name: '展开侧边栏' })).toBeVisible();
    await expect(page.getByRole('button', { name: '收起右栏' })).toBeVisible();
    await expect(page.getByText('产物仓库')).toBeVisible();

    // 右栏再收起，只剩对话区 + 左侧图标条
    await page.getByRole('button', { name: '收起右栏' }).click();
    await expect(page.getByText('产物仓库')).toHaveCount(0);
    await expect(rail.getByRole('button', { name: '展开侧边栏' })).toBeVisible();
    await expect(page.getByLabel('任务输入框')).toBeVisible();
  });

  test('右栏底部有桌面端入口，点开给安装指引', async ({ page }) => {
    await page.goto('/?mock=1');
    await page.getByRole('button', { name: '展开右栏' }).click();

    const entry = page.getByRole('button', { name: /安装桌面端|桌面端已就绪/ });
    await expect(entry).toBeVisible();
    await entry.click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    // 只给电脑端的步骤：手机 / 平板拿不到本机文件夹，装上去也用不了
    await expect(dialog.getByText('Chrome / Edge（Windows、macOS）')).toBeVisible();
    await expect(dialog.getByText('Safari（macOS 14 及以上）')).toBeVisible();
    await expect(dialog.getByText(/iPhone|iPad|Android|添加到主屏幕/)).toHaveCount(0);

    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  test.describe('手机 / 平板不给桌面端入口', () => {
    // UA 按 iPhone 走，但视口留成桌面宽度：这样右栏是挂在 DOM 里的，
    // 断言「没有这个入口」才是真被平台判断挡住，而不是整块压根没渲染。
    test.use({
      userAgent:
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
      viewport: { width: 1280, height: 800 },
    });

    test('iPhone 上不渲染「安装桌面端」', async ({ page }) => {
      await page.goto('/?mock=1');
      // 手机拿不到本机文件夹，装了也只是个用不了的壳子
      await expect(page.locator('[aria-label="桌面端"]')).toHaveCount(0);
      await expect(page.getByRole('button', { name: /安装桌面端|桌面端已就绪/ })).toHaveCount(0);
    });
  });

  test('桌面端是真的可安装：manifest 有效 + Service Worker 已接管', async ({ page }) => {
    await page.goto('/?mock=1');

    // manifest 能被浏览器解析，且带 192/512 图标——少了这两条，Chrome 不给安装入口
    const manifest = await page.evaluate(async () => {
      const response = await fetch('/manifest.webmanifest');
      return response.json() as Promise<{ display?: string; icons?: { sizes?: string }[] }>;
    });
    expect(manifest.display).toBe('standalone');
    const sizes = (manifest.icons ?? []).map((icon) => icon.sizes ?? '');
    expect(sizes).toContain('192x192');
    expect(sizes).toContain('512x512');

    // SW 注册成功才有安装资格
    await page.waitForFunction(
      async () => Boolean(await navigator.serviceWorker.getRegistration()),
      undefined,
      { timeout: 15_000 },
    );

    // 用浏览器自己的可安装性检查来判分：除了「无痕窗口」这一条，
    // 不允许有任何错误（少了图标/display/start_url/SW 都会在这里报出来）
    const client = await page.context().newCDPSession(page);
    const { installabilityErrors } = (await client.send('Page.getInstallabilityErrors')) as {
      installabilityErrors: { errorId: string }[];
    };
    expect(installabilityErrors.map((item) => item.errorId)).toEqual(['in-incognito']);
  });

  test('桌面端窗口融进外壳：声明 WCO 就必须自己让位，标题栏颜色跟着主题走', async ({ page }) => {
    await page.goto('/?mock=1');

    // 上一版因为「声明了 window-controls-overlay 却没让位，右栏标题行的「⋯」顶进 — □ ✕」
    // 退回标准 standalone，结果是窗口顶部多一条浏览器画的标题栏，和卡片式外壳割裂。
    // 现在两头一起做：声明 overlay，同时由 --titlebar-h 给窗口按钮让位、补顶部拖拽区。
    const manifest = await page.evaluate(async () => {
      const response = await fetch('/manifest.webmanifest');
      return response.json() as Promise<{ display?: string; display_override?: string[] }>;
    });
    expect(manifest.display_override?.[0]).toBe('window-controls-overlay');
    // 不支持 overlay 的浏览器/系统必须还能装，所以保留 standalone 兜底
    expect(manifest.display_override).toContain('standalone');

    // 让位机制：变量默认 0（网页态布局不变），外壳留 10px 内边距把三块面板浮起来，
    // 标题栏那一条高度交给面板内部的 `.window-inset-top`（减去外壳已经给过的那 10px）
    const shell = page.getByTestId('workbench-shell');
    expect(
      await page.evaluate(() =>
        getComputedStyle(document.documentElement).getPropertyValue('--titlebar-h').trim(),
      ),
    ).toBe('0px');
    const shellTop = async () =>
      Number.parseFloat(await shell.evaluate((node) => getComputedStyle(node).paddingTop));
    // 卡片式外壳：四周留一圈内边距（0.625rem，根字号 90% 基准下 9px），
    // 三块面板各自是圆角卡片，而不是贴边铺满的平铺面板
    const shellPad = await shellTop();
    expect(shellPad).toBeGreaterThan(6);
    expect(shellPad).toBeLessThan(12);

    // 装上之后 JS 会把真实高度写进这个变量。外壳**不整体下移**（那样会在标题栏
    // 下面留一条空隙，左栏顶部像悬空），而是由每个面板内部让出按钮高度：
    // 面板仍贴着外壳上沿，里面的按钮 / 标题落在 — □ ✕ 下沿之下。
    const main = page.locator('main').first();
    const inset = async () =>
      Number.parseFloat(await main.evaluate((node) => getComputedStyle(node).paddingTop));
    expect(await inset()).toBe(0);
    await page.evaluate(() => {
      document.documentElement.style.setProperty('--titlebar-h', '34px');
    });
    expect(await shellTop()).toBe(shellPad);
    // 外壳已经让了一圈内边距，面板内部只需要补差额，内容刚好落在窗口按钮下沿
    expect(await inset()).toBe(34 - shellPad);
    // 面板上沿仍在窗口顶上（只是被外壳的 10px 内边距托着），没有被推到标题栏下面
    expect(await main.evaluate((node) => node.getBoundingClientRect().top)).toBeLessThan(16);

    // 原生标题栏不在了，顶部这条透明区负责拖窗口
    const band = page.getByTestId('titlebar-drag-band');
    const dragRegion = await band.evaluate((node) => {
      const style = getComputedStyle(node);
      return { height: style.height, region: style.getPropertyValue('-webkit-app-region') };
    });
    expect(dragRegion.height).toBe('34px');
    expect(dragRegion.region).toBe('drag');
    await page.evaluate(() => {
      document.documentElement.style.removeProperty('--titlebar-h');
    });

    // 标题栏颜色不能是品牌蓝（会涂满整条系统标题栏），也不能比页面顶边更深：
    // 必须是页面最上沿那个色，否则屏幕上沿会出现一条「另一套配色」的横带
    const themeColors = () =>
      page.evaluate(() =>
        Array.from(document.querySelectorAll('meta[name="theme-color"]')).map((meta) =>
          meta.getAttribute('content'),
        ),
      );
    expect(await themeColors()).toEqual(['#101317', '#101317']);

    await page.getByRole('button', { name: '切换到浅色主题' }).click();
    expect(await themeColors()).toEqual(['#f3f5f9', '#f3f5f9']);
    // 窗口最外沿、页面底色、工作台外壳三处同值：翻页时整扇窗口不该变色
    const tokens = await page.evaluate(() => {
      const style = getComputedStyle(document.documentElement);
      return {
        canvas: style.getPropertyValue('--color-canvas').trim(),
        shell: style.getPropertyValue('--color-shell').trim(),
        top: style.getPropertyValue('--color-surface').trim(),
      };
    });
    expect(tokens.shell).toBe(tokens.canvas);
    expect(await themeColors()).toEqual([tokens.canvas, tokens.canvas]);
    // 面板仍然是比底色亮一档的 surface，卡片层级靠它 + 描边 + 投影撑住
    expect(tokens.top).not.toBe(tokens.canvas);
  });

  test('独立窗口里浮层也让位：右栏抽屉、弹窗都不钻到 — □ ✕ 底下', async ({ page }) => {
    // 窄窗口下右栏变成抽屉。抽屉是 fixed inset-0，坐标相对窗口而不是外壳，
    // 少让这一步就会把面板顶边和「本次会话」一行送到窗口按钮底下（桌面端实测的 bug）。
    await page.setViewportSize({ width: 900, height: 640 });
    await page.goto('/?mock=1');
    await page.evaluate(() => {
      document.documentElement.style.setProperty('--titlebar-h', '34px');
    });

    await page.getByRole('button', { name: '展开右栏' }).click();
    const drawerLabel = page.getByText('本次会话').first();
    await expect(drawerLabel).toBeVisible();
    const drawerBox = await drawerLabel.boundingBox();
    // 34（标题栏）+ 8（抽屉自己的 p-2）是下限
    expect(drawerBox?.y ?? 0).toBeGreaterThanOrEqual(34);
    await page.getByRole('button', { name: '关闭右栏' }).click();

    // 弹窗同样：容器让出标题栏高度，标题行不会被窗口按钮压住
    // 技能入口已经内化到「+」菜单里（第六十轮），先开加号菜单 → 悬停「技能」→ 导入技能
    await page.getByRole('button', { name: /更多输入选项/ }).click();
    await page.getByRole('menuitem', { name: /技能/ }).hover();
    await page.locator('[role="menu"][aria-label="技能"] button', { hasText: '导入技能' }).click();
    const guide = page.getByRole('dialog', { name: '做一个自己的技能' });
    await expect(guide).toBeVisible();
    const containerPadding = await guide.evaluate(
      (node) => getComputedStyle(node.parentElement as Element).paddingTop,
    );
    expect(Number.parseFloat(containerPadding)).toBeGreaterThanOrEqual(34);
  });

  test('会话导出：只剩两个真动作，假分享渠道已撤', async ({ page }) => {
    await page.goto('/?mock=1');

    // 先发一条任务建出会话（空列表没有行内动作）
    const box = page.locator('textarea').first();
    await box.fill('把这份材料整理成 600 字周报');
    await box.press('Enter');

    const rail = page.locator('aside').first();
    const exportButton = rail.getByRole('button', { name: '导出会话' }).first();
    await expect(exportButton).toBeVisible({ timeout: 15_000 });
    await exportButton.click();

    const menu = page.getByRole('menu', { name: '导出会话' });
    await expect(menu).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: /复制 Markdown/ })).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: /下载 \.md/ })).toBeVisible();
    // 六个点不出结果的渠道按钮不该再出现
    for (const label of ['微信', '企业微信', 'QQ', '钉钉', '腾讯文档', '复制链接']) {
      await expect(menu.getByRole('menuitem', { name: label, exact: true })).toHaveCount(0);
    }

    // 导出 .md 是真的下载文件，不只是弹提示
    const download = page.waitForEvent('download');
    await menu.getByRole('menuitem', { name: /下载 \.md/ }).click();
    expect((await download).suggestedFilename()).toContain('.md');
  });

  test('会话 ⋮ 菜单一次显示全（不被列表容器裁切）', async ({ page }) => {
    await page.goto('/?mock=1');

    // 先发一条任务建出会话（空列表没有 ⋮ 可点）
    const box = page.locator('textarea').first();
    await box.fill('把这份材料整理成 600 字周报');
    await box.press('Enter');

    await page.getByRole('button', { name: '更多操作' }).first().click();
    const menu = page.getByRole('menu', { name: '会话操作' });
    await expect(menu).toBeVisible();

    // 四个动作全在，且整块在视口内 —— 之前贴着列表底部就被 overflow 裁掉半截
    for (const label of [/置顶/, /重命名/, /复制标题/, /删除/]) {
      await expect(menu.getByRole('menuitem', { name: label })).toBeVisible();
    }
    const menuBox = await menu.boundingBox();
    const viewport = page.viewportSize();
    expect(menuBox).not.toBeNull();
    if (menuBox && viewport) {
      expect(menuBox.y).toBeGreaterThanOrEqual(0);
      expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(viewport.height);
    }
    // 菜单打开时按钮不再弹 hover 气泡（否则两条浮层叠在一起）
    await expect(page.getByRole('tooltip')).toHaveCount(0);
  });

  test('复制会话标题弹出轻提示：操作不再静默', async ({ page }) => {
    await page.goto('/?mock=1');

    // 先发一条任务建出会话（空列表没有 ⋮ 可点）
    const box = page.locator('textarea').first();
    await box.fill('把这份材料整理成 600 字周报');
    await box.press('Enter');

    await page.getByRole('button', { name: '更多操作' }).first().click();
    await page.getByRole('menuitem', { name: /复制标题/ }).click();

    // 剪贴板权限可能被拒，成功/失败都得给反馈（以前点了没有任何提示）
    const toast = page.getByRole('status').filter({ hasText: /已复制会话标题|复制失败/ });
    await expect(toast).toBeVisible();

    // 提示挂在 body 上、落在视口内右下角，不会被左栏的 overflow 裁掉
    const toastBox = await toast.boundingBox();
    const viewport = page.viewportSize();
    expect(toastBox).not.toBeNull();
    if (toastBox && viewport) {
      expect(toastBox.x + toastBox.width).toBeLessThanOrEqual(viewport.width);
      expect(toastBox.y + toastBox.height).toBeLessThanOrEqual(viewport.height);
    }

    // 自动消失，不需要用户手动关
    await expect(toast).toHaveCount(0, { timeout: 8000 });
  });

  test('输入框：技能弹层（勾选 / 删除 / 导入）与审批策略', async ({ page }) => {
    await page.goto('/?mock=1');

    // 技能入口在「+」菜单里：工具条上不再单挂一个胶囊，和「产物格式」共用一套二级面板
    await page.getByRole('button', { name: /更多输入选项/ }).click();
    await page.getByRole('menuitem', { name: /技能/ }).hover();
    const panel = page.locator('[role="menu"][aria-label="技能"]');
    await expect(panel).toBeVisible();
    await expect(panel.getByText(/启用 · 提示词/)).toBeVisible();
    // 勾一个技能：开关是本轮生效，不能因为换地方就失效
    const toggle = panel.getByRole('checkbox', { name: /启用技能/ }).first();
    await toggle.click();
    await toggle.click();
    // 导入走「引导弹窗」，不是直接弹系统文件框
    await panel.locator('button', { hasText: '导入技能' }).click();
    const guide = page.getByRole('dialog', { name: '做一个自己的技能' });
    await expect(guide).toBeVisible();
    await expect(guide.getByRole('button', { name: /下载便签/ })).toBeVisible();
    await expect(guide.getByRole('button', { name: /选文件导入/ })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(guide).toHaveCount(0);
    // 二级面板是「藏起来」而不是卸载（要留淡出过渡），再按一次 Esc 收加号菜单本身
    await page.keyboard.press('Escape');
    await expect(panel).toBeHidden();

    // 审批策略：始终询问 / 按需确认 / 全部允许
    await page.getByLabel('审批策略').click();
    const options = await page.getByRole('option').allTextContents();
    expect(options.join(' ')).toContain('始终询问');
    expect(options.join(' ')).toContain('按需确认');
    expect(options.join(' ')).toContain('全部允许');
    await page.getByRole('option', { name: /全部允许/ }).click();
  });

  test('输入框：模型与用量合成一个控件组', async ({ page }) => {
    await page.goto('/?mock=1');

    // 以前是「用量」「模型」两个图标按钮各开一层浮层；现在一个胶囊里看完这两件事
    await expect(page.getByRole('button', { name: '当前用量' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '模型选择' })).toHaveCount(0);

    await page.getByRole('button', { name: '模型与用量' }).click();
    const panel = page.getByRole('dialog', { name: '模型与用量' });
    await expect(panel).toBeVisible();
    // 上半是模型列表
    await expect(panel.getByText('本地 mock', { exact: true })).toBeVisible();
    await expect(panel.getByText(/个已配置/)).toBeVisible();
    // 下半是近 7 天用量：和模型在同一个面板里，不用再点第二个图标
    await expect(panel.getByText('近 7 天用量')).toBeVisible();
    await expect(panel.getByRole('link', { name: /明细/ })).toBeVisible();
    await expect(panel.getByRole('link', { name: /前往设置管理/ })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
  });

  test('跑完一轮：对话里直接给出产物卡，能预览能下载', async ({ page }) => {
    await page.goto('/?mock=1');
    await page.getByLabel('任务输入框').fill('把这份材料整理成 600 字周报');
    await page.getByRole('button', { name: '发送' }).click();

    const approve = page.getByRole('button', { name: /批准并继续/ });
    await expect(approve).toBeVisible({ timeout: 20_000 });
    await approve.click();
    await expect(page.getByText('运行完成')).toBeVisible({ timeout: 20_000 });

    // 交付物不再只写在回复里：回复下面直接摆一张能操作的卡
    const delivery = page.getByLabel('本次产物');
    await expect(delivery).toBeVisible();
    await expect(delivery.getByRole('button', { name: /下载/ })).toBeVisible();
    await expect(delivery.getByRole('button', { name: /预览/ })).toBeVisible();
  });

  test('会话条目 ⋮ 菜单：置顶 / 重命名 / 删除', async ({ page }) => {
    await page.goto('/?mock=1');

    // 跑一次 mock 运行，产生会话（mock 流末尾必经写盘审批）
    await page.getByLabel('任务输入框').fill('把这份材料整理成周报');
    await page.getByRole('button', { name: '发送' }).click();
    const approve = page.getByRole('button', { name: /批准并继续/ });
    await expect(approve).toBeVisible({ timeout: 20_000 });
    await approve.click();
    await expect(page.getByText('运行完成')).toBeVisible({ timeout: 20_000 });

    const row = page.locator('li', { hasText: '把这份材料整理成周报' }).first();
    await expect(row).toBeVisible();
    await row.hover();
    await row.getByRole('button', { name: '更多操作' }).click();
    const menu = page.getByRole('menu');
    await expect(menu).toBeVisible();
    await expect(menu.getByText('置顶')).toBeVisible();
    await expect(menu.getByText('重命名')).toBeVisible();
    await expect(menu.getByText('删除')).toBeVisible();

    await menu.getByText('置顶').click();
    await expect(menu).toBeHidden();
    // 置顶后行内出现置顶标记（标题含「取消置顶」入口）
    await row.hover();
    await row.getByRole('button', { name: '更多操作' }).click();
    await expect(page.getByRole('menu').getByText('取消置顶')).toBeVisible();
  });

  test('最近会话：批量清理进选择模式，点一次只进确认态（不误删）', async ({ page }) => {
    await page.goto('/?mock=1');

    // 先发一条任务把会话建出来（mock 模式下会话由首条消息创建），否则列表是空的、清理按钮禁用
    await page.getByLabel('任务输入框').fill('建一条会话用来试批量清理');
    await page.getByRole('button', { name: '发送' }).click();
    const bulkEntry = page.getByRole('button', { name: '批量清理会话' });
    await expect(bulkEntry).toBeEnabled({ timeout: 15_000 });

    await bulkEntry.click();
    const boxes = page.getByRole('checkbox');
    await expect(boxes.first()).toBeVisible();

    await boxes.first().click();
    await expect(page.getByText('已选')).toBeVisible();
    await page.getByRole('button', { name: /删除选中（1）/ }).click();
    // 第一次点击只把按钮换成确认文案，绝不真删
    await expect(page.getByRole('button', { name: /确认删除 1 个/ })).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: '批量清理会话' })).toBeVisible();
    await expect(page.getByRole('checkbox')).toHaveCount(0);
  });

  test('对话流：思考过程先于结果展示', async ({ page }) => {
    await page.goto('/?mock=1');

    await page.getByLabel('任务输入框').fill('把这份材料整理成周报');
    await page.getByRole('button', { name: '发送' }).click();

    // 思考区块（流式态）先于助手正文出现
    await expect(page.getByText('正在思考').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/我先理解任务目标与约束/).first()).toBeVisible();

    // 完成后折叠为「已思考」摘要
    await expect(page.getByText('已思考').first()).toBeVisible({ timeout: 20_000 });
  });

  test('输入框：运行中发的任务排进队列，跑完自动接着执行', async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto('/?mock=1');

    await page.getByLabel('任务输入框').fill('先把材料整理成周报');
    await page.getByRole('button', { name: '发送' }).click();

    // 运行中输入框不再被锁死：主按钮变「排队」，停止按钮同时在场
    await expect(page.getByRole('button', { name: '排队', exact: true })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole('button', { name: '停止' })).toBeVisible();

    await page.getByLabel('任务输入框').fill('再把这些汇总成台账');
    await page.getByRole('button', { name: '排队', exact: true }).click();

    const queue = page.getByLabel('排队中的任务');
    await expect(queue).toBeVisible();
    await expect(queue.getByText('再把这些汇总成台账')).toBeVisible();
    await expect(page.getByText('1 条排队中')).toBeVisible();

    // 第一条卡在审批：审批没过之前，队列那条不能抢跑
    const approve = page.getByRole('button', { name: /批准并继续/ });
    await expect(approve).toBeVisible({ timeout: 20_000 });
    await expect(queue).toBeVisible();
    await approve.click();

    // 前一条跑完：队列自己清空，第二条直接进入对话流（不用再点发送）
    await expect(queue).toBeHidden({ timeout: 60_000 });
    await expect(page.getByText('再把这些汇总成台账').first()).toBeVisible();
  });

  test('输入框：优先执行把那条排队任务提到队首', async ({ page }) => {
    await page.goto('/?mock=1');

    await page.getByLabel('任务输入框').fill('先把材料整理成周报');
    await page.getByRole('button', { name: '发送' }).click();
    await expect(page.getByRole('button', { name: '排队', exact: true })).toBeVisible({
      timeout: 15_000,
    });

    await page.getByLabel('任务输入框').fill('再把这些汇总成台账');
    await page.getByRole('button', { name: '排队', exact: true }).click();
    await page.getByLabel('任务输入框').fill('顺手再画个饼图');
    await page.getByRole('button', { name: '排队', exact: true }).click();

    const queue = page.getByLabel('排队中的任务');
    await expect(queue.getByText('2 条排队中')).toBeVisible();
    await expect(queue.getByTestId('queued-message').first()).toContainText('再把这些汇总成台账');

    // 点第二条的「优先执行」：它挪到队首，编号顺序跟着换
    await queue.getByRole('button', { name: '优先执行这条排队任务' }).nth(1).click();
    await expect(queue.getByTestId('queued-message').first()).toContainText('顺手再画个饼图');
    await expect(queue.getByTestId('queued-message').last()).toContainText('再把这些汇总成台账');
    await expect(queue.getByText('下一个')).toBeVisible();
  });

  test('审计用量页：dsh 风格总览与趋势图', async ({ page }) => {
    await page.goto('/audit');

    await expect(page.getByRole('heading', { name: '审计用量' })).toBeVisible();
    // 总览三卡（真实聚合）
    await expect(page.getByText('累计消费金额')).toBeVisible();
    await expect(page.getByText('近 30 天消耗')).toBeVisible();
    await expect(page.getByText('API 请求次数').first()).toBeVisible();
    // 趋势图 + 按模型分组 + 无导出按钮
    await expect(page.getByText(/消费金额（CNY）/)).toBeVisible();
    await expect(page.getByText('按模型')).toBeVisible();
    await expect(page.getByRole('button', { name: /导出 JSON/ })).toBeHidden();
    await expect(page.getByRole('button', { name: /导出 CSV/ })).toBeHidden();
    // 时间维度筛选：审计数据是异步装载的，页面可能重渲染一次把刚展开的弹层收起，
    // 所以用 toPass 重试「展开 → 看到选项」，再点具体项
    const rangeTrigger = page.getByLabel('时间维度');
    await expect(async () => {
      await rangeTrigger.click();
      await expect(page.getByRole('option', { name: '近 7 天' })).toBeVisible({ timeout: 1000 });
    }).toPass({ timeout: 10_000 });
    await page.getByRole('option', { name: '近 7 天' }).click();
    await expect(page.getByText('当前范围：近 7 天 · 全部会话')).toBeVisible();
    await page.getByRole('button', { name: '清除筛选条件' }).click();
    await expect(page.getByText('当前范围：近 30 天 · 全部会话')).toBeVisible();
  });

  test('设置页：添加 Key 可直接粘贴供应商 Key', async ({ page }) => {
    await page.goto('/settings');

    await expect(page.getByText('可用模型与 Key 状态')).toBeVisible();
    // 配置来源等冗余技术块已删除
    await expect(page.getByText('配置来源')).toBeHidden();
    await expect(page.getByText('环境变量提示')).toBeHidden();
    await expect(page.getByText('后端运行信息')).toBeHidden();

    // 添加 Key：必须有「可以直接粘贴 Key」的输入框（不能只登记 env 名）
    await page.getByRole('button', { name: '添加 Key' }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const keyInput = dialog.getByLabel('API Key');
    await expect(keyInput).toBeVisible();
    // 默认是 password 类型，可切换显示
    await expect(keyInput).toHaveAttribute('type', 'password');
    await dialog.getByRole('button', { name: '显示' }).click();
    await expect(keyInput).toHaveAttribute('type', 'text');

    // 空 Key 时保存按钮不可用
    await expect(dialog.getByRole('button', { name: '保存' })).toBeDisabled();
    await keyInput.fill('sk-e2e-placeholder-key');
    await expect(dialog.getByRole('button', { name: '保存' })).toBeEnabled();

    await dialog.getByRole('button', { name: '取消' }).click();
    await expect(dialog).toBeHidden();
  });

  test('设置页：审批工具说人话，外观能调字号 / 字重 / 字体样式', async ({ page }) => {
    await page.goto('/settings?mock=1');

    // 审批：不再让人在一排 code.run_python 里做选择
    await page.getByRole('button', { name: '审批与安全' }).click();
    await expect(page.getByRole('button', { name: '执行 Python' })).toBeVisible();
    await expect(page.getByText('code.run_python', { exact: true })).toHaveCount(0);

    await page.getByRole('button', { name: '外观', exact: true }).click();
    // 字号：滑杆右侧带「小 / 默认 / 大」三档说明（不是只有裸滑杆）
    await expect(page.getByText('界面缩放', { exact: true })).toBeVisible();
    await expect(page.getByText('字体大小', { exact: true })).toBeVisible();
    await expect(page.getByText('字体粗细', { exact: true })).toBeVisible();

    // 字号与页面缩放是两件事：调字号只写 --font-scale，不许带着整页排版一起变
    const size = page.getByLabel('字体大小');
    await size.fill('130');
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--font-scale')),
      )
      .toBe('1.3');
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--ui-scale')),
      )
      .toBe('90%');

    // 反过来：调「界面缩放」只动间距/控件，字号变量保持不动
    const pageScale = page.getByLabel('界面缩放');
    await pageScale.fill('100');
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--ui-scale')),
      )
      .toBe('100%');
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--font-scale')),
      )
      .toBe('1.3');

    const weight = page.getByLabel('字体粗细');
    await weight.fill('600');
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--ui-font-weight')),
      )
      .toBe('600');

    // 字体样式：自绘下拉，选项按各自字族渲染
    await page.getByRole('button', { name: '字体样式' }).click();
    await page.getByRole('option', { name: '楷体' }).click();
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--font-sans')),
      )
      .toContain('KaiTi');

    // 恢复默认：四项一起回初始值（内联变量要清掉，不然默认字体栈被顶掉）
    await page.getByRole('button', { name: '恢复默认' }).click();
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--ui-font-weight')),
      )
      .toBe('400');
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--font-sans')),
      )
      .toBe('');
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--font-scale')),
      )
      .toBe('1');
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.style.getPropertyValue('--ui-scale')),
      )
      .toBe('90%');
  });
});

test.describe('B3 页面与真实后端联调', () => {
  test('设置中心：保存即生效（并还原）', async ({ page, request }) => {
    test.skip(!(await backendReady(request)), '后端未启动');

    await page.goto('/settings');
    const uploadInput = page.getByLabel('上传上限');
    await expect(uploadInput).toBeVisible({ timeout: 15_000 });
    const original = await uploadInput.inputValue();

    await uploadInput.fill('25');
    await page.getByRole('button', { name: '保存设置' }).click();
    await expect(page.getByText('设置已保存并生效')).toBeVisible({ timeout: 15_000 });

    // 还原配置，避免污染演示环境
    await uploadInput.fill(original);
    await page.getByRole('button', { name: '保存设置' }).click();
    await expect(page.getByText('设置已保存并生效')).toBeVisible({ timeout: 15_000 });
  });

  test('扩展页：插件 / 技能两个 tab，技能就地标记已添加，规范包入口在工具条', async ({
    page,
    request,
  }) => {
    test.skip(!(await backendReady(request)), '后端未启动');

    await page.goto('/skills');
    await expect(page.getByRole('tab', { name: '技能' })).toHaveAttribute('aria-selected', 'true', {
      timeout: 15_000,
    });
    await expect(page.getByRole('tab', { name: '插件' })).toBeVisible();
    // 规范包入口在顶部工具条上，不再缩在列表末尾
    await expect(page.getByRole('button', { name: /内置规范包/ })).toBeVisible();
    // 已添加的技能不再单开一片区域，行内就能看到状态
    await expect(page.getByRole('heading', { name: '已添加' })).toHaveCount(0);

    // 搜索只影响展示，不改任何后端状态
    await page.getByLabel('搜索技能').fill('zzz-不存在的技能');
    await expect(page.getByText(/没有匹配的技能/)).toBeVisible();

    // 插件 tab 读的是 runtime 真实注册的工具
    await page.getByRole('tab', { name: '插件' }).click();
    await expect(page.getByRole('heading', { name: '内置插件' })).toBeVisible();
    await expect(page.getByTestId('skills-catalog').getByText('文档生成')).toBeVisible();
  });

  test('产物中心：列表、类型分类与分页可达', async ({ page, request }) => {
    test.skip(!(await backendReady(request)), '后端未启动');

    await page.goto('/artifacts');
    await expect(page.getByText('产物中心').first()).toBeVisible({ timeout: 15_000 });

    // 等列表加载完再点筛选：加载中页面还在长高，抢在加载完之前点会点空
    await expect(page.getByText(/共 \d+ 个/).first()).toBeVisible();

    // 类型/会话都收在胶囊里：点开才浮出选项（平铺成两行会把筛选区顶成半屏）
    const typePill = page.getByRole('button', { name: /^类型/ });
    await expect(typePill).toHaveAttribute('aria-expanded', 'false');
    await typePill.click();
    await expect(page.getByRole('group', { name: '类型筛选' })).toBeVisible();
    for (const label of ['全部类型', 'Word 文档', 'Excel 表格', 'PDF', '文本']) {
      await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
    }
    // Esc 收起，胶囊上仍写着当前选的值
    await page.keyboard.press('Escape');
    await expect(page.getByRole('group', { name: '类型筛选' })).toHaveCount(0);
    await expect(typePill).toHaveTextContent('全部类型');

    // 主视图切换仍独占整宽，排在两个维度下面
    await expect(page.getByRole('button', { name: /全部产物/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /回收站/ })).toBeVisible();

    // 有产物时卡片带类型徽标；分页控件在多页时出现
    const cards = page.locator('.grid > div', { hasText: '下载' });
    if ((await cards.count()) > 0) {
      await expect(cards.first()).toBeVisible();
    }
    // 计数文案跟视图走（全部产物 / 回收站），这里只校验有总数
    const total = await page
      .getByText(/共 \d+ 个/)
      .first()
      .textContent();
    expect(total).toMatch(/共 \d+ 个/);
  });
});

test.describe('新增交互：回收站与充值供应商', () => {
  test('产物中心：可以切到回收站视图（提示误删可恢复）', async ({ page }) => {
    await page.goto('/artifacts');
    await expect(page.getByText('产物中心').first()).toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: /回收站/ }).click();
    await expect(page.getByText('删除的产物会在这里保留，随时可以恢复')).toBeVisible();

    // 回收站里的条目带「恢复 / 彻底删除」，或者显示空态
    const restore = page.getByRole('button', { name: '恢复' });
    const empty = page.getByText('回收站是空的');
    await expect(restore.first().or(empty)).toBeVisible();
  });

  test('审计用量：去充值先让用户选供应商（圆角面板，不是固定 DeepSeek）', async ({ page }) => {
    await page.goto('/audit');
    await page.getByRole('button', { name: /去充值/ }).hover();

    const menu = page.getByRole('menu', { name: '选择要充值的模型供应商' });
    await expect(menu).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: /deepseek harness/i })).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: /通义千问/ })).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: /智谱 GLM/ })).toBeVisible();
  });

  test('本机服务断开时说人话：去双击启动器，而不是只弹「无法连接后端」', async ({ page }) => {
    // 模拟「黑窗口被关掉 / 电脑重启后服务没了」：接口全掐掉，页面还能显示旧内容
    await page.route('**/api/v1/**', (route) => route.abort());
    await page.goto('/settings');

    const banner = page.getByTestId('service-down-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('本机服务已断开');
    // 用户得知道具体去双击哪个文件，抽象成「启动器」等于没说
    await expect(banner).toContainText('启动 Office Agent.cmd');

    // 服务恢复后点「重试」提示自己消失，不用刷新页面
    await page.unroute('**/api/v1/**');
    await banner.getByRole('button', { name: '重试' }).click();
    await expect(page.getByTestId('service-down-banner')).toHaveCount(0, { timeout: 10_000 });
  });

  test('独立窗口：面板贴到窗口顶沿，但可点元素都让开窗口按钮', async ({ page }) => {
    await page.goto('/?mock=1');
    await expect(page.getByRole('heading', { name: /把一份材料/ })).toBeVisible();

    // 模拟装到本机后的 window-controls-overlay：浏览器给出 32px 标题栏
    await page.evaluate(() => {
      document.documentElement.style.setProperty('--titlebar-h', '32px');
      document.documentElement.dataset.titlebar = 'overlay';
    });

    const shell = page.getByTestId('workbench-shell');
    const pad = await shell.evaluate((node) => {
      const style = getComputedStyle(node);
      return {
        top: Number.parseFloat(style.paddingTop),
        left: Number.parseFloat(style.paddingLeft),
      };
    });
    // 四边同一档：不再「顶部多让一条」——那正是左栏顶部悬空的那块空隙
    expect(pad.top).toBe(pad.left);

    // 面板上沿贴着窗口顶（10px 边框留白），不是被推到标题栏下面
    const sidebarTop = await page
      .locator('aside')
      .first()
      .evaluate((node) => node.getBoundingClientRect().top);
    expect(sidebarTop).toBeLessThan(16);

    // 窗口按钮画在右上角 32px 内：这块区域里不能有任何可点元素，
    // 否则点保存/刷新会变成点 ✕（上一版桌面端踩过的坑）
    const blocked = await page.evaluate(() => {
      const zone = { left: window.innerWidth - 150, bottom: 32 };
      const hits: string[] = [];
      for (const element of document.querySelectorAll('button,a,input,textarea,[role="button"]')) {
        const rect = element.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        if (rect.left < window.innerWidth && rect.right > zone.left && rect.top < zone.bottom) {
          hits.push((element.getAttribute('aria-label') || element.textContent || '').trim());
        }
      }
      return hits;
    });
    expect(blocked).toEqual([]);
  });
});
