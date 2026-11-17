/**
 * 模型探测失败的「原因」在界面上怎么说。
 *
 * 后端 degraded_reason 存的是上游原始异常（HTTP 状态 + JSON body + request_id + Key 尾号），
 * 那是给排查用的日志，不是给用户看的文案。设置页和底栏降级提示都走这里收成一句人话，
 * 原始串留在后端日志里，界面只给「哪家 + 哪类问题」。
 */

/** 已经是中文短句（model_hint / 本地降级说明）就别二次改写。 */
function isPlainHint(text: string): boolean {
  return !/[{}]|request_id|HTTP\s*\d{3}|api[ _-]?key|timeout|connection|refused|Traceback/i.test(
    text,
  );
}

export function friendlyEngineReason(reason: string | null | undefined): string {
  const raw = (reason ?? '').trim();
  if (!raw) return '';
  if (isPlainHint(raw)) return raw.length <= 80 ? raw : `${raw.slice(0, 80)}…`;

  // 「deepseek: HTTP 401: {...}」→ 只留供应商名，后面那串全丢
  const provider = raw.split(/[：:]/)[0]?.trim() ?? '';
  const lower = raw.toLowerCase();
  let message = '模型服务暂时不可用';
  if (/401|authentication|unauthorized|invalid.*api.*key|api.*key.*invalid/.test(lower)) {
    message = 'API Key 无效或已失效';
  } else if (/429|rate.?limit|quota|too many requests/.test(lower)) {
    message = '调用过于频繁或额度用尽';
  } else if (/403|forbidden|permission/.test(lower)) {
    message = '没有权限访问该模型';
  } else if (/404|model.*not.*found|does not exist/.test(lower)) {
    message = '模型名不存在';
  } else if (/timeout|timed out|connection|network|unreachable/.test(lower)) {
    message = '连不上模型服务';
  }
  return provider ? `${provider}：${message}` : message;
}
