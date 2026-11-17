/**
 * 「设置接口」弹窗：填供应商的 Base URL 与模型名。
 *
 * 为什么需要这个入口：WorkBuddy 这类模型没有公共默认地址（各家账号拿到的地址不一样），
 * 只给「添加 Key」的话，用户粘完 Key 还是不通，却看不出差在哪。这里把两件事分开：
 * 先把地址填对，再填 Key。
 *
 * 只登记到后端（POST /models），不存任何明文；Key 仍然走「添加 Key」那条独立通道。
 */
import { useState } from 'react';
import { providerLabel } from '../../../shared/config/providers';
import { Button, Modal } from '../../../shared/ui/primitives';
import type { ModelOut } from '../api';

const inputClass =
  'h-8 w-full rounded-control border border-line bg-surface px-2 font-mono text-mini text-ink placeholder:text-faint focus:border-brand focus:outline-none';

/** 只接受 http(s) 绝对地址：填成 `api.xxx.com/v1` 的话后端会直接拒绝。 */
function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

export function EndpointModal({
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
  onSave: (baseUrl: string, modelName: string) => void;
}) {
  const [baseUrl, setBaseUrl] = useState(model.base_url ?? '');
  const [modelName, setModelName] = useState(model.model ?? '');
  const [touched, setTouched] = useState(false);

  const trimmedUrl = baseUrl.trim().replace(/\/+$/, '');
  const urlValid = isValidUrl(trimmedUrl);
  const canSave = urlValid && !saving;
  const name = providerLabel(model.provider);

  return (
    <Modal
      title={`设置 ${name} 的接口`}
      size="md"
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
              if (canSave) onSave(trimmedUrl, modelName.trim());
            }}
          >
            保存
          </Button>
        </>
      }
    >
      <div className="flex items-start gap-2 rounded-control border border-brand-line bg-brand-soft px-2.5 py-2 text-caption text-brand-strong">
        <span className="min-w-0">
          把供应商给你的接口地址贴在这里。一般以 <code>/v1</code> 结尾， 不用自己加{' '}
          <code>/chat/completions</code>，程序会自动接上。
        </span>
      </div>

      <label className="mt-3 block text-mini">
        <span className="mb-1 block font-medium text-ink-soft">接口地址</span>
        <input
          value={baseUrl}
          onChange={(event) => setBaseUrl(event.target.value)}
          onBlur={() => setTouched(true)}
          autoComplete="off"
          spellCheck={false}
          aria-label="接口地址"
          placeholder="https://api.example.com/v1"
          className={inputClass}
        />
      </label>
      {touched && !urlValid ? (
        <p className="mt-1 text-caption text-danger">
          {baseUrl.trim() ? '要以 http:// 或 https:// 开头' : '请粘贴接口地址'}
        </p>
      ) : null}

      <label className="mt-2.5 block text-mini">
        <span className="mb-1 block font-medium text-ink-soft">模型名</span>
        <input
          value={modelName}
          onChange={(event) => setModelName(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          aria-label="模型名"
          placeholder="workbuddy-chat"
          className={inputClass}
        />
      </label>
      <p className="mt-1 text-caption text-faint">
        不知道就先留着：报「模型不存在」时回来改成账号里给的名字即可。
      </p>

      {error ? <p className="mt-1.5 text-caption text-danger">{error}</p> : null}

      <p className="mt-2 border-t border-line pt-2 text-caption text-faint">
        保存后回列表点「测试连接」：通了再「添加 Key」。地址只存本机。
      </p>
    </Modal>
  );
}
