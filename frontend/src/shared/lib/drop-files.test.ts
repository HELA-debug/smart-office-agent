/**
 * 拖拽落点解析（filesFromDrop）。
 *
 * 守护的产品约束：用户拖什么进来都得有声——文件夹要递归进去，`~$` 锁文件
 * 不该变成素材，某些壳给不出 entry 时要回落 `files`，不能静默返回空。
 */
import { describe, expect, it } from 'vitest';
import { MAX_DROP_FILES, filesFromDrop } from './drop-files';

/** jsdom 没有 FileSystemEntry：按浏览器那两个 API 的形状造一个假的 */
function fileEntry(name: string) {
  return {
    isFile: true,
    isDirectory: false,
    name,
    file: (ok: (file: File) => void) => ok(new File(['x'], name)),
  };
}

function dirEntry(name: string, batches: unknown[][]) {
  let index = 0;
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => ({
      readEntries: (ok: (batch: unknown[]) => void) => {
        // 先取再自增：回调是同步进来的（真实 API 是异步的），
        // 在回调后面自增会永远读到同一批，直接栈溢出
        const batch = batches[index] ?? [];
        index += 1;
        ok(batch);
      },
    }),
  };
}

function dropWith(entries: unknown[], files: File[] = []): DataTransfer {
  return {
    files,
    items: entries.map((entry) => ({ kind: 'file', webkitGetAsEntry: () => entry })),
  } as unknown as DataTransfer;
}

describe('filesFromDrop', () => {
  it('拖文件夹：递归取里面的文件，跳过 ~$ 锁文件，分批也要读全', async () => {
    const folder = dirEntry('合同归档', [
      [fileEntry('a.docx'), fileEntry('~$a.docx')],
      [dirEntry('子目录', [[fileEntry('b.xlsx')]])],
      [],
    ]);

    const files = await filesFromDrop(dropWith([folder]));

    expect(files.map((file) => file.name)).toEqual(['a.docx', 'b.xlsx']);
  });

  it('拿不到 entry 的壳：回落 dataTransfer.files，而不是当成空的', async () => {
    const files = [new File(['x'], '周会截图.png')];
    const dataTransfer = { files, items: [] } as unknown as DataTransfer;

    expect(await filesFromDrop(dataTransfer)).toEqual(files);
  });

  it('entry 走通但一个文件都没取到：仍然回落 files', async () => {
    const files = [new File(['x'], '旧合同.doc')];
    const dataTransfer = { files, items: [] } as unknown as DataTransfer;

    expect((await filesFromDrop(dataTransfer)).map((file) => file.name)).toEqual(['旧合同.doc']);
  });

  it('只给 items 的壳：dataTransfer.files 是空的也要收下', async () => {
    // 某些内嵌 webview / 国产内核只实现 getAsFile()，`files` 一直是空的。
    // 只看 files 的写法在这里会直接判「没读到文件」——用户拖的是真文件。
    const file = new File(['x'], '方案.pptx');
    const dataTransfer = {
      files: [],
      items: [{ kind: 'file', getAsFile: () => file }],
      types: ['Files'],
    } as unknown as DataTransfer;

    expect((await filesFromDrop(dataTransfer)).map((item) => item.name)).toEqual(['方案.pptx']);
  });

  it('文件夹读不出来（条目在事件结束后失效）：退回同步抓到的那批，不返回空', async () => {
    const file = new File(['x'], '合同.docx');
    const broken = {
      isFile: false,
      isDirectory: true,
      name: '归档',
      createReader: () => ({
        readEntries: (_ok: unknown, fail: (error: Error) => void) => fail(new Error('invalid')),
      }),
    };
    const dataTransfer = {
      files: [file],
      items: [{ kind: 'file', webkitGetAsEntry: () => broken }],
      types: ['Files'],
    } as unknown as DataTransfer;

    expect((await filesFromDrop(dataTransfer)).map((item) => item.name)).toEqual(['合同.docx']);
  });

  it('数量按上限截断，不把上传队列一次撑爆', async () => {
    const many = Array.from({ length: MAX_DROP_FILES + 5 }, (_, i) => fileEntry(`f${i}.txt`));
    const folder = dirEntry('一堆', [many, []]);

    const files = await filesFromDrop(dropWith([folder]));

    expect(files).toHaveLength(MAX_DROP_FILES);
  });
});
