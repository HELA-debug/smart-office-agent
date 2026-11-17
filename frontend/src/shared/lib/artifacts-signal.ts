/**
 * 产物变动的广播口。
 *
 * 产物散在三个地方：产物中心（整页）、右栏的产物仓库、对话底部的交付区。
 * 「会话列表里那个 N 产物」是第四个地方——它由会话接口算出来，
 * 产物中心删完文件后它不会自己变，用户看到的就是「明明清空了还显示 3 产物」。
 *
 * 所以产物侧任何增删改都从这里喊一声，关心它的地方（工作台的会话列表）安静地
 * 重新拉一次。用模块级订阅而不是全局状态：这两边没有共享数据，
 * 只需要一个「变了」的信号，不值得引入 store。
 */
type Listener = () => void;

const listeners = new Set<Listener>();

/** 订阅产物变动，返回取消订阅的函数（给 useEffect 的 cleanup 用）。 */
export function onArtifactsChanged(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 产物被删 / 恢复 / 新增后调用一次。 */
export function notifyArtifactsChanged(): void {
  for (const listener of [...listeners]) listener();
}
