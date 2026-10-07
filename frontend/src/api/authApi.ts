/** 云端鉴权 API（经本地 sidecar 转发到云端服务器）。 */
import { authHeaders } from './common';

const isDev = location.port === '5173';
const isElectron = !!(window as any).autoresume?.apiBase;
const API_BASE = isDev ? '' : (isElectron ? (window as any).autoresume.apiBase : '');

export interface AuthUser {
  id: number;
  account: string;
  nickname: string;
  role: string;
  status: string;
}

export interface AuthStatus {
  status: 'not_logged_in' | 'active' | 'banned';
  user: AuthUser | null;
  ban_reason: string | null;
  cloud_server: string;
}

/** 额度用量：按功能来源的明细项（label 由后端映射，如 自动打招呼/简历对话） */
export interface UsageSourceItem {
  source: string;
  label: string;
  tokens: number;
  requests: number;
}

export interface UsageStats {
  day: string;
  today_tokens: number;
  today_requests: number;
  month_tokens: number;
  month_requests: number;
  daily_quota: number;
  remaining_today: number;
  today_by_source: UsageSourceItem[];
  month_by_source: UsageSourceItem[];
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try { detail = (await res.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

export const authApi = {
  status: () => http<AuthStatus>('/api/auth/status'),
  login: (account: string, password: string) =>
    http<AuthStatus>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ account, password }),
    }),
  logout: () => http<AuthStatus>('/api/auth/logout', { method: 'POST' }),
  changePassword: (oldPassword: string, newPassword: string) =>
    http<{ ok: boolean; message: string }>('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    }),
  cloudModels: () => http<any[]>('/api/auth/cloud-models'),
  cloudActivate: (templateId: number) =>
    http<{ ok: boolean; provider: string }>('/api/auth/cloud-activate', {
      method: 'POST',
      body: JSON.stringify({ template_id: templateId }),
    }),
  usage: () => http<UsageStats>('/api/auth/usage'),
};
