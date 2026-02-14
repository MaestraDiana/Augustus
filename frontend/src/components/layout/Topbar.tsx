import { Bell, Sun, Moon, Activity, Play, Pause } from 'lucide-react';
import { useTheme } from '../../hooks/useTheme';
import StatusChip from '../ui/StatusChip';
import UpdateBanner from '../ui/UpdateBanner';
import { useState, useEffect } from 'react';
import { api } from '../../api/client';

interface TopbarProps {
  pageTitle?: string;
}

export default function Topbar({ pageTitle }: TopbarProps) {
  const { theme, toggleTheme } = useTheme();
  const [orchestratorStatus, setOrchestratorStatus] = useState<'running' | 'paused' | 'error' | 'idle'>('idle');
  const [activeSessions, setActiveSessions] = useState(0);
  const [budget, setBudget] = useState({ used: 0, total: 25 });
  const [isTogglingOrchestrator, setIsTogglingOrchestrator] = useState(false);

  // Poll orchestrator status every 10 seconds
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const status = await api.orchestrator.status();
        setOrchestratorStatus(status.status);
        setActiveSessions(status.active_sessions || 0);
      } catch (error) {
        console.error('Failed to fetch orchestrator status:', error);
        setOrchestratorStatus('error');
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  // Poll budget data every 30 seconds
  useEffect(() => {
    const fetchBudget = async () => {
      try {
        const usage = await api.usage.summary();
        setBudget({
          used: usage.total_cost || 0,
          total: usage.budget_limit || 25,
        });
      } catch (error) {
        console.error('Failed to fetch budget data:', error);
        // Silently keep defaults on error
      }
    };

    fetchBudget();
    const interval = setInterval(fetchBudget, 30000);
    return () => clearInterval(interval);
  }, []);

  const budgetPercentage = (budget.used / budget.total) * 100;
  const budgetColor = budgetPercentage > 75 ? 'red' : budgetPercentage > 50 ? 'amber' : 'green';

  const handleOrchestratorToggle = async () => {
    if (isTogglingOrchestrator) return;

    try {
      setIsTogglingOrchestrator(true);

      if (orchestratorStatus === 'running') {
        await api.orchestrator.pause();
        setOrchestratorStatus('paused');
      } else {
        await api.orchestrator.resume();
        setOrchestratorStatus('running');
      }
    } catch (error) {
      console.error('Failed to toggle orchestrator:', error);
      // Don't change status on error - keep the current state
    } finally {
      setIsTogglingOrchestrator(false);
    }
  };

  return (
    <>
    <UpdateBanner />
    <header className="topbar">
      <div className="topbar-left">
        {pageTitle && <h1 className="page-title">{pageTitle}</h1>}
      </div>

      <div className="topbar-right">
        <button
          className="orchestrator-control-btn"
          onClick={handleOrchestratorToggle}
          disabled={isTogglingOrchestrator}
          title={orchestratorStatus === 'running' ? 'Pause orchestrator' : 'Start orchestrator'}
        >
          {orchestratorStatus === 'running' ? <Pause size={14} /> : <Play size={14} />}
          <StatusChip
            status={orchestratorStatus}
            label={`Orchestrator ${orchestratorStatus}`}
          />
        </button>

        <div className="status-chip">
          <Activity size={14} />
          {activeSessions} active
        </div>

        <div className="budget-chip">
          <span>${budget.used.toFixed(2)} / ${budget.total}</span>
          <div className="budget-bar">
            <div className={`budget-fill ${budgetColor}`} style={{ width: `${budgetPercentage}%` }} />
          </div>
        </div>

        <button className="notification-btn" title="Notifications">
          <Bell size={20} />
        </button>

        <div className="mode-switcher">
          <button
            className={`mode-btn ${theme === 'light' ? 'active' : ''}`}
            onClick={() => toggleTheme()}
            title="Light mode"
          >
            <Sun size={16} />
          </button>
          <button
            className={`mode-btn ${theme === 'dark' ? 'active' : ''}`}
            onClick={() => toggleTheme()}
            title="Dark mode"
          >
            <Moon size={16} />
          </button>
        </div>
      </div>
    </header>
    </>
  );
}
