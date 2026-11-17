/**
 * 扩展页（/skills）：上面是「插件 / 技能」两个 tab，下面是同一套商店式列表。
 *
 * 两类东西的关系（页面上也要说清）：
 * - 插件 = 随应用发布的工具能力（文档生成、脚本加工、素材读取…），常驻，不能卸；
 *   卡片上把风险写出来，高风险工具动手前会过门控（会动已有文件才要明确授权）；
 * - 技能 = 可复用的做法包：技能库里的技能点「添加」才进 app/skills、才写进系统提示词，
 *   **添加前不占提示词**，所以技能变多也不会把上下文撑爆；
 * - 内置规范包 = 按本轮需求自动挑 1–2 段的专业规范，不常驻；入口放在顶部工具条上，
 *   点开在弹窗里读原文（目录 + 正文）。
 *
 * 布局取舍（用户反馈）：
 * - 两个 tab 一套排版：一行「分区标题 + 数量 + 右侧统计」，下面一片网格；
 * - 不再单开「已添加」一片区域：已添加的就地变成「已添加 ✓」，省下一整块高度；
 * - 不做精选大卡：它比列表高出两倍，还只能截两行说明，跟插件页放在一起像两种风格；
 *   技能和插件都是「图标 + 标题 + 两行说明 + 右侧按钮」的条目，一排到底；
 * - 添加按钮自己说状态：点完直接变「已添加」，不再靠顶部横幅确认；
 * - 启用/停用、移除收成行内小图标（移除是软删，技能库里还能再加回来）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  IconBook,
  IconCheck,
  IconClock,
  IconFile,
  IconFolder,
  IconList,
  IconPlus,
  IconPower,
  IconPuzzle,
  IconRefresh,
  IconSearch,
  IconShield,
  IconSparkle,
  IconSpinner,
  IconTerminal,
  IconTrash,
  IconX,
} from '../../shared/ui/Icons';
import { Markdown } from '../../shared/ui/Markdown';
import { PageShell } from '../../shared/ui/PageShell';
import { Button, CardError, CardLoading, IconButton, Modal } from '../../shared/ui/primitives';
import { promptPacksApi } from './api';
import { SkillImportGuide } from './components/SkillImportGuide';
import { usePlugins } from './usePlugins';
import { useSkills } from './useSkills';
import type { CatalogSkill, PromptPack, SkillItem } from './api';
import type { PluginInfo } from './usePlugins';
import type { ReactNode } from 'react';

// 340px 起：1280 宽下排三列（和参考的商店列表一致），再窄自动降到两列/一列
const GRID_CLASS = 'grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-2.5';

/** 图标键 → 图标组件（SKILL.md 里写 `icon: doc` 这种）。 */
const GLYPHS: Record<string, typeof IconFile> = {
  doc: IconFile,
  sheet: IconList,
  minutes: IconClock,
  retro: IconRefresh,
  shield: IconShield,
  book: IconBook,
  terminal: IconTerminal,
  folder: IconFolder,
  trash: IconTrash,
  list: IconList,
  puzzle: IconPuzzle,
};

/** 分类配色：同一类技能在整页里颜色一致，扫一眼就知道是哪一类。 */
const CATEGORY_TONES: Record<string, { tile: string; badge: 'brand' | 'ok' | 'accent' | 'warn' }> =
  {
    办公文档: { tile: 'bg-brand-soft text-brand', badge: 'brand' },
    表格数据: { tile: 'bg-ok-soft text-ok', badge: 'ok' },
    会议协作: { tile: 'bg-accent-soft text-accent', badge: 'accent' },
    内容写作: { tile: 'bg-warn-soft text-warn', badge: 'warn' },
    文件处理: { tile: 'bg-surface-sunken text-ink-soft', badge: 'brand' },
  };

/** 兜底配色：分类没写或者写了新分类时用它，避免整页出现无色图标。 */
const DEFAULT_TONE = { tile: 'bg-brand-soft text-brand', badge: 'brand' as const };

function toneOf(category: string): { tile: string; badge: 'brand' | 'ok' | 'accent' | 'warn' } {
  return CATEGORY_TONES[category] ?? DEFAULT_TONE;
}

const ALL = '全部';
/** 分类的展示顺序：从「最常用」到「专项」，只看名字就能排 */
const CATEGORY_ORDER = ['办公文档', '表格数据', '会议协作', '内容写作', '文件处理'];

type StoreTab = 'plugins' | 'skills';

function Glyph({ icon, tone, size = 'md' }: { icon: string; tone: string; size?: 'md' | 'lg' }) {
  const GlyphIcon = GLYPHS[icon] ?? IconSparkle;
  // 圆形色块：和参考里的应用图标一个观感，比圆角方块更像「插件」
  const box = size === 'lg' ? 'h-12 w-12' : 'h-10 w-10';
  const glyphSize = size === 'lg' ? 22 : 18;
  return (
    <span className={`grid shrink-0 place-items-center rounded-full ${box} ${toneOf(tone).tile}`}>
      <GlyphIcon size={glyphSize} />
    </span>
  );
}

/**
 * 商店条目：图标 / 标题 + 右侧动作 / 两行说明 / 一行元信息。
 * 不带边框、不带卡片底色——一列一列排下来更像商店列表，也比卡片省一半高度。
 */
function StoreRow({
  icon,
  tone,
  title,
  description,
  meta,
  action,
  hint,
}: {
  icon: string;
  tone: string;
  title: string;
  description: string;
  meta: ReactNode;
  action: ReactNode;
  hint?: string;
}) {
  return (
    <article
      className="group flex h-full items-start gap-2.5 rounded-card border border-line bg-surface px-3 py-3 transition-colors hover:border-line-strong hover:shadow-card"
      title={hint}
    >
      <Glyph icon={icon} tone={tone} />
      <div className="flex min-w-0 flex-1 flex-col">
        {/*
          动作槽固定 28px 高（h-7）：技能行里「添加」是 28px 的按钮、「已添加」只是一行字，
          两种状态高度不一样，同一行的标题就会被顶得高低不齐——之前看着像栅格错位。
        */}
        <div className="flex h-7 items-center gap-2">
          <h3 className="min-w-0 flex-1 truncate text-mini font-semibold text-ink" title={title}>
            {title}
          </h3>
          {action}
        </div>
        {/* 固定两行高度：同一行里有人一行说明、有人两行，对齐后栅格才不犬牙交错 */}
        <p className="mt-0.5 line-clamp-2 min-h-[2.6em] text-caption leading-snug text-muted">
          {description}
        </p>
        <div className="mt-auto flex flex-wrap items-center gap-x-1.5 gap-y-0.5 pt-1 text-[calc(11px*var(--font-scale))] text-faint">
          {meta}
        </div>
      </div>
    </article>
  );
}

/** 技能行：没添加的给「添加」，添加过的就地变成「已添加 ✓」+ 启停 / 移除。 */
function SkillRow({
  skill,
  busy,
  onInstall,
  onToggle,
  onRemove,
}: {
  skill: CatalogSkill;
  busy: boolean;
  onInstall: () => void;
  onToggle: (enabled: boolean) => void;
  onRemove: () => void;
}) {
  const enabled = skill.enabled;
  return (
    <StoreRow
      icon={skill.icon}
      tone={skill.category}
      title={skill.title}
      description={skill.description}
      hint={skill.triggers.join('、')}
      meta={
        <>
          <span className="truncate">
            {skill.triggers.length > 0
              ? `触发 ${skill.triggers.slice(0, 2).join(' / ')}`
              : '没写触发词'}
          </span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">{skill.content_chars} 字</span>
          {skill.installed ? (
            <>
              <span aria-hidden>·</span>
              <span className={enabled ? 'text-ok' : 'text-warn'}>
                {enabled ? '已进提示词' : '已停用'}
              </span>
            </>
          ) : null}
        </>
      }
      action={
        busy ? (
          <IconSpinner size={14} className="shrink-0 text-muted" />
        ) : skill.installed ? (
          <span className="flex shrink-0 items-center gap-0.5">
            <span className="inline-flex items-center gap-0.5 text-[calc(11px*var(--font-scale))] font-medium text-ok">
              <IconCheck size={11} />
              已添加
            </span>
            <IconButton
              label={enabled ? `停用技能 ${skill.title}` : `启用技能 ${skill.title}`}
              className="h-6 w-6"
              onClick={() => onToggle(!enabled)}
            >
              <IconPower size={12} />
            </IconButton>
            <span className="flex opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
              <IconButton label={`移除技能 ${skill.title}`} className="h-6 w-6" onClick={onRemove}>
                <IconTrash size={12} />
              </IconButton>
            </span>
          </span>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            className="h-7 shrink-0 px-2.5 text-caption"
            onClick={onInstall}
          >
            添加
          </Button>
        )
      }
    />
  );
}

/** 插件行：随应用发布、常驻启用，所以按钮位只放一个「已启用」状态。 */
function PluginRow({ plugin }: { plugin: PluginInfo }) {
  return (
    <StoreRow
      icon={plugin.icon}
      tone={plugin.tone}
      title={plugin.title}
      description={plugin.summary}
      hint={plugin.tools.join('、')}
      meta={
        <>
          <span className="tabular-nums">{plugin.tools.length} 个工具</span>
          <span aria-hidden>·</span>
          <span className={plugin.highRisk ? 'text-warn' : ''}>
            {plugin.highRisk ? '含高风险工具，执行前需确认' : '低风险，直接执行'}
          </span>
        </>
      }
      action={
        <span className="inline-flex shrink-0 items-center gap-0.5 text-[calc(11px*var(--font-scale))] font-medium text-ok">
          <IconCheck size={11} />
          已启用
        </span>
      }
    />
  );
}

/**
 * 规范包正文去重：文件开头一般就是 `## 同名标题`，弹窗里已经有标题了，
 * 直接渲染会连着出现两行一样的大标题。
 */
function packBody(pack: PromptPack): string {
  const text = pack.body.trim();
  const firstLine = text.split('\n')[0] ?? '';
  const heading = /^#{1,3}\s+(.*)$/.exec(firstLine);
  if (heading && (heading[1] ?? '').trim() === pack.title.trim()) {
    return text.slice(firstLine.length).trim();
  }
  return text;
}

/** 规范包阅读器：左边目录、右边原文。 */
function PacksModal({ packs, onClose }: { packs: PromptPack[]; onClose: () => void }) {
  const [activeId, setActiveId] = useState(packs[0]?.id ?? '');
  const active = packs.find((pack) => pack.id === activeId) ?? packs[0];

  return (
    <Modal
      title="内置规范包"
      size="lg"
      onClose={onClose}
      footer={
        <>
          <span className="mr-auto min-w-0 truncate text-caption text-faint">
            只读 · 由 prompts/packs 目录维护
          </span>
          <Button variant="secondary" size="sm" onClick={onClose}>
            关闭
          </Button>
        </>
      }
    >
      <p className="text-caption leading-snug text-muted">
        共 {packs.length} 段，每轮按需求自动匹配 1–2 段注入，不常驻上下文。
      </p>

      {packs.length === 0 ? (
        <p className="mt-3 rounded-control border border-dashed border-line px-3 py-6 text-center text-caption text-faint">
          没有读到规范包（检查后端 prompts/packs 目录）。
        </p>
      ) : (
        <div className="mt-2.5 grid gap-2.5 sm:grid-cols-[12.5rem_1fr]">
          <ul
            className="max-h-[10rem] space-y-0.5 overflow-y-auto rounded-control border border-line p-1 sm:max-h-[54vh]"
            aria-label="规范包目录"
          >
            {packs.map((pack) => {
              const on = pack.id === active?.id;
              return (
                <li key={pack.id}>
                  <button
                    type="button"
                    onClick={() => setActiveId(pack.id)}
                    aria-current={on ? 'true' : undefined}
                    className={`flex w-full items-baseline gap-2 rounded-control px-2 py-1.5 text-left transition-colors ${
                      on
                        ? 'bg-brand-soft text-brand-strong'
                        : 'text-ink-soft hover:bg-surface-hover'
                    }`}
                  >
                    <span
                      className={`min-w-0 flex-1 truncate text-caption ${on ? 'font-semibold' : ''}`}
                      title={pack.title}
                    >
                      {pack.title}
                    </span>
                    <span className="shrink-0 text-[calc(10px*var(--font-scale))] tabular-nums text-faint">
                      {pack.chars} 字
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          {active ? (
            <div className="min-h-0 max-h-[54vh] overflow-y-auto rounded-control border border-line bg-surface-sunken/30 px-4 py-3">
              <div className="flex items-baseline gap-2">
                <h3 className="min-w-0 flex-1 text-mini font-semibold text-ink">{active.title}</h3>
                <span className="shrink-0 text-[calc(10px*var(--font-scale))] tabular-nums text-faint">
                  {active.chars} 字
                </span>
              </div>
              {active.keywords.length > 0 ? (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {active.keywords.slice(0, 10).map((keyword) => (
                    <span
                      key={keyword}
                      className="rounded-full bg-surface px-1.5 py-px text-[calc(10px*var(--font-scale))] text-muted"
                    >
                      {keyword}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="mt-2.5 text-body text-ink-soft">
                {active.body ? (
                  <Markdown text={packBody(active)} />
                ) : (
                  <p className="text-faint">
                    这段规范没有正文（检查 prompts/packs 里的 md 文件）。
                  </p>
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

/**
 * 技能行数据：技能库（catalog）里的全部技能 + 本地导入的技能。
 * catalog 的 installed 标记只作参考——以「已安装列表里有没有这个名字」为准，
 * 这样添加/移除之后不用等接口刷新也不会出现两边状态打架。
 */
interface StoreSkill extends CatalogSkill {
  enabled: boolean;
}

function buildSkillRows(items: SkillItem[], catalog: CatalogSkill[]): StoreSkill[] {
  const installedByName = new Map(items.map((item) => [item.name, item]));
  const rows: StoreSkill[] = catalog.map((entry) => ({
    ...entry,
    installed: installedByName.has(entry.name),
    enabled: installedByName.get(entry.name)?.enabled ?? false,
  }));
  const known = new Set(rows.map((row) => row.name));
  for (const item of items) {
    if (known.has(item.name)) continue;
    // 用户自己导入的技能：技能库里没有它，但已经装好、可以启停/移除
    rows.push({ ...item, slug: item.name, installed: true });
  }
  return rows;
}

export function SkillsPage() {
  const skills = useSkills();
  const plugins = usePlugins();
  const [packs, setPacks] = useState<PromptPack[]>([]);
  const [packsOpen, setPacksOpen] = useState(false);
  const [tab, setTab] = useState<StoreTab>('skills');
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState(ALL);
  const [importOpen, setImportOpen] = useState(false);

  const loadPacks = useCallback(async () => {
    try {
      const response = await promptPacksApi.list();
      setPacks(response.data);
    } catch {
      // 规范包只是展示用，读失败不影响技能管理
      setPacks([]);
    }
  }, []);

  useEffect(() => {
    void loadPacks();
  }, [loadPacks]);

  const rows = useMemo(
    () => buildSkillRows(skills.items, skills.catalog),
    [skills.items, skills.catalog],
  );

  /**
   * 分类筛选项：按固定的办公场景顺序排（后端给的是目录名字母序，读起来跳），
   * 没列进顺序表的新分类排在后面，避免以后加技能时被吞掉。
   */
  const categories = useMemo(() => {
    const merged: string[] = [];
    for (const row of rows) {
      if (row.category && !merged.includes(row.category)) merged.push(row.category);
    }
    const ordered = merged.sort((a, b) => {
      const left = CATEGORY_ORDER.indexOf(a);
      const right = CATEGORY_ORDER.indexOf(b);
      return (left < 0 ? 99 : left) - (right < 0 ? 99 : right);
    });
    return [ALL, ...ordered];
  }, [rows]);

  const query = keyword.trim().toLowerCase();

  const visibleSkills = rows.filter((row) => {
    if (category !== ALL && row.category !== category) return false;
    if (!query) return true;
    return [row.title, row.name, row.description, ...row.triggers].some((text) =>
      text.toLowerCase().includes(query),
    );
  });

  const visiblePlugins = plugins.plugins.filter((plugin) => {
    if (category !== ALL && plugin.title !== category) return false;
    if (!query) return true;
    return [plugin.title, plugin.summary, ...plugin.tools].some((text) =>
      text.toLowerCase().includes(query),
    );
  });

  const installedCount = rows.filter((row) => row.installed).length;
  const availableCount = rows.length - installedCount;
  const allCategories = categories;

  const loading =
    tab === 'skills'
      ? skills.status === 'loading' && skills.catalogStatus === 'loading'
      : plugins.status === 'loading';
  const failed =
    tab === 'skills'
      ? skills.status === 'error' && skills.catalogStatus === 'error'
      : plugins.status === 'error';

  const switchTab = (next: StoreTab) => {
    setTab(next);
    // 两个 tab 的筛选不是一套（分类不同、搜索对象也不同），切过去就回到干净状态，
    // 免得带着上一个 tab 的关键词进来看到一片空
    setCategory(ALL);
    setKeyword('');
  };

  /**
   * 技能按分类顺序排（办公文档 → 表格数据 → …），同类里按名字；
   * 一排到底、不插分类小标题、不留精选位——跟插件 tab 一样的一片网格，
   * 分类靠上面的 chip 筛，页面上只有一种排版节奏。
   */
  const sortedSkills = [...visibleSkills].sort((a, b) => {
    const left = CATEGORY_ORDER.indexOf(a.category);
    const right = CATEGORY_ORDER.indexOf(b.category);
    const diff = (left < 0 ? 99 : left) - (right < 0 ? 99 : right);
    return diff !== 0 ? diff : a.title.localeCompare(b.title, 'zh-Hans-CN');
  });

  return (
    <PageShell
      title="插件与技能"
      description="插件是 Agent 的工具能力，随应用发布、常驻启用；技能是可复用的做法包，添加后才写进系统提示词——不添加就不占上下文。"
      actions={
        <span className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setImportOpen(true)}
            leading={<IconPlus size={13} />}
          >
            导入技能
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              skills.reload();
              plugins.reload();
              void loadPacks();
            }}
            leading={<IconRefresh size={13} />}
          >
            刷新
          </Button>
        </span>
      }
    >
      {skills.notice ? (
        <p className="mb-3 rounded-control border border-brand-line bg-brand-soft px-3 py-1.5 text-caption text-brand-strong">
          {skills.notice}
        </p>
      ) : null}

      {/* 一级切换：插件 / 技能（下划线 tab，右边放搜索与规范包入口） */}
      <div className="mb-3 flex flex-wrap items-end gap-x-4 gap-y-2 border-b border-line">
        <div role="tablist" aria-label="扩展分类" className="-mb-px flex items-center gap-4">
          {(
            [
              { key: 'plugins', label: '插件' },
              { key: 'skills', label: '技能' },
            ] as { key: StoreTab; label: string }[]
          ).map((entry) => {
            const on = tab === entry.key;
            return (
              <button
                key={entry.key}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => switchTab(entry.key)}
                className={`border-b-2 px-0.5 pb-2 text-regular font-semibold transition-colors ${
                  on ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink'
                }`}
              >
                {entry.label}
              </button>
            );
          })}
        </div>

        <div className="mb-1.5 ml-auto flex items-center gap-2">
          <label className="flex h-8 w-full items-center gap-1.5 rounded-control border border-line bg-surface px-2 sm:w-52">
            <IconSearch size={13} className="shrink-0 text-faint" />
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder={tab === 'skills' ? '搜索技能、触发词' : '搜索插件、工具'}
              aria-label={tab === 'skills' ? '搜索技能' : '搜索插件'}
              className="min-w-0 flex-1 bg-transparent text-caption text-ink placeholder:text-faint focus:outline-none"
            />
            {keyword ? (
              <IconButton
                label="清空搜索"
                className="h-5 w-5"
                tip={false}
                onClick={() => setKeyword('')}
              >
                <IconX size={11} />
              </IconButton>
            ) : null}
          </label>

          {/* 规范包入口放在工具条上：之前缩在列表最末尾，用户根本注意不到 */}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setPacksOpen(true)}
            leading={<IconBook size={13} />}
            className="shrink-0"
          >
            内置规范包
            <span className="ml-1 tabular-nums text-faint">{packs.length}</span>
          </Button>
        </div>
      </div>

      {/*
        两个 tab 用同一套排版：上面一行「分区标题 + 数量 + 右侧统计」，下面一片网格。
        技能多一排分类 chip（插件只有 5 个，筛起来反而碍事），除此之外不另起结构。
      */}
      {tab === 'skills' ? (
        <div className="mb-1.5 flex flex-wrap items-center gap-1">
          {allCategories.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setCategory(name)}
              aria-pressed={category === name}
              className={`rounded-full px-2.5 py-1 text-caption font-medium transition-colors ${
                category === name
                  ? 'bg-ink text-surface'
                  : 'text-muted hover:bg-surface-hover hover:text-ink'
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      ) : null}

      <div className="mb-1 flex items-baseline gap-2">
        <h2 className="text-mini font-semibold text-ink">
          {tab === 'skills' ? '技能库' : '内置插件'}
        </h2>
        <span className="text-[calc(11px*var(--font-scale))] tabular-nums text-faint">
          {tab === 'skills' ? sortedSkills.length : visiblePlugins.length}
        </span>
        <span className="ml-auto text-caption text-faint">
          {tab === 'skills'
            ? `已添加 ${installedCount} · 可添加 ${availableCount} · 提示词共 ${skills.promptChars} 字`
            : `内置 ${plugins.plugins.length} 个插件 · ${plugins.toolCount} 个工具全部启用`}
        </span>
      </div>

      {loading ? (
        <CardLoading label={tab === 'skills' ? '正在读取技能…' : '正在读取插件…'} />
      ) : failed ? (
        <CardError
          message={
            (tab === 'skills' ? skills.error : plugins.error) ??
            (tab === 'skills' ? '技能读取失败' : '插件读取失败')
          }
          onRetry={tab === 'skills' ? skills.reload : plugins.reload}
        />
      ) : tab === 'plugins' ? (
        plugins.plugins.length === 0 ? (
          <p className="px-1 py-6 text-center text-caption text-faint">
            后端没有注册工具（检查 app/tools/builtin）。
          </p>
        ) : visiblePlugins.length === 0 ? (
          <p className="px-2 py-4 text-center text-caption text-faint">
            没有匹配的插件，换个关键词试试。
          </p>
        ) : (
          <div className={GRID_CLASS} data-testid="skills-catalog">
            {visiblePlugins.map((plugin) => (
              <PluginRow key={plugin.id} plugin={plugin} />
            ))}
          </div>
        )
      ) : (
        <>
          {visibleSkills.length === 0 ? (
            <p className="px-2 py-6 text-center text-caption text-faint">
              没有匹配的技能，换个关键词或切回「全部」。
            </p>
          ) : (
            <div className={GRID_CLASS} data-testid="skills-grid">
              {sortedSkills.map((skill) => (
                <SkillRow
                  key={skill.name}
                  skill={skill}
                  busy={skills.busyName === skill.name}
                  onInstall={() => void skills.install(skill.slug || skill.name)}
                  onToggle={(enabled) => void skills.toggle(skill.name, enabled)}
                  onRemove={() => void skills.remove(skill.name)}
                />
              ))}
            </div>
          )}
        </>
      )}

      {packsOpen ? <PacksModal packs={packs} onClose={() => setPacksOpen(false)} /> : null}

      {/* 导入技能：不再是「直接弹系统文件框」，先给三步引导 + 可下载的模板 */}
      {importOpen ? (
        <SkillImportGuide
          importing={skills.busyName === '__import__'}
          notice={skills.notice}
          onImport={(file) => void skills.importFile(file)}
          onDraft={skills.draft}
          onUseDraft={(draft) => void skills.importDraft(draft)}
          drafting={skills.drafting}
          draftError={skills.draftError}
          onClose={() => {
            setImportOpen(false);
            skills.dismissNotice();
          }}
        />
      ) : null}
    </PageShell>
  );
}
