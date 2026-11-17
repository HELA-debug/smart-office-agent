/**
 * 会话导出：复制 Markdown、下载 .md。
 *
 * 曾经这里还有「分享到微信 / 企业微信 / QQ / 钉钉 / 腾讯文档」五个渠道加一个「复制链接」。
 * 全删了：网页端没有一家提供「一键把内容投递到指定会话」的公开能力（要么要企业应用与密钥，
 * 要么要分享 SDK 与域名认证）；而「复制链接」更没意义——会话在前端是本地状态，
 * 应用里也没有 /threads/:id 这条路由，别人打开链接只会落到首页。留着就是五个点了没反应的假按钮。
 *
 * 现在只保留两种真的能交付出去的动作：复制正文、存成 .md 文件。
 */

/** 复制到剪贴板；不安全上下文（http 非 localhost）没有 clipboard API，退回 execCommand。 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // 继续走退路
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.top = '-1000px';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

export interface ExportDocMeta {
  title: string;
  updatedAt?: string;
  messageCount?: number;
  artifactCount?: number;
}

/** 导出成 .md：给对方一份能离线看、也能再编辑的会话摘要。 */
export function buildThreadMarkdown(meta: ExportDocMeta): string {
  const lines = [`# ${meta.title || '未命名会话'}`, ''];
  if (meta.updatedAt) lines.push(`- 最近更新：${meta.updatedAt}`);
  if (typeof meta.messageCount === 'number') lines.push(`- 消息数：${meta.messageCount}`);
  if (typeof meta.artifactCount === 'number' && meta.artifactCount > 0) {
    lines.push(`- 产物数：${meta.artifactCount}`);
  }
  lines.push('', '---', '', '由 Office Agent 导出。');
  return lines.join('\n');
}

/** 触发浏览器下载（Blob → a[download]），不上传、不联网。 */
export function downloadTextFile(filename: string, content: string, mime = 'text/markdown') {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // 给浏览器一点时间取数据再回收，立刻 revoke 在部分浏览器里会下到空文件
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** 文件名里不能出现的字符替换掉，避免下载被浏览器改名成 download(1).md */
export function safeFilename(name: string): string {
  const cleaned = name
    .replace(/[\\/:*?"<>|]+/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 40);
  return cleaned || '会话';
}
