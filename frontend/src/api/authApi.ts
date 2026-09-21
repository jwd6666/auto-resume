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
};
