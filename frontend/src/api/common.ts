/** 公共请求辅助：本地 sidecar 访问令牌。
 *
 * Electron（开发/生产）下由 preload 注入；纯浏览器开发模式下为空字符串
 * （此时 sidecar 未配置令牌，跳过校验）。
 */
export const API_TOKEN: string = (window as any).autoresume?.apiToken || '';

/** 构造请求头：注入 X-Api-Token（extra 中的键优先）。 */
export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...(extra || {}) };
  if (API_TOKEN) headers['X-Api-Token'] = API_TOKEN;
  return headers;
}

/** URL 追加令牌查询参数。
 *
 * 用于无法携带自定义请求头的场景：WebSocket 握手、webview 加载、
 * window.open 下载/导出链接等。
 */
export function withTokenQuery(url: string): string {
  if (!API_TOKEN) return url;
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(API_TOKEN)}`;
}
