import { NavLink, useParams } from 'react-router-dom';
import { useAgentBadges } from '../../hooks/useAgentBadges';

export default function AgentSubNav() {
  const { agentId } = useParams<{ agentId: string }>();
  const { pendingProposals, unreviewedFlags } = useAgentBadges();

  if (!agentId) return null;

  const tabs = [
    { path: `/agents/${agentId}`, label: 'Overview', end: true },
    { path: `/agents/${agentId}/trajectories`, label: 'Trajectories' },
    { path: `/agents/${agentId}/sessions`, label: 'Sessions' },
    { path: `/agents/${agentId}/co-activation`, label: 'Co-Activation' },
    { path: `/agents/${agentId}/proposals`, label: 'Proposals', count: pendingProposals },
    { path: `/agents/${agentId}/flags`, label: 'Flags', count: unreviewedFlags },
  ];

  return (
    <nav className="agent-subnav">
      {tabs.map(({ path, label, end, count }) => (
        <NavLink
          key={path}
          to={path}
          className={({ isActive }) => `agent-subnav-tab ${isActive ? 'active' : ''}`}
          end={end}
        >
          {label}
          {count != null && count > 0 && (
            <span className="subnav-badge">{count}</span>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
