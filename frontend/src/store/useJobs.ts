import { create } from 'zustand';
import { agentApi, type Job } from '../api/agentApi';

/**
 * 共享岗位 store：供「岗位管理 / 简历优化 / 职位分析」等页面共用，
 * 任意一处增删改岗位都通过本 store 更新全局列表，实现各页面实时同步。
 */
interface JobsState {
  jobs: Job[];
  loading: boolean;
  refresh: () => Promise<void>;
  setJobs: (list: Job[]) => void;
  upsert: (job: Job) => void;
  upsertMany: (jobs: Job[]) => void;
  remove: (id: number) => void;
  removeMany: (ids: number[]) => void;
}

const sortDesc = (list: Job[]) => [...list].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));

export const useJobs = create<JobsState>((set) => ({
  jobs: [],
  loading: false,
  refresh: async () => {
    set({ loading: true });
    try {
      const list = await agentApi.listJobs();
      set({ jobs: sortDesc(list) });
    } finally {
      set({ loading: false });
    }
  },
  setJobs: (list) => set({ jobs: sortDesc(list) }),
  upsert: (job) =>
    set((s) => {
      if (s.jobs.some((j) => j.id === job.id)) {
        return { jobs: s.jobs.map((j) => (j.id === job.id ? job : j)) };
      }
      return { jobs: [job, ...s.jobs] };
    }),
  upsertMany: (jobs) =>
    set((s) => {
      const ids = new Set(s.jobs.map((j) => j.id));
      const fresh = jobs.filter((j) => !ids.has(j.id));
      return { jobs: sortDesc([...fresh, ...s.jobs]) };
    }),
  remove: (id) => set((s) => ({ jobs: s.jobs.filter((j) => j.id !== id) })),
  removeMany: (ids) => {
    const idSet = new Set(ids);
    set((s) => ({ jobs: s.jobs.filter((j) => !idSet.has(j.id)) }));
  },
}));