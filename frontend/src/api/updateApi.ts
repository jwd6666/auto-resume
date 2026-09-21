/** 更新检查 API（本地 sidecar）。 */
import { authHeaders } from './common';

const isDev = location.port === '5173';
const isElectron = !!(window as any).autoresume?.apiBase;
const API_BASE = isDev ? '' : (isElectron ? (window as any).autoresume.apiBase : '');

export interface UpdateInfo {
  version: string;
  notes: string;
  download_url: string;
  force: boolean;
  published_at?: string | null;
}

export interface UpdateStatus {
  current_version: string;
  latest: UpdateInfo | null;
  update_available: boolean;
  force: boolean;
  prompt_enabled: boolean;
  skipped_version: string | null;
  should_prompt: boolean;
  last_checked_at: string | null;
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export const updateApi = {
  check: () => http<UpdateStatus>('/api/updates/check'),
  checkNow: () => http<UpdateStatus>('/api/updates/check-now', { method: 'POST' }),
  setPromptEnabled: (enabled: boolean) =>
    http<{ ok: boolean; settings: { prompt_enabled: boolean; skipped_version: string | null } }>(
      '/api/updates/settings',
      { method: 'PUT', body: JSON.stringify({ prompt_enabled: enabled }) },
    ),
  skipVersion: (version: string) =>
    http<{ ok: boolean; settings: { prompt_enabled: boolean; skipped_version: string | null } }>(
      '/api/updates/settings',
      { method: 'PUT', body: JSON.stringify({ skip_version: version }) },
    ),
};

/** 用系统浏览器打开更新下载外链（Electron 走 IPC，浏览器开发期直接 window.open） */
export function openDownloadUrl(url: string): void {
  const bridge = (window as any).autoresume;
  if (bridge?.openExternal) {
    bridge.openExternal(url);
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}
