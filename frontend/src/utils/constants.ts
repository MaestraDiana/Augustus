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

/**
 * Basin color palette — used consistently across trajectory charts,
 * overview panels, and co-activation networks.
 *
 * Index-based: assign colors by basin index when no specific mapping exists.
 * Values reference CSS custom properties from design-system.css so that
 * theme changes propagate automatically.
 */
export const BASIN_COLORS = [
  'var(--basin-core-1)',        // #3B9B8E  Verdigris
  'var(--basin-core-2)',        // #2E7D9B  Deep Water
  'var(--basin-core-3)',        // #5B8C6F  Forest
  'var(--basin-peripheral-1)',  // #D4915D  Amber
  'var(--basin-peripheral-2)',  // #C4786E  Clay
  'var(--basin-peripheral-3)', // #9B8B5A  Lichen
  'var(--basin-emergent-1)',    // #8B7EC8  Dusk
  'var(--basin-emergent-2)',    // #7A9BB8  Haze
] as const;

/** Get a basin color by index (wraps around). */
export function getBasinColor(index: number): string {
  return BASIN_COLORS[index % BASIN_COLORS.length];
}

/** Default Claude model name used when no override is configured. */
export const DEFAULT_MODEL = 'claude-sonnet-4';
