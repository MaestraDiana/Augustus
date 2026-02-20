import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { MessageSquare } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { useDataEvents } from '../hooks/useEventStream';
import { timeAgo } from '../utils/time';
import type { Annotation } from '../types';
import EmptyState from '../components/ui/EmptyState';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';

const PAGE_SIZE = 20;

export default function Annotations() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [page, setPage] = useState(0);
  const [tagFilter, setTagFilter] = useState('');

  const { data, loading, error, refetch } = useApi<Annotation[]>(
    () => api.annotations.list(agentId!),
    [agentId],
  );

  useDataEvents(['annotation_created'], refetch, agentId);

  const annotations = data ?? [];

  const filtered = tagFilter.trim()
    ? annotations.filter((a) =>
        a.tags.some((t) => t.toLowerCase().includes(tagFilter.trim().toLowerCase())) ||
        a.content.toLowerCase().includes(tagFilter.trim().toLowerCase())
      )
    : annotations;

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const pageItems = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // Collect all unique tags for quick-filter chips
  const allTags = Array.from(new Set(annotations.flatMap((a) => a.tags))).sort();

  if (loading) {
    return <div style={{ padding: 'var(--space-6)' }}><LoadingSkeleton lines={6} /></div>;
  }

  if (error) {
    return (
      <div style={{ padding: 'var(--space-6)' }}>
        <EmptyState
          icon={<MessageSquare size={48} style={{ color: 'var(--text-muted)' }} />}
          title="Failed to Load Annotations"
          message={error}
        />
      </div>
    );
  }

  return (
    <div style={{ padding: 'var(--space-5) var(--space-6)' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          <MessageSquare size={20} style={{ color: 'var(--accent-primary)' }} />
          <h2 style={{ fontFamily: 'var(--font-voice)', fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)' }}>
            Annotations
          </h2>
          <span style={{
            padding: '2px var(--space-2)', background: 'var(--bg-raised)',
            borderRadius: 'var(--radius-sm)', fontSize: '13px', color: 'var(--text-muted)',
            fontFamily: 'var(--font-data)',
          }}>
            {filtered.length} {filtered.length !== annotations.length ? `of ${annotations.length}` : 'total'}
          </span>
        </div>

        {/* Search / filter input */}
        <div style={{ position: 'relative' }}>
          <input
            type="text"
            value={tagFilter}
            onChange={(e) => { setTagFilter(e.target.value); setPage(0); }}
            placeholder="Filter by tag or content..."
            style={{
              padding: 'var(--space-2) var(--space-4)',
              paddingLeft: '36px',
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-md)',
              fontFamily: 'var(--font-body)',
              fontSize: '14px',
              color: 'var(--text-primary)',
              outline: 'none',
              width: '260px',
            }}
            onFocus={(e) => { e.target.style.borderColor = 'var(--border-focus)'; }}
            onBlur={(e) => { e.target.style.borderColor = 'var(--border-color)'; }}
          />
          <svg
            xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" width="16" height="16"
            style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none' }}
          >
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
          </svg>
        </div>
      </div>

      {/* Tag quick-filter chips */}
      {allTags.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
          {allTags.map((tag) => (
            <button
              key={tag}
              onClick={() => { setTagFilter(tagFilter === tag ? '' : tag); setPage(0); }}
              style={{
                padding: '3px var(--space-3)',
                background: tagFilter === tag ? 'var(--accent-primary-dim)' : 'var(--bg-raised)',
                border: `1px solid ${tagFilter === tag ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                borderRadius: '100px',
                fontSize: '12px',
                color: tagFilter === tag ? 'var(--accent-primary)' : 'var(--text-secondary)',
                cursor: 'pointer',
                transition: 'all var(--transition-color)',
              }}
            >
              {tag}
            </button>
          ))}
        </div>
      )}

      {/* Annotation list */}
      {pageItems.length === 0 ? (
        <EmptyState
          icon={<MessageSquare size={48} style={{ color: 'var(--text-muted)' }} />}
          title={tagFilter ? 'No Matching Annotations' : 'No Annotations Yet'}
          message={tagFilter ? 'Try adjusting your filter.' : 'Annotations can be added via the Session Detail view or MCP tools.'}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {pageItems.map((ann) => (
            <div
              key={ann.annotation_id}
              style={{
                padding: 'var(--space-4) var(--space-5)',
                background: 'var(--bg-surface)',
                borderRadius: 'var(--radius-lg)',
                border: '1px solid var(--border-color)',
                borderLeft: '3px solid var(--accent-primary)',
              }}
            >
              <div style={{ fontSize: '15px', lineHeight: 1.6, color: 'var(--text-primary)', marginBottom: 'var(--space-3)' }}>
                {ann.content}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                {ann.tags.map((tag) => (
                  <span
                    key={tag}
                    onClick={() => { setTagFilter(tagFilter === tag ? '' : tag); setPage(0); }}
                    style={{
                      padding: '2px var(--space-2)',
                      background: 'var(--accent-primary-dim)',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '12px',
                      color: 'var(--accent-primary)',
                      cursor: 'pointer',
                    }}
                  >
                    {tag}
                  </span>
                ))}

                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
                  {ann.session_id && (
                    <span
                      onClick={() => navigate(`/agents/${agentId}/sessions/${ann.session_id}`)}
                      style={{
                        fontSize: '13px', color: 'var(--accent-primary)',
                        fontFamily: 'var(--font-data)', cursor: 'pointer',
                        textDecoration: 'underline',
                      }}
                    >
                      {ann.session_id}
                    </span>
                  )}
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-data)' }}>
                    {timeAgo(ann.created_at)}
                  </span>
                  {ann.created_by && (
                    <span style={{
                      fontSize: '12px', color: 'var(--text-muted)',
                      padding: '1px var(--space-2)',
                      background: 'var(--bg-raised)',
                      borderRadius: 'var(--radius-sm)',
                    }}>
                      {ann.created_by}
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: 'var(--space-2)', marginTop: 'var(--space-6)',
        }}>
          <button
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            style={{
              padding: 'var(--space-2) var(--space-3)',
              background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-md)', fontSize: '14px',
              color: page === 0 ? 'var(--text-muted)' : 'var(--text-primary)',
              cursor: page === 0 ? 'default' : 'pointer',
            }}
          >
            ← Prev
          </button>

          {Array.from({ length: totalPages }, (_, i) => i).map((i) => (
            <button
              key={i}
              onClick={() => setPage(i)}
              style={{
                padding: 'var(--space-2) var(--space-3)',
                background: i === page ? 'var(--accent-primary-dim)' : 'var(--bg-surface)',
                border: `1px solid ${i === page ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                borderRadius: 'var(--radius-md)', fontSize: '14px',
                color: i === page ? 'var(--accent-primary)' : 'var(--text-primary)',
                cursor: 'pointer',
                minWidth: '36px',
              }}
            >
              {i + 1}
            </button>
          ))}

          <button
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={page === totalPages - 1}
            style={{
              padding: 'var(--space-2) var(--space-3)',
              background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-md)', fontSize: '14px',
              color: page === totalPages - 1 ? 'var(--text-muted)' : 'var(--text-primary)',
              cursor: page === totalPages - 1 ? 'default' : 'pointer',
            }}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
