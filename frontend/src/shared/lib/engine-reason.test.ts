import { describe, expect, it } from 'vitest';
import { friendlyEngineReason } from './engine-reason';

describe('friendlyEngineReason', () => {
  it('401 原始异常收成一句人话，不露 JSON / request_id / Key 尾号', () => {
    const raw =
      'deepseek: HTTP 401: {"error": {"message":"Authentication Fails, Your api key: ****7890 is invalid (request_id: d821c30d-edf3-499d-b579-41306eb03704)","type":"authentication_error"}}';
    const result = friendlyEngineReason(raw);
    expect(result).toBe('deepseek：API Key 无效或已失效');
    expect(result).not.toMatch(/7890|request_id|d821|authentication_error|\{/);
  });

  it('限流 / 断网 / 模型名错也各归一类', () => {
    expect(friendlyEngineReason('openai: HTTP 429: rate limit exceeded')).toBe(
      'openai：调用过于频繁或额度用尽',
    );
    expect(friendlyEngineReason('deepseek: connection timeout')).toBe('deepseek：连不上模型服务');
    expect(friendlyEngineReason('qwen: HTTP 404: model does not exist')).toBe('qwen：模型名不存在');
  });

  it('本来就是中文短句（model_hint）原样保留，不二次改写', () => {
    expect(friendlyEngineReason('MOCK_MODE=true 还开着')).toBe('MOCK_MODE=true 还开着');
    expect(friendlyEngineReason('deepseek: 模型返回空内容')).toBe('deepseek: 模型返回空内容');
  });

  it('空值给空串，界面上就不显示「原因：」', () => {
    expect(friendlyEngineReason('')).toBe('');
    expect(friendlyEngineReason(null)).toBe('');
    expect(friendlyEngineReason(undefined)).toBe('');
  });
});
