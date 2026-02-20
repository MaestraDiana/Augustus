import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Shell from './components/layout/Shell';
import Dashboard from './views/Dashboard';
import AgentList from './views/AgentList';
import AgentForm from './views/AgentForm';
import AgentOverview from './views/AgentOverview';
import TrajectoryDashboard from './views/TrajectoryDashboard';
import SessionList from './views/SessionList';
import SessionDetail from './views/SessionDetail';
import CoActivationNetwork from './views/CoActivationNetwork';
import TierProposals from './views/TierProposals';
import EvaluatorFlags from './views/EvaluatorFlags';
import Annotations from './views/Annotations';
import Search from './views/Search';
import Usage from './views/Usage';
import Settings from './views/Settings';
import EvaluatorPromptManager from './views/EvaluatorPromptManager';
import { EventStreamProvider } from './hooks/useEventStream';

function App() {
  return (
    <EventStreamProvider>
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/agents" element={<AgentList />} />
          <Route path="/agents/new" element={<AgentForm mode="create" />} />
          <Route path="/agents/:agentId" element={<AgentOverview />} />
          <Route path="/agents/:agentId/edit" element={<AgentForm mode="edit" />} />
          <Route path="/agents/:agentId/trajectories" element={<TrajectoryDashboard />} />
          <Route path="/agents/:agentId/sessions" element={<SessionList />} />
          <Route path="/agents/:agentId/sessions/:sessionId" element={<SessionDetail />} />
          <Route path="/agents/:agentId/co-activation" element={<CoActivationNetwork />} />
          <Route path="/agents/:agentId/proposals" element={<TierProposals />} />
          <Route path="/agents/:agentId/flags" element={<EvaluatorFlags />} />
          <Route path="/agents/:agentId/annotations" element={<Annotations />} />
          <Route path="/search" element={<Search />} />
          <Route path="/usage" element={<Usage />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/evaluator-prompts" element={<EvaluatorPromptManager />} />
        </Route>
      </Routes>
    </BrowserRouter>
    </EventStreamProvider>
  );
}

export default App;
