/** 提示词增强接口（输入框右侧星形按钮，正式 /api/v1）。 */
import { asRecord, requestV1 } from '../../../shared/lib/api';
import type { ApiResponse } from '../../../shared/types/api';

export interface EnhancePromptInput {
  /** 输入框里的原文；后端按它改写，不改库、不改会话 */
  text: string;
  /** 期望产物格式，只作为改写提示（例如补上「输出 Word 文档」的结构要求） */
  outputFormat?: string | null;
}

export interface EnhancedPrompt {
  text: string;
  /** model：模型改写；rules：没配模型/模型失败时按本地规则补全 */
  source: 'model' | 'rules';
  model: string;
  /** 给用户的一句说明（本地补全时解释为什么） */
  note: string;
}

export const promptsApi = {
  async enhance(
    input: EnhancePromptInput,
    signal?: AbortSignal,
  ): Promise<ApiResponse<EnhancedPrompt>> {
    const response = await requestV1<unknown>('/prompts/enhance', 'POST', {
      body: JSON.stringify({
        text: input.text,
        ...(input.outputFormat ? { output_format: input.outputFormat } : {}),
      }),
      signal,
      // 模型改写比普通读写慢：默认 15s 太紧，用户会以为按钮坏了
      timeoutMs: 30_000,
    });
    const record = asRecord(response.data) ?? {};
    return {
      data: {
        text: typeof record.text === 'string' ? record.text : '',
        source: record.source === 'model' ? 'model' : 'rules',
        model: typeof record.model === 'string' ? record.model : '',
        note: typeof record.note === 'string' ? record.note : '',
      },
      traceId: response.traceId,
    };
  },
};
