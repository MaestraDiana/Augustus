import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { timeAgo } from '../utils/time';
import { toggleSetItem } from '../utils/collections';
import { AGENT_COLORS, getAgentColor } from '../utils/constants';
import type { SearchResult, Agent } from '../types';
import EmptyState from '../components/ui/EmptyState';

// Normalize backend type aliases to frontend type keys
function normalizeType(type: string): string {
  if (type === 'emergence') return 'observation';
  return type;
}

function getTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    transcript: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
    'close-report': 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6',
    evaluator: 'M9 11l3 3L22 4 M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11',
    annotation: 'M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7 M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z',
    observation: 'M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z M12 8v4 M12 16h.01',
  };
  return icons[type] || icons.transcript;
}

function getTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    transcript: 'Transcript',
    'close-report': 'Close Report',
    evaluator: 'Evaluator Output',
    annotation: 'Annotation',
    observation: 'Emergent Observation',
  };
  return labels[type] || type;
}

function getTypeColor(type: string): string {
  const colors: Record<string, string> = {
    transcript: '#3B9B8E',
    'close-report': '#2E7D9B',
    evaluator: '#8B7EC8',
    annotation: '#D4915D',
    observation: '#6BAF7D',
  };
  return colors[type] || '#3B9B8E';
}

// Content types that navigate to session detail when clicked.
// annotation and observation may also be expanded in-place if no session_id.
const SESSION_NAV_TYPES = new Set(['transcript', 'close-report', 'evaluator', 'annotation', 'observation']);

export default function Search() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [scope, setScope] = useState('all');
  const [scopeMenuOpen, setScopeMenuOpen] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [activeTypes, setActiveTypes] = useState<Set<string>>(
    new Set(['transcript', 'close-report', 'evaluator', 'annotation', 'observation']),
  );
  const [expandedCards, setExpandedCards] = useState<Set<number>>(new Set());
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    api.agents.list().then(setAgents).catch(() => {});
  }, []);

  useEffect(() => {
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    if (!query.trim()) {
      setResults([]);
      setSearched(false);
      return;
    }
    searchTimeoutRef.current = setTimeout(() => {
      handleSearch();
    }, 400);
    return () => {
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    };
  }, [query, scope]);

  async function handleSearch() {
    if (!query.trim()) return;
    setLoading(true);
    setSearchError(null);
    try {
      const raw =
        scope === 'all'
          ? await api.search.global(query)
          : await api.search.agent(scope, query);
      const data = raw.map((r: SearchResult) => ({ ...r, content_type: normalizeType(r.content_type) }));
      setResults(data);
      setExpandedCards(new Set());
    } catch (err) {
      console.error('Failed to search:', err);
      setResults([]);
      setSearchError(err instanceof Error ? err.message : 'Search failed. Check backend connectivity.');
    } finally {
      setLoading(false);
      setSearched(true);
    }
  }

  function handleResultClick(result: SearchResult, index: number) {
    const isExpandable = result.content_type === 'annotation' || result.content_type === 'observation' || result.content_type === 'evaluator';
    if (result.session_id && SESSION_NAV_TYPES.has(result.content_type)) {
      navigate(`/agents/${result.agent_id}/sessions/${result.session_id}`);
    } else if (isExpandable) {
      // No session to navigate to — expand in place
      setExpandedCards(prev => toggleSetItem(prev, index));
    }
  }

  function toggleType(type: string) {
    setActiveTypes(prev => toggleSetItem(prev, type));
  }

  const filteredResults = results.filter((r) => activeTypes.has(r.content_type));

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto' }}>
      {/* Search Header */}
      <div style={{ textAlign: 'center', marginBottom: 'var(--space-8)' }}>
        <h1 style={{
          fontFamily: 'var(--font-voice)', fontSize: '28px', fontWeight: 600,
          color: 'var(--text-primary)', marginBottom: 'var(--space-2)',
        }}>Search Everything</h1>
        <p style={{ fontSize: '15px', color: 'var(--text-secondary)' }}>
          Semantic search across transcripts, reports, annotations, and observations
        </p>
      </div>

      {/* Search Bar */}
      <div style={{ display: 'flex', gap: 'var(--space-3)', marginBottom: 'var(--space-5)' }}>
        <div style={{ flex: 1, position: 'relative' }}>
          <div style={{
            position: 'absolute', left: 'var(--space-4)', top: '50%',
            transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none',
          }}>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="22" height="22">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
          </div>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
            placeholder="Search for patterns, concepts, or specific content..."
            style={{
              width: '100%', padding: 'var(--space-4) var(--space-5)', paddingLeft: '52px',
              fontFamily: 'var(--font-body)', fontSize: '16px', color: 'var(--text-primary)',
              background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-lg)', outline: 'none',
              transition: 'border-color var(--transition-color), box-shadow var(--transition-color)',
            }}
            onFocus={(e) => {
              e.target.style.borderColor = 'var(--border-focus)';
              e.target.style.boxShadow = '0 0 0 3px var(--accent-primary-dim)';
            }}
            onBlur={(e) => {
              e.target.style.borderColor = 'var(--border-color)';
              e.target.style.boxShadow = 'none';
            }}
          />
        </div>
        <button className="btn btn-primary" style={{ padding: '0 var(--space-6)' }} onClick={handleSearch}>
          Search
        </button>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 'var(--space-6)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-secondary)' }}>Scope</span>
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setScopeMenuOpen(!scopeMenuOpen)}
              style={{
                display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                padding: 'var(--space-2) var(--space-3)', background: 'var(--bg-surface)',
                border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)',
                fontFamily: 'var(--font-body)', fontSize: '14px', color: 'var(--text-primary)',
                cursor: 'pointer', minWidth: '160px',
              }}
            >
              <span>{scope === 'all' ? 'All Agents' : scope}</span>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {scopeMenuOpen && (
              <div style={{
                position: 'absolute', top: 'calc(100% + 4px)', left: 0, minWidth: '200px',
                background: 'var(--bg-raised)', border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-dropdown)', zIndex: 50,
              }}>
                <div
                  onClick={() => { setScope('all'); setScopeMenuOpen(false); }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                    padding: 'var(--space-3) var(--space-4)', fontSize: '14px', color: 'var(--text-primary)',
                    cursor: 'pointer', background: scope === 'all' ? 'var(--accent-primary-dim)' : 'transparent',
                  }}
                >All Agents</div>
                {agents.map((agent, idx) => (
                  <div
                    key={agent.agent_id}
                    onClick={() => { setScope(agent.agent_id); setScopeMenuOpen(false); }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                      padding: 'var(--space-3) var(--space-4)', fontSize: '14px', color: 'var(--text-primary)',
                      cursor: 'pointer', background: scope === agent.agent_id ? 'var(--accent-primary-dim)' : 'transparent',
                    }}
                  >
                    <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: AGENT_COLORS[idx % AGENT_COLORS.length] }} />
                    {agent.agent_id}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-secondary)' }}>Content Types</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
            {[
              { key: 'transcript', label: 'Transcripts' },
              { key: 'close-report', label: 'Close Reports' },
              { key: 'evaluator', label: 'Evaluator Output' },
              { key: 'annotation', label: 'Annotations' },
              { key: 'observation', label: 'Emergent Observations' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => toggleType(key)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                  padding: 'var(--space-2) var(--space-3)',
                  background: activeTypes.has(key) ? 'var(--accent-primary-dim)' : 'var(--bg-surface)',
                  border: `1px solid ${activeTypes.has(key) ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                  borderRadius: 'var(--radius-md)', fontSize: '13px',
                  color: activeTypes.has(key) ? 'var(--accent-primary)' : 'var(--text-secondary)',
                  cursor: 'pointer', transition: 'all var(--transition-color)',
                }}
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                  <path d={getTypeIcon(key)} />
                </svg>
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content area */}
      {loading ? (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          padding: 'var(--space-12) 0', color: 'var(--text-muted)',
        }}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="32" height="32" style={{ animation: 'spin 1s linear infinite' }}>
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
          <p style={{ marginTop: 'var(--space-3)', fontSize: '15px' }}>Searching...</p>
        </div>
      ) : !searched ? (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          padding: 'var(--space-12) 0', color: 'var(--text-muted)',
        }}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="64" height="64">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <p style={{ marginTop: 'var(--space-4)', fontSize: '16px', fontWeight: 500, color: 'var(--text-secondary)' }}>
            Enter a query to begin searching across all sessions
          </p>
        </div>
      ) : searchError ? (
        <div style={{ padding: 'var(--space-8) 0' }}>
          <EmptyState
            icon={<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="48" height="48" style={{ color: 'var(--accent-alert)' }}><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>}
            title="Search Failed"
            message="Could not reach the backend. Check that the server is running."
          />
        </div>
      ) : filteredResults.length === 0 ? (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          padding: 'var(--space-12) 0', color: 'var(--text-muted)',
        }}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="64" height="64">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <p style={{ marginTop: 'var(--space-4)', fontSize: '16px', fontWeight: 500, color: 'var(--text-secondary)' }}>
            No results found
          </p>
          <p style={{ marginTop: 'var(--space-2)', fontSize: '14px' }}>
            Try different keywords or adjust your filters
          </p>
        </div>
      ) : (
        <div style={{ marginTop: 'var(--space-6)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-4)' }}>
            <div style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>
              Found <strong style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                {filteredResults.length} result{filteredResults.length !== 1 ? 's' : ''}
              </strong> for &ldquo;{query}&rdquo;
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '13px', color: 'var(--text-secondary)' }}>
              <span>Sort by:</span>
              <select style={{
                background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)', padding: 'var(--space-1) var(--space-2)',
                fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-primary)', cursor: 'pointer',
              }}>
                <option value="relevance">Relevance</option>
                <option value="newest">Newest First</option>
                <option value="oldest">Oldest First</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            {filteredResults.map((result, i) => {
              const typeColor = getTypeColor(result.content_type);
              const agentColor = getAgentColor(result.agent_id, agents);
              const isExpanded = expandedCards.has(i);
              const canNavigate = result.session_id && SESSION_NAV_TYPES.has(result.content_type);
              const canExpand = !result.session_id && (result.content_type === 'annotation' || result.content_type === 'observation' || result.content_type === 'evaluator');
              return (
                <div key={`${result.session_id}-${result.content_type}-${i}`}
                  onClick={() => handleResultClick(result, i)}
                  style={{
                    background: 'var(--bg-surface)', border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-lg)', padding: 'var(--space-4)', cursor: 'pointer',
                    transition: 'border-color var(--transition-color), box-shadow var(--transition-color)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--text-muted)';
                    e.currentTarget.style.boxShadow = 'var(--shadow-card)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--border-color)';
                    e.currentTarget.style.boxShadow = 'none';
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
                    <div style={{
                      width: '36px', height: '36px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      borderRadius: 'var(--radius-md)', flexShrink: 0,
                      background: `${typeColor}26`, color: typeColor,
                    }}>
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18">
                        <path d={getTypeIcon(result.content_type)} />
                      </svg>
                    </div>

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap', marginBottom: 'var(--space-1)' }}>
                        <span style={{
                          fontSize: '12px', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.5px',
                          color: typeColor,
                        }}>
                          {getTypeLabel(result.content_type)}
                        </span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontFamily: 'var(--font-data)', fontSize: '13px', color: 'var(--text-secondary)' }}>
                          <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: agentColor }} />
                          {result.agent_id}
                        </div>
                        <span style={{ fontFamily: 'var(--font-data)', fontSize: '13px', color: 'var(--text-muted)' }}>
                          {result.session_id}
                        </span>
                        <span style={{ fontFamily: 'var(--font-data)', fontSize: '13px', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                          {timeAgo(result.timestamp)}
                        </span>
                      </div>
                    </div>

                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 'var(--space-1)',
                      padding: 'var(--space-1) var(--space-2)', background: 'var(--accent-primary-dim)',
                      borderRadius: 'var(--radius-sm)', fontFamily: 'var(--font-data)', fontSize: '12px',
                      fontWeight: 500, color: 'var(--accent-primary)',
                    }}>
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                      </svg>
                      {result.relevance_score.toFixed(2)}
                    </div>
                  </div>

                  <div
                    style={{ fontSize: '15px', lineHeight: 1.6, color: 'var(--text-secondary)' }}
                    dangerouslySetInnerHTML={{
                      __html: (result.snippet || '').replace(
                        /<mark>/g,
                        '<mark style="background: var(--highlight-bg); color: var(--text-primary); padding: 1px 3px; border-radius: 2px; font-weight: 500;">',
                      ),
                    }}
                  />
                  {canExpand && isExpanded && (
                    <div style={{ marginTop: 'var(--space-3)', paddingTop: 'var(--space-3)', borderTop: '1px solid var(--border-color)' }}>
                      <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 'var(--space-2)' }}>
                        Full Content
                      </div>
                      <div style={{ fontSize: '14px', lineHeight: 1.7, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
                        {result.snippet}
                      </div>
                    </div>
                  )}
                  <div style={{ marginTop: 'var(--space-3)', fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}>
                    {canNavigate ? (
                      <>
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3"/></svg>
                        Open session
                      </>
                    ) : canExpand ? (
                      isExpanded ? '▲ Collapse' : '▼ Expand full text'
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <style>{`
        :root { --highlight-bg: rgba(59, 155, 142, 0.25); }
        [data-theme="light"] { --highlight-bg: rgba(59, 155, 142, 0.2); }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
