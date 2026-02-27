import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { FileText, Trash2 } from 'lucide-react';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
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

interface SessionListResponse {
  sessions: SessionItem[];
  total: number;
}

export default function SessionList() {
  const { agentId } = useParams<{ agentId: string }>();
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const { data, loading, refetch } = useApi<SessionListResponse>(
    () => api.sessions.list(agentId!, limit, offset),
    [agentId, offset],
  );

  const sessions = data?.sessions ?? [];
  const total = data?.total ?? 0;

  const handleDelete = async (sessionId: string) => {
    setDeleting(sessionId);
    setDeleteError(null);
    try {
      await api.sessions.delete(agentId!, sessionId);
      refetch();
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : 'Delete failed. Please try again.');
    } finally {
      setDeleting(null);
      setConfirmDeleteId(null);
    }
  };

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
      {deleteError && (
        <div style={{
          margin: 'var(--space-4) var(--space-4) 0',
          padding: 'var(--space-3) var(--space-4)',
          background: 'var(--accent-alert-dim)',
          color: 'var(--accent-alert)',
          borderRadius: 'var(--radius-md)',
          fontSize: '14px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span>{deleteError}</span>
          <button
            onClick={() => setDeleteError(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', padding: '0 0 0 var(--space-3)', fontSize: '16px', lineHeight: 1 }}
          >×</button>
        </div>
      )}
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
                    <th></th>
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
                      <td style={{ width: '1%', whiteSpace: 'nowrap', paddingRight: 'var(--space-4)' }}>
                        {confirmDeleteId === session.session_id ? (
                          <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '13px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>Delete?</span>
                            <button
                              className="btn btn-sm"
                              style={{ color: 'var(--accent-alert)', background: 'var(--accent-alert-dim)', border: 'none', padding: '2px 8px' }}
                              disabled={deleting === session.session_id}
                              onClick={() => handleDelete(session.session_id)}
                            >
                              {deleting === session.session_id ? '…' : 'Yes'}
                            </button>
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => setConfirmDeleteId(null)}
                            >
                              No
                            </button>
                          </span>
                        ) : (
                          <button
                            className="btn btn-ghost btn-sm"
                            title="Delete session"
                            onClick={() => setConfirmDeleteId(session.session_id)}
                            style={{ color: 'var(--text-muted)', padding: '2px 4px' }}
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
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
