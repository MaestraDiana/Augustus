import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import AgentSubNav from './AgentSubNav';
import { AgentBadgeProvider } from '../../hooks/useAgentBadges';

export default function Shell() {
  const location = useLocation();

  // Determine if we should show AgentSubNav
  const showAgentSubNav = /^\/agents\/[^/]+/.test(location.pathname) &&
                          !location.pathname.includes('/new') &&
                          !location.pathname.includes('/edit');

  // Extract page title from route
  const getPageTitle = () => {
    if (location.pathname === '/') return 'Dashboard';
    if (location.pathname === '/agents') return 'Agents';
    if (location.pathname === '/search') return 'Search';
    if (location.pathname === '/usage') return 'Usage';
    if (location.pathname === '/settings') return 'Settings';
    if (location.pathname.includes('/agents/')) {
      const segments = location.pathname.split('/');
      const agentId = segments[2];
      if (location.pathname.endsWith('/trajectories')) return `${agentId} — Trajectories`;
      if (location.pathname.endsWith('/sessions')) return `${agentId} — Sessions`;
      if (location.pathname.endsWith('/co-activation')) return `${agentId} — Co-Activation`;
      if (location.pathname.endsWith('/proposals')) return `${agentId} — Proposals`;
      if (location.pathname.endsWith('/flags')) return `${agentId} — Flags`;
      if (location.pathname.endsWith('/edit')) return `Edit ${agentId}`;
      return agentId;
    }
    return '';
  };

  return (
    <div className="app">
      <Sidebar />
      <div className="main-content">
        <Topbar pageTitle={getPageTitle()} />
        {showAgentSubNav ? (
          <AgentBadgeProvider>
            <AgentSubNav />
            <div className="page-content">
              <Outlet />
            </div>
          </AgentBadgeProvider>
        ) : (
          <div className="page-content">
            <Outlet />
          </div>
        )}
      </div>
    </div>
  );
}
