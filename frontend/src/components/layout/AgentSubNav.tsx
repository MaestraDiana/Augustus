import { NavLink, useParams } from 'react-router-dom';

export default function AgentSubNav() {
  const { agentId } = useParams<{ agentId: string }>();

  if (!agentId) return null;

  const tabs = [
    { path: `/agents/${agentId}`, label: 'Overview', end: true },
    { path: `/agents/${agentId}/trajectories`, label: 'Trajectories' },
    { path: `/agents/${agentId}/sessions`, label: 'Sessions' },
    { path: `/agents/${agentId}/co-activation`, label: 'Co-Activation' },
    { path: `/agents/${agentId}/proposals`, label: 'Proposals' },
    { path: `/agents/${agentId}/flags`, label: 'Flags' },
  ];

  return (
    <nav className="agent-subnav">
      {tabs.map(({ path, label, end }) => (
        <NavLink
          key={path}
          to={path}
          className={({ isActive }) => `agent-subnav-tab ${isActive ? 'active' : ''}`}
          end={end}
        >
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
