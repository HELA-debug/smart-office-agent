import { useState } from 'react';
import { formatCost, formatDateTime, formatNumber } from '../../../shared/lib/format';
import { IconExternal, IconRefresh } from '../../../shared/ui/Icons';
import { Badge, Button, Card } from '../../../shared/ui/primitives';
import type { ProviderUsageOut } from '../../../shared/api/types';

interface LocalSide {
  cost: number;
  calls: number;
  tokens: number;
}

interface Props {
  data: ProviderUsageOut | null;
  loading: boolean;
  /** 本地账本同期数据，用来和官方口径做差 */
  local: LocalSide;
  onRefresh: () => void;
  onSaveToken: (token: string) => Promise<void>;
}

/**
 * 官方账单对账卡。
 *
 * 为什么要有这张卡：本地账本只能看见「本应用」发出的请求。同一把 Key 被别的
 * 工具用过、或者历史脚本跑过，本地怎么加都对不上官方那本账，数字差得越多越像
 * 系统在编数据。与其解释，不如把两本账并排摆出来，差额写在脸上。
 *
 * token 只走后端进程内存，这里也不做本地持久化——刷新页面就要重新填是刻意设计。
 */
export function ProviderLedgerCard({ data, loading, local, onRefresh, onSaveToken }: Props) {
  const [token, setToken] = useState('');
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);

  const available = Boolean(data?.available);
  const hasToken = Boolean(data?.has_token);
  const showTokenForm = !hasToken || editing || data?.error?.code === 'TOKEN_EXPIRED';
  const errorCode = data?.error?.code ?? '';
  const diffCost = available ? Math.max(0, (data?.cost_cny ?? 0) - local.cost) : 0;
  const diffCalls = available ? Math.max(0, (data?.requests ?? 0) - local.calls) : 0;

  const submit = async () => {
    const value = token.trim();
    if (!value) return;
    setSaving(true);
    try {
      await onSaveToken(value);
      setToken('');
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
        <span className="text-regular font-semibold text-ink">官方账单</span>
        {data?.month ? <Badge tone="neutral">{data.month}</Badge> : null}
        {available ? <Badge tone="ok">已对账</Badge> : null}
        {errorCode === 'TOKEN_EXPIRED' ? <Badge tone="warn">token 已失效</Badge> : null}
        <span className="ml-auto flex items-center gap-1.5">
          {hasToken ? (
            <Button variant="ghost" size="sm" onClick={() => setEditing((v) => !v)}>
              {editing ? '取消' : '换个 token'}
            </Button>
          ) : null}
          <Button
            variant="secondary"
            size="sm"
            loading={loading}
            onClick={onRefresh}
            leading={<IconRefresh size={13} />}
          >
            刷新
          </Button>
        </span>
      </div>

      {available ? (
        <>
          <div className="grid gap-3 px-4 py-3 sm:grid-cols-3">
            <div>
              <div className="text-caption text-faint">官方消费</div>
              <div className="text-display font-semibold text-ink">
                {formatCost(data?.cost_cny ?? 0)}
              </div>
            </div>
            <div>
              <div className="text-caption text-faint">API 请求次数</div>
              <div className="text-display font-semibold text-ink">
                {formatNumber(data?.requests ?? 0)}
              </div>
            </div>
            <div>
              <div className="text-caption text-faint">Tokens</div>
              <div className="text-display font-semibold text-ink">
                {formatNumber(data?.tokens ?? 0)}
              </div>
            </div>
          </div>
          <div className="border-t border-line px-4 py-2.5 text-caption text-muted">
            本应用同期 {formatCost(local.cost)} · {formatNumber(local.calls)} 次请求
            {diffCost > 0 || diffCalls > 0 ? (
              <>
                <span className="mx-1.5 text-faint">|</span>
                差额 {formatCost(diffCost)} · {formatNumber(diffCalls)} 次
                <span className="ml-1 text-faint">（本应用之外的消耗：其它工具或历史调用）</span>
              </>
            ) : (
              <span className="ml-1 text-faint">（两边一致）</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2 text-caption text-faint">
            <span>{data?.note}</span>
            {data?.fetched_at ? <span>· {formatDateTime(data.fetched_at)} 取回</span> : null}
            {data?.source ? (
              <a
                href={data.source.replace('/api/v0/usage/amount', '/usage')}
                target="_blank"
                rel="noreferrer noopener"
                className="ml-auto inline-flex items-center gap-1 text-brand-strong hover:underline"
              >
                控制台
                <IconExternal size={11} />
              </a>
            ) : null}
          </div>
        </>
      ) : (
        <div className="px-4 py-3">
          <p className="text-caption text-muted">
            {errorCode === 'TOKEN_EXPIRED'
              ? '官方 token 已失效。重新登录 platform.deepseek.com，从浏览器 localStorage.userToken 复制新值。'
              : errorCode === 'NETWORK'
                ? '连不上官方平台接口，暂时只显示本地账本。'
                : '官方账单需要一次性的控制台登录态 token——官方用量接口不接受 API Key（用 API Key 调只回 40003）。'}
          </p>
          {data?.error?.message && errorCode !== 'NETWORK' ? (
            <p className="mt-1 text-caption text-faint">{data.error.message}</p>
          ) : null}
        </div>
      )}

      {showTokenForm ? (
        <div className="border-t border-line px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void submit();
              }}
              placeholder="粘贴 localStorage.userToken 的值"
              aria-label="官方用量 token"
              autoComplete="off"
              spellCheck={false}
              className="h-8 min-w-0 flex-1 rounded-control border border-line bg-surface px-2 font-mono text-mini text-ink outline-none focus:border-brand"
            />
            <Button
              variant="primary"
              size="sm"
              loading={saving}
              disabled={!token.trim()}
              onClick={() => void submit()}
            >
              保存
            </Button>
          </div>
          <p className="mt-1.5 text-caption text-faint">
            浏览器按 F12 → Console → 输入 <code className="font-mono">localStorage.userToken</code>{' '}
            回车，复制返回的值。只存后端进程内存，重启即失效，不写盘、不进日志。
          </p>
        </div>
      ) : null}
    </Card>
  );
}
