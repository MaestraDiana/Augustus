import type {
  Agent,
  TierProposal,
  FlagRecord,
  SearchResult,
  ActivityEvent,
  SystemAlert,
  AgentFormData,
  ParseYamlResponse,
  OrchestratorStatusResponse,
  UsageDailyRecord,
  UsageSummaryResponse,
  TrajectoryResponse,
  CoActivationResponse,
  SessionListResponse,
  SessionDetailResponse,
  YamlDiffResponse,
  Settings,
  ValidateKeyResponse,
  AgentOverviewResponse,
  EvaluatorPrompt,
  Annotation,
} from '../types';

const API_BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.text();
    throw new Error(`API Error: ${res.status} - ${error}`);
  }
  // 204 No Content has no body — don't try to parse it
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
}

function get<T>(path: string) {
  return request<T>(path);
}

function post<T>(path: string, data?: unknown) {
  return request<T>(path, {
    method: 'POST',
    body: data ? JSON.stringify(data) : undefined,
  });
}

function put<T>(path: string, data?: unknown) {
  return request<T>(path, {
    method: 'PUT',
    body: data ? JSON.stringify(data) : undefined,
  });
}

function del<T>(path: string, params?: Record<string, string>) {
  const query = params ? '?' + new URLSearchParams(params).toString() : '';
  return request<T>(path + query, { method: 'DELETE' });
}

export const api = {
  agents: {
    list: () => get<Agent[]>('/agents'),
    get: (id: string) => get<Agent>(`/agents/${id}`),
    create: (data: AgentFormData) => post<Agent>('/agents', data),
    update: (id: string, data: Partial<AgentFormData>) => put<Agent>(`/agents/${id}`, data),
    delete: (id: string, hard: boolean = false) =>
      del<void>(`/agents/${id}`, hard ? { hard: 'true' } : undefined),
    pause: (id: string) => post<{ agent_id: string; status: string }>(`/agents/${id}/pause`),
    resume: (id: string) => post<{ agent_id: string; status: string }>(`/agents/${id}/resume`),
    clone: (id: string, newAgentId: string) => post<Agent>(`/agents/${id}/clone`, { new_agent_id: newAgentId }),
    export: (id: string) => {
      window.open(`${API_BASE}/agents/${id}/export`, '_blank');
      return Promise.resolve({ agent_id: id, export_path: '' });
    },
    overview: (id: string) => get<AgentOverviewResponse>(`/agents/${id}/overview`),
    parseYaml: (yamlText: string) =>
      post<ParseYamlResponse>('/agents/parse-yaml', { yaml_text: yamlText }),
  },

  sessions: {
    list: (agentId: string, limit = 50, offset = 0) =>
      get<SessionListResponse>(
        `/agents/${agentId}/sessions?limit=${limit}&offset=${offset}`
      ),
    get: (agentId: string, sessionId: string) =>
      get<SessionDetailResponse>(`/agents/${agentId}/sessions/${sessionId}`),
    getYamlDiff: (agentId: string, sessionId: string) =>
      get<YamlDiffResponse>(`/agents/${agentId}/sessions/${sessionId}/yaml-diff`),
  },

  trajectories: {
    get: (agentId: string, nSessions = 20) =>
      get<TrajectoryResponse>(`/agents/${agentId}/trajectories?n_sessions=${nSessions}`),
  },

  proposals: {
    list: (agentId: string) => get<TierProposal[]>(`/agents/${agentId}/tier-proposals`),
    approve: (agentId: string, proposalId: string) =>
      post<void>(`/agents/${agentId}/tier-proposals/${proposalId}/approve`),
    reject: (agentId: string, proposalId: string, rationale?: string) =>
      post<void>(`/agents/${agentId}/tier-proposals/${proposalId}/reject`, { rationale }),
  },

  flags: {
    list: (agentId: string) => get<FlagRecord[]>(`/agents/${agentId}/evaluator-flags`),
    review: (agentId: string, flagId: string, note?: string) =>
      post<void>(`/agents/${agentId}/evaluator-flags/${flagId}/review`, { note }),
  },

  coactivation: {
    get: (agentId: string) => get<CoActivationResponse>(`/agents/${agentId}/co-activation`),
  },

  search: {
    agent: (agentId: string, query: string) =>
      get<SearchResult[]>(`/agents/${agentId}/search?q=${encodeURIComponent(query)}`),
    global: (query: string) =>
      get<SearchResult[]>(`/search?q=${encodeURIComponent(query)}`),
  },

  usage: {
    summary: (period?: string) =>
      get<UsageSummaryResponse>(period ? `/usage?period=${period}` : '/usage'),
    daily: (days?: number) => get<UsageDailyRecord[]>(days ? `/usage/daily?days=${days}` : '/usage/daily'),
  },

  settings: {
    get: () => get<Settings>('/settings'),
    update: (data: Partial<Settings>) => put<Settings>('/settings', data),
    validateKey: (key: string) => post<ValidateKeyResponse>('/settings/validate-key', { api_key: key }),
  },

  evaluatorPrompts: {
    list: () => get<EvaluatorPrompt[]>('/evaluator-prompts'),
    create: (data: { prompt_text: string; change_rationale?: string; set_active?: boolean }) =>
      post<EvaluatorPrompt>('/evaluator-prompts', data),
    activate: (versionId: string) =>
      put<{ version_id: string; is_active: boolean }>(`/evaluator-prompts/${versionId}/activate`),
  },

  orchestrator: {
    status: () => get<OrchestratorStatusResponse>('/orchestrator/status'),
    pause: () => post<{ status: string; message: string }>('/orchestrator/pause'),
    resume: () => post<{ status: string; message: string }>('/orchestrator/resume'),
  },

  activity: {
    feed: (limit = 20) => get<ActivityEvent[]>(`/activity-feed?limit=${limit}`),
    alerts: () => get<SystemAlert[]>('/system-alerts'),
  },

  annotations: {
    create: (agentId: string, data: { content: string; session_id?: string; tags?: string[] }) =>
      post<Annotation>(`/agents/${agentId}/annotations`, data),
  },
};
