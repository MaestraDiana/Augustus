import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { LineChart, Line } from 'recharts';
import {
  Users,
  Play,
  Pause,
  ChevronRight,
  CheckCircle,
  Flag,
  Circle,
  Edit,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  Loader2,
} from 'lucide-react';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import { api } from '../api/client';
import { timeAgo } from '../utils/time';
import { getAgentColor, DEFAULT_MODEL } from '../utils/constants';
import { useDataEvents } from '../hooks/useEventStream';
import { useAlertDismissals, alertDismissKey } from '../hooks/useAlertDismissals';
import type { Agent, ActivityEvent, SystemAlert, BasinClass } from '../types';

interface TrajectoryResponse {
  agent_id: string;
  n_sessions: number;
  trajectories: Record<string, {
    metadata: {
      basin_class?: string;
      tier?: number;
      current_alpha?: number;
      lambda?: number;
      eta?: number;
    };
    points: Array<{
      session_id: string;
      alpha_start: number;
      alpha_end: number;
      delta: number;
      relevance_score: number | null;
    }>;
  }>;
}

interface AgentWithTrajectory extends Agent {
  trajectoryData: TrajectoryResponse | null;
}

const AgentCard: React.FC<{
  agent: AgentWithTrajectory;
  agents: AgentWithTrajectory[];
  onToggle: (agentId: string, isActive: boolean) => void
}> = ({ agent, agents, onToggle }) => {
  // Transform trajectory data into sparkline format
  const sparklineData = React.useMemo(() => {
    if (!agent.trajectoryData?.trajectories) {
      // Return flat line placeholder if no data
      return Array.from({ length: 20 }, (_, i) => ({ x: i }));
    }

    const trajectories = agent.trajectoryData.trajectories;
    const basinNames = Object.keys(trajectories);

    // Find the maximum number of points across all basins
    const maxPoints = Math.max(
      ...basinNames.map(name => trajectories[name].points.length),
      1
    );

    // Build data points indexed by session
    const data: Array<Record<string, number>> = [];
    for (let i = 0; i < maxPoints; i++) {
      const point: Record<string, number> = { x: i };
      basinNames.forEach(basinName => {
        const points = trajectories[basinName].points;
        if (i < points.length) {
          point[basinName] = points[i].alpha_end;
        }
      });
      data.push(point);
    }

    return data;
  }, [agent.trajectoryData]);

  // Get basin colors for sparklines
  const getBasinColor = (basinName: string, index: number): string => {
    if (!agent.trajectoryData?.trajectories) return 'var(--text-tertiary)';

    const basinClass = agent.trajectoryData.trajectories[basinName]?.metadata.basin_class;

    if (basinClass === 'core') {
      return index === 0 ? 'var(--basin-core-1)' : 'var(--basin-core-2)';
    } else if (basinClass === 'peripheral') {
      return index === 0 ? 'var(--basin-peripheral-1)' : 'var(--basin-peripheral-2)';
    }
    return 'var(--accent-primary)';
  };

  // Get basins sorted by class (core first) for rendering
  const getBasinsForSparkline = (): string[] => {
    if (!agent.trajectoryData?.trajectories) return [];

    const trajectories = agent.trajectoryData.trajectories;
    const basinEntries = Object.entries(trajectories);

    // Sort: core basins first, then peripheral, then emergent
    basinEntries.sort(([, a], [, b]) => {
      const classOrder = { core: 0, peripheral: 1, emergent: 2 };
      const aClass = a.metadata.basin_class as BasinClass || 'emergent';
      const bClass = b.metadata.basin_class as BasinClass || 'emergent';
      return classOrder[aClass] - classOrder[bClass];
    });

    // Return up to 4 basins for sparkline (2 core + 2 peripheral)
    return basinEntries.slice(0, 4).map(([name]) => name);
  };

  const basinsToRender = getBasinsForSparkline();

  const formatLastActive = (timestamp: string | null) => {
    if (!timestamp) return 'never';
    return timeAgo(timestamp);
  };

  const isActive = agent.status === 'active';
  const model = agent.model_override || DEFAULT_MODEL;
  const qs = agent.queue_status;

  // Derive a display label from queue state.
  // "Running session" = orchestrator is actively executing a session for this agent.
  // "N queued" = pending YAML files waiting to run. Only count pending/, not active/
  //   (active/ is either the currently-running session or stale debris).
  const pendingCount = qs?.pending_count ?? 0;
  const queueLabel = qs?.is_running ? 'Running session'
    : pendingCount > 0 ? `${pendingCount} queued`
    : null;

  return (
    <Link to={`/agents/${agent.agent_id}`} style={{ textDecoration: 'none' }}>
      <div className="agent-card">
        <div className="agent-card-top">
          <div>
            <div className="agent-id-row">
              <span
                className="agent-color-dot"
                style={{ background: getAgentColor(agent.agent_id, agents) }}
              />
              <span className="agent-id">{agent.agent_id}</span>
              <Badge variant={agent.status}>{agent.status}</Badge>
              {queueLabel && (
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: '4px',
                  fontSize: '11px', fontFamily: 'var(--font-data)',
                  color: qs?.is_running ? 'var(--accent-success)' : 'var(--accent-primary)',
                  marginLeft: 'var(--space-1)',
                }}>
                  {qs?.is_running ? (
                    <Loader2 size={11} style={{ animation: 'spin 1.5s linear infinite' }} />
                  ) : (
                    <Clock size={11} />
                  )}
                  {queueLabel}
                </span>
              )}
            </div>
            <div className="agent-description">{agent.description}</div>
          </div>
        </div>

        <div className="agent-stats">
          <div className="agent-stat">
            <span className="agent-stat-label">Sessions</span>
            <span className="agent-stat-value">{agent.session_count ?? 0}</span>
          </div>
          <div className="agent-stat">
            <span className="agent-stat-label">Last active</span>
            <span className="agent-stat-value">
              {formatLastActive(agent.last_active)}
            </span>
          </div>
          <div className="agent-stat">
            <span className="agent-stat-label">Model</span>
            <span className="agent-stat-value">{model}</span>
          </div>
        </div>

        <div className="agent-card-bottom">
          <div className="sparkline-container">
            {basinsToRender.length === 0 ? (
              <div style={{
                width: '200px',
                height: '36px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 'var(--text-xs)',
                color: 'var(--text-tertiary)',
              }}>
                No trajectory data
              </div>
            ) : (
              <LineChart data={sparklineData} width={200} height={36}>
                {basinsToRender.map((basinName, index) => (
                  <Line
                    key={basinName}
                    type="monotone"
                    dataKey={basinName}
                    stroke={getBasinColor(basinName, index)}
                    strokeWidth={1.5}
                    dot={false}
                  />
                ))}
              </LineChart>
            )}
          </div>
          <div className="agent-actions">
            <button
              className="agent-action-btn"
              title={isActive ? 'Pause' : 'Resume'}
              onClick={(e) => {
                e.preventDefault();
                onToggle(agent.agent_id, isActive);
              }}
            >
              {isActive ? <Pause size={16} /> : <Play size={16} />}
            </button>
            <button
              className="agent-action-btn"
              title="View details"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>
    </Link>
  );
};

const ActivityFeedItem: React.FC<{ event: ActivityEvent }> = ({ event }) => {
  const getIcon = () => {
    switch (event.event_type) {
      case 'session_complete':
        return <CheckCircle size={16} />;
      case 'flag':
        return <Flag size={16} />;
      case 'proposal':
        return <Circle size={16} />;
      case 'annotation':
        return <Edit size={16} />;
      case 'approved':
        return <CheckCircle2 size={16} />;
      default:
        return <Circle size={16} />;
    }
  };

  const getIconClass = () => {
    switch (event.event_type) {
      case 'session_complete':
        return 'feed-icon session-complete';
      case 'flag':
        return 'feed-icon flag';
      case 'proposal':
        return 'feed-icon proposal';
      case 'annotation':
        return 'feed-icon annotation';
      case 'approved':
        return 'feed-icon approved';
      default:
        return 'feed-icon';
    }
  };

  const formatActivityTime = timeAgo;

  const inner = (
    <div className="feed-item">
      <div className={getIconClass()}>{getIcon()}</div>
      <div className="feed-body">
        <div className="feed-text">{event.content}</div>
        <div className="feed-timestamp">{formatActivityTime(event.timestamp)}</div>
      </div>
    </div>
  );

  if (event.agent_id && event.session_id) {
    return (
      <Link to={`/agents/${event.agent_id}/sessions/${event.session_id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
        {inner}
      </Link>
    );
  }

  if (event.agent_id) {
    return (
      <Link to={`/agents/${event.agent_id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
        {inner}
      </Link>
    );
  }

  return inner;
};

const ALERT_DETAIL_THRESHOLD = 80;

const alertSignature = (a: SystemAlert) =>
  alertDismissKey(a.link_type, a.agent_id, a.session_id);

const AlertItem: React.FC<{ alert: SystemAlert; onDismiss: () => void }> = ({ alert, onDismiss }) => {
  const [expanded, setExpanded] = useState(false);
  const isLong = alert.detail.length > ALERT_DETAIL_THRESHOLD;

  const getIcon = () => {
    switch (alert.alert_type) {
      case 'warn':
        return <AlertTriangle size={18} />;
      case 'error':
        return <XCircle size={18} />;
      case 'info':
        return <Circle size={18} />;
      default:
        return <Circle size={18} />;
    }
  };

  const getAlertClass = () => {
    switch (alert.alert_type) {
      case 'warn':
        return 'alert-item alert-warn';
      case 'error':
        return 'alert-item alert-error';
      case 'info':
        return 'alert-item alert-info';
      default:
        return 'alert-item';
    }
  };

  const getAlertLink = (): string | null => {
    const agentId = alert.agent_id;
    switch (alert.link_type) {
      case 'pending_proposals':
        return agentId ? `/agents/${agentId}/proposals` : null;
      case 'unreviewed_flags':
      case 'constraint_erosion':
        return agentId ? `/agents/${agentId}/flags` : null;
      case 'agent_errors':
        return agentId ? `/agents/${agentId}` : '/agents';
      case 'session_failed': {
        const sessionId = alert.session_id;
        if (agentId && sessionId) return `/agents/${agentId}/sessions/${sessionId}`;
        return agentId ? `/agents/${agentId}/sessions` : '/agents';
      }
      case 'budget_warning':
        return '/usage';
      default:
        return null;
    }
  };

  const link = getAlertLink();

  const inner = (
    <div className={getAlertClass()} style={{ cursor: link ? 'pointer' : undefined }}>
      {getIcon()}
      <div className="alert-text">
        <div className="alert-title">{alert.title}</div>
        <div className={`alert-detail${isLong && !expanded ? ' alert-detail-collapsed' : ''}`}>
          {alert.detail}
        </div>
        <div className="alert-actions">
          {isLong && (
            <button
              className="alert-expand-btn"
              onClick={e => { e.preventDefault(); e.stopPropagation(); setExpanded(v => !v); }}
            >
              {expanded ? 'Show less' : 'Show more'}
            </button>
          )}
          <button
            className="alert-dismiss-link"
            onClick={e => { e.preventDefault(); e.stopPropagation(); onDismiss(); }}
          >
            Dismiss
          </button>
        </div>
      </div>
      {link && (
        <ChevronRight size={16} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
      )}
    </div>
  );

  if (link) {
    return (
      <Link to={link} style={{ textDecoration: 'none', color: 'inherit' }}>
        {inner}
      </Link>
    );
  }

  return inner;
};

export default function Dashboard() {
  const [agents, setAgents] = useState<AgentWithTrajectory[]>([]);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [alerts, setAlerts] = useState<SystemAlert[]>([]);
  const { dismissed: dismissedAlerts, dismiss } = useAlertDismissals();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const dismissAlert = (alert: SystemAlert) => dismiss(alertSignature(alert));

  const refreshAlerts = useCallback(() => {
    api.activity.alerts()
      .then(data => setAlerts(data as SystemAlert[]))
      .catch(() => {});
    api.activity.feed(20)
      .then(data => setActivity(data))
      .catch(() => {});
  }, []);

  const refreshAgents = useCallback(() => {
    api.agents.list().then(async (agentsData) => {
      const agentsWithTrajectories = await Promise.all(
        agentsData.map(async (agent) => {
          try {
            const trajectoryData = await api.trajectories.get(agent.agent_id, 20);
            return { ...agent, trajectoryData } as AgentWithTrajectory;
          } catch {
            return { ...agent, trajectoryData: null } as AgentWithTrajectory;
          }
        })
      );
      setAgents(agentsWithTrajectories);
    }).catch(() => {});
  }, []);

  // Refresh agent cards (is_running state) when a session starts or completes
  useDataEvents(
    ['session_start', 'session_complete', 'session_failed'],
    () => {
      refreshAgents();
      refreshAlerts();
    },
  );

  // Auto-refresh alerts + activity when real-time events arrive via SSE
  useDataEvents(
    [
      'flag_resolved', 'flag_created',
      'proposal_resolved', 'proposal_created',
      'basin_updated',
    ],
    refreshAlerts,
  );

  useEffect(() => {
    let cancelled = false;

    const fetchData = async () => {
      try {
        const [agentsData, activityData, alertsData] = await Promise.all([
          api.agents.list(),
          api.activity.feed(20),
          api.activity.alerts(),
        ]);

        if (cancelled) return;

        // Fetch trajectory data for each agent
        const agentsWithTrajectories = await Promise.all(
          agentsData.map(async (agent) => {
            try {
              const trajectoryData = await api.trajectories.get(agent.agent_id, 20);
              return { ...agent, trajectoryData } as AgentWithTrajectory;
            } catch (err) {
              console.error(`Failed to load trajectory for ${agent.agent_id}:`, err);
              return { ...agent, trajectoryData: null } as AgentWithTrajectory;
            }
          })
        );

        if (cancelled) return;

        setAgents(agentsWithTrajectories);
        setActivity(activityData);
        setAlerts(alertsData as SystemAlert[]);
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to load dashboard data:', err);
        setError('Failed to load data.');
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
  }, []);

  const handleToggleAgent = async (agentId: string, isActive: boolean) => {
    try {
      if (isActive) {
        await api.agents.pause(agentId);
      } else {
        await api.agents.resume(agentId);
      }
      // Refresh agents list with trajectory data
      const agentsData = await api.agents.list();
      const agentsWithTrajectories = await Promise.all(
        agentsData.map(async (agent) => {
          try {
            const trajectoryData = await api.trajectories.get(agent.agent_id, 20);
            return { ...agent, trajectoryData } as AgentWithTrajectory;
          } catch (err) {
            console.error(`Failed to load trajectory for ${agent.agent_id}:`, err);
            return { ...agent, trajectoryData: null } as AgentWithTrajectory;
          }
        })
      );
      setAgents(agentsWithTrajectories);
    } catch (err) {
      console.error('Failed to toggle agent:', err);
    }
  };

  if (loading) {
    return (
      <div className="dashboard-content">
        <div style={{ padding: 'var(--space-6)' }}>
          <LoadingSkeleton lines={6} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard-content">
        <div style={{ padding: 'var(--space-6)' }}>
          <EmptyState
            icon={<AlertTriangle size={48} style={{ color: 'var(--accent-alert)' }} />}
            title="Failed to Load Dashboard"
            message={error}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-content">
      <div className="section-header">
        <h2 className="section-title">Agents</h2>
        <Link to="/agents/new">
          <button className="btn btn-sm btn-secondary">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              width="14"
              height="14"
            >
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            New Agent
          </button>
        </Link>
      </div>

      {agents.length === 0 ? (
        <EmptyState
          icon={<Users size={44} />}
          title="No agents yet"
          message="Create your first agent to begin identity research sessions."
        />
      ) : (
        <>
          <div className="agent-cards-grid">
            {agents.map((agent) => (
              <AgentCard key={agent.agent_id} agent={agent} agents={agents} onToggle={handleToggleAgent} />
            ))}
          </div>

          <div className="dashboard-bottom">
            <div className="section-card">
              <div className="section-card-header">
                <span className="section-title">Recent Activity</span>
                <button className="btn btn-ghost btn-xs">View all</button>
              </div>
              <div className="section-card-body">
                <div className="feed-list">
                  {activity.length === 0 ? (
                    <div style={{ padding: 'var(--space-4)', color: 'var(--text-tertiary)', fontSize: 'var(--text-sm)' }}>
                      No activity yet. Activity will appear here after sessions run.
                    </div>
                  ) : (
                    activity.map((event) => (
                      <ActivityFeedItem key={event.event_id} event={event} />
                    ))
                  )}
                </div>
              </div>
            </div>

            <div className="section-card">
              <div className="section-card-header">
                <span className="section-title">System Alerts</span>
                {alerts.length > 0 && <Badge variant="paused">{alerts.length}</Badge>}
              </div>
              <div className="alerts-card-body">
                <div className="alerts-panel">
                  {alerts.filter(a => !dismissedAlerts.has(alertSignature(a))).length === 0 ? (
                    <div style={{ padding: 'var(--space-4)', color: 'var(--text-tertiary)', fontSize: 'var(--text-sm)' }}>
                      No active alerts.
                    </div>
                  ) : (
                    alerts
                      .filter(a => !dismissedAlerts.has(alertSignature(a)))
                      .map((alert) => (
                        <AlertItem key={alert.alert_id} alert={alert} onDismiss={() => dismissAlert(alert)} />
                      ))
                  )}
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
