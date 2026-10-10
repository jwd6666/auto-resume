/** 后端 REST/WebSocket 客户端封装。 */
// 开发环境（Vite dev server）使用相对路径走 proxy，避免系统代理拦截 localhost 请求
// 生产环境（Electron）使用 preload 注入的绝对路径
import { authHeaders, withTokenQuery } from './common';

const isDev = location.port === '5173';
const isElectron = !!(window as any).autoresume?.apiBase;
const API_BASE = isDev ? '' : (isElectron ? (window as any).autoresume.apiBase : '');

export type TaskStatus =
  | 'idle' | 'launching' | 'awaiting_login' | 'logged_in' | 'running'
  | 'paused' | 'stopped' | 'finished' | 'error';

export interface JobFilter {
  keyword: string;
  city?: string;
  salary?: string;
  experience?: string;
  degree?: string;
  scale?: string;
  exclude_keywords: string[];
}

export interface SubTask {
  filter: JobFilter;
  limit: number;
}

export interface AIConfig {
  enabled: boolean;
  /** 独立的 AI 匹配筛选开关：判断 JD 是否匹配并跳过不匹配岗位，与生成招呼语无关 */
  match_enabled?: boolean;
  provider: string;
  api_key: string;
  base_url: string;
  model: string;
  resume: string;
  expect_jd: string;
}

export interface TaskInfo {
  id: string;
  name: string;
  status: TaskStatus;
  sub_tasks: SubTask[];
  /** 兼容老字段：单子任务情况下等价于 sub_tasks[0].filter */
  filter?: JobFilter | null;
  greetings: string[];
  interval_seconds: number;
  daily_limit: number;
  click_delay_seconds: number;
  sent_today: number;
  /** 各子任务今日已发数（与 sub_tasks 同序） */
  sub_sent_today: number[];
  current_sub_index: number;
  has_login: boolean;
  last_msg?: string | null;
  created_at: string;
  ai_config?: AIConfig | null;
  /** AI 招呼语发送成功后自动追加发送的固定图片（greet_images 目录下的文件名） */
  greet_image?: string | null;
}

export interface TaskCreatePayload {
  name: string;
  sub_tasks: SubTask[];
  greetings: string[];
  interval_seconds: number;
  daily_limit: number;
  click_delay_seconds: number;
  ai_config?: AIConfig | null;
  greet_image?: string | null;
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  list: () => http<{ items: TaskInfo[] }>('/api/tasks'),
  create: (p: TaskCreatePayload) =>
    http<TaskInfo>('/api/tasks', { method: 'POST', body: JSON.stringify(p) }),
  update: (id: string, p: TaskCreatePayload) =>
    http<TaskInfo>(`/api/tasks/${id}`, { method: 'PUT', body: JSON.stringify(p) }),
  remove: (id: string) =>
    http<{ ok: boolean }>(`/api/tasks/${id}`, { method: 'DELETE' }),
  start: (id: string) => http<TaskInfo>(`/api/tasks/${id}/start`, { method: 'POST' }),
  login: (id: string) => http<TaskInfo>(`/api/tasks/${id}/login`, { method: 'POST' }),
  pause: (id: string) => http<{ ok: boolean }>(`/api/tasks/${id}/pause`, { method: 'POST' }),
  resume: (id: string) => http<{ ok: boolean }>(`/api/tasks/${id}/resume`, { method: 'POST' }),
  stop: (id: string) => http<{ ok: boolean }>(`/api/tasks/${id}/stop`, { method: 'POST' }),
  logs: (id: string, n = 200) =>
    http<{ items: { ts: string; level: string; msg: string }[] }>(
      `/api/tasks/${id}/logs?n=${n}`
    ),
  greeted: (id: string, limit = 100) =>
    http<{ items: { job_key: string; greeted_at: string; title: string; company: string }[] }>(
      `/api/tasks/${id}/greeted?limit=${limit}`
    ),
  resetAiJudged: (id: string) =>
    http<{ ok: boolean; deleted: number }>(`/api/tasks/${id}/reset-ai-judged`, { method: 'POST' }),
  /** 上传打招呼固定图片 → 保存到后端 data/greet_images，返回文件名 */
  uploadGreetImage: async (file: File): Promise<{ filename: string }> => {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${API_BASE}/api/tasks/upload-greet-image`, {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  /** 图片预览 URL：<img> 无法携带请求头，令牌走查询参数（与头像预览一致） */
  greetImagePreviewUrl(filename: string): string {
    const base = isDev ? 'http://127.0.0.1:8765' : API_BASE;
    return withTokenQuery(`${base}/api/tasks/greet-image/${encodeURIComponent(filename)}`);
  },
};

export function openTaskWS(taskId: string, onMessage: (m: any) => void): WebSocket {
  const wsUrl = withTokenQuery(API_BASE.replace(/^http/, 'ws') + `/api/tasks/ws/${taskId}`);
  const ws = new WebSocket(wsUrl);
  ws.onmessage = (ev) => {
    try { onMessage(JSON.parse(ev.data)); } catch { /* ignore */ }
  };
  return ws;
}
