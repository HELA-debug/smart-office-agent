/**
 * 任务队列（排队中）的 reducer 规则。
 *
 * 这里只测状态怎么变：什么时候把素材从输入区搬进队列、什么时候搬回来、
 * 换会话/删会话时队列该不该跟着走。真正的「跑完自动接着执行」在
 * useWorkbench.test.ts 里用假流驱动。
 */
import { describe, expect, it } from 'vitest';
import { createInitialState, workbenchReducer } from './workbench';
import type { QueuedMessage, UploadItem, WorkbenchAction, WorkbenchState } from './workbench';

const AT = '2026-10-25T10:00:00.000Z';

function upload(localId: string, fileId?: string): UploadItem {
  return {
    local_id: localId,
    filename: `${localId}.docx`,
    size: 1024,
    status: fileId ? 'parsed' : 'staged',
    ...(fileId ? { file_id: fileId } : {}),
    error: null,
  };
}

function queued(id: string, uploads: UploadItem[] = [], threadId = 'th_1'): QueuedMessage {
  return {
    id,
    threadId,
    text: `任务 ${id}`,
    uploads,
    created_at: AT,
  };
}

function dispatch(state: WorkbenchState, action: WorkbenchAction): WorkbenchState {
  return workbenchReducer(state, action);
}

describe('队列 reducer', () => {
  it('入队：任务进队列，它的素材同时从输入区摘走', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'upload/start', item: upload('u1') });
    state = dispatch(state, { type: 'upload/start', item: upload('u2') });

    state = dispatch(state, { type: 'queue/add', item: queued('q1', [upload('u1')]) });

    expect(state.queue.map((item) => item.id)).toEqual(['q1']);
    // u1 跟着任务走了，u2 还留在输入区等下一条消息
    expect(state.uploads.map((item) => item.local_id)).toEqual(['u2']);
  });

  it('入队会解除「停止」造成的暂停：用户又写了一条，说明他想让它跑', () => {
    let state = dispatch(createInitialState(), { type: 'queue/pause' });
    expect(state.queuePaused).toBe(true);

    state = dispatch(state, { type: 'queue/add', item: queued('q1') });
    expect(state.queuePaused).toBe(false);
  });

  it('删除：只摘掉那一条，顺序不乱', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'queue/add', item: queued('q1') });
    state = dispatch(state, { type: 'queue/add', item: queued('q2') });
    state = dispatch(state, { type: 'queue/add', item: queued('q3') });

    state = dispatch(state, { type: 'queue/remove', id: 'q2' });
    expect(state.queue.map((item) => item.id)).toEqual(['q1', 'q3']);
  });

  it('编辑：素材还回输入区，重复的不会挂两份', () => {
    let state = createInitialState();
    state = dispatch(state, {
      type: 'queue/add',
      item: queued('q1', [upload('u1'), upload('u2')]),
    });
    expect(state.uploads).toHaveLength(0);

    state = dispatch(state, { type: 'queue/returnUploads', uploads: [upload('u1')] });
    state = dispatch(state, { type: 'queue/returnUploads', uploads: [upload('u1'), upload('u2')] });

    expect(state.uploads.map((item) => item.local_id)).toEqual(['u1', 'u2']);
  });

  it('暂停 / 继续', () => {
    let state = dispatch(createInitialState(), { type: 'queue/pause' });
    expect(state.queuePaused).toBe(true);
    state = dispatch(state, { type: 'queue/resume' });
    expect(state.queuePaused).toBe(false);
  });

  it('优先执行：挪到队首并解除暂停，其余顺序不变', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'queue/add', item: queued('q1') });
    state = dispatch(state, { type: 'queue/add', item: queued('q2') });
    state = dispatch(state, { type: 'queue/add', item: queued('q3') });
    state = dispatch(state, { type: 'queue/pause' });

    state = dispatch(state, { type: 'queue/promote', id: 'q2' });
    // 出队取「本会话最早的一条」，排第一 = 下一个就轮到它
    expect(state.queue.map((item) => item.id)).toEqual(['q2', 'q1', 'q3']);
    expect(state.queuePaused).toBe(false);
  });

  it('优先执行：id 已经不在队列里时什么都不改（连点两下不会打乱顺序）', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'queue/add', item: queued('q1') });
    state = dispatch(state, { type: 'queue/pause' });

    const next = dispatch(state, { type: 'queue/promote', id: 'q_missing' });
    expect(next.queue.map((item) => item.id)).toEqual(['q1']);
    expect(next.queuePaused).toBe(true);
  });

  it('换会话不丢队列：任务记着自己的会话，切回去还能接着跑', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'queue/add', item: queued('q1') });

    state = dispatch(state, { type: 'thread/new' });
    expect(state.queue.map((item) => item.id)).toEqual(['q1']);

    state = dispatch(state, {
      type: 'thread/selected',
      threadId: 'th_2',
      title: '另一个会话',
      history: [],
    });
    expect(state.queue.map((item) => item.id)).toEqual(['q1']);
  });

  it('会话被删：它的排队任务一起清掉，别的会话的不动', () => {
    let state = createInitialState();
    state = dispatch(state, { type: 'queue/add', item: queued('q1', [], 'th_1') });
    state = dispatch(state, { type: 'queue/add', item: queued('q2', [], 'th_2') });

    state = dispatch(state, { type: 'sessions/removed', threadId: 'th_1' });
    expect(state.queue.map((item) => item.id)).toEqual(['q2']);
  });
});
