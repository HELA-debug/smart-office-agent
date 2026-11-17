import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../../../shared/lib/api';
import { formatCost, formatNumber, formatClock } from '../../../shared/lib/format';
import {
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconGauge,
  IconRefresh,
  IconSparkle,
} from '../../../shared/ui/Icons';
import { Badge } from '../../../shared/ui/primitives';
import { auditApi } from '../../audit';
import { settingsApi } from '../../settings';
import type { ModelBalanceOut, UsageOut } from '../../../shared/api/types';
import type { ModelOut } from '../../settings';

/**
 * 输入框工具栏的「模型」控件组（第六十轮合并）。
 *
 * 以前这里是两个并排的图标按钮：一个「用量」、一个「模型」——都是和「这次用哪个模型、
 * 花了多少」有关的信息，却分成两个浮层，用户得记住哪个图标是哪个。现在收成一个胶囊：
 * 收起时直接写着当前模型名，展开后上半是模型列表、下半是近 7 天用量，一处看完。
 *
 * 只做信息归并，不改行为：切换仍走 PATCH /settings（下一次运行生效），用量仍走审计接口。
 */
export function ComposerQuickAccess({
  model,
  isMock,
  blocked = false,
  onModelChanged,
}: {
  model: string | null;
  isMock: boolean;
  /**
   * 一个能用的模型都没有（真实引擎下没 Key）：胶囊直接写「未配置模型」，
   * 不能再显示后端兜底的 mock-scripted——看着像选好了模型，实际发不出去。
   */
  blocked?: boolean;
  /** 切换模型后通知外层刷新健康检查（顶栏 model 展示） */
  onModelChanged?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const label = blocked ? '未配置模型' : (model ?? (isMock ? '本地 mock' : '选择模型'));

  return (
    <div ref={rootRef} className="relative flex items-center">
      <button
        type="button"
        aria-label="模型与用量"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={`flex h-7 max-w-[10rem] items-center gap-1 rounded-full border px-2 text-caption transition-colors ${
          blocked
            ? 'border-warn-line bg-warn-soft text-warn'
            : open
              ? 'border-brand-line bg-brand-soft text-brand-strong'
              : 'border-line bg-surface text-ink-soft hover:border-line-strong hover:bg-surface-hover hover:text-ink'
        }`}
      >
        <IconSparkle size={13} className="shrink-0 text-brand" />
        {/* 窄屏写「模型」，宽屏写具体型号：再长也不该把发送键挤到第二行 */}
        <span className="font-medium sm:hidden">模型</span>
        <span className="hidden min-w-0 truncate font-medium sm:inline">{label}</span>
        <IconChevronDown
          size={12}
          className={`shrink-0 text-muted transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open ? (
        <ModelPanel
          // blocked 时不能拿 mock-scripted 充当选中项：那一行不在列表里，
          // 却会让某个「同名」模型被错误高亮成「当前」
          current={blocked ? null : (model ?? (isMock ? 'mock-scripted' : null))}
          isMock={isMock}
          onNavigate={() => setOpen(false)}
          onChanged={onModelChanged}
        />
      ) : null}
    </div>
  );
}

const PANEL =
  // 窄屏把面板挂到触发点的中线上，不再死贴右边缘：触发按钮在手机上离右边缘很远，
  // 右对齐会让 21rem 的面板整块往左溢出屏幕（实测 390 宽时左边被切掉 86px）。
  'absolute bottom-full right-0 z-30 mb-2 w-[21rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-card border border-line bg-surface shadow-pop max-sm:right-auto max-sm:left-1/2 max-sm:-translate-x-1/2';

type LoadState = 'loading' | 'ready' | 'error';

/** 列表行与用量块共用的内边距：左右 12px，跟面板标题对齐 */
const PAD = 'px-3';

function ModelPanel({
  current,
  isMock,
  onNavigate,
  onChanged,
}: {
  current: string | null;
  isMock: boolean;
  onNavigate: () => void;
  onChanged?: () => void;
}) {
  const [models, setModels] = useState<ModelOut[]>([]);
  const [state, setState] = useState<LoadState>('loading');
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  /** 刚切过去的模型：先本地记下，绿色「当前」立刻挪过去，不等外层健康检查回来 */
  const [picked, setPicked] = useState<string | null>(null);
  const active = picked ?? current;

  useEffect(() => {
    const controller = new AbortController();
    settingsApi
      .listModels(controller.signal)
      .then((response) => {
        setModels(response.data.models);
        setState('ready');
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setState('error');
      });
    return () => controller.abort();
  }, []);

  const choose = async (model: ModelOut) => {
    if (!model.configured) {
      setMessage(`${model.provider} 还没配置 Key：到设置页粘贴后即可切换`);
      return;
    }
    setBusy(model.id);
    setMessage(null);
    try {
      await settingsApi.updateSettings({
        model_provider: model.provider,
        model_name: model.model,
      });
      setPicked(model.model);
      setMessage(`已切换到 ${model.model}，下一次运行生效`);
      onChanged?.();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(null);
    }
  };

  const configuredCount = models.filter((model) => model.configured).length;

  return (
    <div role="dialog" aria-label="模型与用量" className={PANEL}>
      <header className={`flex items-center gap-1.5 border-b border-line py-2.5 ${PAD}`}>
        <span className="text-mini font-semibold text-ink">模型</span>
        {state === 'ready' ? (
          <span className="min-w-0 truncate text-caption">
            {/* 配好的数量标绿：跟列表里的绿点、「可用」是同一套信号色 */}
            <span className={configuredCount > 0 ? 'font-medium text-ok' : 'text-muted'}>
              {configuredCount} 个已配置
            </span>
            <span className="text-muted"> / 共 {models.length} 个</span>
          </span>
        ) : (
          <span className="min-w-0 truncate text-caption text-muted">读取中…</span>
        )}
        {isMock ? (
          <Badge tone="brand" className="ml-auto shrink-0">
            本地 mock
          </Badge>
        ) : null}
      </header>

      <div className="max-h-[15rem] overflow-y-auto overscroll-contain p-1.5">
        {state === 'loading' ? (
          <p className={`py-3 text-caption text-muted ${PAD}`}>加载模型列表…</p>
        ) : state === 'error' ? (
          <p className={`py-3 text-caption text-danger ${PAD}`}>模型列表读取失败，可到设置页查看</p>
        ) : models.length === 0 ? (
          <p className={`py-3 text-caption text-muted ${PAD}`}>后端未返回模型</p>
        ) : (
          <>
            {/* 一家都没配好：先说清「为什么点不了」，别让用户对着满屏灰行猜 */}
            {configuredCount === 0 ? (
              <p
                className={`mb-1.5 rounded-control border border-warn-line bg-warn-soft px-2 py-1.5 text-caption text-warn ${PAD}`}
              >
                还没有配好的模型：到设置页给任意一家添加 Key 后即可选择并发送
              </p>
            ) : null}
            {models.map((model) => {
              const selected = active === model.model;
              const disabled = !model.configured || busy !== null;
              return (
                <button
                  key={model.id}
                  type="button"
                  disabled={disabled}
                  onClick={() => void choose(model)}
                  aria-pressed={selected}
                  className={`relative flex w-full items-center gap-2 rounded-control py-1.5 pr-2 pl-2.5 text-left transition-colors ${
                    selected
                      ? // 当前用的这个：底色比其它行深一档，再加一圈描边和左侧竖条，
                        // 扫一眼就知道「现在跑的是它」，不用去读右边的小字
                        'bg-brand-soft-strong ring-1 ring-brand-line ring-inset'
                      : model.configured
                        ? 'hover:bg-surface-hover'
                        : ''
                  } ${disabled ? 'cursor-not-allowed' : ''}`}
                >
                  {selected ? (
                    <span
                      aria-hidden
                      className="absolute inset-y-1.5 left-0 w-[2px] rounded-full bg-brand"
                    />
                  ) : null}
                  {/* 绿点 = 已经配好 Key、能直接切；灰点 = 还差 Key */}
                  <span
                    aria-hidden
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      model.configured ? 'bg-ok' : 'bg-line-strong'
                    }`}
                  />
                  <span
                    className={`min-w-0 shrink truncate text-mini ${
                      selected
                        ? 'font-semibold text-brand-strong'
                        : model.configured
                          ? 'font-medium text-ink'
                          : 'text-muted'
                    }`}
                  >
                    {model.model}
                  </span>
                  <span className="shrink-0 text-caption text-muted">{model.provider}</span>
                  <span className="ml-auto flex shrink-0 items-center gap-1">
                    {busy === model.id ? (
                      <span className="text-caption text-muted">切换中…</span>
                    ) : selected ? (
                      <>
                        <IconCheck size={12} className="text-brand-strong" />
                        <span className="text-caption font-semibold text-brand-strong">当前</span>
                      </>
                    ) : model.configured ? (
                      // 配好的写成绿色：一眼分辨「能切的」和「还差 Key 的」，
                      // 空白会让「这一行到底能不能点」变成猜谜
                      <span className="text-caption font-medium text-ok">可用</span>
                    ) : (
                      <span className="text-caption text-faint">未配置</span>
                    )}
                  </span>
                </button>
              );
            })}
          </>
        )}
      </div>

      {message ? <p className={`pb-1 text-caption text-muted ${PAD}`}>{message}</p> : null}

      <UsageSummary
        onNavigate={onNavigate}
        balanceModelId={models.find((model) => model.model === active)?.id}
      />

      <footer
        className={`flex items-center justify-between gap-2 border-t border-line py-2 ${PAD}`}
      >
        <span className="min-w-0 truncate text-caption text-faint">切换后作用于下一次运行</span>
        <Link
          to="/settings"
          onClick={onNavigate}
          className="flex shrink-0 items-center gap-0.5 text-caption font-medium text-brand-strong hover:underline"
        >
          前往设置管理
          <IconChevronRight size={11} />
        </Link>
      </footer>
    </div>
  );
}

/**
 * 近 7 天用量：并进模型面板，省掉工具栏上另一个图标入口。
 *
 * 顺带查一次账户余额：本地显示花了多少钱、控制台也显示同一个余额，
 * 才能证明「这些 token 真是这个账号花的」，而不是本地编出来的数字。
 */
function UsageSummary({
  onNavigate,
  balanceModelId,
}: {
  onNavigate: () => void;
  balanceModelId?: string;
}) {
  const [usage, setUsage] = useState<UsageOut | null>(null);
  const [state, setState] = useState<LoadState>('loading');
  const [balance, setBalance] = useState<ModelBalanceOut | null>(null);
  const [balanceBusy, setBalanceBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    auditApi
      .getUsageSummary({ range: '7d', limit: 500 }, controller.signal)
      .then((response) => {
        setUsage(response.data);
        setState('ready');
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setState('error');
      });
    return () => controller.abort();
  }, []);

  // 余额每次都现场问官方：面板一打开就查，点刷新再查。缓存过的余额对不上账，
  // 用户只会看到「本地余额」和「控制台余额」差几分钱，然后怀疑整块数据都是编的。
  const loadBalance = useCallback(
    (signal?: AbortSignal) => {
      if (!balanceModelId) return;
      setBalanceBusy(true);
      settingsApi
        .getBalance(balanceModelId, signal)
        .then((response) => setBalance(response.data))
        // 查余额失败不影响用量展示：有的供应商压根没有这个接口
        .catch(() => setBalance(null))
        .finally(() => setBalanceBusy(false));
    },
    [balanceModelId],
  );

  useEffect(() => {
    const controller = new AbortController();
    loadBalance(controller.signal);
    return () => controller.abort();
  }, [loadBalance]);

  // 成本口径（官方分时价 + 缓存分级）由后端给：价格表改了这里跟着变，不在前端写死数字
  const priceNote = usage?.price_note ?? '';
  const checkedAt = balance?.checked_at ? `查询于 ${formatClock(balance.checked_at)}` : '';
  const balanceTitle = balance
    ? `同一次实时查询：合计 ${formatCost(balance.total_balance)} = 充值 ${formatCost(
        balance.topped_up_balance ?? 0,
      )} + 赠送 ${formatCost(balance.granted_balance ?? 0)}${checkedAt ? `（${checkedAt}）` : ''}`
    : '';

  return (
    <section aria-label="近 7 天用量" className={`border-t border-line py-2.5 ${PAD}`}>
      <div className="flex items-center gap-1.5">
        <IconGauge size={12} className="shrink-0 text-muted" />
        <span className="text-caption font-medium text-ink-soft">近 7 天用量</span>
        {state === 'error' ? <span className="text-caption text-danger">加载失败</span> : null}
        <Link
          to="/audit"
          onClick={onNavigate}
          className="ml-auto flex shrink-0 items-center gap-0.5 text-caption text-muted transition-colors hover:text-ink"
        >
          明细
          <IconChevronRight size={11} />
        </Link>
      </div>
      {state === 'ready' && usage ? (
        <>
          <dl className="mt-1.5 grid grid-cols-3 gap-2">
            {[
              // 只数真实调用：mock 的 tokens/成本是本地编的，混进来就跟控制台对不上账
              { key: 'runs', label: '真实调用', value: `${formatNumber(usage.real_runs)} 次` },
              { key: 'tokens', label: 'tokens', value: formatNumber(usage.tokens) },
              // 按价格表算出来的，不是账单原值；余额才是官网的真数
              { key: 'cost', label: '成本估算', value: formatCost(usage.cost_cny) },
            ].map((item) => (
              <div
                key={item.key}
                className="min-w-0"
                title={item.key === 'cost' ? priceNote : undefined}
              >
                <dt className="text-caption text-muted">{item.label}</dt>
                <dd className="truncate text-mini font-medium tabular-nums text-ink">
                  {item.value}
                </dd>
              </div>
            ))}
          </dl>
          {/* 口径细节（官方实扣模型名、单价、缓存命中、mock 次数）不进面板正文：
              这几行又长又被截断，把三个关键数字挤成脚注。口径统一放到
              「成本估算」的悬停提示里，正文只留数字和余额。 */}
          {balance?.supported && balance.total_balance != null ? (
            <div className="mt-1 flex items-center gap-1 text-caption text-faint">
              {/* 「查询于 12:11」也挪进 title：留在正文里必被截成「查询...」，
                  多出来的省略号比信息本身更刺眼 */}
              <span className="min-w-0 truncate" title={balanceTitle}>
                账户余额{' '}
                <span className="font-medium text-ink-soft">
                  {formatCost(balance.total_balance)}
                </span>
                {' · '}充值 {formatCost(balance.topped_up_balance ?? 0)}+赠送{' '}
                {formatCost(balance.granted_balance ?? 0)}
              </span>
              <button
                type="button"
                aria-label="刷新账户余额"
                onClick={() => loadBalance()}
                className="ml-auto flex shrink-0 items-center gap-0.5 text-caption text-muted transition-colors hover:text-ink"
              >
                <IconRefresh size={11} className={balanceBusy ? 'animate-spin' : ''} />
                刷新
              </button>
            </div>
          ) : null}
        </>
      ) : (
        <p className="mt-1 text-caption text-muted">{state === 'error' ? '—' : '读取中…'}</p>
      )}
    </section>
  );
}
