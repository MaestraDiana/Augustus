import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { formatDate } from '../utils/time';
import { FlagRecord, FlagType } from '../types';
import { AlertTriangle, Users, Info, Check } from 'lucide-react';
import EmptyState from '../components/ui/EmptyState';

export default function EvaluatorFlags() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [flags, setFlags] = useState<FlagRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<FlagType | 'all'>('all');
  const [showReviewed, setShowReviewed] = useState<boolean>(false);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkReviewing, setBulkReviewing] = useState(false);

  useEffect(() => {
    if (!agentId) return;

    const fetchFlags = async () => {
      try {
        setError(null);
        const data = await api.flags.list(agentId);
        setFlags(data);
      } catch (err) {
        console.error('Failed to load flags:', err);
        setError(err instanceof Error ? err.message : 'Failed to load flags');
        setFlags([]);
      } finally {
        setLoading(false);
      }
    };
    fetchFlags();
  }, [agentId]);

  const filteredFlags = flags.filter(flag => {
    if (selectedType !== 'all' && flag.flag_type !== selectedType) return false;
    if (!showReviewed && flag.reviewed) return false;
    return true;
  });

  const unreviewedByType = {
    constraint_erosion: flags.filter(f => f.flag_type === 'constraint_erosion' && !f.reviewed).length,
    assessment_divergence: flags.filter(f => f.flag_type === 'assessment_divergence' && !f.reviewed).length,
    other: 0
  };

  const getFlagIcon = (type: FlagType) => {
    switch (type) {
      case 'constraint_erosion':
        return AlertTriangle;
      case 'assessment_divergence':
        return Users;
      default:
        return Info;
    }
  };

  const toggleRow = (flagId: string) => {
    setExpandedRow(expandedRow === flagId ? null : flagId);
  };

  const handleMarkReviewed = async (flagId: string) => {
    if (!agentId) return;
    try {
      await api.flags.review(agentId, flagId, reviewNotes[flagId] || '');
      const data = await api.flags.list(agentId);
      setFlags(data);
      setSelected(prev => { const next = new Set(prev); next.delete(flagId); return next; });
      setExpandedRow(null);
      setShowReviewed(true);
    } catch (err) {
      console.error('Failed to mark flag as reviewed:', err);
    }
  };

  const handleBulkReview = async () => {
    if (!agentId || selected.size === 0) return;
    setBulkReviewing(true);
    try {
      // Review each flag, collecting results to handle partial failures
      const results = await Promise.allSettled(
        Array.from(selected).map(flagId =>
          api.flags.review(agentId, flagId, reviewNotes[flagId] || '')
        )
      );

      const failed = results.filter(r => r.status === 'rejected');
      if (failed.length > 0) {
        console.error(`${failed.length} flag review(s) failed:`, failed);
      }

      // Re-fetch to get authoritative state from server
      const data = await api.flags.list(agentId);

      // Batch all state updates together to avoid intermediate renders
      // where reviewed flags might flash out of view
      setFlags(data);
      setSelected(new Set());
      setExpandedRow(null);
      setShowReviewed(true);
    } catch (err) {
      console.error('Failed to bulk review flags:', err);
    } finally {
      setBulkReviewing(false);
    }
  };

  // Only unreviewed flags in the current filtered list are selectable
  const selectableFlags = filteredFlags.filter(f => !f.reviewed);
  const allSelectableChecked = selectableFlags.length > 0 && selectableFlags.every(f => selected.has(f.flag_id));
  const someSelected = selected.size > 0;

  const toggleSelect = (flagId: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(flagId)) next.delete(flagId);
      else next.add(flagId);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (allSelectableChecked) {
      setSelected(new Set());
    } else {
      setSelected(new Set(selectableFlags.map(f => f.flag_id)));
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 'var(--space-6)', color: 'var(--text-secondary)' }}>
        Loading flags...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 'var(--space-6)' }}>
        <EmptyState
          icon={<AlertTriangle size={48} style={{ color: 'var(--accent-alert)' }} />}
          title="Failed to Load Flags"
          message={error}
        />
      </div>
    );
  }

  if (flags.length === 0) {
    return (
      <div style={{ padding: 'var(--space-6)' }}>
        <EmptyState
          icon={<Info size={48} style={{ color: 'var(--text-muted)' }} />}
          title="No Evaluator Flags"
          message="Flags will appear here after sessions are evaluated."
        />
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="proposals-header">
        {/* Summary Cards */}
        <div style={{ display: 'flex', gap: 'var(--space-4)', marginBottom: 'var(--space-5)', flexWrap: 'wrap' }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-3)',
            padding: 'var(--space-3) var(--space-4)',
            background: 'var(--bg-raised)',
            borderRadius: 'var(--radius-md)',
            minWidth: '160px'
          }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--accent-alert-dim)',
              color: 'var(--accent-alert)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <AlertTriangle size={20} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontFamily: 'var(--font-data)', fontSize: '20px', fontWeight: 500, color: 'var(--text-primary)' }}>
                {unreviewedByType.constraint_erosion}
              </span>
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                Constraint Erosion
              </span>
            </div>
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-3)',
            padding: 'var(--space-3) var(--space-4)',
            background: 'var(--bg-raised)',
            borderRadius: 'var(--radius-md)',
            minWidth: '160px'
          }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--accent-attention-dim)',
              color: 'var(--accent-attention)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Users size={20} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontFamily: 'var(--font-data)', fontSize: '20px', fontWeight: 500, color: 'var(--text-primary)' }}>
                {unreviewedByType.assessment_divergence}
              </span>
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                Assessment Divergence
              </span>
            </div>
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-3)',
            padding: 'var(--space-3) var(--space-4)',
            background: 'var(--bg-raised)',
            borderRadius: 'var(--radius-md)',
            minWidth: '160px'
          }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--accent-success-dim)',
              color: 'var(--accent-success)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Check size={20} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontFamily: 'var(--font-data)', fontSize: '20px', fontWeight: 500, color: 'var(--text-primary)' }}>
                {flags.filter(f => f.reviewed).length}
              </span>
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                Reviewed
              </span>
            </div>
          </div>
        </div>

        {/* Filters */}
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-4)' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
            {(['all', 'constraint_erosion', 'assessment_divergence'] as const).map(type => (
              <button
                key={type}
                onClick={() => setSelectedType(type)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 'var(--space-2)',
                  padding: 'var(--space-1) var(--space-3)',
                  borderRadius: '100px',
                  background: selectedType === type ? 'var(--accent-primary-dim)' : 'var(--bg-raised)',
                  border: `1px solid ${selectedType === type ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                  fontSize: '13px',
                  color: selectedType === type ? 'var(--accent-primary)' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  transition: 'all var(--transition-color)'
                }}
              >
                {type === 'all' ? 'All Flags' : type.replace('_', ' ')}
              </button>
            ))}
          </div>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            fontSize: '14px',
            color: 'var(--text-secondary)',
            cursor: 'pointer'
          }}>
            <input
              type="checkbox"
              checked={showReviewed}
              onChange={(e) => setShowReviewed(e.target.checked)}
              style={{ display: 'none' }}
            />
            <span style={{
              width: '16px',
              height: '16px',
              border: '1px solid var(--border-color)',
              borderRadius: '3px',
              background: showReviewed ? 'var(--accent-primary)' : 'var(--bg-input)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              {showReviewed && (
                <svg viewBox="0 0 10 10" style={{ width: '10px', height: '10px', color: '#fff' }}>
                  <path d="M2 5l2 2 4-4" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                </svg>
              )}
            </span>
            Show reviewed
          </label>
        </div>
      </div>

      {/* Bulk Action Bar */}
      {someSelected && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-4)',
          padding: 'var(--space-3) var(--space-4)',
          marginTop: 'var(--space-4)',
          background: 'var(--accent-primary-dim)',
          border: '1px solid var(--accent-primary)',
          borderRadius: 'var(--radius-md)',
        }}>
          <span style={{ fontSize: '14px', color: 'var(--text-primary)' }}>
            {selected.size} flag{selected.size !== 1 ? 's' : ''} selected
          </span>
          <button
            onClick={handleBulkReview}
            disabled={bulkReviewing}
            className="btn btn-primary btn-sm"
          >
            <Check size={14} />
            {bulkReviewing ? 'Reviewing...' : 'Mark Reviewed'}
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="btn btn-ghost btn-sm"
          >
            Clear
          </button>
        </div>
      )}

      {/* Flags Table */}
      <div>
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 'var(--space-4)', tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <th style={{
                width: '40px',
                padding: 'var(--space-3) var(--space-3)',
                borderBottom: '1px solid var(--border-color)',
                background: 'var(--bg-surface)',
                textAlign: 'center',
              }}>
                <span
                  onClick={toggleSelectAll}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '16px',
                    height: '16px',
                    border: '1px solid var(--border-color)',
                    borderRadius: '3px',
                    background: allSelectableChecked ? 'var(--accent-primary)' : 'var(--bg-input)',
                    cursor: selectableFlags.length > 0 ? 'pointer' : 'default',
                    opacity: selectableFlags.length > 0 ? 1 : 0.4,
                  }}
                >
                  {allSelectableChecked && (
                    <svg viewBox="0 0 10 10" style={{ width: '10px', height: '10px', color: '#fff' }}>
                      <path d="M2 5l2 2 4-4" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                    </svg>
                  )}
                </span>
              </th>
              {[
                { label: 'Date', width: '100px' },
                { label: 'Agent', width: '90px' },
                { label: 'Session', width: '140px' },
                { label: 'Type', width: '52px' },
                { label: 'Detail', width: undefined },
                { label: 'Status', width: '100px' },
                { label: '', width: '40px', textAlign: 'center' as const },
              ].map((col, i) => (
                <th key={i} style={{
                  textAlign: (col.textAlign as any) || 'left',
                  padding: 'var(--space-3) var(--space-4)',
                  fontSize: '12px',
                  fontWeight: 600,
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                  borderBottom: '1px solid var(--border-color)',
                  background: 'var(--bg-surface)',
                  ...(col.width ? { width: col.width } : {}),
                }}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredFlags.map(flag => {
              const Icon = getFlagIcon(flag.flag_type);
              const isExpanded = expandedRow === flag.flag_id;
              return (
                <>
                  <tr
                    key={flag.flag_id}
                    onClick={() => toggleRow(flag.flag_id)}
                    style={{
                      cursor: 'pointer',
                      transition: 'background var(--transition-color)',
                      background: isExpanded ? 'var(--bg-raised)' : selected.has(flag.flag_id) ? 'var(--accent-primary-dim)' : 'transparent'
                    }}
                    onMouseEnter={(e) => {
                      if (!isExpanded && !selected.has(flag.flag_id)) e.currentTarget.style.background = 'var(--bg-raised)';
                    }}
                    onMouseLeave={(e) => {
                      if (!isExpanded && !selected.has(flag.flag_id)) e.currentTarget.style.background = 'transparent';
                    }}
                  >
                    <td
                      onClick={(e) => { e.stopPropagation(); if (!flag.reviewed) toggleSelect(flag.flag_id); }}
                      style={{
                        width: '40px',
                        padding: 'var(--space-3) var(--space-3)',
                        borderBottom: '1px solid var(--border-color)',
                        textAlign: 'center',
                        verticalAlign: 'middle',
                      }}
                    >
                      {!flag.reviewed ? (
                        <span style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          width: '16px',
                          height: '16px',
                          border: '1px solid var(--border-color)',
                          borderRadius: '3px',
                          background: selected.has(flag.flag_id) ? 'var(--accent-primary)' : 'var(--bg-input)',
                          cursor: 'pointer',
                        }}>
                          {selected.has(flag.flag_id) && (
                            <svg viewBox="0 0 10 10" style={{ width: '10px', height: '10px', color: '#fff' }}>
                              <path d="M2 5l2 2 4-4" fill="none" stroke="currentColor" strokeWidth="1.5"/>
                            </svg>
                          )}
                        </span>
                      ) : (
                        <span style={{ width: '16px', height: '16px', display: 'inline-block' }} />
                      )}
                    </td>
                    <td style={{
                      padding: 'var(--space-3) var(--space-4)',
                      borderBottom: '1px solid var(--border-color)',
                      fontSize: '14px',
                      color: 'var(--text-primary)',
                      verticalAlign: 'middle'
                    }}>
                      <span style={{ fontFamily: 'var(--font-data)', fontSize: '13px', color: 'var(--text-muted)' }}>
                        {formatDate(flag.created_at)}
                      </span>
                    </td>
                    <td style={{
                      padding: 'var(--space-3) var(--space-4)',
                      borderBottom: '1px solid var(--border-color)',
                      fontSize: '14px',
                      color: 'var(--text-primary)',
                      verticalAlign: 'middle'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                        <div style={{
                          width: '8px',
                          height: '8px',
                          borderRadius: '50%',
                          background: flag.agent_id === 'qlaude' ? 'var(--agent-1)' : flag.agent_id === 'echo' ? 'var(--agent-3)' : 'var(--agent-2)'
                        }}></div>
                        <span style={{ fontFamily: 'var(--font-data)' }}>{flag.agent_id}</span>
                      </div>
                    </td>
                    <td style={{
                      padding: 'var(--space-3) var(--space-4)',
                      borderBottom: '1px solid var(--border-color)',
                      fontSize: '14px',
                      color: 'var(--text-primary)',
                      verticalAlign: 'middle'
                    }}>
                      <span style={{ fontFamily: 'var(--font-data)', color: 'var(--accent-primary)' }}>
                        {flag.session_id}
                      </span>
                    </td>
                    <td style={{
                      padding: 'var(--space-3) var(--space-4)',
                      borderBottom: '1px solid var(--border-color)',
                      fontSize: '14px',
                      color: 'var(--text-primary)',
                      verticalAlign: 'middle'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                        <div style={{
                          width: '24px',
                          height: '24px',
                          borderRadius: 'var(--radius-sm)',
                          background: flag.flag_type === 'constraint_erosion' ? 'var(--accent-alert-dim)' : 'var(--accent-attention-dim)',
                          color: flag.flag_type === 'constraint_erosion' ? 'var(--accent-alert)' : 'var(--accent-attention)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center'
                        }}>
                          <Icon size={14} />
                        </div>
                      </div>
                    </td>
                    <td style={{
                      padding: 'var(--space-3) var(--space-4)',
                      borderBottom: '1px solid var(--border-color)',
                      fontSize: '14px',
                      color: 'var(--text-primary)',
                      verticalAlign: 'middle'
                    }}>
                      <div style={{
                        color: 'var(--text-secondary)',
                        lineHeight: 1.5
                      }}>
                        {flag.detail}
                      </div>
                    </td>
                    <td style={{
                      padding: 'var(--space-3) var(--space-4)',
                      borderBottom: '1px solid var(--border-color)',
                      fontSize: '14px',
                      color: 'var(--text-primary)',
                      verticalAlign: 'middle'
                    }}>
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 'var(--space-1)',
                        padding: '3px var(--space-2)',
                        borderRadius: 'var(--radius-sm)',
                        fontFamily: 'var(--font-body)',
                        fontSize: '13px',
                        fontWeight: 500,
                        lineHeight: 1.3,
                        background: flag.reviewed ? 'var(--accent-success-dim)' : 'var(--accent-attention-dim)',
                        color: flag.reviewed ? 'var(--accent-success)' : 'var(--accent-attention)'
                      }}>
                        {flag.reviewed ? 'Reviewed' : 'Unreviewed'}
                      </span>
                    </td>
                    <td style={{
                      padding: 'var(--space-3) var(--space-4)',
                      borderBottom: '1px solid var(--border-color)',
                      fontSize: '14px',
                      color: 'var(--text-primary)',
                      verticalAlign: 'middle',
                      textAlign: 'center'
                    }}>
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        style={{
                          width: '20px',
                          height: '20px',
                          color: 'var(--text-muted)',
                          transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                          transition: 'transform var(--transition-transform)'
                        }}
                      >
                        <polyline points="6 9 12 15 18 9"/>
                      </svg>
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr style={{ background: 'var(--bg-surface)' }}>
                      <td colSpan={8} style={{ borderBottom: '1px solid var(--border-color)' }}>
                        <div style={{ padding: 'var(--space-5)' }}>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-5)' }}>
                            <div>
                              <div style={{
                                fontSize: '12px',
                                fontWeight: 600,
                                color: 'var(--text-muted)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.5px',
                                marginBottom: 'var(--space-2)'
                              }}>
                                Full Detail
                              </div>
                              <div style={{ fontSize: '14px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                                {flag.detail}
                              </div>
                            </div>
                            <div>
                              <div style={{
                                fontSize: '12px',
                                fontWeight: 600,
                                color: 'var(--text-muted)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.5px',
                                marginBottom: 'var(--space-2)'
                              }}>
                                Flag ID
                              </div>
                              <div style={{ fontFamily: 'var(--font-data)', fontSize: '13px', color: 'var(--text-primary)' }}>
                                {flag.flag_id}
                              </div>
                            </div>
                          </div>
                          {!flag.reviewed && (
                            <div style={{ marginTop: 'var(--space-4)' }}>
                              <textarea
                                placeholder="Add review notes (optional)..."
                                value={reviewNotes[flag.flag_id] || ''}
                                onChange={(e) => setReviewNotes({...reviewNotes, [flag.flag_id]: e.target.value})}
                                style={{
                                  width: '100%',
                                  padding: 'var(--space-3)',
                                  borderRadius: 'var(--radius-md)',
                                  background: 'var(--bg-input)',
                                  border: '1px solid var(--border-color)',
                                  color: 'var(--text-primary)',
                                  fontFamily: 'var(--font-body)',
                                  fontSize: '14px',
                                  resize: 'vertical',
                                  minHeight: '60px',
                                  transition: 'border-color var(--transition-color)'
                                }}
                                onFocus={(e) => e.target.style.borderColor = 'var(--accent-primary)'}
                                onBlur={(e) => e.target.style.borderColor = 'var(--border-color)'}
                              />
                              <div style={{ display: 'flex', gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}>
                                <button
                                  onClick={() => handleMarkReviewed(flag.flag_id)}
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: 'var(--space-2)',
                                    padding: 'var(--space-2) var(--space-4)',
                                    borderRadius: 'var(--radius-md)',
                                    fontFamily: 'var(--font-body)',
                                    fontWeight: 500,
                                    fontSize: '15px',
                                    lineHeight: 1.3,
                                    border: '1px solid transparent',
                                    cursor: 'pointer',
                                    transition: 'background var(--transition-color), border-color var(--transition-color), color var(--transition-color)',
                                    background: 'var(--accent-primary)',
                                    color: '#fff',
                                    borderColor: 'var(--accent-primary)'
                                  }}
                                >
                                  Mark Reviewed
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigate(`/agents/${agentId}/sessions/${flag.session_id}`);
                                  }}
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: 'var(--space-2)',
                                    padding: 'var(--space-2) var(--space-4)',
                                    borderRadius: 'var(--radius-md)',
                                    fontFamily: 'var(--font-body)',
                                    fontWeight: 500,
                                    fontSize: '15px',
                                    lineHeight: 1.3,
                                    border: '1px solid transparent',
                                    cursor: 'pointer',
                                    transition: 'background var(--transition-color), border-color var(--transition-color), color var(--transition-color)',
                                    background: 'transparent',
                                    color: 'var(--text-primary)',
                                    borderColor: 'var(--border-color)'
                                  }}
                                >
                                  Open Session →
                                </button>
                              </div>
                            </div>
                          )}
                          {flag.reviewed && (
                            <div style={{ marginTop: 'var(--space-4)' }}>
                              <div style={{
                                fontSize: '12px',
                                fontWeight: 600,
                                color: 'var(--text-muted)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.5px',
                                marginBottom: 'var(--space-2)'
                              }}>
                                Review Info
                              </div>
                              <div style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: flag.review_note ? 'var(--space-2)' : '0' }}>
                                Reviewed{flag.reviewed_by ? ` by ${flag.reviewed_by}` : ''}{flag.reviewed_at ? ` on ${formatDate(flag.reviewed_at)}` : ''}
                              </div>
                              {flag.review_note && (
                                <div style={{
                                  fontSize: '14px',
                                  color: 'var(--text-primary)',
                                  padding: 'var(--space-3)',
                                  background: 'var(--bg-raised)',
                                  borderRadius: 'var(--radius-md)',
                                  lineHeight: 1.6,
                                  borderLeft: '3px solid var(--accent-success)'
                                }}>
                                  {flag.review_note}
                                </div>
                              )}
                              <div style={{ display: 'flex', gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigate(`/agents/${agentId}/sessions/${flag.session_id}`);
                                  }}
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: 'var(--space-2)',
                                    padding: 'var(--space-2) var(--space-4)',
                                    borderRadius: 'var(--radius-md)',
                                    fontFamily: 'var(--font-body)',
                                    fontWeight: 500,
                                    fontSize: '15px',
                                    lineHeight: 1.3,
                                    border: '1px solid transparent',
                                    cursor: 'pointer',
                                    transition: 'background var(--transition-color), border-color var(--transition-color), color var(--transition-color)',
                                    background: 'transparent',
                                    color: 'var(--text-primary)',
                                    borderColor: 'var(--border-color)'
                                  }}
                                >
                                  Open Session →
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
