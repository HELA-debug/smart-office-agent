/**
 * 后台任务：用户切走会话（或新开一个会话）时，正在跑的任务不中断，转到这里继续执行。
 *
 * 只在本机前端保存运行态：SSE 连接留在页面里继续消费事件，
 * 所以「多任务并行」= 多个流同时在线，而不是后端排队。
 * 刷新页面会丢失这些后台流（后端会继续把这一轮跑完，历史仍可在会话里看到）。
 */
import { useSyncExternalStore } from 'react';

export interface BackgroundTask {
  /** 前端流标识（不是 run_id：run.started 之前就要能显示） */
  key: string;
  threadId: string;
  threadTitle: string;
  /** 一句话任务描述（首条消息摘要） */
  label: string;
  runId: string | null;
  startedAt: number;
  status: 'running' | 'waiting_approval';
}

let tasks: BackgroundTask[] = [];
const listeners = new Set<() => void>();

function publish(next: BackgroundTask[]) {
  tasks = next;
  listeners.forEach((listener) => listener());
}

export function listBackgroundTasks(): BackgroundTask[] {
  return tasks;
}

export function subscribeBackgroundTasks(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getBackgroundTask(key: string): BackgroundTask | undefined {
  return tasks.find((task) => task.key === key);
}

export function upsertBackgroundTask(task: BackgroundTask): void {
  const exists = tasks.some((item) => item.key === task.key);
  publish(
    exists
      ? tasks.map((item) => (item.key === task.key ? { ...item, ...task } : item))
      : [...tasks, task],
  );
}

export function patchBackgroundTask(key: string, patch: Partial<BackgroundTask>): void {
  if (!tasks.some((task) => task.key === key)) return;
  publish(tasks.map((task) => (task.key === key ? { ...task, ...patch } : task)));
}

export function removeBackgroundTask(key: string): void {
  if (!tasks.some((task) => task.key === key)) return;
  publish(tasks.filter((task) => task.key !== key));
}

/** 仅用于测试：清空模块级状态。 */
export function resetBackgroundTasks(): void {
  publish([]);
}

export function useBackgroundTasks(): BackgroundTask[] {
  return useSyncExternalStore(subscribeBackgroundTasks, listBackgroundTasks, listBackgroundTasks);
}
