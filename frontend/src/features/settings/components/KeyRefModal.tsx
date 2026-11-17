/**
 * 「添加 Key」弹窗：直接粘贴供应商开放平台获取的 Key。
 *
 * 明文只经本机回环发到后端，写入本地 .env 与进程内存；响应只回掩码，
 * 界面上不做任何持久化（受控输入 + 关闭即清空）。
 */
import { useState } from 'react';
import {
  hasProviderConsole,
  providerConsole,
  providerLabel,
} from '../../../shared/config/providers';
import { IconAlertTriangle, IconExternal } from '../../../shared/ui/Icons';
import { Button, Modal } from '../../../shared/ui/primitives';
import { DEFAULT_ENV_NAME } from '../keys';
import type { ModelOut } from '../api';

/**
 * 添加 Key：直接粘贴供应商开放平台获取的 Key。
 *
 * 明文只经本机回环发到后端，写入本地 .env 与进程内存；响应只回掩码，
 * 界面上不做任何持久化（受控输入 + 关闭即清空）。
 */
export function KeyRefModal({
  model,
  saving,
  error,
  onClose,
  onSave,
}: {
  model: ModelOut;
  saving: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (apiKey: string, envName: string) => void;
}) {
  const existingRef = model.api_key_ref?.startsWith('env:') ? model.api_key_ref.slice(4) : '';
  const [apiKey, setApiKey] = useState('');
  const [envName, setEnvName] = useState(existingRef || DEFAULT_ENV_NAME[model.provider] || '');
  const [reveal, setReveal] = useState(false);
  const [touched, setTouched] = useState(false);

  const keyValid = apiKey.trim().length >= 8 && !/\s/.test(apiKey.trim());
  const envValid = /^[A-Z][A-Z0-9_]*$/.test(envName);
  const canSave = keyValid && envValid && !saving;
  const console_ = providerConsole(model.provider);
  const hasConsole = hasProviderConsole(model.provider);
  const label = providerLabel(model.provider);

  return (
    <Modal
      title={`添加 ${label} Key`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!canSave}
            loading={saving}
            onClick={() => {
              setTouched(true);
              if (canSave) onSave(apiKey.trim(), envName);
            }}
          >
            保存
          </Button>
        </>
      }
    >
      <div className="flex items-start gap-2 rounded-control border border-brand-line bg-brand-soft px-2.5 py-2 text-caption text-brand-strong">
        <span className="min-w-0">
          在开放平台创建 Key 后粘贴到下面，点保存就立即生效，不用改配置文件，也不用重启。
        </span>
      </div>
      {model.base_url ? null : (
        <p className="mt-1.5 flex items-start gap-1.5 rounded-control border border-warn-line bg-warn-soft px-2.5 py-1.5 text-caption text-warn">
          <IconAlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>这一行还没填接口地址，先回到列表点「填接口」把它填上，否则保存会失败。</span>
        </p>
      )}
      {hasConsole ? (
        <button
          type="button"
          onClick={() => window.open(console_.keys, '_blank', 'noopener')}
          className="mt-2 inline-flex items-center gap-1 text-caption text-brand-strong hover:underline"
        >
          前往 {label} 开放平台获取 Key
          <IconExternal size={12} />
        </button>
      ) : (
        <p className="mt-2 text-caption text-faint">
          {label} 没有公共开放平台页面：Key 由你的账号提供，直接粘到下面即可。
        </p>
      )}

      <label className="mt-3 block text-mini">
        <span className="mb-1 block font-medium text-ink-soft">API Key</span>
        <span className="relative block">
          <input
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            onBlur={() => setTouched(true)}
            type={reveal ? 'text' : 'password'}
            autoComplete="off"
            spellCheck={false}
            aria-label="API Key"
            placeholder={model.provider === 'deepseek' ? 'sk-...' : '粘贴供应商提供的 Key'}
            className="h-8 w-full rounded-control border border-line bg-surface px-2 pr-14 font-mono text-mini text-ink placeholder:text-faint focus:border-brand focus:outline-none"
          />
          <button
            type="button"
            onClick={() => setReveal((value) => !value)}
            className="absolute right-1 top-1 h-6 rounded-chip px-2 text-caption text-muted hover:bg-surface-hover hover:text-ink"
          >
            {reveal ? '隐藏' : '显示'}
          </button>
        </span>
      </label>
      {touched && !keyValid ? (
        <p className="mt-1 text-caption text-danger">
          {apiKey.trim() ? 'Key 至少 8 位且不能包含空格' : '请粘贴从开放平台获取的 Key'}
        </p>
      ) : null}

      <details className="mt-3">
        <summary className="cursor-pointer text-caption text-muted">高级：指定环境变量名</summary>
        <label className="mt-2 block text-mini">
          <span className="mb-1 block font-medium text-ink-soft">环境变量名（env:NAME）</span>
          <input
            value={envName}
            onChange={(event) => setEnvName(event.target.value.trim().toUpperCase())}
            aria-label="环境变量名"
            placeholder="DEEPSEEK_API_KEY"
            className="h-8 w-full rounded-control border border-line bg-surface px-2 font-mono text-mini text-ink placeholder:text-faint focus:border-brand focus:outline-none"
          />
        </label>
        {!envValid ? (
          <p className="mt-1 text-caption text-danger">
            仅支持大写字母、数字与下划线，且以字母开头
          </p>
        ) : null}
        <p className="mt-1 text-caption text-faint">
          默认使用 {DEFAULT_ENV_NAME[model.provider] ?? `${model.provider.toUpperCase()}_API_KEY`}
          ；改了名字之后，请确保读取 Key 的地方用的是同一个名字。
        </p>
      </details>

      {error ? <p className="mt-1.5 text-caption text-danger">{error}</p> : null}
      <p className="mt-2 text-caption text-faint">
        Key 只保存在这台电脑上，界面上只显示掩码；不会上传到任何第三方。
      </p>
    </Modal>
  );
}
