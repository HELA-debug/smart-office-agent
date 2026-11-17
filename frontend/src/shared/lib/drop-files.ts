/**
 * 拖拽落点 → File[]：把一次 drop 变成真正能上传的文件列表。
 *
 * 单独放一个模块（而不是塞在输入框组件里），是因为「拖进来的到底是什么」
 * 值得独立测：文件夹要递归、`~$` 锁文件要跳过、某些壳给不出 entry 时要回落。
 *
 * 分两步（`captureDrop` → `expandDrop`）是刻意的：
 * `dataTransfer` 只在 drop 事件的**同步执行期间**有效，一旦离开回调，`files` / `items`
 * 就可能被清空。所以抓取必须在事件里一次抓完（同步），异步的文件夹递归才能慢慢跑。
 * 以前两步揉在一个 async 函数里，靠「第一个 await 之前都是同步的」侥幸成立——
 * 谁在前面加一个 await，整套拖拽就会静默失效，而现象只是「拖进来没反应」。
 */

/** 一次拖拽最多收多少个文件：拖一个文件夹进来可能就是几百个，别把上传队列撑爆。 */
export const MAX_DROP_FILES = 50;
/** 文件夹递归深度上限：防止误拖盘符根目录时一路扫下去。 */
export const MAX_DROP_DEPTH = 8;

/** 该跳过的条目：Office 的 `~$` 临时锁文件、系统隐藏文件。 */
function isNoiseEntry(name: string): boolean {
  return name.startsWith('~$') || name.startsWith('.');
}

/** 同一个文件可能同时出现在 items 和 files 里：按名字 + 大小 + 修改时间去重。 */
function dedupe(files: File[]): File[] {
  const seen = new Set<string>();
  const out: File[] = [];
  for (const file of files) {
    const key = `${file.name}|${file.size}|${file.lastModified}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(file);
  }
  return out;
}

/** drop 事件里同步抓到的一切：文件、目录条目，以及「这次到底给了什么」的证据。 */
export interface DropCapture {
  /** 已经到手的文件（含 items.getAsFile() 与 files，去重后） */
  files: File[];
  /** 目录条目：只有它能读到文件夹里的内容，且必须趁事件还活着取 */
  entries: FileSystemEntry[];
  /** `dataTransfer.types`，用来区分「拖的是文件」还是「拖的是页面内容」 */
  types: string[];
  itemCount: number;
}

/**
 * 在 drop 回调里**同步**调用，把有效数据一次抓完。
 *
 * 三条路都要走，因为不同的壳给的字段不一样：
 * - `items[i].getAsFile()`：某些内嵌 webview / 国产内核只给这个，`files` 是空的；
 * - `items[i].webkitGetAsEntry()`：只有它能展开文件夹；
 * - `dataTransfer.files`：最通用的一条，前面两条都空时它就是全部。
 */
export function captureDrop(dataTransfer: DataTransfer | null): DropCapture {
  if (!dataTransfer) return { files: [], entries: [], types: [], itemCount: 0 };

  const files: File[] = [];
  const entries: FileSystemEntry[] = [];
  const items = Array.from(dataTransfer.items ?? []);
  for (const item of items) {
    if (item.kind !== 'file') continue;
    if (typeof item.getAsFile === 'function') {
      const direct = item.getAsFile();
      if (direct) files.push(direct);
    }
    if (typeof item.webkitGetAsEntry === 'function') {
      const entry = item.webkitGetAsEntry();
      if (entry) entries.push(entry);
    }
  }
  for (const file of Array.from(dataTransfer.files ?? [])) files.push(file);

  return {
    files: dedupe(files),
    entries,
    types: Array.from(dataTransfer.types ?? []),
    itemCount: items.length,
  };
}

function readFileEntry(entry: FileSystemFileEntry): Promise<File | null> {
  return new Promise((resolve) => {
    entry.file(
      (file) => resolve(file),
      () => resolve(null),
    );
  });
}

/**
 * 读完一个文件夹。
 *
 * `readEntries` 每次只回一批（Chrome 是 100 条），必须反复读到空为止——
 * 只读一次的话，超过一批的文件夹会被静默截断，用户会发现「拖进来少了一半」。
 */
function readDirectoryEntries(dir: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
  const reader = dir.createReader();
  const all: FileSystemEntry[] = [];
  return new Promise((resolve) => {
    const readBatch = () => {
      reader.readEntries(
        (batch) => {
          if (batch.length === 0) {
            resolve(all);
            return;
          }
          all.push(...batch);
          readBatch();
        },
        () => resolve(all),
      );
    };
    readBatch();
  });
}

async function collectFiles(entries: FileSystemEntry[], out: File[], depth: number): Promise<void> {
  for (const entry of entries) {
    if (out.length >= MAX_DROP_FILES) return;
    if (isNoiseEntry(entry.name)) continue;
    if (entry.isFile) {
      const file = await readFileEntry(entry as FileSystemFileEntry);
      if (file) out.push(file);
      continue;
    }
    if (entry.isDirectory && depth < MAX_DROP_DEPTH) {
      const children = await readDirectoryEntries(entry as FileSystemDirectoryEntry);
      await collectFiles(children, out, depth + 1);
    }
  }
}

/**
 * 把同步抓到的内容展开成文件列表：文件夹递归进去，读不出来就退回同步抓到的那批。
 *
 * 目录读取是异步的，可能失败（entry 在事件结束后失效、网络位置断连、空文件夹）。
 * 失败时**绝不能返回空**——同步抓到的 `files` 还在，那是用户真实拖进来的东西，
 * 丢掉它等于告诉他「你拖了个空气」。
 */
export async function expandDrop(capture: DropCapture): Promise<File[]> {
  if (capture.entries.length === 0) return capture.files;
  const out: File[] = [];
  await collectFiles(capture.entries, out, 0);
  return out.length > 0 ? dedupe([...out, ...capture.files]) : capture.files;
}

/** 老入口：抓取 + 展开一步到位。调用方必须在 drop 回调里**同步**调用它。 */
export async function filesFromDrop(dataTransfer: DataTransfer): Promise<File[]> {
  return expandDrop(captureDrop(dataTransfer));
}
