import { NavLink } from 'react-router-dom';
import { Home, Users, Search, BarChart2, Settings, PanelLeft } from 'lucide-react';
import { useState } from 'react';

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);

  const navItems = [
    { path: '/', icon: Home, label: 'Dashboard' },
    { path: '/agents', icon: Users, label: 'Agents' },
    { path: '/search', icon: Search, label: 'Search' },
    { path: '/usage', icon: BarChart2, label: 'Usage' },
    { path: '/settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-header">
        <div className="wordmark">
          <span className="wordmark-text">Augustus</span>
          <span className="period">.</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        <div className="nav-section-label">Main</div>
        {navItems.map(({ path, icon: Icon, label }) => (
          <NavLink
            key={path}
            to={path}
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            end={path === '/'}
          >
            <Icon />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <button className="collapse-btn" onClick={() => setCollapsed(!collapsed)}>
          <PanelLeft />
          <span>Collapse</span>
        </button>
      </div>
    </aside>
  );
}
