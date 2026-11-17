import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { PROVIDER_CONSOLES } from '../../shared/config/providers';
import { errorMessage } from '../../shared/lib/api';
import { formatCost, formatDateTime, formatDuration, formatNumber } from '../../shared/lib/format';
import { BarChart } from '../../shared/ui/BarChart';
import { IconExternal, IconRefresh } from '../../shared/ui/Icons';
import { PageShell } from '../../shared/ui/PageShell';
import {
  Badge,
  Button,
  Card,
  CardEmpty,
  CardError,
  CardLoading,
  SectionLabel,
} from '../../shared/ui/primitives';
import { Select } from '../../shared/ui/Select';
import { sessionsApi } from '../sessions';
import { auditApi } from './api';
import { ProviderLedgerCard } from './components/ProviderLedgerCard';
import type { AuditOut, ProviderUsageOut, ThreadOut, UsageOut } from '../../shared/api/types';

type RangeKey = 'today' | '7d' | '30d' | 'all';

const RANGE_OPTIONS: { value: RangeKey; label: string }[] = [
  { value: 'today', label: '今天' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: 'all', label: '全部' },
];

const RANGE_LABEL: Record<RangeKey, string> = {
  today: '今天',
  '7d': '近 7 天',
  '30d': '近 30 天',
  all: '全部',
};

function statusTone(status: string): 'ok' | 'warn' | 'danger' | 'neutral' {
  if (status === 'completed') return 'ok';
  if (status === 'rejected') return 'warn';
  if (status === 'failed') return 'danger';
  return 'neutral';
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    completed: '已完成',
    rejected: '已拒绝',
    failed: '失败',
    running: '运行中',
  };
  return map[status] ?? status;
}

/** 统计卡（数值 + 说明）。 */
function StatCard({
  label,
  value,
  hint,
  action,
}: {
  label: string;
  value: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <Card className="px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="text-caption text-faint">{label}</span>
        {action ? <span className="ml-auto">{action}</span> : null}
      </div>
      <div className="mt-1 text-display font-semibold text-ink">{value}</div>
      {hint ? <div className="mt-0.5 text-caption text-faint">{hint}</div> : null}
    </Card>
  );
}

/**
 * 充值入口：模型有好几个，所以悬停/点击先让用户挑供应商，再跳它的开放平台。
 * 面板用圆角卡片 + 圆角选项（跟全站自绘下拉一致，不用原生菜单）。
 */
function TopUpMenu({ usedProviders }: { usedProviders: string[] }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const buttonRef = useRef<HTMLSpanElement>(null);
  const closeTimer = useRef<number | null>(null);

  // 用浮层渲染到 body：卡片本身会创建层叠上下文，面板放在卡片里会被下一张卡盖住
  const openMenu = () => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPos({ top: rect.bottom + 6, left: Math.max(8, rect.right - 224) });
    setOpen(true);
  };

  const cancelClose = () => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  };

  // 鼠标从按钮移到面板中间会经过空隙，给一点延迟再收起
  const scheduleClose = () => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => {
      setOpen(false);
      setPos(null);
    }, 180);
  };

  useEffect(() => {
    if (!open) return;
    const onScroll = () => {
      setOpen(false);
      setPos(null);
    };
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
    };
  }, [open]);

  useEffect(() => () => cancelClose(), []);

  const keys = Object.keys(PROVIDER_CONSOLES);
  // 用过的供应商排前面，其余也列出来（方便给还没用过的模型充值）
  const ordered = [
    ...usedProviders.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !usedProviders.includes(key)),
  ];

  return (
    <div onMouseEnter={openMenu} onMouseLeave={scheduleClose}>
      <span ref={buttonRef} className="inline-flex">
        <Button
          variant="primary"
          size="sm"
          aria-expanded={open}
          aria-haspopup="menu"
          onClick={() => (open ? (setOpen(false), setPos(null)) : openMenu())}
          trailing={<IconExternal size={12} />}
        >
          去充值
        </Button>
      </span>
      {open && pos
        ? createPortal(
            <div
              role="menu"
              tabIndex={-1}
              aria-label="选择要充值的模型供应商"
              style={{ top: pos.top, left: pos.left }}
              onMouseEnter={cancelClose}
              onMouseLeave={scheduleClose}
              className="fixed z-[90] w-[14rem] rounded-2xl border border-line bg-surface p-1 shadow-pop"
            >
              <div className="px-2 py-1 text-caption text-faint">选择要充值的模型</div>
              {ordered.map((key) => {
                const entry = PROVIDER_CONSOLES[key];
                if (!entry) return null;
                return (
                  <button
                    key={key}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      window.open(entry.topUp, '_blank', 'noopener');
                      setOpen(false);
                      setPos(null);
                    }}
                    className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-mini text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink"
                  >
                    <span className="min-w-0 flex-1 truncate">{entry.label}</span>
                    {usedProviders.includes(key) ? <Badge tone="neutral">用过</Badge> : null}
                    <IconExternal size={12} className="shrink-0 text-faint" />
                  </button>
                );
              })}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

/**
 * 审计用量（dsh 风格信息架构）：
 * 余额/消耗总览 → 筛选 → 区间统计 → 按日趋势图 → 按模型分组 → 运行明细。
 * 全部为后端真实聚合数据；充值跳转模型供应商开放平台。
 */
export function AuditPage() {
  const [threads, setThreads] = useState<ThreadOut[]>([]);
  const [threadId, setThreadId] = useState('');
  const [range, setRange] = useState<RangeKey>('30d');
  const [usage, setUsage] = useState<UsageOut | null>(null);
  const [usage30d, setUsage30d] = useState<UsageOut | null>(null);
  const [usageAll, setUsageAll] = useState<UsageOut | null>(null);
  const [audit, setAudit] = useState<AuditOut | null>(null);
  const [providerUsage, setProviderUsage] = useState<ProviderUsageOut | null>(null);
  const [providerLoading, setProviderLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    void sessionsApi
      .listThreads()
      .then((response) => setThreads(response.data.threads))
      .catch(() => setThreads([]));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [rangeRes, d30Res, allRes] = await Promise.all([
        auditApi.getUsageSummary({ threadId: threadId || undefined, range, limit: 500 }),
        auditApi.getUsageSummary({ threadId: threadId || undefined, range: '30d', limit: 500 }),
        auditApi.getUsageSummary({ threadId: threadId || undefined, range: 'all', limit: 500 }),
      ]);
      setUsage(rangeRes.data);
      setUsage30d(d30Res.data);
      setUsageAll(allRes.data);
      if (threadId) {
        const auditResponse = await auditApi.getAudit(threadId);
        setAudit(auditResponse.data);
      } else {
        setAudit(null);
      }
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [range, threadId]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * 官方账单单独拉：它随时可能因为 token 过期 / 网络问题失败，
   * 失败就只是不显示这一块，不能连带把本地账本也搞成一片报错。
   */
  const loadProvider = useCallback(async (force = false) => {
    setProviderLoading(true);
    try {
      const response = await auditApi.getProviderUsage({ force });
      setProviderUsage(response.data);
    } catch {
      setProviderUsage(null);
    } finally {
      setProviderLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProvider();
  }, [loadProvider]);

  const saveProviderToken = useCallback(
    async (token: string) => {
      await auditApi.setProviderToken(token);
      await loadProvider(true);
    },
    [loadProvider],
  );

  const threadLabel = useMemo(() => {
    if (!threadId) return '全部会话';
    return threads.find((thread) => thread.thread_id === threadId)?.title ?? threadId;
  }, [threadId, threads]);

  /** 按日序列（升序，补足近 N 天连续日期，图表不断档）。 */
  const daySeries = useMemo(() => {
    const days = range === 'today' ? 1 : range === '7d' ? 7 : range === '30d' ? 30 : null;
    const raw = [...(usage?.by_day ?? [])].reverse();
    if (!days || raw.length === 0) {
      return raw.map((day) => ({ label: day.date.slice(5), value: day.cost_cny }));
    }
    const byDate = new Map(raw.map((day) => [day.date, day.cost_cny]));
    const today = new Date();
    const series: { label: string; value: number }[] = [];
    for (let offset = days - 1; offset >= 0; offset -= 1) {
      const date = new Date(today);
      date.setDate(today.getDate() - offset);
      const key = date.toISOString().slice(0, 10);
      series.push({ label: key.slice(5), value: byDate.get(key) ?? 0 });
    }
    return series;
  }, [usage, range]);

  const modelTotal = usage?.by_model ?? [];
  const maxModelTokens = Math.max(...modelTotal.map((item) => item.tokens), 1);
  const usedProviders = [...new Set((usage?.by_provider ?? []).map((item) => item.provider))];
  const runs = audit?.runs ?? [];
  const approvals = audit?.approvals ?? [];
  const artifacts = audit?.artifacts ?? [];

  return (
    <PageShell
      title="审计用量"
      description="运行消耗与用量趋势：本地账本来自每次运行的审计记录，官方账单按平台口径另列一路做对账。"
      actions={
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void load()}
          leading={<IconRefresh size={13} />}
          loading={loading}
        >
          刷新
        </Button>
      }
    >
      {loading ? (
        <Card>
          <CardLoading label="正在汇总用量…" rows={4} />
        </Card>
      ) : loadError ? (
        <Card>
          <CardError message={loadError} onRetry={() => void load()} />
        </Card>
      ) : (
        <div className="space-y-4">
          {/* 总览：累计消耗 / 近 30 天消耗 / 请求次数 */}
          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard
              label="累计消费金额"
              value={formatCost(usageAll?.cost_cny ?? 0)}
              hint={`全部范围 · ${formatNumber(usageAll?.runs ?? 0)} 次运行`}
              action={<TopUpMenu usedProviders={usedProviders} />}
            />
            <StatCard
              label="近 30 天消耗"
              value={formatCost(usage30d?.cost_cny ?? 0)}
              hint={`${formatNumber(usage30d?.runs ?? 0)} 次运行 · ${formatNumber(
                usage30d?.tokens ?? 0,
              )} tokens`}
            />
            <StatCard
              label="API 请求次数"
              value={formatNumber(usage30d?.api_calls ?? 0)}
              // 官方控制台数的是「HTTP 请求」，不是「任务数」。一次运行内部
              // 有十几轮工具调用，每轮都单独计费——用运行数去比官方账单，
              // 差出几十倍是必然的，还容易被当成没记账。
              hint={`近 30 天 ${formatNumber(usage30d?.real_runs ?? 0)} 次运行`}
            />
          </div>

          <ProviderLedgerCard
            data={providerUsage}
            loading={providerLoading}
            local={{
              cost: usage30d?.cost_cny ?? 0,
              calls: usage30d?.api_calls ?? 0,
              tokens: usage30d?.tokens ?? 0,
            }}
            onRefresh={() => void loadProvider(true)}
            onSaveToken={saveProviderToken}
          />

          {/* 筛选行 */}
          <Card className="px-4 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1.5 text-caption text-muted">
                <span className="shrink-0">时间维度</span>
                <Select
                  value={range}
                  options={RANGE_OPTIONS.map((option) => ({
                    value: option.value,
                    label: option.label,
                  }))}
                  onChange={(next) => setRange(next as RangeKey)}
                  ariaLabel="时间维度"
                  className="w-[8.5rem]"
                  minWidth={140}
                />
              </div>
              <div className="flex items-center gap-1.5 text-caption text-muted">
                <span className="shrink-0">会话</span>
                <Select
                  value={threadId}
                  options={[
                    { value: '', label: '全部会话' },
                    ...threads.map((thread) => ({
                      value: thread.thread_id,
                      label: thread.title,
                    })),
                  ]}
                  onChange={(next) => setThreadId(next)}
                  ariaLabel="选择会话"
                  className="w-[14rem]"
                  minWidth={190}
                />
              </div>
              {threadId || range !== '30d' ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setThreadId('');
                    setRange('30d');
                  }}
                >
                  清除筛选条件
                </Button>
              ) : null}
              <span className="ml-auto text-caption text-faint">
                当前范围：{RANGE_LABEL[range]} · {threadLabel}
              </span>
            </div>
          </Card>

          {/* 区间统计 */}
          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard
              label="消费金额"
              value={formatCost(usage?.cost_cny ?? 0)}
              // 口径写在卡片上：官方是分时 + 缓存分级计价，单看总价会以为「贵得离谱」
              hint={usage?.price_note || RANGE_LABEL[range]}
            />
            <StatCard
              label="真实调用"
              value={formatNumber(usage?.real_runs ?? 0)}
              hint={
                usage && usage.cancelled_runs > 0
                  ? // 取消的运行也花了钱：不标出来，用户会以为「只有这几次完整运行的费用」
                    `含 ${formatNumber(usage.cancelled_runs)} 次中途取消 · 已花 ${formatCost(
                      usage.cancelled_cost_cny,
                    )}`
                  : usage && usage.mock_runs > 0
                    ? `另有本地 mock ${formatNumber(usage.mock_runs)} 次（不计费）`
                    : RANGE_LABEL[range]
              }
            />
            <StatCard
              label="Tokens"
              value={formatNumber(usage?.tokens ?? 0)}
              hint={
                usage && usage.cache_hit_tokens + usage.cache_miss_tokens > 0
                  ? `命中缓存 ${formatNumber(usage.cache_hit_tokens)} · 未命中 ${formatNumber(
                      usage.cache_miss_tokens,
                    )}`
                  : `${RANGE_LABEL[range]} · 仅真实调用`
              }
            />
          </div>

          {/* 消费金额趋势 */}
          <Card>
            <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
              <span className="text-regular font-semibold text-ink">
                每日消费金额（CNY）{formatCost(usage?.cost_cny ?? 0)}
              </span>
              <span className="ml-auto text-caption text-faint">{RANGE_LABEL[range]}</span>
            </div>
            <div className="px-2 pb-2 pt-3">
              <BarChart
                data={daySeries}
                formatValue={(value) => formatCost(value)}
                unit=""
                height={132}
              />
            </div>
          </Card>

          {/* 按模型分组 */}
          <Card>
            <div className="border-b border-line px-4 py-2.5">
              <SectionLabel>按模型</SectionLabel>
            </div>
            {modelTotal.length === 0 ? (
              <CardEmpty label="暂无模型用量" hint="完成一次运行后按模型汇总" />
            ) : (
              <ul className="max-h-[280px] divide-y divide-line overflow-y-auto">
                {modelTotal.map((item) => (
                  <li key={item.model} className="px-4 py-2.5">
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption">
                      <span className="font-medium text-ink">{item.model}</span>
                      <span className="text-faint">请求 {formatNumber(item.runs)} 次</span>
                      <span className="text-faint">tokens {formatNumber(item.tokens)}</span>
                      <span className="ml-auto text-ink-soft">{formatCost(item.cost_cny)}</span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-sunken">
                      <div
                        className="h-full rounded-full bg-brand"
                        style={{ width: `${Math.max(2, (item.tokens / maxModelTokens) * 100)}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* 运行明细（选中会话后展示） */}
          {threadId ? (
            <>
              <Card>
                <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
                  <span className="text-regular font-semibold text-ink">运行明细</span>
                  <span className="text-caption text-faint">{runs.length} 条</span>
                </div>
                {runs.length === 0 ? (
                  <CardEmpty label="该会话还没有运行记录" />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[640px] text-left text-caption">
                      <thead className="bg-surface-soft text-faint">
                        <tr>
                          <th className="px-3 py-2 font-medium">运行</th>
                          <th className="px-3 py-2 font-medium">状态</th>
                          <th className="px-3 py-2 font-medium">模型</th>
                          <th className="px-3 py-2 font-medium">tokens</th>
                          <th className="px-3 py-2 font-medium">成本</th>
                          <th className="px-3 py-2 font-medium">耗时</th>
                          <th className="px-3 py-2 font-medium">开始时间</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line">
                        {runs.map((run) => (
                          <tr key={run.run_id} className="hover:bg-surface-soft">
                            <td className="px-3 py-2 font-mono text-mini text-ink">{run.run_id}</td>
                            <td className="px-3 py-2">
                              <Badge tone={statusTone(run.status)}>{statusLabel(run.status)}</Badge>
                            </td>
                            <td className="px-3 py-2 text-ink-soft">
                              {run.provider}/{run.model}
                            </td>
                            <td className="px-3 py-2 text-ink-soft">{formatNumber(run.tokens)}</td>
                            <td className="px-3 py-2 text-ink-soft">{formatCost(run.cost_cny)}</td>
                            <td className="px-3 py-2 text-ink-soft">
                              {formatDuration(run.elapsed_ms)}
                            </td>
                            <td className="px-3 py-2 text-ink-soft">
                              {formatDateTime(run.started_at)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <div className="border-b border-line px-4 py-2.5 text-regular font-semibold text-ink">
                    审批记录
                  </div>
                  {approvals.length === 0 ? (
                    <CardEmpty label="没有审批记录" />
                  ) : (
                    <ul className="max-h-[240px] divide-y divide-line overflow-y-auto">
                      {approvals.map((approval) => (
                        <li
                          key={approval.approval_id}
                          className="flex items-center gap-2 px-4 py-2 text-caption"
                        >
                          <span className="font-mono text-ink-soft">{approval.tool}</span>
                          <Badge
                            tone={
                              approval.decision === 'approved'
                                ? 'ok'
                                : approval.decision === 'rejected'
                                  ? 'danger'
                                  : 'warn'
                            }
                          >
                            {approval.decision === 'approved'
                              ? '已批准'
                              : approval.decision === 'rejected'
                                ? '已拒绝'
                                : '待决定'}
                          </Badge>
                          <span className="ml-auto text-faint">
                            {approval.decided_at ? formatDateTime(approval.decided_at) : '—'}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>

                <Card>
                  <div className="border-b border-line px-4 py-2.5 text-regular font-semibold text-ink">
                    产物清单
                  </div>
                  {artifacts.length === 0 ? (
                    <CardEmpty label="没有产物" />
                  ) : (
                    <ul className="max-h-[240px] divide-y divide-line overflow-y-auto">
                      {artifacts.map((artifact) => (
                        <li
                          key={artifact.artifact_id}
                          className="flex items-center gap-2 px-4 py-2 text-caption"
                        >
                          <Badge tone="neutral">{artifact.type}</Badge>
                          <span className="min-w-0 flex-1 truncate text-ink-soft">
                            {artifact.filename}
                          </span>
                          <a
                            href={artifact.download_url}
                            download={artifact.filename}
                            className="text-brand-strong hover:underline"
                          >
                            下载
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
            </>
          ) : (
            <div className="rounded-control border border-dashed border-line px-4 py-4 text-center text-mini text-muted">
              选择具体会话后，可查看该会话的运行明细、审批与产物。
            </div>
          )}
        </div>
      )}
    </PageShell>
  );
}
