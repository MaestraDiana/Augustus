import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';

interface BadgeCounts {
  pendingProposals: number;
  unreviewedFlags: number;
}

interface AgentBadgeContextValue extends BadgeCounts {
  refreshBadges: () => void;
}

const AgentBadgeContext = createContext<AgentBadgeContextValue>({
  pendingProposals: 0,
  unreviewedFlags: 0,
  refreshBadges: () => {},
});

export function AgentBadgeProvider({ children }: { children: ReactNode }) {
  const { agentId } = useParams<{ agentId: string }>();
  const [counts, setCounts] = useState<BadgeCounts>({ pendingProposals: 0, unreviewedFlags: 0 });

  const refreshBadges = useCallback(() => {
    if (!agentId) return;

    api.proposals.list(agentId).then(proposals => {
      const pending = proposals.filter(p => p.status === 'pending').length;
      setCounts(prev => ({ ...prev, pendingProposals: pending }));
    }).catch(() => {});

    api.flags.list(agentId).then(flags => {
      const unreviewed = flags.filter(f => !f.reviewed).length;
      setCounts(prev => ({ ...prev, unreviewedFlags: unreviewed }));
    }).catch(() => {});
  }, [agentId]);

  useEffect(() => {
    refreshBadges();
  }, [refreshBadges]);

  return (
    <AgentBadgeContext.Provider value={{ ...counts, refreshBadges }}>
      {children}
    </AgentBadgeContext.Provider>
  );
}

export function useAgentBadges() {
  return useContext(AgentBadgeContext);
}
