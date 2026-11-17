/** 可用模型与 Key 状态列表（设置页右栏顶部）。 */
import { hasProviderConsole, providerLabel } from '../../../shared/config/providers';
import { IconExternal, IconKey, IconLink } from '../../../shared/ui/Icons';
import { Badge, Button, Card } from '../../../shared/ui/primitives';
import type { ModelOut } from '../api';

export function ModelListCard({
  models,
  activeProvider,
  testing,
  testResult,
  keyNotice,
  onTest,
  onAddKey,
  onEditEndpoint,
  onDisconnect,
  disconnecting,
}: {
  models: ModelOut[];
  /** 当前真正在用的供应商（来自设置里的 model_provider），用来标「当前使用」 */
  activeProvider?: string | null;
  testing: string | null;
  testResult: Record<string, string>;
  keyNotice: string | null;
  onTest: (model: ModelOut) => void;
  onAddKey: (model: ModelOut) => void;
  onEditEndpoint: (model: ModelOut) => void;
  /** 断开这家的 Key（env / .env / 内存三处同清；分享或部署给别人前用） */
  onDisconnect: (model: ModelOut) => void;
  /** 正在断开的行（按钮转圈） */
  disconnecting?: string | null;
}) {
  return (
    <Card>
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <span className="text-regular font-semibold text-ink">可用模型与 Key 状态</span>
        <Badge tone="neutral" className="ml-auto">
          {models.length} 个供应商
        </Badge>
      </div>
      <div className="divide-y divide-line">
        {models.length === 0 ? (
          <div className="px-4 py-4 text-mini text-muted">暂时没有拿到模型列表，稍后重试即可。</div>
        ) : (
          models.map((model) => (
            <div key={model.provider} className="flex flex-wrap items-center gap-2 px-4 py-2.5">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-mini font-semibold text-ink">
                    {providerLabel(model.provider)}
                  </span>
                  <Badge tone={model.configured ? 'ok' : 'neutral'}>
                    {model.configured ? '已配置' : '未配置'}
                  </Badge>
                  {/* 只有此刻真在用的那一个才标：内置供应商的 priority 全是 0，
                      原来按 priority 判断会让每一行都挂「首选」，等于没标 */}
                  {activeProvider && model.provider === activeProvider ? (
                    <Badge tone="brand">当前使用</Badge>
                  ) : null}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-caption text-faint">
                  <span className="font-mono">{model.model}</span>
                  <span>· Key 来源：{model.api_key_ref || '未配置'}</span>
                </div>
                {/* 接口地址：WorkBuddy 这类没有公共默认值的供应商，这一行就是它能不能用的关键 */}
                <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-caption text-faint">
                  <IconLink size={11} className="shrink-0" />
                  <span
                    className={`min-w-0 truncate font-mono ${model.base_url ? '' : 'text-warn'}`}
                  >
                    {model.base_url || '接口地址待填'}
                  </span>
                  <button
                    type="button"
                    onClick={() => onEditEndpoint(model)}
                    className="shrink-0 rounded-chip px-1 text-caption text-brand-strong hover:underline"
                    aria-label={`设置 ${providerLabel(model.provider)} 的接口地址`}
                  >
                    {model.base_url ? '改' : '填接口'}
                  </button>
                </div>
                {model.configured ? null : (
                  <div className="mt-0.5 text-caption text-danger">
                    × 还差
                    {model.base_url ? ' Key' : '接口地址'}
                    {model.base_url ? '（环境变量中未找到，仅返回引用）' : '（填完地址再添加 Key）'}
                  </div>
                )}
              </div>
              <div className="ml-auto flex items-center gap-1.5">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onTest(model)}
                  loading={testing === model.id}
                  leading={testing === model.id ? undefined : <IconExternal size={12} />}
                >
                  测试连接
                </Button>
                {model.configured ? (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => onDisconnect(model)}
                    loading={disconnecting === model.id}
                  >
                    断开
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => onAddKey(model)}
                    leading={<IconKey size={12} />}
                  >
                    添加 Key
                  </Button>
                )}
              </div>
              {(() => {
                const result = testResult[model.id];
                if (!result) return null;
                return (
                  <div
                    className={`basis-full text-caption ${
                      result.startsWith('✓')
                        ? 'text-ok'
                        : result.startsWith('ⓘ')
                          ? 'text-warn'
                          : 'text-danger'
                    }`}
                    role="status"
                  >
                    {result}
                  </div>
                );
              })()}
            </div>
          ))
        )}
      </div>
      {keyNotice ? (
        <div
          role="status"
          className="border-t border-ok-line bg-ok-soft px-4 py-2 text-caption text-ok"
        >
          {keyNotice}
        </div>
      ) : null}
      <div className="border-t border-line px-4 py-2.5 text-caption text-faint">
        Key 只写进本机 .env 与服务端内存，界面只显示掩码，不会回传明文。
        <span className="mt-1 block">
          换主模型：在左边「模型供应商」里选，保存后生效（这一栏只管 Key 与接口）。
        </span>
        <span className="mt-1 block">
          把项目分享或部署给别人前，点「断开」把 Key 从本机彻底清掉（含 .env），别人就 用不了你的
          Key；重新粘贴一把新 Key 即可再接上。
        </span>
        {models.some((model) => !hasProviderConsole(model.provider)) ? (
          <span className="mt-1 block">
            WorkBuddy 没有公共接口地址：先「填接口」，再「添加 Key」，最后「测试连接」。
          </span>
        ) : null}
      </div>
    </Card>
  );
}
