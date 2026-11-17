import { fireEvent } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { DROP_FILES_EVENT, installDropGuard, type DropFilesDetail } from './drop-guard';

/**
 * 窗口兜底：文件拖到输入框以外时，不能让浏览器把应用换成一个文件。
 *
 * 这几条断言的都是「浏览器默认行为有没有被拦住」——`fireEvent` 的返回值就是
 * `!event.defaultPrevented`，所以 `false` 才是我们要的结果。
 */

let uninstall: (() => void) | null = null;

function setup() {
  uninstall = installDropGuard(document);
  const received: DataTransfer[] = [];
  const onDrop = (event: Event) => {
    received.push((event as CustomEvent<DropFilesDetail>).detail.dataTransfer);
  };
  window.addEventListener(DROP_FILES_EVENT, onDrop);
  return {
    received,
    cleanup: () => window.removeEventListener(DROP_FILES_EVENT, onDrop),
  };
}

afterEach(() => {
  uninstall?.();
  uninstall = null;
});

describe('窗口级拖拽兜底', () => {
  it('拖文件时拦住 dragover：不拦浏览器根本不会派发 drop', () => {
    setup();
    const notPrevented = fireEvent.dragOver(document, { dataTransfer: { types: ['Files'] } });
    expect(notPrevented).toBe(false);
  });

  it('落在输入框以外的 drop：拦住导航，并转成窗口事件交给输入框', () => {
    const { received, cleanup } = setup();
    const file = new File(['x'], '周会截图.png', { type: 'image/png' });

    const notPrevented = fireEvent.drop(document, {
      dataTransfer: { files: [file], types: ['Files'] },
    });

    expect(notPrevented).toBe(false);
    expect(received).toHaveLength(1);
    cleanup();
  });

  it('输入框已经接住的 drop 不再转一次：否则同一批文件会被传两遍', () => {
    const { received, cleanup } = setup();
    const zone = document.createElement('div');
    document.body.append(zone);
    // 输入框的 onDrop 第一行就是 preventDefault
    zone.addEventListener('drop', (event) => event.preventDefault());

    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(['x'], 'a.docx')], types: ['Files'] },
    });

    expect(received).toHaveLength(0);
    zone.remove();
    cleanup();
  });

  it('在应用内拖一段选中的文字：一句都不拦，正常编辑不能让路', () => {
    const { received, cleanup } = setup();

    expect(fireEvent.dragOver(document, { dataTransfer: { types: ['text/plain'] } })).toBe(true);
    expect(
      fireEvent.drop(document, { dataTransfer: { types: ['text/plain'], getData: () => '' } }),
    ).toBe(true);
    expect(received).toHaveLength(0);
    cleanup();
  });

  it('卸载之后不再介入', () => {
    const { received, cleanup } = setup();
    uninstall?.();
    uninstall = null;

    fireEvent.drop(document, {
      dataTransfer: { files: [new File(['x'], 'a.docx')], types: ['Files'] },
    });

    expect(received).toHaveLength(0);
    cleanup();
  });
});
