import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { computeDiff, diffSummary, type DiffLine } from '../utils/diff';
import LoadingSkeleton from './ui/LoadingSkeleton';

interface YamlDiffViewerProps {
  agentId: string;
  sessionId: string;
}

export default function YamlDiffViewer({ agentId, sessionId }: YamlDiffViewerProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [diffLines, setDiffLines] = useState<DiffLine[]>([]);
  const [previousSessionId, setPreviousSessionId] = useState<string | null>(null);
  const [summary, setSummary] = useState({ added: 0, removed: 0, unchanged: 0 });

  useEffect(() => {
    let cancelled = false;

    async function fetchDiff() {
      try {
        setLoading(true);
        setError(null);
        const data = await api.sessions.getYamlDiff(agentId, sessionId);

        if (cancelled) return;

        if (data.is_first_session) {
          setError('This is the first session — no previous YAML to compare against.');
          return;
        }

        if (!data.yaml_raw && !data.previous_yaml_raw) {
          setError(
            'Instruction YAML not available for these sessions. ' +
            'YAML recording was added in a later version.'
          );
          return;
        }

        if (!data.previous_yaml_raw) {
          setError(
            'Previous session YAML not available. ' +
            'YAML recording was added in a later version.'
          );
          return;
        }

        if (!data.yaml_raw) {
          setError('Current session YAML not available.');
          return;
        }

        setPreviousSessionId(data.previous_session_id);
        const lines = computeDiff(data.previous_yaml_raw, data.yaml_raw);
        setDiffLines(lines);
        setSummary(diffSummary(lines));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load YAML diff');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchDiff();
    return () => { cancelled = true; };
  }, [agentId, sessionId]);

  if (loading) {
    return (
      <div style={{ padding: 'var(--space-4)' }}>
        <LoadingSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        padding: 'var(--space-5)',
        color: 'var(--text-secondary)',
        fontStyle: 'italic',
        textAlign: 'center',
      }}>
        {error}
      </div>
    );
  }

  return (
    <div>
      <div className="diff-controls">
        <div className="diff-selector">
          <span className="diff-selector-label">
            Comparing with previous session:&nbsp;
            <span style={{ fontFamily: 'var(--font-data)', color: 'var(--text-primary)' }}>
              {previousSessionId}
            </span>
          </span>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 'var(--space-3)', fontSize: '13px' }}>
          {summary.added > 0 && (
            <span style={{ color: 'var(--accent-success)' }}>+{summary.added} added</span>
          )}
          {summary.removed > 0 && (
            <span style={{ color: 'var(--accent-alert)' }}>−{summary.removed} removed</span>
          )}
          <span style={{ color: 'var(--text-muted)' }}>{summary.unchanged} unchanged</span>
        </div>
      </div>

      <div className="diff-panel">
        <div className="diff-panel-header">
          Instruction YAML changes
        </div>
        <div className="diff-panel-body">
          {diffLines.map((line, idx) => (
            <div key={idx} className={`diff-line ${line.type}`}>
              <span className="diff-line-number">
                {line.oldLineNumber ?? ''}
              </span>
              <span className="diff-line-number">
                {line.newLineNumber ?? ''}
              </span>
              <span className="diff-line-content">
                {line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  '}
                {line.content}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
