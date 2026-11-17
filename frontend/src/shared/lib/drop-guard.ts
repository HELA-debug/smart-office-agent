/**
 * 窗口级拖拽兜底：把文件拖到「输入框以外」的地方，别让浏览器把整个应用换成那个文件。
 *
 * 浏览器（含桌面端的 webview）默认行为是「drop 就导航到该文件 / 直接下载」。
 * 以前只有输入框那一小块 preventDefault，于是拖偏一点、落到左栏或对话区，
 * 页面就直接跳走 / 白屏——用户看到的就是「拖不进去，还把应用拖没了」。
 *
 * 这里做两件事，都只在拖的是**文件**时才生效：
 * 1. `dragover` 一律放行（不 preventDefault 的话浏览器根本不派发 drop）；
 * 2. `drop` 一律 preventDefault 拦住导航；不是输入框自己接住的，就转成一个窗口事件，
 *    交给输入框去收（拖到哪儿都能加素材）。
 *
 * 拖的是**选中的文字**时什么都不做：在输入框里拖一段话到另一个位置是正常编辑行为，
 * 拦住它等于把文字拖拽编辑弄坏。
 */

/** 窗口事件名：别人接住（已 preventDefault）就不会发出来。 */
export const DROP_FILES_EVENT = 'office-agent:drop-files';

export interface DropFilesDetail {
  dataTransfer: DataTransfer;
}

function carriesFiles(dataTransfer: DataTransfer | null): boolean {
  if (!dataTransfer) return false;
  return Array.from(dataTransfer.types ?? []).includes('Files');
}

/**
 * 装上兜底，返回卸载函数（测试里要能卸干净，免得串到下一条）。
 */
export function installDropGuard(target: Document | Window = window): () => void {
  // dragenter 与 dragover 都要放行：有些内核只认 dragenter 上的 preventDefault，
  // 漏了它 drop 会照常触发，但 dataTransfer 里空着——用户看到的就是
  // 「拖进来了，却提示没读到文件」。
  const onDragEnter = (event: DragEvent) => {
    if (carriesFiles(event.dataTransfer)) event.preventDefault();
  };

  const onDragOver = (event: DragEvent) => {
    // 不拦文字拖拽：那只会在应用内部挪动选区，跟「拖文件进来」不是一件事
    if (carriesFiles(event.dataTransfer)) event.preventDefault();
  };

  const onDrop = (event: DragEvent) => {
    if (!carriesFiles(event.dataTransfer)) return;
    // 先看有没有人接住：输入框已经处理过的 drop，不能再走一遍，
    // 否则同一批文件会被上传两次（一次它自己收，一次从窗口事件转回来）
    const handled = event.defaultPrevented;
    event.preventDefault();
    if (handled || !event.dataTransfer) return;
    window.dispatchEvent(
      new CustomEvent<DropFilesDetail>(DROP_FILES_EVENT, {
        detail: { dataTransfer: event.dataTransfer },
      }),
    );
  };

  target.addEventListener('dragenter', onDragEnter as EventListener);
  target.addEventListener('dragover', onDragOver as EventListener);
  target.addEventListener('drop', onDrop as EventListener);
  return () => {
    target.removeEventListener('dragenter', onDragEnter as EventListener);
    target.removeEventListener('dragover', onDragOver as EventListener);
    target.removeEventListener('drop', onDrop as EventListener);
  };
}
