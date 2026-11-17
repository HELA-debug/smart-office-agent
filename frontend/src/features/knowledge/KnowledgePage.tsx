import { useMemo, useState } from 'react';
import { IconSearch, IconX } from '../../shared/ui/Icons';
import { PageShell } from '../../shared/ui/PageShell';
import { Badge, Card, CardEmpty, IconButton, SectionLabel } from '../../shared/ui/primitives';
import {
  BROWSE_PAGE_SIZE,
  CATEGORY_STATS,
  SUGGESTED_QUERIES,
  TOTAL_PASSAGES,
  searchStatic,
  type StaticHit,
} from './staticCorpus';

/**
 * 知识库 = 给**用户**查知识的图书馆，Agent 也从这里取，但页面第一读者是人。
 *
 * 因此这里写死的是普通人读得懂的常识，不是项目内部文档、接口名或技术术语；
 * 范围暂时只收文档办公（Word / Excel / PPT / PDF、公文与汇报、校对）和写论文
 * （论文格式、模板、参考文献、查重）。
 *
 * 「随便翻翻」有硬上限：一批固定几条、一屏放得下，翻批控件放在结果标题行
 * （不用滚到底才点得到），不让它无限往下铺，也不套一层框内滚动。
 * 检索只给前几条，命中总数单独报出来。
 *
 * 当前纯静态：语料、检索、统计全在前端本地完成，不联网、不读后端、不会自动更新。
 * 后期要接真实语料，把 searchStatic 换成 features/knowledge/api.ts 的 searchKnowledge，
 * 按 contracts.ts 的形状映射一次字段即可；页面骨架不用动。
 */

/** 命中处标一下检索词，多个词时标最靠前的那一处。 */
function Highlight({ text, query }: { text: string; query: string }) {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return <>{text}</>;
  const lower = text.toLowerCase();
  let at = -1;
  let length = 0;
  for (const term of terms) {
    const found = lower.indexOf(term);
    if (found >= 0 && (at < 0 || found < at)) {
      at = found;
      length = term.length;
    }
  }
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded-chip bg-warn-soft px-0.5 text-warn">
        {text.slice(at, at + length)}
      </mark>
      {text.slice(at + length)}
    </>
  );
}

function PassageHit({ item, query }: { item: StaticHit; query: string }) {
  return (
    <article className="rounded-card border border-line bg-surface px-4 py-3 transition-colors hover:border-line-strong hover:shadow-card">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="min-w-0 text-mini font-semibold text-ink">
              <Highlight text={item.title} query={query} />
            </h3>
            <Badge>{item.category}</Badge>
          </div>
          <p className="mt-0.5 text-caption text-faint">
            {item.source} · {item.section}
          </p>
          <p className="mt-1.5 line-clamp-3 text-caption leading-relaxed text-muted">
            <Highlight text={item.snippet} query={query} />
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-x-1.5 text-[calc(11px*var(--font-scale))] text-faint">
            <span className="font-mono">{item.id}</span>
            {item.tags.map((tag) => (
              <span key={tag} className="rounded-chip border border-line px-1.5 py-[1px]">
                {tag}
              </span>
            ))}
          </div>
        </div>
        {item.score !== null ? (
          <div className="shrink-0 text-right">
            <div className="text-caption font-medium tabular-nums text-brand">
              {item.score.toFixed(2)}
            </div>
            <div className="mt-0.5 text-[calc(11px*var(--font-scale))] text-faint">相关度</div>
          </div>
        ) : null}
      </div>
    </article>
  );
}

export function KnowledgePage() {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const result = useMemo(() => searchStatic(query, category, page), [query, category, page]);
  const browsing = result.level === 'browsing';

  return (
    <PageShell
      title="知识库"
      description="像在图书馆找书一样：输入想问的事，看看有哪些能用到的知识，以及它们出自哪本书。暂时只收文档办公和写论文这两类内容，随时可查，不用先添加，也不用先启用。"
      actions={<Badge tone="brand">示例内容</Badge>}
    >
      <Card className="mb-4 px-4 py-3">
        <label className="flex h-10 items-center gap-2 rounded-control border border-line bg-surface-sunken px-3">
          <IconSearch size={16} className="shrink-0 text-faint" />
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCategory(null);
              setPage(0);
            }}
            placeholder="想查点什么？比如：论文格式、模板、参考文献、Excel…"
            aria-label="检索知识库"
            className="min-w-0 flex-1 bg-transparent text-regular text-ink placeholder:text-faint focus:outline-none"
          />
          {query ? (
            <IconButton
              label="清空检索"
              tip={false}
              className="h-6 w-6"
              onClick={() => {
                setQuery('');
                setCategory(null);
                setPage(0);
              }}
            >
              <IconX size={12} />
            </IconButton>
          ) : null}
        </label>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-caption text-faint">大家常搜</span>
          {SUGGESTED_QUERIES.map((word) => (
            <button
              key={word}
              type="button"
              onClick={() => {
                setQuery(word);
                setCategory(null);
                setPage(0);
              }}
              className="rounded-full border border-line bg-surface px-2.5 py-1 text-caption text-muted transition-colors hover:border-line-strong hover:text-ink"
            >
              {word}
            </button>
          ))}
          <span className="ml-auto text-caption tabular-nums text-faint">
            收录 {TOTAL_PASSAGES} 条 · {CATEGORY_STATS.length} 个领域 ·{' '}
            {browsing ? `本批 ${result.hits.length} 条` : `命中 ${result.matched} 条`}
          </span>
        </div>
      </Card>

      <p className="mb-5 rounded-control border border-brand-line bg-brand-soft px-3 py-2 text-caption text-brand-strong">
        现在只收文档办公和写论文这两类：Word、Excel、PPT、PDF、公文与汇报、校对规范，以及论文格式、模板、参考文献与查重。内容是写死的示例，不会自动更新；「随便翻翻」一次只铺{' '}
        {BROWSE_PAGE_SIZE} 条，翻完点「换一批」。
      </p>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <SectionLabel>
              {category ? `领域 · ${category}` : browsing ? '随便翻翻' : '检索结果'}
            </SectionLabel>
            <span className="text-caption tabular-nums text-faint">{result.hits.length} 条</span>
            <div className="ml-auto flex items-center gap-2 text-caption text-faint">
              {browsing ? (
                <>
                  <span className="tabular-nums">
                    第 {result.page + 1} / {result.pageCount} 批 · 共 {result.matched} 条
                  </span>
                  {result.pageCount > 1 ? (
                    <button
                      type="button"
                      onClick={() => setPage((current) => current + 1)}
                      className="rounded-full border border-line bg-surface px-2.5 py-1 text-caption text-muted transition-colors hover:border-line-strong hover:text-ink"
                    >
                      换一批
                    </button>
                  ) : null}
                </>
              ) : (
                <span>
                  {result.matched > result.hits.length
                    ? `共命中 ${result.matched} 条，先看前 ${result.hits.length} 条`
                    : '按相关度排序'}
                </span>
              )}
            </div>
          </div>
          {result.hits.length ? (
            <div className="space-y-2.5">
              {result.hits.map((item) => (
                <PassageHit key={item.id} item={item} query={query} />
              ))}
            </div>
          ) : (
            <Card>
              <CardEmpty label="没找到相关的内容" hint="换个更常见的说法试试，或点上面的常用词" />
            </Card>
          )}
        </div>

        <aside className="flex h-full flex-col gap-4">
          <Card className="px-4 py-3">
            <SectionLabel>怎么用</SectionLabel>
            <ol className="mt-2 space-y-2 text-caption leading-relaxed text-muted">
              {[
                ['1', '搜一个词', '想到什么就搜什么，不用记分类'],
                ['2', '看命中片段', '每条都是几句话，直接能读懂'],
                ['3', '看出处', '书名和章节写在下面，方便回头找原文'],
              ].map(([step, name, note]) => (
                <li key={step} className="flex gap-2">
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand-soft text-[calc(11px*var(--font-scale))] font-medium text-brand">
                    {step}
                  </span>
                  <span className="min-w-0">
                    <span className="block font-medium text-ink">{name}</span>
                    <span className="block text-faint">{note}</span>
                  </span>
                </li>
              ))}
            </ol>
          </Card>

          <Card className="px-4 py-3">
            <SectionLabel>按领域翻</SectionLabel>
            <p className="mt-1 text-caption text-faint">点一下，就看这个领域里的内容</p>
            <ul className="mt-2 space-y-0.5">
              {CATEGORY_STATS.map((entry) => (
                <li key={entry.name}>
                  <button
                    type="button"
                    onClick={() => {
                      setQuery('');
                      setCategory(entry.name === category ? null : entry.name);
                      setPage(0);
                    }}
                    className={`flex w-full items-center justify-between rounded-control px-2 py-1.5 text-left text-caption transition-colors ${
                      entry.name === category
                        ? 'bg-brand-soft font-medium text-brand'
                        : 'text-muted hover:bg-surface-sunken hover:text-ink'
                    }`}
                  >
                    <span>{entry.name}</span>
                    <span className="tabular-nums text-faint">{entry.count}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>

          {/* 最后一块撑到与左栏等高：两栏下边缘齐平，右栏下方不再空出一块背景 */}
          <Card className="flex-1 px-4 py-3">
            <SectionLabel>关于这个库</SectionLabel>
            <p className="mt-1.5 text-caption leading-relaxed text-muted">
              现在只放文档办公和写论文相关的知识，别的内容暂时没收。这里不是可以安装或启用的功能，找不到想要的，多半是还没收进来；以后会持续补充，也能让助手在写文件、改论文时自己来查。
            </p>
          </Card>
        </aside>
      </div>
    </PageShell>
  );
}
