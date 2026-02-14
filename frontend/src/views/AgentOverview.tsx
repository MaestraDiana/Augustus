import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Edit, ArrowRight } from 'lucide-react';
import Badge from '../components/ui/Badge';
import { api } from '../api/client';
import { formatTimestamp, formatDuration } from '../utils/time';
import type { Agent } from '../types';

// Dynamic basin colors — cycles through brand palette
const BASIN_COLOR_PALETTE = [
  '#3B9B8E', '#2E7D9B', '#5B8C6F', '#D4915D', '#C4786E', '#8B7EC8',
];

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

export default function AgentOverview() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([]);
  const [loading, setLoading] = useState(true);

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

        // Fetch recent sessions from the sessions endpoint
        try {
          const sessionsData = await api.sessions.list(agentId, 10, 0);
          if (!cancelled) setRecentSessions(sessionsData.sessions || []);
        } catch {
          // Sessions may not exist yet for new agents
          if (!cancelled) setRecentSessions([]);
        }
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to load agent overview:', err);
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
  }, [agentId]);

  if (loading) {
    return (
      <div style={{ padding: 'var(--space-6)', color: 'var(--text-secondary)' }}>
        Loading agent overview...
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

  const basins = overview?.current_basins ?? agent.basins.map((b) => ({
    name: b.name,
    basin_class: b.class,
    alpha: b.alpha,
    lambda: b.lambda,
    eta: b.eta,
    tier: b.tier,
  }));

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
        {/* Identity Snapshot Panel */}
        <div className="section-card identity-panel">
          <div className="section-card-header">
            <h2 className="section-title">Identity Snapshot</h2>
            <Link to={`/agents/${agentId}/edit`} className="btn btn-ghost btn-sm">
              <Edit size={16} />
              Edit
            </Link>
          </div>
          <div className="section-card-body">
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
                <span className="identity-meta-value">
                  {agent.identity_core.length} characters
                </span>
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

        {/* Basin State Panel */}
        <div className="section-card basin-panel">
          <div className="section-card-header">
            <h2 className="section-title">Basin States</h2>
            <Link to={`/agents/${agentId}/trajectories`} className="btn btn-ghost btn-sm">
              View Trajectories →
            </Link>
          </div>
          <div className="section-card-body">
            {basins.length === 0 ? (
              <div style={{ padding: 'var(--space-4)', color: 'var(--text-muted)', textAlign: 'center' }}>
                No basins configured.
              </div>
            ) : (
              <div className="basin-list">
                {basins.map((basin, idx) => {
                  const basinClass = basin.basin_class || 'peripheral';
                  const basinTier = basin.tier || 3;
                  const color = BASIN_COLOR_PALETTE[idx % BASIN_COLOR_PALETTE.length];

                  return (
                    <div key={basin.name} className="basin-item" data-emphasis={getBasinEmphasis(basin.alpha)}>
                      <div className="basin-main">
                        <div className="basin-header">
                          <span className="basin-name">{basin.name}</span>
                          <Badge variant={basinClass === 'core' ? 'active' : 'paused'}>
                            {basinClass}
                          </Badge>
                          <Badge variant={basinTier === 2 ? 'tier-2' : 'tier-3'}>
                            Tier {basinTier}
                          </Badge>
                        </div>
                        <div className="basin-alpha-row">
                          <span className="basin-alpha-value">{basin.alpha.toFixed(2)}</span>
                          <div className="basin-alpha-bar">
                            <div
                              className="basin-alpha-fill"
                              style={{
                                width: `${basin.alpha * 100}%`,
                                background: color,
                              }}
                            />
                          </div>
                          {getTrendIcon()}
                        </div>
                      </div>
                      <div className="basin-params">
                        <div className="basin-param">
                          <span className="basin-param-label">λ</span>
                          <span className="basin-param-value">{basin.lambda.toFixed(2)}</span>
                        </div>
                        <div className="basin-param">
                          <span className="basin-param-label">η</span>
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

        {/* Recent Sessions Panel */}
        <div className="section-card sessions-panel">
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
      </div>
    </div>
  );
}
