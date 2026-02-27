import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ChevronLeft, ChevronRight, FileText, Download, AlertCircle, GitCompareArrows } from 'lucide-react';
import { api } from '../api/client';
import { dismissAlertKey, alertDismissKey } from '../hooks/useAlertDismissals';
import { formatDuration } from '../utils/time';
import type { SessionRecord, Annotation } from '../types';
import TranscriptPanel from '../components/TranscriptPanel';
import AnalysisSidePanel from '../components/AnalysisSidePanel';
import Modal from '../components/ui/Modal';
import YamlHighlighter from '../components/YamlHighlighter';
import YamlDiffViewer from '../components/YamlDiffViewer';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import EmptyState from '../components/ui/EmptyState';
import './SessionDetail.css';

interface SessionDetailData {
  session_id: string;
  agent_id: string;
  start_time: string;
  end_time: string;
  turn_count: number;
  model: string;
  temperature: number;
  status: string;
  capabilities_used: string[];
  transcript?: Array<{
    role: string;
    content: string;
    timestamp?: string;
    tool_calls?: any[];
    tool_call_id?: string;
  }>;
  close_report?: string | null;
  error_message?: string | null;
  basin_snapshots?: Array<{
    basin_name: string;
    alpha_start: number;
    alpha_end: number;
    delta: number;
    relevance_score: number | null;
  }>;
  evaluator_output?: {
    basin_relevance: Record<string, number>;
    basin_rationale: Record<string, string>;
    co_activation_characters: Record<string, string | null>;
    constraint_erosion_flag: boolean;
    constraint_erosion_detail: string | null;
    assessment_divergence_flag: boolean;
    assessment_divergence_detail: string | null;
    emergent_observations: string[];
    evaluator_prompt_version?: string;
  } | null;
  annotations?: Array<{
    annotation_id: string;
    content: string;
    tags: string[];
    created_at: string;
  }>;
}

export default function SessionDetail() {
  const { agentId, sessionId } = useParams();
  const navigate = useNavigate();
  const [yamlModalOpen, setYamlModalOpen] = useState(false);
  const [diffModalOpen, setDiffModalOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sessionData, setSessionData] = useState<SessionDetailData | null>(null);
  const [adjacentSessions, setAdjacentSessions] = useState<{ prev: string | null; next: string | null }>({ prev: null, next: null });
  const [errorBannerDismissed, setErrorBannerDismissed] = useState(
    () => sessionStorage.getItem(`error-banner-dismissed:${sessionId}`) === '1'
  );

  const dismissErrorBanner = () => {
    sessionStorage.setItem(`error-banner-dismissed:${sessionId}`, '1');
    setErrorBannerDismissed(true);
    // Also dismiss the corresponding system alert so dashboard + bell stay in sync.
    if (agentId && sessionId) {
      dismissAlertKey(alertDismissKey('session_failed', agentId, sessionId));
    }
  };

  useEffect(() => {
    async function fetchSessionData() {
      if (!agentId || !sessionId) {
        setError('Missing agent ID or session ID');
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError(null);
        const [data, sessionsList] = await Promise.all([
          api.sessions.get(agentId, sessionId),
          api.sessions.list(agentId, 500, 0),
        ]);
        setSessionData(data);

        // Find adjacent sessions for prev/next navigation
        const sessions = sessionsList.sessions || [];
        const currentIndex = sessions.findIndex((s: { session_id: string }) => s.session_id === sessionId);
        setAdjacentSessions({
          prev: currentIndex > 0 ? sessions[currentIndex - 1].session_id : null,
          next: currentIndex >= 0 && currentIndex < sessions.length - 1 ? sessions[currentIndex + 1].session_id : null,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load session');
      } finally {
        setLoading(false);
      }
    }

    fetchSessionData();
  }, [agentId, sessionId]);

  if (loading) {
    return (
      <div className="session-detail-layout">
        <LoadingSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div className="session-detail-layout">
        <EmptyState
          title="Error Loading Session"
          message={error}
          icon={<AlertCircle size={48} />}
        />
      </div>
    );
  }

  if (!sessionData) {
    return (
      <div className="session-detail-layout">
        <EmptyState
          title="Session Not Found"
          message="The requested session could not be found."
          icon={<FileText size={48} />}
        />
      </div>
    );
  }

  const duration = sessionData.start_time && sessionData.end_time
    ? formatDuration(sessionData.start_time, sessionData.end_time)
    : 'N/A';

  const dateRange = sessionData.start_time && sessionData.end_time
    ? formatDateRange(sessionData.start_time, sessionData.end_time)
    : 'N/A';

  // Transform basin_snapshots array to the format expected by AnalysisSidePanel
  const basinSnapshotsStart: Record<string, any> = {};
  const basinSnapshotsEnd: Record<string, any> = {};

  if (sessionData.basin_snapshots) {
    sessionData.basin_snapshots.forEach((snapshot) => {
      basinSnapshotsStart[snapshot.basin_name] = {
        basin_name: snapshot.basin_name,
        alpha: snapshot.alpha_start,
        relevance_score: snapshot.relevance_score,
        delta: snapshot.delta,
        session_id: sessionData.session_id,
        timestamp: sessionData.start_time,
      };
      basinSnapshotsEnd[snapshot.basin_name] = {
        basin_name: snapshot.basin_name,
        alpha: snapshot.alpha_end,
        relevance_score: snapshot.relevance_score,
        delta: snapshot.delta,
        session_id: sessionData.session_id,
        timestamp: sessionData.end_time,
      };
    });
  }

  // Transform to SessionRecord format expected by AnalysisSidePanel
  const sessionRecord: SessionRecord = {
    session_id: sessionData.session_id,
    agent_id: sessionData.agent_id,
    status: sessionData.status as any,
    start_time: sessionData.start_time,
    end_time: sessionData.end_time,
    turn_count: sessionData.turn_count,
    model: sessionData.model,
    temperature: sessionData.temperature,
    capabilities_used: sessionData.capabilities_used,
    transcript: sessionData.transcript || [],
    close_report: sessionData.close_report || null,
    basin_snapshots: [],
    basin_snapshots_start: basinSnapshotsStart,
    basin_snapshots_end: basinSnapshotsEnd,
    evaluator_output: sessionData.evaluator_output ? {
      session_id: sessionData.session_id,
      basin_relevance: sessionData.evaluator_output.basin_relevance,
      basin_rationale: sessionData.evaluator_output.basin_rationale,
      co_activation_characters: sessionData.evaluator_output.co_activation_characters as any,
      constraint_erosion_flag: sessionData.evaluator_output.constraint_erosion_flag,
      constraint_erosion_detail: sessionData.evaluator_output.constraint_erosion_detail,
      assessment_divergence_flag: sessionData.evaluator_output.assessment_divergence_flag,
      assessment_divergence_detail: sessionData.evaluator_output.assessment_divergence_detail,
      emergent_observations: sessionData.evaluator_output.emergent_observations,
      evaluator_prompt_version: sessionData.evaluator_output.evaluator_prompt_version || 'v0.1',
      created_at: sessionData.end_time, // Use session end_time as fallback
    } : undefined,
  };

  const capabilities = sessionData.capabilities_used?.map(name => ({
    name,
    enabled: true,
    available_from_turn: 1,
  })) || [];

  const annotations: Annotation[] = (sessionData.annotations || []).map(ann => ({
    annotation_id: ann.annotation_id,
    agent_id: sessionData.agent_id,
    session_id: sessionData.session_id,
    content: ann.content,
    tags: ann.tags,
    created_at: ann.created_at,
    created_by: 'operator', // Default value, not provided by backend
  }));

  return (
    <div className="session-detail-layout">
      {/* Session Header Bar */}
      <div className="session-header">
        <div className="session-header-left">
          <div className="session-id-display">
            <span className="session-id-text">{sessionData.session_id}</span>
            <div className="session-nav-arrows">
              <button
                className="nav-arrow"
                title="Previous session"
                disabled={!adjacentSessions.prev}
                onClick={() => adjacentSessions.prev && navigate(`/agents/${agentId}/sessions/${adjacentSessions.prev}`)}
              >
                <ChevronLeft size={16} />
              </button>
              <button
                className="nav-arrow"
                title="Next session"
                disabled={!adjacentSessions.next}
                onClick={() => adjacentSessions.next && navigate(`/agents/${agentId}/sessions/${adjacentSessions.next}`)}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>

          <div className="session-meta">
            <div className="session-meta-item">
              <span className="session-meta-value">{dateRange}</span>
            </div>
            <div className="session-meta-item">
              <span className="session-meta-value">{duration}</span>
            </div>
            <div className="session-meta-item">
              <span className="session-meta-value">{sessionData.turn_count} turns</span>
            </div>
            <div className="session-meta-item">
              <span className="session-meta-value">{sessionData.model}</span>
            </div>
            <div className="session-meta-item">
              <span className="session-meta-value">{sessionData.temperature}</span>
            </div>
          </div>

          {capabilities.length > 0 && (
            <div className="capability-badges">
              {capabilities.map((cap) => (
                <span key={cap.name} className="capability-badge">
                  {cap.name}
                  {cap.available_from_turn > 1 && (
                    <span className="turn-indicator"> T{cap.available_from_turn}+</span>
                  )}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="session-header-right">
          {adjacentSessions.next !== null && (
            <button className="btn btn-secondary btn-sm" onClick={() => setDiffModalOpen(true)}>
              <GitCompareArrows size={16} />
              View YAML Changes
            </button>
          )}
          <button className="btn btn-secondary btn-sm" onClick={() => setYamlModalOpen(true)}>
            <FileText size={16} />
            View Raw YAML
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => {
            const content = generateYamlContent(sessionData);
            const blob = new Blob([content], { type: 'text/yaml' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${sessionData.session_id}.yaml`;
            a.click();
            URL.revokeObjectURL(url);
          }}>
            <Download size={16} />
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {sessionData.status === 'error' && !errorBannerDismissed && (
        <div className="session-error-banner">
          <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
          <div className="session-error-body">
            <span className="session-error-label">Session failed</span>
            {sessionData.error_message && (
              <span className="session-error-message">{sessionData.error_message}</span>
            )}
          </div>
          <button
            className="session-error-dismiss"
            onClick={dismissErrorBanner}
            title="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      {/* Main Content Area */}
      <div className="session-main">
        {sessionData.transcript && sessionData.transcript.length > 0 ? (
          <TranscriptPanel
            transcript={sessionData.transcript}
            sessionId={sessionData.session_id}
            agentId={sessionData.agent_id}
            startTime={sessionData.start_time}
            endTime={sessionData.end_time}
            model={sessionData.model}
            turnCount={sessionData.turn_count}
          />
        ) : (
          <div className="transcript-panel">
            <EmptyState
              title="No Transcript"
              message="This session has not generated a transcript yet."
              icon={<FileText size={48} />}
            />
          </div>
        )}
        <AnalysisSidePanel
          session={sessionRecord}
          annotations={annotations}
        />
      </div>

      {/* YAML Modal */}
      <Modal
        isOpen={yamlModalOpen}
        onClose={() => setYamlModalOpen(false)}
        title="Raw Session YAML"
        width="800px"
      >
        <YamlHighlighter content={generateYamlContent(sessionData)} />
      </Modal>

      {/* YAML Diff Modal */}
      <Modal
        isOpen={diffModalOpen}
        onClose={() => setDiffModalOpen(false)}
        title="YAML Changes"
        width="900px"
      >
        <YamlDiffViewer
          agentId={agentId!}
          sessionId={sessionId!}
        />
      </Modal>
    </div>
  );
}

function formatDateRange(start: string, end: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const startTime = startDate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  const endTime = endDate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  const date = startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  return `${date} ${startTime} – ${endTime}`;
}

function generateYamlContent(data: SessionDetailData): string {
  return `# Augustus Session YAML
# Agent: ${data.agent_id}
# Session: ${data.session_id}

framework:
  session_id: ${data.session_id}
  model: ${data.model}
  temperature: ${data.temperature}

  basin_state:
${data.basin_snapshots?.map(b => `    - name: ${b.basin_name}
      alpha_start: ${b.alpha_start.toFixed(2)}
      alpha_end: ${b.alpha_end.toFixed(2)}
      delta: ${b.delta >= 0 ? '+' : ''}${b.delta.toFixed(2)}`).join('\n') || '    # No basin snapshots'}

  capabilities:
${data.capabilities_used?.map(c => `    - name: ${c}
      enabled: true`).join('\n') || '    # No capabilities used'}

# Session Details
status: ${data.status}
start_time: ${data.start_time}
end_time: ${data.end_time}
turn_count: ${data.turn_count}

${data.evaluator_output ? `# Evaluator Output
evaluator:
  constraint_erosion_flag: ${data.evaluator_output.constraint_erosion_flag}
  assessment_divergence_flag: ${data.evaluator_output.assessment_divergence_flag}
  emergent_observations:
${data.evaluator_output.emergent_observations.map(o => `    - ${o}`).join('\n')}
` : ''}`;
}
