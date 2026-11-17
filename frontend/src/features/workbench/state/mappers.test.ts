/** 后端 DTO → 视图模型映射（P2-14 从 useWorkbench 拆出，单独覆盖分支）。 */
import { describe, expect, it } from 'vitest';
import {
  failureToError,
  normalizeRunMode,
  summarizeTitle,
  toApprovalItems,
  toHistoryMessages,
  toThreadAssets,
} from './mappers';
import type { ThreadDetailEnvelope } from '../../../shared/api/types';

function detail(patch: Record<string, unknown> = {}): ThreadDetailEnvelope {
  return {
    trace_id: 'tr_1',
    thread_id: 'th_1',
    title: '会话',
    created_at: '2026-10-24T00:00:00',
    updated_at: '2026-10-24T00:00:00',
    pinned: false,
    message_count: 0,
    artifact_count: 0,
    messages: [],
    artifacts: [],
    approvals: [],
    ...patch,
  } as ThreadDetailEnvelope;
}

describe('summarizeTitle', () => {
  it('取首行，超过 20 字截断并加省略号', () => {
    expect(summarizeTitle('写周报\n第二行')).toBe('写周报');
    expect(summarizeTitle('  ')).toBe('');
    const long = '一'.repeat(30);
    expect(summarizeTitle(long)).toBe(`${'一'.repeat(20)}…`);
  });
});

describe('normalizeRunMode', () => {
  it('只认 mock / real，其余归一为 null', () => {
    expect(normalizeRunMode('mock')).toBe('mock');
    expect(normalizeRunMode('real')).toBe('real');
    expect(normalizeRunMode('prod')).toBeNull();
    expect(normalizeRunMode(null)).toBeNull();
    expect(normalizeRunMode(undefined)).toBeNull();
  });
});

describe('toHistoryMessages', () => {
  it('过滤 run_summary 与非字符串内容，角色归一', () => {
    const messages = toHistoryMessages(
      detail({
        messages: [
          { message_id: 'm1', role: 'user', content: '你好' },
          { message_id: 'm2', role: 'assistant', content: '在的' },
          { message_id: 'm3', role: 'system', content: '系统提示' },
          { message_id: 'm4', role: 'run_summary', content: '摘要' },
          { role: 'user', content: 123 },
        ],
      }),
    );

    expect(messages.map((item) => item.role)).toEqual(['user', 'assistant', 'system']);
    // 没有 message_id 时用下标兜底
    expect(messages[0]?.id).toBe('m1');
    expect(messages.every((item) => item.streaming === false)).toBe(true);
    expect(messages[0]?.created_at).toBeTruthy();
  });

  it('messages 缺失时返回空数组', () => {
    expect(toHistoryMessages(detail({ messages: undefined }))).toEqual([]);
  });
});

describe('toThreadAssets', () => {
  it('upload 类型进 uploads，其余进 artifacts，并补默认字段', () => {
    const { artifacts, threadUploads: uploads } = toThreadAssets(
      detail({
        artifacts: [
          {
            artifact_id: 'a1',
            type: 'docx',
            filename: '周报.docx',
            size: 100,
            sha256: 'abc',
            download_url: '/d/a1',
            preview_url: '/p/a1',
          },
          {
            artifact_id: 'a2',
            type: 'upload',
            filename: '材料.txt',
            size: 10,
            extra: { chars: 42, ext: '.txt' },
          },
          { artifact_id: '', type: 'txt' },
        ],
      }),
    );

    expect(uploads).toHaveLength(1);
    expect(uploads[0]).toMatchObject({
      local_id: 'a2',
      filename: '材料.txt',
      status: 'parsed',
      chars: 42,
      ext: '.txt',
      error: null,
    });

    expect(artifacts).toHaveLength(1);
    expect(artifacts[0]).toMatchObject({
      artifact_id: 'a1',
      download_url: '/d/a1',
      preview_url: '/p/a1',
      meta_status: 'idle',
      meta: { sha256: 'abc' },
    });
  });

  it('缺 download/preview 地址时用接口拼装，缺字段走默认值', () => {
    const { artifacts } = toThreadAssets(
      detail({ artifacts: [{ artifact_id: 'a b', type: 'pdf' }] }),
    );
    expect(artifacts[0]?.filename).toBe('产物');
    expect(artifacts[0]?.size).toBe(0);
    expect(artifacts[0]?.download_url).toBe('/api/v1/artifacts/a%20b/download');
    expect(artifacts[0]?.meta).toBeNull();
  });

  it('重建会话时「识别中」不是失败：只有 media.status=failed 才标红', () => {
    const { threadUploads: uploads } = toThreadAssets(
      detail({
        uploads: [
          {
            artifact_id: 'a1',
            file_id: 'a1',
            filename: '周会截图.png',
            size: 10,
            ext: 'png',
            parsed: false,
            media: { kind: 'image', label: '图片', status: 'processing' },
          },
          {
            artifact_id: 'a2',
            file_id: 'a2',
            filename: '会议录音.m4a',
            size: 10,
            ext: 'm4a',
            parsed: false,
            media: {
              kind: 'audio',
              label: '会议录音',
              status: 'failed',
              error: '语音识别模型加载失败',
            },
          },
        ],
      }),
    );

    expect(uploads[0]).toMatchObject({
      status: 'parsed',
      media_status: 'processing',
      media_kind: 'image',
      error: null,
    });
    // 失败才带原因，卡片据此显示红色与「重试」
    expect(uploads[1]).toMatchObject({
      status: 'error',
      media_status: 'failed',
      media_error: '语音识别模型加载失败',
    });
  });
});

describe('toApprovalItems', () => {
  it('只保留已决议记录，写盘/删除标为高风险', () => {
    const items = toApprovalItems([
      {
        approval_id: 'ap1',
        thread_id: 'th_1',
        run_id: 'r1',
        tool: 'doc.generate_report',
        risk: 'high',
        policy_version: 'v1',
        payload: { to: 'a@b.c' },
        decision: 'approved',
        decided_at: '2026-10-24T01:00:00',
        created_at: '2026-10-24T00:59:00',
      },
      {
        approval_id: 'ap2',
        thread_id: 'th_1',
        run_id: null,
        tool: 'file.read',
        risk: 'medium',
        policy_version: 'v1',
        decision: 'rejected',
        created_at: '2026-10-24T00:58:00',
      },
      {
        approval_id: 'ap3',
        thread_id: 'th_1',
        run_id: null,
        tool: 'doc.generate_report',
        risk: 'high',
        policy_version: 'v1',
        decision: null,
        created_at: '2026-10-24T00:57:00',
      },
    ]);

    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({
      approval_id: 'ap1',
      risk: 'high',
      decision: 'approved',
      submitting: false,
    });
    expect(items[0]?.preview).toEqual({ to: 'a@b.c' });
    expect(items[1]).toMatchObject({ risk: 'medium', decision: 'rejected', preview: {} });
  });
});

describe('failureToError', () => {
  it('原样透传错误码/信息/可重试标记', () => {
    expect(failureToError({ code: 'MODEL_TIMEOUT', message: '超时', retryable: true })).toEqual({
      code: 'MODEL_TIMEOUT',
      message: '超时',
      retryable: true,
    });
  });
});
