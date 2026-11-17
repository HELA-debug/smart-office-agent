/**
 * 记住「最近打开的会话」。
 *
 * 需求：是否新建会话必须完全由用户决定。工作台是路由页面，去产物中心/设置页再回来会
 * 卸载重挂、组件内 state 全部丢失；如果不记住 threadId，用户每次回首页都会看到一个空
 * 会话，发消息时又偷偷建一个新线程 —— 观感就是「返回首页必定新会话」。
 *
 * 所以把当前 threadId 落到 localStorage，回到首页时恢复它；只有用户点「新建会话」
 * （或删掉了当前会话）才清掉这条记录。
 */
const KEY = 'oa:last-thread';

export function readLastThreadId(): string | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value && value.trim() ? value.trim() : null;
  } catch {
    return null; // 隐私模式 / 禁用存储：当作没有记录
  }
}

export function writeLastThreadId(threadId: string): void {
  try {
    window.localStorage.setItem(KEY, threadId);
  } catch {
    /* 存不下就算了，不影响主流程 */
  }
}

export function clearLastThreadId(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* 忽略 */
  }
}
