/** 简历 Agent 后端 API 封装（/agent 前缀） */
// 开发环境（Vite dev server）使用相对路径走 proxy，避免系统代理拦截 localhost 请求
// 生产环境（Electron）使用 preload 注入的绝对路径
const isDev = location.port === '5173';
const API_BASE = isDev ? '' : ((window as any).autoresume?.apiBase || 'http://127.0.0.1:8765');

const AGENT = `${API_BASE}/agent`;

// ── Types ──

export interface Job {
  id: number;
  title: string;
  content: string;
  created_at: string;
  updated_at?: string;
}

export interface GreetedItem {
  id: number;
  task_id: string;
  job_key: string;
  day: string;
  greeted_at: string;
  title: string;
  company: string;
  jd_text: string;
}

export interface Resume {
  id: number;
  job_id: number;
  title?: string;
  content: string;
  structured?: string | null;
  rendered_html?: string | null;
  current_template?: string | null;
  enabled?: boolean;
  file_type?: string;
  file_size?: number;
  version: number;
  background_profile_id?: number;
  angle?: string;
  created_at: string;
  updated_at?: string;
}

export interface RefChip {
  id: string;
  type: 'section' | 'entry' | 'field' | 'highlight' | 'full-resume' | 'html-part';
  label: string;
  section: string;
  index?: number;
  fieldPath?: string;
  sourceJson: any;
  sourceHtml: string;
  resumePartId?: string;
}

export interface HtmlPatch {
  resumePartId: string;
  newHtml: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  images?: string[];
  references?: RefChip[];
  scorecard?: Scorecard;
  patches?: HtmlPatch[];
}

export interface BackgroundProfile {
  id: number;
  name: string;
  content: string;
  created_at: string;
  updated_at?: string;
}

export interface ScoreCardItem {
  competency: string;
  score: number;
  confidence: string;
  summary: string;
  evidence: { source: string; quote: string; why?: string }[];
  gap?: string;
  suggestion?: string;
}

export interface Scorecard {
  overall_score: number;
  overall_summary: string;
  items: ScoreCardItem[];
  needs_verification: string[];
}

export interface CustomModel {
  id: string;
  api_format: string;
  base_url: string;
  full_url: boolean;
  model_id: string;
  multimodal: boolean;
  api_key_set: string; // "••••••" 或 ""
  model_series: string;
  display_name: string;
  context_input: number;
  context_output: number;
  tool_call_rounds: number;
}

export interface SettingsInfo {
  provider: string;
  model: string;
  api_keys_set: Record<string, string>;
  providers: Record<string, any>;
  custom: {
    base_url: string;
    api_key_set: string;
    model: string;
  };
  custom_models: CustomModel[];
}

// ── Jobs ──

export const agentApi = {
  async listJobs(): Promise<Job[]> {
    const r = await fetch(`${AGENT}/jobs`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async createJob(data: Partial<Job>): Promise<Job> {
    const r = await fetch(`${AGENT}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async updateJob(id: number, data: Partial<Job>): Promise<Job> {
    const r = await fetch(`${AGENT}/jobs/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deleteJob(id: number): Promise<void> {
    const r = await fetch(`${AGENT}/jobs/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
  },

  // ── Resumes ──

  async listResumes(jobId?: number): Promise<Resume[]> {
    const params = jobId ? `?job_id=${jobId}` : '';
    const r = await fetch(`${AGENT}/resumes${params}`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async getResume(id: number): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes/${id}`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async createResume(data: { job_id: number; title?: string; content?: string; structured?: string; background_profile_id?: number; file_type?: string; file_size?: number }): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async generateResume(jobId: number, background: string, style?: string, accent?: string): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId, background, style: style || 'classic', accent: accent || '#2563eb' }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async *generateResumeStream(
    jobId: number,
    background: string,
    style?: string,
    accent?: string,
  ): AsyncGenerator<{ type: string; content?: string; resume_id?: number }> {
    const r = await fetch(`${AGENT}/resumes/generate/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId, background, style: style || 'classic', accent: accent || '#2563eb' }),
    });
    if (!r.ok || !r.body) throw new Error(await r.text());

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              yield data;
              if (data.type === 'done' || data.type === 'error') return;
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `连接中断: ${e.message || '网络错误'}` };
    }
  },

  async createFromTemplate(jobId: number, template: string, accent?: string): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes/create-from-template`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId, template, accent }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async *restyleResumeStream(
    resumeId: number,
    style: string,
    accent: string,
    description?: string,
    avatarBase64?: string,
    referenceImageBase64?: string,
  ): AsyncGenerator<{ type: string; content?: string; resume_id?: number }> {
    const r = await fetch(`${AGENT}/resumes/${resumeId}/restyle/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        style,
        accent,
        description: description || '',
        avatar_base64: avatarBase64 || null,
        reference_image_base64: referenceImageBase64 || null,
      }),
    });
    if (!r.ok || !r.body) {
      let msg = '重新排版失败';
      try { msg = await r.text(); } catch { /* */ }
      throw new Error(msg);
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              yield data;
              if (data.type === 'done' || data.type === 'error') return;
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `连接中断: ${e.message || '网络错误'}` };
    }
  },

  async updateResume(id: number, data: Partial<Resume>): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deleteResume(id: number): Promise<void> {
    const r = await fetch(`${AGENT}/resumes/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
  },

  // ── Chat ──

  async getConversation(resumeId: number): Promise<{ id: number; messages: string } | null> {
    const r = await fetch(`${AGENT}/chat/conversations/${resumeId}`);
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async saveConversation(resumeId: number, messages: ChatMessage[]): Promise<void> {
    await fetch(`${AGENT}/chat/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resume_id: resumeId, messages }),
    });
  },

  /** 流式对话，返回 AsyncGenerator */
  async *chatStream(
    resumeId: number,
    jobId: number,
    messages: ChatMessage[],
    userBackground?: string,
    signal?: AbortSignal,
  ): AsyncGenerator<{ type: 'text' | 'patch' | 'tool_call' | 'tool_result' | 'error' | 'done'; content?: string; resumePartId?: string; newHtml?: string; toolName?: string; arguments?: any; result?: string }> {
    const r = await fetch(`${AGENT}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resume_id: resumeId, job_id: jobId, messages, user_background: userBackground }),
      signal,
    });
    if (!r.ok || !r.body) throw new Error(await r.text());

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.type === 'text') yield { type: 'text', content: data.content };
              else if (data.type === 'patch') yield { type: 'patch', resumePartId: data.resumePartId, newHtml: data.newHtml };
              else if (data.type === 'tool_call') yield { type: 'tool_call', toolName: data.name, arguments: data.arguments };
              else if (data.type === 'tool_result') yield { type: 'tool_result', toolName: data.name, result: data.result };
              else if (data.type === 'error') { yield { type: 'error', content: data.content }; return; }
              else if (data.type === 'done') { yield { type: 'done' }; return; }
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `[连接中断: ${e.message || '网络错误'}]` };
    }
  },

  /** 获取简历磁盘文件最新内容 */
  async getResumeFile(resumeId: number): Promise<{ resume_id: number; html: string; path: string }> {
    const r = await fetch(`${AGENT}/resumes/${resumeId}/file`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  /** 订阅简历文件变更 WebSocket，返回关闭函数 */
  subscribeResumeFileChange(
    resumeId: number,
    onFileChange: (data: { type: string; resume_id: number; path: string }) => void,
  ): () => void {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = isDev
      ? `${proto}//${location.host}${AGENT}/ws/resume/${resumeId}`
      : `${API_BASE.replace(/^http/, 'ws')}${AGENT.replace(API_BASE, '')}/ws/resume/${resumeId}`;
    let ws: WebSocket | null = null;
    let closed = false;

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(wsUrl);
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'file_changed') onFileChange(data);
        } catch { /* skip */ }
      };
      ws.onclose = () => {
        if (!closed) {
          // 断线重连（3 秒后）
          setTimeout(connect, 3000);
        }
      };
      ws.onerror = () => {
        try { ws?.close(); } catch { /* */ }
      };
    };
    connect();

    return () => {
      closed = true;
      try { ws?.close(); } catch { /* */ }
    };
  },

  // ── Upload ──

  /** 上传简历文件 → 后端自动提取文本 + 结构化 + 生成HTML → 返回完整Resume */
  async uploadAndGenerate(jobId: number, file: File, accent?: string, signal?: AbortSignal): Promise<Resume> {
    const fd = new FormData();
    fd.append('file', file);
    const params = new URLSearchParams({ job_id: String(jobId), accent: accent || '#2563eb' });
    const r = await fetch(`${AGENT}/uploads/upload-resume?${params}`, {
      method: 'POST',
      body: fd,
      signal,
    });
    if (!r.ok) {
      let msg = await r.text();
      try { msg = JSON.parse(msg).detail || msg; } catch { /* keep */ }
      throw new Error(msg || '上传生成简历失败');
    }
    return r.json();
  },

  /** 流式版：上传简历文件 → 逐步推送 parse/generate 进度 → 最终返回 resume_id */
  async *uploadAndGenerateStream(
    jobId: number,
    file: File,
    accent?: string,
  ): AsyncGenerator<{ type: string; phase?: string; content?: string; resume_id?: number }> {
    const fd = new FormData();
    fd.append('file', file);
    const params = new URLSearchParams({ job_id: String(jobId), accent: accent || '#2563eb' });
    const r = await fetch(`${AGENT}/uploads/upload-resume/stream?${params}`, {
      method: 'POST',
      body: fd,
    });
    if (!r.ok || !r.body) {
      let msg = '上传生成简历失败';
      try { msg = await r.text(); } catch { /* */ }
      throw new Error(msg);
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              yield data;
              if (data.type === 'done' || data.type === 'error') return;
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `连接中断: ${e.message || '网络错误'}` };
    }
  },

  async uploadResumePdf(file: File): Promise<{ filename: string; text: string; parser: string; warning?: string }> {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`${AGENT}/uploads/parse-resume-background`, {
      method: 'POST',
      body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async *uploadResumePdfStream(file: File): AsyncGenerator<{ type: string; content?: string; parser?: string; warning?: string | null }> {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`${AGENT}/uploads/parse-resume-background/stream`, {
      method: 'POST',
      body: fd,
    });
    if (!r.ok || !r.body) throw new Error(await r.text());

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              yield data;
              if (data.type === 'done' || data.type === 'error') return;
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `连接中断: ${e.message || '网络错误'}。模型可能输出不完整。` };
    }
  },

  // ── Export ──

  exportUrl(type: 'markdown' | 'pdf' | 'word', resumeId: number, extra?: string): string {
    const q = extra ? `?${extra}` : '';
    return `${AGENT}/export/${type}/${resumeId}${q}`;
  },

  // ── Evaluation ──

  async generateScorecard(data: {
    job_id: number;
    resume_id: number;
    transcript?: string;
    user_background?: string;
  }): Promise<Scorecard> {
    const r = await fetch(`${AGENT}/evaluation/scorecard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  // ── Background Profiles ──

  async listBackgrounds(): Promise<BackgroundProfile[]> {
    const r = await fetch(`${AGENT}/background/profiles`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async createBackground(data: { name: string; content: string }): Promise<BackgroundProfile> {
    const r = await fetch(`${AGENT}/background/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async updateBackground(id: number, data: { name?: string; content?: string }): Promise<BackgroundProfile> {
    const r = await fetch(`${AGENT}/background/profiles/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deleteBackground(id: number): Promise<void> {
    const r = await fetch(`${AGENT}/background/profiles/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
  },

  // ── Settings ──

  async getSettings(): Promise<SettingsInfo> {
    const r = await fetch(`${AGENT}/settings`);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async updateSettings(data: {
    provider: string;
    model: string;
    api_keys?: Record<string, string>;
    custom_base_url?: string;
    custom_api_key?: string;
    custom_model?: string;
  }): Promise<void> {
    const r = await fetch(`${AGENT}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async testConnection(provider: string, model: string, apiKey?: string, baseUrl?: string): Promise<{ success: boolean; message: string }> {
    const r = await fetch(`${AGENT}/settings/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model, api_key: apiKey, base_url: baseUrl }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  // ── Custom Models ──

  async addCustomModel(data: {
    api_format: string;
    base_url: string;
    full_url: boolean;
    model_id: string;
    multimodal: boolean;
    api_key: string;
    model_series: string;
    display_name: string;
    context_input: number;
    context_output: number;
    tool_call_rounds: number;
  }): Promise<CustomModel> {
    const r = await fetch(`${AGENT}/settings/custom-models`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deleteCustomModel(modelId: string): Promise<void> {
    const r = await fetch(`${AGENT}/settings/custom-models/${modelId}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
  },

  /**
   * 更新自定义模型。api_key 留空或 '••••••' 表示保留原值。
   * 只传需要更新的字段即可。
   */
  async updateCustomModel(modelId: string, data: {
    api_format?: string;
    base_url?: string;
    full_url?: boolean;
    model_id?: string;
    multimodal?: boolean;
    api_key?: string;
    model_series?: string;
    display_name?: string;
    context_input?: number;
    context_output?: number;
    tool_call_rounds?: number;
  }): Promise<CustomModel> {
    const r = await fetch(`${AGENT}/settings/custom-models/${modelId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  /**
   * 通过后端代理测试自定义模型连通性（避免浏览器 CORS 拦截）。
   * 完整返回 HTTP 状态码、响应体、错误类型，由前端组装展示。
   * 编辑模式下 api_key 可为空或 '••••••'，需同时传 existing_model_id 以便后端查找已存储的密钥。
   */
  async testCustomModel(data: {
    base_url: string;
    full_url: boolean;
    model_id: string;
    api_key: string;
    existing_model_id?: string;
  }): Promise<{
    success: boolean;
    status_code?: number;
    status_text?: string;
    body?: string;
    error_type?: string;
    message?: string;
  }> {
    const r = await fetch(`${AGENT}/settings/test-custom-model`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async batchCreateJobs(jobs: { title: string; content: string }[]): Promise<Job[]> {
    const r = await fetch(`${AGENT}/jobs/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobs }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async listGreetedRecent(days: number = 3): Promise<GreetedItem[]> {
    const r = await fetch(`${API_BASE}/api/tasks/greeted-recent?days=${days}`);
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    return data.items || [];
  },

  async batchDeleteGreeted(ids: number[]): Promise<{ ok: boolean; deleted: number }> {
    const r = await fetch(`${API_BASE}/api/tasks/greeted-batch-delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
};
