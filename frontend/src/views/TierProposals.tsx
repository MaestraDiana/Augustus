import React, { useState } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { useAgentBadges } from '../hooks/useAgentBadges';
import { useDataEvents } from '../hooks/useEventStream';
import { formatDate } from '../utils/time';
import { toggleSetItem } from '../utils/collections';
import type { TierProposal } from '../types';

// Backend response includes a tier field not in the TypeScript type
interface TierProposalWithTier extends TierProposal {
  tier: number;
}

export default function TierProposals() {
  const { agentId } = useParams<{ agentId: string }>();
  const [selectedProposals, setSelectedProposals] = useState<Set<string>>(new Set());
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [rejectFormVisible, setRejectFormVisible] = useState<Set<string>>(new Set());

  const { refreshBadges } = useAgentBadges();

  const { data, loading, error, refetch } = useApi<TierProposalWithTier[]>(
    () => api.proposals.list(agentId!) as Promise<TierProposalWithTier[]>,
    [agentId],
  );

  // Auto-refresh when proposals change externally (e.g. via MCP)
  useDataEvents(['proposal_resolved', 'proposal_created'], refetch, agentId);

  const proposals = data ?? [];

  const handleApprove = async (proposalId: string) => {
    if (!agentId) return;
    try {
      await api.proposals.approve(agentId, proposalId);
      refetch();
      refreshBadges();
    } catch (err) {
      console.error('Failed to approve proposal:', err);
    }
  };

  const handleReject = async (proposalId: string, rationale?: string) => {
    if (!agentId) return;
    try {
      await api.proposals.reject(agentId, proposalId, rationale);
      refetch();
      refreshBadges();
    } catch (err) {
      console.error('Failed to reject proposal:', err);
    }
  };

  const pendingCount = proposals.filter(p => p.status === 'pending').length;
  const approvedLast30 = proposals.filter(p => p.status === 'approved' || p.status === 'auto_approved').length;
  const rejectedLast30 = proposals.filter(p => p.status === 'rejected').length;
  const autoApprovedCount = proposals.filter(p => p.status === 'auto_approved').length;
  const totalResolved = approvedLast30 + rejectedLast30;
  const autoApprovalRate = totalResolved > 0 ? Math.round((autoApprovedCount / totalResolved) * 100) : 0;

  if (loading) {
    return (
      <div style={{ padding: 'var(--space-6)', color: 'var(--text-secondary)' }}>
        Loading proposals...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        padding: 'var(--space-6)',
        background: 'var(--accent-alert-dim)',
        border: '1px solid var(--accent-alert)',
        borderRadius: 'var(--radius-md)',
        color: 'var(--accent-alert)',
        margin: 'var(--space-4)'
      }}>
        <strong>Error:</strong> {error}
      </div>
    );
  }

  if (proposals.length === 0) {
    return (
      <div style={{
        padding: 'var(--space-8)',
        textAlign: 'center',
        color: 'var(--text-muted)'
      }}>
        <div style={{ marginBottom: 'var(--space-3)', fontSize: '48px' }}>📋</div>
        <div style={{ fontSize: '16px', marginBottom: 'var(--space-2)', color: 'var(--text-secondary)' }}>
          No tier proposals
        </div>
        <div style={{ fontSize: '14px' }}>
          Proposals are generated when agents request basin modifications.
        </div>
      </div>
    );
  }

  const toggleRow = (id: string) => {
    setExpandedRows(prev => toggleSetItem(prev, id));
  };

  const toggleSelect = (id: string) => {
    setSelectedProposals(prev => toggleSetItem(prev, id));
  };

  const toggleSelectAll = () => {
    const pendingIds = proposals.filter(p => p.status === 'pending').map(p => p.proposal_id);
    if (selectedProposals.size === pendingIds.length) {
      setSelectedProposals(new Set());
    } else {
      setSelectedProposals(new Set(pendingIds));
    }
  };

  const toggleRejectForm = (id: string) => {
    setRejectFormVisible(prev => toggleSetItem(prev, id));
  };

  const getTypeIcon = (type: string) => {
    const icons: Record<string, string> = {
      modify: 'M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z',
      remove: 'M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2',
      add: 'M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zM12 8v8M8 12h8',
    };
    return icons[type] || icons.modify;
  };

  const getStatusBadgeClass = (status: string) => {
    const classes: Record<string, string> = {
      pending: 'badge-pending',
      approved: 'badge-approved',
      auto_approved: 'badge-auto-approved',
      rejected: 'badge-rejected',
    };
    return classes[status] || 'badge';
  };

  const formatStatus = (status: string) => {
    const labels: Record<string, string> = {
      pending: 'Pending',
      approved: 'Approved',
      auto_approved: 'Auto-approved',
      rejected: 'Rejected',
    };
    return labels[status] || status;
  };

  return (
    <div>
      {/* Summary & Filters */}
      <div className="proposals-header">
        {/* Summary Cards */}
        <div style={{ display: 'flex', gap: 'var(--space-4)', marginBottom: 'var(--space-5)', flexWrap: 'wrap' }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
            padding: 'var(--space-3) var(--space-4)', background: 'var(--bg-raised)',
            borderRadius: 'var(--radius-md)', minWidth: '140px'
          }}>
            <div style={{
              width: '36px', height: '36px', borderRadius: 'var(--radius-md)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--accent-attention-dim)', color: 'var(--accent-attention)'
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontFamily: 'var(--font-data)', fontSize: '20px', fontWeight: 500, color: 'var(--text-primary)' }}>{pendingCount}</span>
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Pending</span>
            </div>
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
            padding: 'var(--space-3) var(--space-4)', background: 'var(--bg-raised)',
            borderRadius: 'var(--radius-md)', minWidth: '140px'
          }}>
            <div style={{
              width: '36px', height: '36px', borderRadius: 'var(--radius-md)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--accent-identity-dim)', color: 'var(--accent-identity)'
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontFamily: 'var(--font-data)', fontSize: '20px', fontWeight: 500, color: 'var(--text-primary)' }}>{pendingCount}</span>
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Tier 2 Pending</span>
            </div>
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
            padding: 'var(--space-3) var(--space-4)', background: 'var(--bg-raised)',
            borderRadius: 'var(--radius-md)', minWidth: '140px'
          }}>
            <div style={{
              width: '36px', height: '36px', borderRadius: 'var(--radius-md)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--accent-success-dim)', color: 'var(--accent-success)'
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontFamily: 'var(--font-data)', fontSize: '20px', fontWeight: 500, color: 'var(--text-primary)' }}>{approvedLast30}</span>
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Approved (30d)</span>
            </div>
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
            padding: 'var(--space-3) var(--space-4)', background: 'var(--bg-raised)',
            borderRadius: 'var(--radius-md)', minWidth: '140px'
          }}>
            <div style={{
              width: '36px', height: '36px', borderRadius: 'var(--radius-md)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--accent-alert-dim)', color: 'var(--accent-alert)'
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontFamily: 'var(--font-data)', fontSize: '20px', fontWeight: 500, color: 'var(--text-primary)' }}>{rejectedLast30}</span>
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Rejected (30d)</span>
            </div>
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
            padding: 'var(--space-3) var(--space-4)', background: 'var(--bg-raised)',
            borderRadius: 'var(--radius-md)', minWidth: '140px'
          }}>
            <div style={{
              width: '36px', height: '36px', borderRadius: 'var(--radius-md)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--accent-primary-dim)', color: 'var(--accent-primary)'
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontFamily: 'var(--font-data)', fontSize: '20px', fontWeight: 500, color: 'var(--text-primary)' }}>{autoApprovalRate}%</span>
              <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Auto-approval rate</span>
            </div>
          </div>
        </div>

        {/* Filters */}
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-4)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-muted)', fontWeight: 500 }}>Status</span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)',
                padding: 'var(--space-1) var(--space-3)', borderRadius: '100px',
                background: 'var(--accent-primary-dim)', border: '1px solid var(--accent-primary)',
                fontSize: '13px', color: 'var(--accent-primary)', cursor: 'pointer'
              }}>All</div>
              <div style={{
                display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)',
                padding: 'var(--space-1) var(--space-3)', borderRadius: '100px',
                background: 'var(--bg-raised)', border: '1px solid var(--border-color)',
                fontSize: '13px', color: 'var(--text-secondary)', cursor: 'pointer'
              }}>Pending</div>
            </div>
          </div>

          {selectedProposals.size > 0 && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
              padding: 'var(--space-3) var(--space-4)',
              background: 'var(--accent-primary-dim)',
              borderRadius: 'var(--radius-md)',
              marginLeft: 'auto'
            }}>
              <span style={{ fontSize: '14px', color: 'var(--accent-primary)', fontWeight: 500 }}>
                {selectedProposals.size} selected
              </span>
              <button className="btn btn-success btn-sm">Approve All</button>
              <button className="btn btn-danger btn-sm">Reject All</button>
            </div>
          )}
        </div>
      </div>

      {/* Table */}
      <div>
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 'var(--space-4)' }}>
          <thead>
            <tr>
              {['checkbox', 'Date', 'Basin', 'Tier', 'Type', 'Status', 'Rationale', ''].map((label, i) => {
                const thStyle: React.CSSProperties = {
                  textAlign: 'left', padding: 'var(--space-3) var(--space-3)',
                  fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)',
                  textTransform: 'uppercase', letterSpacing: '0.5px',
                  borderBottom: '1px solid var(--border-color)',
                  background: 'var(--bg-surface)',
                  whiteSpace: 'nowrap',
                };
                // Rationale takes remaining space; checkbox & chevron are narrow
                if (label === 'Rationale') { thStyle.width = '100%'; thStyle.whiteSpace = undefined; }
                if (label === 'checkbox' || label === '') { thStyle.width = '40px'; thStyle.padding = 'var(--space-3) var(--space-2)'; }
                return (
                  <th key={i} style={thStyle}>
                    {label === 'checkbox' ? (
                      <div style={{
                        width: '18px', height: '18px', border: '1px solid var(--border-color)',
                        borderRadius: '3px', background: selectedProposals.size > 0 ? 'var(--accent-primary)' : 'var(--bg-input)',
                        cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        borderColor: selectedProposals.size > 0 ? 'var(--accent-primary)' : 'var(--border-color)'
                      }}
                        onClick={toggleSelectAll}>
                        {selectedProposals.size > 0 && (
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" width="12" height="12">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </div>
                    ) : label}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {proposals.map((proposal) => (
              <React.Fragment key={proposal.proposal_id}>
                <tr
                  style={{
                    cursor: 'pointer',
                    background: expandedRows.has(proposal.proposal_id) ? 'var(--bg-raised)' :
                      selectedProposals.has(proposal.proposal_id) ? 'var(--accent-primary-dim)' : 'transparent'
                  }}
                  onClick={() => toggleRow(proposal.proposal_id)}
                >
                  {/* Checkbox */}
                  <td style={{ padding: 'var(--space-3) var(--space-2)', borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' }}
                    onClick={(e) => e.stopPropagation()}>
                    {proposal.status === 'pending' && (
                      <div style={{
                        width: '18px', height: '18px', border: '1px solid var(--border-color)',
                        borderRadius: '3px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: selectedProposals.has(proposal.proposal_id) ? 'var(--accent-primary)' : 'var(--bg-input)',
                        borderColor: selectedProposals.has(proposal.proposal_id) ? 'var(--accent-primary)' : 'var(--border-color)'
                      }}
                        onClick={() => toggleSelect(proposal.proposal_id)}>
                        {selectedProposals.has(proposal.proposal_id) && (
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" width="12" height="12">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </div>
                    )}
                  </td>
                  {/* Date */}
                  <td style={{ padding: 'var(--space-3)', borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' }}>
                    <span style={{ fontFamily: 'var(--font-data)', fontSize: '13px', color: 'var(--text-muted)' }}>
                      {formatDate(proposal.created_at)}
                    </span>
                  </td>
                  {/* Basin */}
                  <td style={{ padding: 'var(--space-3)', borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' }}>
                    <span style={{ fontFamily: 'var(--font-data)', fontSize: '14px' }}>{proposal.basin_name}</span>
                  </td>
                  {/* Tier */}
                  <td style={{ padding: 'var(--space-3)', borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' }}>
                    <span className={`badge badge-tier-${proposal.tier}`}>Tier {proposal.tier}</span>
                  </td>
                  {/* Type */}
                  <td style={{ padding: 'var(--space-3)', borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <div style={{
                        width: '24px', height: '24px', borderRadius: 'var(--radius-sm)', flexShrink: 0,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: proposal.proposal_type === 'modify' ? 'var(--accent-identity-dim)' :
                          proposal.proposal_type === 'remove' ? 'var(--accent-alert-dim)' : 'var(--accent-success-dim)',
                        color: proposal.proposal_type === 'modify' ? 'var(--accent-identity)' :
                          proposal.proposal_type === 'remove' ? 'var(--accent-alert)' : 'var(--accent-success)'
                      }}>
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                          <path d={getTypeIcon(proposal.proposal_type)} />
                        </svg>
                      </div>
                      <span style={{ fontSize: '13px' }}>{proposal.proposal_type.charAt(0).toUpperCase() + proposal.proposal_type.slice(1)}</span>
                    </div>
                  </td>
                  {/* Status */}
                  <td style={{ padding: 'var(--space-3)', borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' }}>
                    <span className={getStatusBadgeClass(proposal.status)}>{formatStatus(proposal.status)}</span>
                  </td>
                  {/* Rationale — this column wraps freely */}
                  <td style={{ padding: 'var(--space-3)', borderBottom: '1px solid var(--border-color)' }}>
                    <span style={{
                      color: 'var(--text-secondary)', fontSize: '13px', lineHeight: 1.5,
                      display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical',
                      overflow: 'hidden',
                    }}>
                      {proposal.rationale}
                    </span>
                  </td>
                  {/* Chevron */}
                  <td style={{ padding: 'var(--space-3) var(--space-2)', borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' }}>
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
                      stroke="currentColor" strokeWidth="2" width="18" height="18"
                      style={{
                        color: 'var(--text-muted)', display: 'block',
                        transform: expandedRows.has(proposal.proposal_id) ? 'rotate(180deg)' : 'none',
                        transition: 'transform var(--transition-transform)'
                      }}
                    >
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </td>
                </tr>

                {expandedRows.has(proposal.proposal_id) && (
                  <tr style={{ background: 'var(--bg-surface)' }}>
                    <td colSpan={8} style={{ padding: 'var(--space-5)', borderBottom: '1px solid var(--border-color)' }}>
                      <div>
                        <div style={{ marginBottom: 'var(--space-4)' }}>
                          <div style={{
                            fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)',
                            textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 'var(--space-2)'
                          }}>Full Rationale</div>
                          <div style={{ fontSize: '14px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                            {proposal.rationale}
                          </div>
                        </div>

                        <div style={{ marginBottom: 'var(--space-4)' }}>
                          <div style={{
                            fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)',
                            textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 'var(--space-2)'
                          }}>Session</div>
                          <a href="#" style={{ fontFamily: 'var(--font-data)', color: 'var(--accent-primary)' }}>
                            {proposal.session_id}
                          </a>
                        </div>

                        {proposal.status === 'pending' && (
                          <div style={{ display: 'flex', gap: 'var(--space-3)', marginTop: 'var(--space-4)' }}>
                            <button
                              className="btn btn-success btn-sm"
                              onClick={() => handleApprove(proposal.proposal_id)}
                            >
                              Approve
                            </button>
                            <button
                              className="btn btn-danger btn-sm"
                              onClick={() => toggleRejectForm(proposal.proposal_id)}
                            >
                              Reject
                            </button>
                            <button className="btn btn-secondary btn-sm">Defer</button>
                          </div>
                        )}
                        {rejectFormVisible.has(proposal.proposal_id) && (
                          <div style={{ marginTop: 'var(--space-3)' }}>
                            <textarea
                              className="form-textarea"
                              placeholder="Rejection rationale (optional)"
                              rows={3}
                              id={`reject-rationale-${proposal.proposal_id}`}
                            />
                            <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-2)' }}>
                              <button
                                className="btn btn-danger btn-sm"
                                onClick={() => {
                                  const textarea = document.getElementById(`reject-rationale-${proposal.proposal_id}`) as HTMLTextAreaElement;
                                  handleReject(proposal.proposal_id, textarea?.value);
                                  toggleRejectForm(proposal.proposal_id);
                                }}
                              >
                                Confirm Rejection
                              </button>
                              <button
                                className="btn btn-ghost btn-sm"
                                onClick={() => toggleRejectForm(proposal.proposal_id)}
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
