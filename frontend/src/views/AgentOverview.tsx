import { useState, useEffect, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Edit, ArrowRight, Lock, AlertCircle } from 'lucide-react';
import Badge from '../components/ui/Badge';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import EmptyState from '../components/ui/EmptyState';
import { api } from '../api/client';
import { useDataEvents } from '../hooks/useEventStream';
import { formatTimestamp, formatDuration, timeAgo } from '../utils/time';
import { getBasinColor } from '../utils/constants';
import type { Agent, BasinDefinition } from '../types';

interface OverviewBasin {
  name: string;
  basin_class: string;
  alpha: number;
  lambda: number;
  eta: number;
  tier: number;
}

interface OverviewData {
  agent: Record<string, unknown>;
  session_count: number;
  current_basins: OverviewBasin[];
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

interface RecentSession {
  session_id: string;
  agent_id: string;
  status: string;
  start_time?: string;
  started_at?: string;
  end_time?: string;
  completed_at?: string;
  turn_count: number;
}

function getBasinEmphasis(alpha: number): 'high' | 'medium' | 'low' {
  if (alpha >= 0.8) return 'high';
  if (alpha >= 0.6) return 'medium';
  return 'low';
}

function getTrendIcon() {
  return <ArrowRight size={16} className="basin-trend stable" />;
}

function getModifierColor(modifiedBy: string): string {
  switch (modifiedBy) {
    case 'brain': return 'var(--basin-core-2)';
    case 'body': return 'var(--accent-success)';
    case 'evaluator': return 'var(--accent-identity)';
    case 'import': return 'var(--text-muted)';
    default: return 'var(--text-muted)';
  }
}

function ModifierBadge({ modifiedBy, modifiedAt }: { modifiedBy: string; modifiedAt: string }) {
  return (
    <span
      className="modifier-badge"
      title={`${modifiedBy} - ${timeAgo(modifiedAt)}`}
      style={{ background: getModifierColor(modifiedBy) }}
    />
  );
}

export default function AgentOverview() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [eventTrigger, setEventTrigger] = useState(0);

  // Auto-refresh when basins, flags, or proposals change via SSE
  useDataEvents(
    ['basin_updated', 'flag_resolved', 'flag_created', 'proposal_resolved', 'proposal_created', 'annotation_created'],
    useCallback(() => setEventTrigger(n => n + 1), []),
    agentId,
  );

  useEffect(() => {
    if (!agentId) return;
    let cancelled = false;

    const fetchData = async () => {
      try {
        const [agentData, overviewData] = await Promise.all([
          api.agents.get(agentId),
          api.agents.overview(agentId),
        ]);

        if (cancelled) return;
        setAgent(agentData);
        setOverview(overviewData);
        setError(null);

        // Fetch recent sessions
        const sessionsResult = await api.sessions.list(agentId, 10, 0).catch(() => ({ sessions: [] }));
        if (!cancelled) {
          setRecentSessions((sessionsResult as any).sessions || []);
        }
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to load agent overview:', err);
        setError(err instanceof Error ? err.message : 'Failed to load agent overview.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 15000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [agentId, eventTrigger]);

  if (loading) {
    return <div style={{ padding: 'var(--space-6)' }}><LoadingSkeleton lines={6} /></div>;
  }

  if (error) {
    return (
      <div style={{ padding: 'var(--space-6)' }}>
        <EmptyState
          icon={<AlertCircle size={48} style={{ color: 'var(--accent-alert)' }} />}
          title="Failed to Load Overview"
          message={error}
        />
      </div>
    );
  }

  if (!agent) {
    return (
      <div style={{ padding: 'var(--space-6)', color: 'var(--text-secondary)' }}>
        Agent not found
      </div>
    );
  }

  const basinDefs = overview?.basin_definitions;
  const basins = overview?.current_basins ?? agent.basins.map((b) => ({
    name: b.name,
    basin_class: b.class,
    alpha: b.alpha,
    lambda: b.lambda,
    eta: b.eta,
    tier: b.tier,
  }));

  // Build a lookup from basin_definitions keyed by name
  const basinDefMap = new Map<string, BasinDefinition>();
  if (basinDefs) {
    for (const bd of basinDefs) {
      basinDefMap.set(bd.name, bd);
    }
  }

  const sessionCount = overview?.session_count ?? 0;
  const lastSession = overview?.last_session ?? null;
  const isActiveSession = lastSession && lastSession.status === 'active';

  return (
    <div>
      {/* Active Session Banner — only show if there's actually an active session */}
      {isActiveSession && lastSession && (
        <div className="active-session-banner">
          <div className="session-pulse" />
          <div className="active-session-info">
            <div className="active-session-title">
              Session {lastSession.session_id} in progress
            </div>
            <div className="active-session-detail">
              Turn {lastSession.turn_count} · Processing
            </div>
          </div>
        </div>
      )}

      {/* Overview Grid */}
      <div className="overview-grid">

        {/* Left column: identity + sessions stacked */}
        <div className="overview-left-col">

          {/* Identity Snapshot Panel */}
          <div className="section-card">
            <div className="section-card-header">
              <h2 className="section-title">Identity Snapshot</h2>
              <Link to={`/agents/${agentId}/edit`} className="btn btn-ghost btn-sm">
                <Edit size={16} />
                Edit
              </Link>
            </div>
            <div className="section-card-body" style={{ padding: 'var(--space-5)' }}>
              {agent.identity_core ? (
                <div className="identity-core-preview">{agent.identity_core}</div>
              ) : (
                <div className="identity-core-preview" style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                  No identity core defined.
                </div>
              )}
              <div className="identity-meta">
                <div className="identity-meta-item">
                  <span className="identity-meta-label">Token Count</span>
                  <span className="identity-meta-value">{agent.identity_core.length} characters</span>
                </div>
                <div className="identity-meta-item">
                  <span className="identity-meta-label">Created</span>
                  <span className="identity-meta-value">{formatTimestamp(agent.created_at)}</span>
                </div>
                <div className="identity-meta-item">
                  <span className="identity-meta-label">Sessions</span>
                  <span className="identity-meta-value">{sessionCount} completed</span>
                </div>
              </div>
            </div>
          </div>

          {/* Recent Sessions Panel */}
          <div className="section-card">
            <div className="section-card-header">
              <h2 className="section-title">Recent Sessions</h2>
              <Link to={`/agents/${agentId}/sessions`} className="btn btn-ghost btn-sm">
                View All →
              </Link>
            </div>
            <div className="section-card-body" style={{ padding: 0 }}>
              {recentSessions.length === 0 ? (
                <div style={{ padding: 'var(--space-6)', color: 'var(--text-muted)', textAlign: 'center' }}>
                  No sessions yet. Start the orchestrator or queue a bootstrap session.
                </div>
              ) : (
                <table className="sessions-table">
                  <thead>
                    <tr>
                      <th>Session</th>
                      <th>Time</th>
                      <th>Turns</th>
                      <th>Duration</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentSessions.map((session) => {
                      const startTime = session.start_time || session.started_at || '';
                      const endTime = session.end_time || session.completed_at || '';
                      return (
                        <tr
                          key={session.session_id}
                          onClick={() => navigate(`/agents/${agentId}/sessions/${session.session_id}`)}
                          style={{ cursor: 'pointer' }}
                        >
                          <td className="session-id-cell">{session.session_id}</td>
                          <td className="session-timestamp">{startTime ? formatTimestamp(startTime) : '—'}</td>
                          <td>{session.turn_count}</td>
                          <td>{startTime && endTime ? formatDuration(startTime, endTime) : '—'}</td>
                          <td>
                            <Badge variant={session.status === 'completed' ? 'active' : session.status === 'error' ? 'error' : 'idle'}>
                              {session.status}
                            </Badge>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>

        </div>{/* end overview-left-col */}

        {/* Basin State Panel — right column */}
        <div className="section-card">
          <div className="section-card-header">
            <h2 className="section-title">Basin States</h2>
            <Link to={`/agents/${agentId}/trajectories`} className="btn btn-ghost btn-sm">
              View Trajectories →
            </Link>
          </div>
          <div className="section-card-body" style={{ padding: 'var(--space-4)' }}>
            {basins.length === 0 ? (
              <div style={{ padding: 'var(--space-4)', color: 'var(--text-muted)', textAlign: 'center' }}>
                No basins configured.
              </div>
            ) : (
              <div className="basin-list">
                {basins.map((basin, idx) => {
                  const basinClass = basin.basin_class || 'peripheral';
                  const basinTier = basin.tier || 3;
                  const color = getBasinColor(idx);
                  const def = basinDefMap.get(basin.name);
                  const isDeprecated = def?.deprecated ?? false;
                  const isLocked = def?.locked_by_brain ?? false;

                  return (
                    <div
                      key={basin.name}
                      className={`basin-item${isDeprecated ? ' basin-deprecated' : ''}${isLocked ? ' basin-locked' : ''}`}
                      data-emphasis={isDeprecated ? undefined : getBasinEmphasis(basin.alpha)}
                      title={def?.last_rationale || undefined}
                    >
                      <div className="basin-main">
                        <div className="basin-header">
                          {isLocked && (
                            <Lock size={14} style={{ color: 'var(--accent-attention)', flexShrink: 0 }} />
                          )}
                          <span className="basin-name">{basin.name}</span>
                          <Badge variant={basinClass === 'core' ? 'active' : 'paused'}>
                            {basinClass}
                          </Badge>
                          <Badge variant={basinTier === 2 ? 'tier-2' : 'tier-3'}>
                            Tier {basinTier}
                          </Badge>
                          {def && (
                            <ModifierBadge modifiedBy={def.last_modified_by} modifiedAt={def.last_modified_at} />
                          )}
                        </div>
                        <div className="basin-alpha-row">
                          <span className="basin-alpha-value">{basin.alpha.toFixed(2)}</span>
                          <div className="basin-alpha-bar">
                            <div
                              className="basin-alpha-fill"
                              style={{ width: `${basin.alpha * 100}%`, background: color }}
                            />
                          </div>
                          {getTrendIcon()}
                        </div>
                      </div>
                      <div className="basin-params">
                        <div className="basin-param">
                          <span className="basin-param-label">{'\u03BB'}</span>
                          <span className="basin-param-value">{basin.lambda.toFixed(2)}</span>
                        </div>
                        <div className="basin-param">
                          <span className="basin-param-label">{'\u03B7'}</span>
                          <span className="basin-param-value">{basin.eta.toFixed(2)}</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
