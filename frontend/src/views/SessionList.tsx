import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { FileText } from 'lucide-react';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import { api } from '../api/client';
import { formatTimestamp, formatDuration } from '../utils/time';

interface SessionItem {
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

export default function SessionList() {
  const { agentId } = useParams<{ agentId: string }>();
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const limit = 50;

  useEffect(() => {
    if (!agentId) return;

    const fetchSessions = async () => {
      setLoading(true);
      try {
        const data = await api.sessions.list(agentId, limit, offset);
        setSessions(data.sessions || []);
        setTotal(data.total || 0);
      } catch (err) {
        console.error('Failed to load sessions:', err);
        setSessions([]);
      } finally {
        setLoading(false);
      }
    };
    fetchSessions();
  }, [agentId, offset]);

  if (loading) {
    return (
      <div style={{ padding: 'var(--space-6)', color: 'var(--text-secondary)' }}>
        Loading sessions...
      </div>
    );
  }

  const hasMore = offset + limit < total;
  const hasPrev = offset > 0;

  return (
    <div>
      <div className="section-card">
        <div className="section-card-header">
          <h2 className="section-title">Sessions</h2>
          {total > 0 && (
            <span style={{ color: 'var(--text-muted)', fontSize: '14px' }}>
              {total} total
            </span>
          )}
        </div>
        <div className="section-card-body" style={{ padding: 0 }}>
          {sessions.length === 0 ? (
            <EmptyState
              icon={<FileText size={56} />}
              title="No Sessions"
              message={`No sessions have been recorded for ${agentId} yet.`}
            />
          ) : (
            <>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Session</th>
                    <th>Started</th>
                    <th>Duration</th>
                    <th>Turns</th>
                    <th>Model</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((session) => (
                    <tr key={session.session_id}>
                      <td>
                        <Link
                          to={`/agents/${agentId}/sessions/${session.session_id}`}
                          style={{ color: 'var(--accent-primary)', textDecoration: 'none' }}
                          className="font-mono"
                        >
                          {session.session_id}
                        </Link>
                      </td>
                      <td className="text-secondary">{formatTimestamp(session.start_time)}</td>
                      <td className="text-secondary">{formatDuration(session.start_time, session.end_time)}</td>
                      <td className="font-mono">{session.turn_count}</td>
                      <td className="font-mono text-secondary">{session.model || '—'}</td>
                      <td>
                        <Badge
                          variant={
                            session.status === 'complete' || session.status === 'completed'
                              ? 'active'
                              : session.status === 'error'
                                ? 'error'
                                : 'idle'
                          }
                        >
                          {session.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Pagination */}
              {(hasPrev || hasMore) && (
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: 'var(--space-4) var(--space-5)',
                  borderTop: '1px solid var(--border-color)',
                }}>
                  <button
                    className="btn btn-ghost btn-sm"
                    disabled={!hasPrev}
                    onClick={() => setOffset(Math.max(0, offset - limit))}
                  >
                    ← Previous
                  </button>
                  <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                    Showing {offset + 1}–{Math.min(offset + limit, total)} of {total}
                  </span>
                  <button
                    className="btn btn-ghost btn-sm"
                    disabled={!hasMore}
                    onClick={() => setOffset(offset + limit)}
                  >
                    Next →
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
