/** Shared constants for the Augustus frontend. */

import type { Agent } from '../types';

/** Ordered color palette for per-agent visualization. */
export const AGENT_COLORS = [
  'var(--agent-1)',
  'var(--agent-2)',
  'var(--agent-3)',
];

/** Pick a consistent color for an agent based on its position in the list. */
export function getAgentColor(agentId: string, agents: Agent[]): string {
  const idx = agents.findIndex((a) => a.agent_id === agentId);
  return AGENT_COLORS[idx >= 0 ? idx % AGENT_COLORS.length : 0];
}

/** Default Claude model name used when no override is configured. */
export const DEFAULT_MODEL = 'claude-sonnet-4';
