/**
 * 把服务端文件存到本机。
 *
 * 为什么不直接用 `<a href download>` 或 `window.open(url)`：
 *   - `window.open` 指向「附件」地址会顺手留下一个空白标签页；连着点几次，
 *     浏览器就把后面的当成弹窗拦掉——用户看到的现象正是「第二次点击没反应」；
 *   - 直接 `href` 走浏览器自己的下载通道，同一地址第二次点击还能不能落盘，
 *     取决于各家的缓存与去重策略（Chrome / Edge / 装了 PWA 的窗口各不相同），
 *     我们控制不了，也没法给用户反馈。
 *
 * 现在每次点击都自己取一份 blob，再造一个**全新的** objectURL 点一下：
 * 对浏览器来说每次都是一个新文件，点几次都能落盘；objectURL 用完立刻回收，
 * 不会把整份文件一直挂在内存里，也不会出现「第一次能用，第二次指向已失效地址」。
 */
export async function fetchRemoteFile(
  url: string,
  options: { signal?: AbortSignal } = {},
): Promise<Blob> {
  const response = await fetch(url, {
    // 产物是同地址重复下载：不吃缓存，才能保证每次拿到的都是完整的这一份
    cache: 'no-store',
    credentials: 'same-origin',
    signal: options.signal,
  });
  if (!response.ok) {
    throw new Error(`下载失败（HTTP ${response.status}）`);
  }
  return response.blob();
}

export async function saveRemoteFile(
  url: string,
  filename: string,
  options: { signal?: AbortSignal } = {},
): Promise<void> {
  const blob = await fetchRemoteFile(url, options);
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = 'noopener';
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // 立刻 revoke 在部分浏览器里会下到空文件；一秒后回收，内存也不会长期占着
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
