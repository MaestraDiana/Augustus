import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Edit,
  Play,
  Pause,
  Copy,
  Download,
  Trash2,
  Plus,
  Users,
} from 'lucide-react';
import Badge from '../components/ui/Badge';
import Modal from '../components/ui/Modal';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import { api } from '../api/client';
import { timeAgo } from '../utils/time';
import { getAgentColor, DEFAULT_MODEL } from '../utils/constants';
import type { Agent } from '../types';

type FilterStatus = 'all' | 'active' | 'idle' | 'paused' | 'error';

const DeleteModal: React.FC<{
  isOpen: boolean;
  agentId: string;
  onClose: () => void;
  onConfirm: (mode: 'archive' | 'hard') => void;
}> = ({ isOpen, agentId, onClose, onConfirm }) => {
  const [deleteMode, setDeleteMode] = useState<'archive' | 'hard'>('archive');
  const [confirmText, setConfirmText] = useState('');

  const handleConfirm = () => {
    if (deleteMode === 'hard' && confirmText !== agentId) return;
    onConfirm(deleteMode);
    setConfirmText('');
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Delete Agent" width="540px">
      <div style={{ marginBottom: 'var(--space-5)' }}>
        <p style={{ color: 'var(--text-secondary)', marginBottom: 'var(--space-4)' }}>
          Choose how to delete agent <code className="font-mono" style={{ background: 'var(--bg-raised)', padding: '2px 6px', borderRadius: 'var(--radius-sm)' }}>{agentId}</code>
        </p>

        <div className="delete-options">
          <div
            className={`delete-option ${deleteMode === 'archive' ? 'selected' : ''}`}
            onClick={() => setDeleteMode('archive')}
          >
            <div className="delete-option-radio" />
            <div className="delete-option-content">
              <div className="delete-option-title">Archive (recommended)</div>
              <div className="delete-option-desc">
                Mark agent as deleted. All data preserved in database, can be restored.
              </div>
            </div>
          </div>

          <div
            className={`delete-option destructive ${deleteMode === 'hard' ? 'selected' : ''}`}
            onClick={() => setDeleteMode('hard')}
          >
            <div className="delete-option-radio" />
            <div className="delete-option-content">
              <div className="delete-option-title">Permanent delete</div>
              <div className="delete-option-desc">
                Remove all agent data from database. This cannot be undone.
              </div>
            </div>
          </div>
        </div>

        {deleteMode === 'hard' && (
          <div className="confirm-input-wrapper">
            <div className="confirm-input-label">
              Type <code>{agentId}</code> to confirm permanent deletion:
            </div>
            <input
              type="text"
              className="form-input mono"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={agentId}
            />
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 'var(--space-3)', justifyContent: 'flex-end' }}>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="destructive"
          onClick={handleConfirm}
          disabled={deleteMode === 'hard' && confirmText !== agentId}
        >
          Delete
        </Button>
      </div>
    </Modal>
  );
};

export default function AgentList() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<FilterStatus>('all');
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingAgent, setDeletingAgent] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchAgents = async () => {
      try {
        const data = await api.agents.list();
        if (!cancelled) setAgents(data);
      } catch (err) {
        if (!cancelled) console.error('Failed to load agents:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchAgents();
    const interval = setInterval(fetchAgents, 15000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const filteredAgents = agents.filter((agent) => {
    if (filter === 'all') return true;
    return agent.status === filter;
  });

  const formatLastActive = (timestamp: string | null) => {
    if (!timestamp) return 'never';
    return timeAgo(timestamp);
  };

  const getFilterCounts = () => {
    return {
      all: agents.length,
      active: agents.filter((a) => a.status === 'active').length,
      idle: agents.filter((a) => a.status === 'idle').length,
      paused: agents.filter((a) => a.status === 'paused').length,
      error: agents.filter((a) => a.status === 'error').length,
    };
  };

  const counts = getFilterCounts();

  const openDeleteModal = (agentId: string) => {
    setSelectedAgent(agentId);
    setDeleteModalOpen(true);
  };

  const handleDelete = async (mode: 'archive' | 'hard') => {
    if (!selectedAgent) return;
    setDeletingAgent(selectedAgent);
    try {
      await api.agents.delete(selectedAgent, mode === 'hard');
      const data = await api.agents.list();
      setAgents(data);
    } catch (err) {
      console.error('Failed to delete agent:', err);
    } finally {
      setDeletingAgent(null);
    }
  };

  const handleToggle = async (agentId: string, isActive: boolean) => {
    try {
      if (isActive) {
        await api.agents.pause(agentId);
      } else {
        await api.agents.resume(agentId);
      }
      // Refresh agents list
      const data = await api.agents.list();
      setAgents(data);
    } catch (err) {
      console.error('Failed to toggle agent:', err);
    }
  };

  const handleClone = async (agentId: string) => {
    const suffix = Date.now().toString(36).slice(-4);
    const newId = `${agentId}-clone-${suffix}`;
    try {
      const newAgent = await api.agents.clone(agentId, newId);
      navigate(`/agents/${newAgent.agent_id}`);
    } catch (err) {
      console.error('Failed to clone agent:', err);
    }
  };

  const handleExport = async (agentId: string) => {
    try {
      await api.agents.export(agentId);
    } catch (err) {
      console.error('Failed to export agent:', err);
    }
  };

  if (loading) {
    return (
      <div style={{ color: 'var(--text-secondary)' }}>
        Loading agents...
      </div>
    );
  }

  return (
    <div>
      <div className="section-header">
        <h2 className="section-title">All Agents</h2>
        <Link to="/agents/new">
          <button className="btn btn-primary">
            <Plus size={16} />
            Create Agent
          </button>
        </Link>
      </div>

      {agents.length > 0 && (
        <div className="filter-bar">
          <div className="filter-chips">
            <div
              className={`filter-chip ${filter === 'all' ? 'active' : ''}`}
              onClick={() => setFilter('all')}
            >
              All <span className="count">{counts.all}</span>
            </div>
            <div
              className={`filter-chip ${filter === 'active' ? 'active' : ''}`}
              onClick={() => setFilter('active')}
            >
              Active <span className="count">{counts.active}</span>
            </div>
            <div
              className={`filter-chip ${filter === 'idle' ? 'active' : ''}`}
              onClick={() => setFilter('idle')}
            >
              Idle <span className="count">{counts.idle}</span>
            </div>
            <div
              className={`filter-chip ${filter === 'paused' ? 'active' : ''}`}
              onClick={() => setFilter('paused')}
            >
              Paused <span className="count">{counts.paused}</span>
            </div>
          </div>
        </div>
      )}

      {agents.length === 0 ? (
        <EmptyState
          icon={<Users size={56} />}
          title="No Agents"
          message="Create your first agent to begin identity research sessions."
          actionLabel="Create Agent"
          onAction={() => navigate('/agents/new')}
        />
      ) : filteredAgents.length === 0 ? (
        <EmptyState
          icon={<Users size={56} />}
          title="No Matching Agents"
          message="No agents match the current filter. Try a different status filter."
        />
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Status</th>
              <th>Sessions</th>
              <th>Last Active</th>
              <th>Model</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredAgents.map((agent) => {
              const model = agent.model_override || DEFAULT_MODEL;
              const isActive = agent.status === 'active';
              const isDeleting = deletingAgent === agent.agent_id;

              return (
                <tr
                  key={agent.agent_id}
                  style={isDeleting ? {
                    opacity: 0.35,
                    filter: 'blur(1px)',
                    pointerEvents: 'none',
                    transition: 'opacity 200ms ease, filter 200ms ease',
                  } : {
                    transition: 'opacity 200ms ease, filter 200ms ease',
                  }}
                >
                  <td>
                    <div className="agent-cell">
                      <span
                        className="agent-color-dot"
                        style={{ background: getAgentColor(agent.agent_id, agents) }}
                      />
                      <div>
                        <div className="agent-name">
                          {isDeleting ? 'Deleting...' : agent.agent_id}
                        </div>
                        <div className="agent-desc">{agent.description}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <Badge variant={agent.status}>{agent.status}</Badge>
                  </td>
                  <td className="font-mono">{agent.session_count}</td>
                  <td className="text-secondary">{formatLastActive(agent.last_active)}</td>
                  <td className="font-mono text-secondary">{model}</td>
                  <td>
                    <div className="action-cell">
                      <Link to={`/agents/${agent.agent_id}/edit`}>
                        <button className="action-btn" title="Edit">
                          <Edit size={16} />
                        </button>
                      </Link>
                      <button
                        className="action-btn"
                        title={isActive ? 'Pause' : 'Resume'}
                        onClick={() => handleToggle(agent.agent_id, isActive)}
                      >
                        {isActive ? <Pause size={16} /> : <Play size={16} />}
                      </button>
                      <button
                        className="action-btn"
                        title="Clone"
                        onClick={() => handleClone(agent.agent_id)}
                      >
                        <Copy size={16} />
                      </button>
                      <button
                        className="action-btn"
                        title="Export"
                        onClick={() => handleExport(agent.agent_id)}
                      >
                        <Download size={16} />
                      </button>
                      <button
                        className="action-btn destructive"
                        title="Delete"
                        onClick={() => openDeleteModal(agent.agent_id)}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <DeleteModal
        isOpen={deleteModalOpen}
        agentId={selectedAgent || ''}
        onClose={() => setDeleteModalOpen(false)}
        onConfirm={handleDelete}
      />
    </div>
  );
}
