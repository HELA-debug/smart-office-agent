import { useState } from 'react';
import { errorMessage } from '../../../shared/lib/api';
import { detectPlatform, isStandalone, PLATFORM_LABEL } from '../../../shared/lib/desktop';
import { useTheme } from '../../../shared/lib/theme';
import { Checkbox } from '../../../shared/ui/Checkbox';
import { IconCheck, IconCopy, IconMail } from '../../../shared/ui/Icons';
import { Button } from '../../../shared/ui/primitives';
import { settingsApi } from '../api';
import { SettingSection } from './SettingRows';
import type { FeedbackKind, FeedbackOut } from '../api';

/**
 * 设置 → 关于 → 意见反馈。
 *
 * 链路是「本机存档 + 用户自己的邮件客户端」：
 *   1. 点发送 → 后端把内容写进 data/feedback/feedback.jsonl（不联网、不上云）；
 *   2. 同时拼好标题与正文，邮箱配了就直接调起系统邮件程序（mailto）；
 *   3. 没装邮件程序 / 邮箱还没配 → 「复制内容」，粘到任何地方都能发。
 *
 * 这样即使将来换掉收件邮箱、或者换一种投递方式（MCP、表单），前端只认
 * `target / subject / body` 三个字段，界面不用改。
 */

const KINDS: { value: FeedbackKind; label: string; hint: string }[] = [
  { value: 'bug', label: '遇到问题', hint: '哪一步不对、报了什么错' },
  { value: 'idea', label: '想要新功能', hint: '希望它还能帮我做什么' },
  { value: 'other', label: '其他', hint: '想法、吐槽、随便说说' },
];

const MAX_MESSAGE = 1500;

export function FeedbackCard() {
  const theme = useTheme();
  const [kind, setKind] = useState<FeedbackKind>('bug');
  const [message, setMessage] = useState('');
  const [contact, setContact] = useState('');
  const [includeDiagnostics, setIncludeDiagnostics] = useState(true);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<FeedbackOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const trimmed = message.trim();
  const canSend = trimmed.length > 0 && !sending;

  const clientInfo = (): Record<string, string> => ({
    window: isStandalone() ? '独立窗口（桌面端）' : '浏览器标签页',
    platform: PLATFORM_LABEL[detectPlatform()],
    screen: `${window.screen.width}×${window.screen.height}`,
    theme: theme === 'dark' ? '深色' : '浅色',
  });

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    setError(null);
    setCopied(false);
    try {
      const response = await settingsApi.sendFeedback({
        kind,
        message: trimmed,
        contact: contact.trim(),
        include_diagnostics: includeDiagnostics,
        client: clientInfo(),
      });
      setResult(response.data);
      setMessage('');
      // 配了收件邮箱：直接调起系统邮件程序，用户点一下「发送」就完成
      if (response.data.mailto) {
        window.location.href = response.data.mailto;
      }
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSending(false);
    }
  };

  const copy = async () => {
    if (!result) return;
    const text = `主题：${result.subject}\n\n${result.body}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setError('复制失败：浏览器没给剪贴板权限，可以手动选中正文复制。');
    }
  };

  const current = KINDS.find((item) => item.value === kind) ?? KINDS[0];

  return (
    <SettingSection
      title="意见反馈"
      description="哪儿不好用、想要什么功能，写在这里。内容只从这台电脑发出去，不上传任何服务器。"
    >
      <div className="space-y-3 px-5 py-3.5">
        <div className="flex flex-wrap gap-1.5">
          {KINDS.map((item) => {
            const active = item.value === kind;
            return (
              <button
                key={item.value}
                type="button"
                aria-pressed={active}
                onClick={() => setKind(item.value)}
                className={`rounded-full border px-3 py-1 text-mini font-medium transition-colors ${
                  active
                    ? 'border-brand-line bg-brand-soft text-brand-strong'
                    : 'border-line bg-surface text-muted hover:bg-surface-hover hover:text-ink'
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>

        <div>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value.slice(0, MAX_MESSAGE))}
            rows={4}
            aria-label="反馈内容"
            placeholder={
              kind === 'bug'
                ? '例：导出周报后，表格里的「合计」行没有加粗，打印出来看不清。'
                : kind === 'idea'
                  ? '例：希望周报能自动带上上周的对比数据。'
                  : '想说什么都可以，写得越具体越好。'
            }
            className="w-full resize-y rounded-control border border-line bg-surface px-3 py-2 text-mini leading-relaxed text-ink placeholder:text-faint focus:border-brand focus:outline-none"
          />
          <div className="mt-1 flex items-center justify-between text-[calc(11px*var(--font-scale))] text-faint">
            <span>{current?.hint}</span>
            <span>
              {trimmed.length}/{MAX_MESSAGE}
            </span>
          </div>
        </div>

        <input
          value={contact}
          onChange={(event) => setContact(event.target.value.slice(0, 120))}
          aria-label="联系方式"
          placeholder="想收到回复就留个邮箱或微信（可以不填）"
          className="h-8 w-full rounded-control border border-line bg-surface px-2.5 text-mini text-ink placeholder:text-faint focus:border-brand focus:outline-none"
        />

        <label
          htmlFor="feedback-diagnostics"
          className="flex items-start gap-2 text-caption leading-relaxed text-muted"
        >
          <Checkbox
            id="feedback-diagnostics"
            checked={includeDiagnostics}
            onChange={setIncludeDiagnostics}
            label="附带环境信息"
            size="sm"
            className="mt-0.5"
          />
          <span>
            附带版本、运行模式、窗口形态这些环境信息（只用于定位问题，不包含你的文档内容）
          </span>
        </label>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            disabled={!canSend}
            loading={sending}
            onClick={() => void send()}
            leading={!sending ? <IconMail size={13} /> : undefined}
          >
            {sending ? '正在准备…' : '发送反馈'}
          </Button>
          {result ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void copy()}
              leading={copied ? <IconCheck size={13} /> : <IconCopy size={13} />}
            >
              {copied ? '已复制' : '复制内容'}
            </Button>
          ) : null}
          <span className="text-[calc(11px*var(--font-scale))] text-faint">
            {result?.target
              ? `会打开你的邮件程序，收件人是 ${result.target}`
              : '只保存在这台电脑上，可以复制后自己发给开发者'}
          </span>
        </div>

        {result ? (
          <p className="flex items-start gap-1.5 rounded-control bg-ok-soft px-2.5 py-2 text-caption leading-relaxed text-ok">
            <IconCheck size={12} className="mt-0.5 shrink-0" />
            <span>
              已存到本机：{result.saved_path}
              {result.target
                ? '。邮件已经准备好，在邮件窗口里点「发送」就完成了；没弹出邮件窗口就点「复制内容」。'
                : '。点「复制内容」，粘贴到邮件或聊天里发给开发者即可。'}
              {result.truncated ? '（内容较长，邮件里只放了前面一段，全文在本机存档里）' : ''}
            </span>
          </p>
        ) : null}

        {error ? (
          <p className="rounded-control bg-danger-soft px-2.5 py-2 text-caption text-danger">
            {error}
          </p>
        ) : null}
      </div>
    </SettingSection>
  );
}
