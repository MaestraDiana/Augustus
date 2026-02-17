// Augustus TypeScript Types
// Matching Python backend dataclasses

export type AgentStatus = 'active' | 'idle' | 'paused' | 'error';
export type BasinClass = 'core' | 'peripheral' | 'emergent';
export type Tier = 1 | 2 | 3;
export type ProposalStatus = 'pending' | 'approved' | 'rejected' | 'auto_approved';
export type ProposalType = 'modify' | 'add' | 'remove';
export type FlagType = 'constraint_erosion' | 'assessment_divergence' | 'other';
export type CoActivationCharacter = 'reinforcing' | 'tensional' | 'serving' | 'competing' | null;

export interface QueueStatus {
  pending_count: number;
  has_active: boolean;
  is_running: boolean;
  queue_status: 'pending' | 'active' | 'running' | 'idle';
}

export interface Agent {
  agent_id: string;
  description: string;
  status: AgentStatus;
  created_at: string;
  last_active: string | null;
  session_count: number;
  model_override: string | null;
  temperature_override: number | null;
  max_turns: number;
  session_interval: number;
  identity_core: string;
  session_task: string;
  close_protocol: string;
  capabilities: CapabilityConfig[];
  basins: BasinConfig[];
  tier_settings: TierSettings;
  queue_status?: QueueStatus;
}

export interface BasinConfig {
  name: string;
  class: BasinClass;
  alpha: number;
  lambda: number;
  eta: number;
  tier: Tier;
}

export interface CapabilityConfig {
  name: string;
  enabled: boolean;
  available_from_turn: number;
}

export interface TierSettings {
  tier_2_auto_approve: boolean;
  tier_2_consecutive_threshold: number;
  new_basin_auto_approve: boolean;
  new_basin_threshold: number;
}

// SessionRecord matches backend dataclass - used for full session data in memory
export interface SessionRecord {
  session_id: string;
  agent_id: string;
  status: string;
  start_time: string;
  end_time: string;
  turn_count: number;
  model: string;
  temperature: number;
  capabilities_used: string[];
  transcript: Array<{
    role: string;
    content: string;
  }>;
  close_report: string | Record<string, unknown> | null;
  basin_snapshots: BasinSnapshot[];
  basin_snapshots_start?: Record<string, BasinSnapshot>; // Legacy - for components still using old format
  basin_snapshots_end?: Record<string, BasinSnapshot>; // Legacy - for components still using old format
  evaluator_output?: EvaluatorOutput | null;
}

// SessionListItem is the shape returned by /agents/{id}/sessions (without transcript)
export interface SessionListItem {
  session_id: string;
  agent_id: string;
  start_time: string;
  end_time: string;
  turn_count: number;
  model: string;
  temperature: number;
  status: string;
  capabilities_used: string[];
}

export interface BasinSnapshot {
  basin_name: string;
  alpha: number;
  relevance_score: number | null;
  delta: number | null;
  session_id: string;
  timestamp: string;
}

export interface TierProposal {
  proposal_id: string;
  agent_id: string;
  session_id: string;
  basin_name: string;
  proposal_type: ProposalType;
  status: ProposalStatus;
  rationale: string;
  consecutive_count: number;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
}

export interface EvaluatorOutput {
  session_id: string;
  basin_relevance: Record<string, number>;
  basin_rationale: Record<string, string>;
  co_activation_characters: Record<string, CoActivationCharacter>;
  constraint_erosion_flag: boolean;
  constraint_erosion_detail: string | null;
  assessment_divergence_flag: boolean;
  assessment_divergence_detail: string | null;
  emergent_observations: string[];
  evaluator_prompt_version: string;
  created_at: string;
}

export interface EvaluatorPrompt {
  version_id: string;
  prompt_text: string;
  created_at: string;
  change_rationale: string;
  is_active: boolean;
}

export interface FlagRecord {
  flag_id: string;
  agent_id: string;
  session_id: string;
  flag_type: FlagType;
  severity: string;
  detail: string;
  reviewed: boolean;
  review_note: string | null;
  reviewed_by?: string | null; // Optional - may not be present in all responses
  reviewed_at?: string | null; // Optional - may not be present in all responses
  created_at: string;
}

export interface Annotation {
  annotation_id: string;
  agent_id: string;
  session_id: string | null;
  content: string;
  tags: string[];
  created_at: string;
  created_by: string;
}

export interface SearchResult {
  content_type: string;
  agent_id: string;
  session_id: string;
  snippet: string;
  relevance_score: number;
  timestamp: string;
}

export interface ActivityEvent {
  event_id: string;
  event_type: 'session_complete' | 'proposal' | 'flag' | 'annotation' | 'approved';
  agent_id: string;
  session_id: string | null;
  content: string;
  timestamp: string;
}

export interface SystemAlert {
  alert_id: string;
  alert_type: 'warn' | 'error' | 'info';
  title: string;
  detail: string;
  link_type?: string;
  agent_id?: string;
  timestamp: string;
  dismissed: boolean;
}

export interface CoActivationEntry {
  pair: [string, string];
  count: number;
  character: CoActivationCharacter;
  sessions: string[];
}

export interface Settings {
  has_api_key: boolean;
  default_model: string;
  default_temperature: number;
  default_max_tokens: number;
  poll_interval: number;
  max_concurrent_agents: number;
  budget_warning: number;
  budget_hard_stop: number;
  budget_per_session: number;
  budget_per_day: number;
  evaluator_enabled: boolean;
  evaluator_model: string;
  formula_in_identity_core: boolean;
  dashboard_port: number;
  mcp_enabled: boolean;
  auto_update: boolean;
  data_directory: string;
}

// Form types
export interface AgentFormData {
  agent_id: string;
  description: string;
  model_override: string | null;
  temperature_override: number | null;
  max_turns: number;
  session_interval: number;
  identity_core: string;
  session_task: string;
  close_protocol: string;
  capabilities: CapabilityConfig[];
  basins: BasinConfig[];
  tier_settings: TierSettings;
  session_protocol: string;
  relational_grounding: string;
}

// YAML import response
export interface ParseYamlResponse {
  max_turns: number | null;
  identity_core: string | null;
  session_task: string | null;
  close_protocol: string | null;
  session_protocol: string | null;
  relational_grounding: string | null;
  capabilities: CapabilityConfig[] | null;
  basins: BasinConfig[] | null;
  warnings: string[];
  errors: string[];
}

// Additional API response types
export interface OrchestratorStatusResponse {
  status: 'running' | 'paused' | 'error' | 'idle';
  active_sessions: number;
  queued_agents: number;
  message?: string;
  last_error?: string;
}

export interface UsageDailyRecord {
  date: string;
  total_cost: number;
  total_sessions: number;
  total_tokens_in: number;
  total_tokens_out: number;
  by_agent: Record<string, {
    sessions: number;
    tokens_in: number;
    tokens_out: number;
    cost: number;
  }>;
}

export interface UsageSummaryResponse {
  period: string;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost: number;
  session_count: number;
  budget_limit?: number; // Optional - may be computed from settings
  by_agent: Record<string, {
    sessions: number;
    tokens_in: number;
    tokens_out: number;
    cost: number;
  }>;
}

export interface TrajectoryPoint {
  session_id: string;
  alpha_start: number;
  alpha_end: number;
  delta: number;
  relevance_score: number | null;
}

export interface TrajectoryMetadata {
  basin_class: string;
  tier: number;
  current_alpha: number;
  lambda: number;
  eta: number;
}

export interface BasinTrajectory {
  metadata: TrajectoryMetadata;
  points: TrajectoryPoint[];
}

export interface TrajectoryResponse {
  agent_id: string;
  n_sessions: number;
  trajectories: Record<string, BasinTrajectory>;
}

export interface CoActivationEdge {
  source: string;
  target: string;
  count: number;
  character: 'reinforcing' | 'tensional' | 'serving' | 'competing' | 'uncharacterized';
}

export interface CoActivationResponse {
  agent_id: string;
  nodes: string[]; // Basin names only - frontend builds GraphNode objects
  edges: CoActivationEdge[];
}

export interface SessionListResponse {
  sessions: SessionListItem[];
  total: number;
  limit: number;
  offset: number;
}

// SessionDetailResponse includes full transcript and evaluator data
export interface SessionDetailResponse {
  session_id: string;
  agent_id: string;
  status: string;
  start_time: string;
  end_time: string;
  turn_count: number;
  model: string;
  temperature: number;
  capabilities_used: string[];
  yaml_raw?: string;
  transcript: Array<{
    role: string;
    content: string;
  }>;
  close_report: string | null;
  basin_snapshots: Array<{
    basin_name: string;
    alpha_start: number;
    alpha_end: number;
    delta: number;
    relevance_score: number | null;
  }>;
  evaluator_output: {
    basin_relevance: Record<string, number>;
    basin_rationale: Record<string, string>;
    co_activation_characters: Record<string, CoActivationCharacter>;
    constraint_erosion_flag: boolean;
    constraint_erosion_detail: string | null;
    assessment_divergence_flag: boolean;
    assessment_divergence_detail: string | null;
    emergent_observations: string[];
  } | null;
  annotations: Array<{
    annotation_id: string;
    content: string;
    tags: string[];
    created_at: string;
  }>;
}

export interface YamlDiffResponse {
  session_id: string;
  yaml_raw: string;
  previous_session_id: string | null;
  previous_yaml_raw: string;
  is_first_session: boolean;
}

export interface ValidateKeyResponse {
  valid: boolean;
  message: string;
}

export interface BasinDefinition {
  id: number;
  agent_id: string;
  name: string;
  basin_class: BasinClass;
  alpha: number;
  lambda: number;
  eta: number;
  tier: Tier;
  locked_by_brain: boolean;
  alpha_floor: number | null;
  alpha_ceiling: number | null;
  deprecated: boolean;
  deprecated_at: string | null;
  deprecation_rationale: string | null;
  created_at: string;
  created_by: string;
  last_modified_at: string;
  last_modified_by: string;
  last_rationale: string | null;
}

export interface BasinModification {
  id: number;
  basin_id: number;
  agent_id: string;
  session_id: string | null;
  modified_by: string;
  modification_type: string;
  previous_values: Record<string, unknown> | null;
  new_values: Record<string, unknown>;
  rationale: string | null;
  created_at: string;
}

export interface AgentOverviewResponse {
  agent: {
    agent_id: string;
    description: string;
    status: string;
    model_override: string | null;
    temperature_override: number | null;
    max_tokens_override: number | null;
    max_turns: number;
    identity_core: string;
    session_task: string;
    close_protocol: string;
    capabilities: Record<string, unknown>;
    basins: Array<{
      name: string;
      basin_class: string;
      alpha: number;
      lambda: number;
      eta: number;
      tier: number;
    }>;
    tier_settings: {
      tier_2_auto_approve: boolean;
      tier_2_threshold: number;
      emergence_auto_approve: boolean;
      emergence_threshold: number;
    } | null;
    created_at: string;
    last_active: string | null;
  };
  session_count: number;
  current_basins: Array<{
    name: string;
    basin_class: string;
    alpha: number;
    lambda: number;
    eta: number;
    tier: number;
  }>;
  recent_flags: Array<{
    flag_id: string;
    flag_type: string;
    severity: string;
    detail: string;
    reviewed: boolean;
    created_at: string;
  }>;
  pending_proposal_count: number;
  last_session: {
    session_id: string;
    start_time: string;
    end_time: string | null;
    turn_count: number;
    status: string;
  } | null;
  basin_definitions?: BasinDefinition[];
}
