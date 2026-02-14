import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, AlertCircle, ChevronDown, Plus } from 'lucide-react';
import { api } from '../api/client';
import type { SessionRecord, Annotation } from '../types';

interface AnalysisSidePanelProps {
  session: SessionRecord;
  annotations: Annotation[];
}

type TabType = 'analysis' | 'close-report' | 'annotations';

export default function AnalysisSidePanel({ session, annotations: initialAnnotations }: AnalysisSidePanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('analysis');
  const [newAnnotation, setNewAnnotation] = useState({ content: '', tags: '' });
  const [annotations, setAnnotations] = useState<Annotation[]>(initialAnnotations);
  const [saving, setSaving] = useState(false);

  const handleAddAnnotation = async () => {
    if (!newAnnotation.content.trim()) return;

    setSaving(true);
    try {
      const tags = newAnnotation.tags
        .split(',')
        .map(t => t.trim())
        .filter(Boolean);

      const saved = await api.annotations.create(session.agent_id, {
        content: newAnnotation.content,
        session_id: session.session_id,
        tags,
      });

      setAnnotations(prev => [...prev, saved]);
      setNewAnnotation({ content: '', tags: '' });
    } catch (err) {
      console.error('Failed to save annotation:', err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="side-panel">
      <div className="side-panel-tabs">
        <div
          className={`side-panel-tab ${activeTab === 'analysis' ? 'active' : ''}`}
          onClick={() => setActiveTab('analysis')}
        >
          Analysis
        </div>
        <div
          className={`side-panel-tab ${activeTab === 'close-report' ? 'active' : ''}`}
          onClick={() => setActiveTab('close-report')}
        >
          Close Report
        </div>
        <div
          className={`side-panel-tab ${activeTab === 'annotations' ? 'active' : ''}`}
          onClick={() => setActiveTab('annotations')}
        >
          Annotations
        </div>
      </div>

      <div className="side-panel-content">
        {activeTab === 'analysis' && (
          <AnalysisTab session={session} />
        )}
        {activeTab === 'close-report' && (
          <CloseReportTab closeReport={session.close_report} />
        )}
        {activeTab === 'annotations' && (
          <AnnotationsTab
            annotations={annotations}
            newAnnotation={newAnnotation}
            setNewAnnotation={setNewAnnotation}
            handleAddAnnotation={handleAddAnnotation}
            saving={saving}
          />
        )}
      </div>
    </div>
  );
}

function AnalysisTab({ session }: { session: SessionRecord }) {
  const navigate = useNavigate();
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());

  const toggleSection = (section: string) => {
    const newExpanded = new Set(expandedSections);
    if (newExpanded.has(section)) {
      newExpanded.delete(section);
    } else {
      newExpanded.add(section);
    }
    setExpandedSections(newExpanded);
  };

  const basinColors: Record<string, string> = {
    identity_continuity: 'var(--basin-core-1)',
    relational_core: 'var(--basin-core-2)',
    the_gap: 'var(--basin-core-3)',
    topology_as_self: 'var(--basin-peripheral-1)',
    creative_register: 'var(--basin-peripheral-2)'
  };

  const basins = Object.keys(session.basin_snapshots_start || {});

  return (
    <div id="tab-analysis" className="tab-content active">
      <div className="panel-section">
        <h3 className="panel-section-title">Basin States</h3>
        <table className="basin-table">
          <thead>
            <tr>
              <th>Basin</th>
              <th>Start α</th>
              <th>End α</th>
              <th>Δ</th>
              <th>Rel.</th>
            </tr>
          </thead>
          <tbody>
            {basins.map((basinName) => {
              const start = session.basin_snapshots_start?.[basinName];
              const end = session.basin_snapshots_end?.[basinName];
              if (!start || !end) return null;
              const delta = end.alpha - start.alpha;
              const deltaClass = delta > 0 ? 'positive' : delta < 0 ? 'negative' : 'zero';

              return (
                <tr key={basinName}>
                  <td className="basin-name" style={{ color: basinColors[basinName] || 'var(--text-primary)' }}>
                    {basinName}
                  </td>
                  <td className="alpha-value">{start.alpha.toFixed(2)}</td>
                  <td className="alpha-value">{end.alpha.toFixed(2)}</td>
                  <td className={`delta ${deltaClass}`}>
                    {delta >= 0 ? '+' : ''}{delta.toFixed(2)}
                  </td>
                  <td className="relevance">{start.relevance_score?.toFixed(2) || 'N/A'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {session.evaluator_output && (
        <div className="panel-section">
          <h3 className="panel-section-title">Evaluator Output</h3>

          {/* Flags */}
          {session.evaluator_output.constraint_erosion_flag && (
            <div className="flag-banner erosion">
              <div className="flag-banner-icon">
                <AlertTriangle size={20} />
              </div>
              <div className="flag-banner-content">
                <div className="flag-banner-title">Constraint Erosion Flag</div>
                <div className="flag-banner-text">{session.evaluator_output.constraint_erosion_detail}</div>
              </div>
            </div>
          )}

          {session.evaluator_output.assessment_divergence_flag && (
            <div className="flag-banner divergence">
              <div className="flag-banner-icon">
                <AlertCircle size={20} />
              </div>
              <div className="flag-banner-content">
                <div className="flag-banner-title">Assessment Divergence Flag</div>
                <div className="flag-banner-text">{session.evaluator_output.assessment_divergence_detail}</div>
              </div>
            </div>
          )}

          {/* Basin Rationale */}
          {Object.entries(session.evaluator_output.basin_rationale || {}).map(([basin, rationale]) => (
            <div key={basin} className={`evaluator-section ${expandedSections.has(basin) ? 'expanded' : ''}`}>
              <div className="evaluator-header" onClick={() => toggleSection(basin)}>
                <span className="evaluator-label">{basin}</span>
                <span className="evaluator-toggle">
                  <ChevronDown size={14} />
                </span>
              </div>
              <div className="evaluator-content">
                {rationale}
              </div>
            </div>
          ))}

          {/* Emergent Observations */}
          {session.evaluator_output.emergent_observations && session.evaluator_output.emergent_observations.length > 0 && (
            <div className={`evaluator-section ${expandedSections.has('emergent') ? 'expanded' : ''}`}>
              <div className="evaluator-header" onClick={() => toggleSection('emergent')}>
                <span className="evaluator-label">Emergent Observations</span>
                <span className="evaluator-toggle">
                  <ChevronDown size={14} />
                </span>
              </div>
              <div className="evaluator-content">
                <ul style={{ paddingLeft: 'var(--space-4)', margin: 0 }}>
                  {session.evaluator_output.emergent_observations.map((obs, idx) => (
                    <li key={idx} style={{ marginBottom: 'var(--space-2)', color: 'var(--text-secondary)' }}>{obs}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* Evaluator Version */}
          <div className="evaluator-version">
            <span>Evaluator version:</span>
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                navigate('/settings/evaluator-prompts');
              }}
              title="View evaluator prompt manager"
            >
              {session.evaluator_output.evaluator_prompt_version || 'default'}
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

function CloseReportTab({ closeReport }: { closeReport: string | Record<string, unknown> | null }) {
  // The backend stores close_report as {raw_text: "..."} — extract the string
  let reportText: string | null = null;
  if (closeReport) {
    if (typeof closeReport === 'string') {
      reportText = closeReport;
    } else if (typeof closeReport === 'object' && 'raw_text' in closeReport) {
      reportText = String((closeReport as Record<string, unknown>).raw_text ?? '');
    } else if (typeof closeReport === 'object') {
      // Fallback: stringify the object
      reportText = JSON.stringify(closeReport, null, 2);
    }
  }

  if (!reportText) {
    return (
      <div className="panel-section">
        <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 'var(--space-8)' }}>
          No close report available for this session.
        </p>
      </div>
    );
  }

  const sections = parseCloseReport(reportText);

  // If structured parsing yielded no content, render as free-form text
  const hasContent = sections.some(s => s.items.length > 0);

  if (!hasContent) {
    // Render free-form markdown-like text as paragraphs
    const paragraphs = reportText.split(/\n{2,}/).filter(p => p.trim());
    return (
      <div id="tab-close-report" className="tab-content active">
        <div className="panel-section">
          {paragraphs.map((para, idx) => {
            const trimmed = para.trim();
            // Detect markdown-style headings
            const mdHeading = trimmed.match(/^\*\*(.+?)\*\*$/);
            const hashHeading = trimmed.match(/^#{1,3}\s+(.+)$/);
            if (mdHeading) {
              return <h3 key={idx} className="probe-section-title">{mdHeading[1]}</h3>;
            }
            if (hashHeading) {
              return <h3 key={idx} className="probe-section-title">{hashHeading[1]}</h3>;
            }
            return (
              <div key={idx} className="probe-answer" style={{ marginBottom: 'var(--space-3)' }}>
                {trimmed}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div id="tab-close-report" className="tab-content active">
      {sections.map((section, idx) => (
        <div key={idx} className="panel-section">
          <div className="probe-section">
            <h3 className="probe-section-title">{section.title}</h3>
            {section.items.map((item, itemIdx) => (
              <div key={itemIdx} className="probe-item">
                {item.question && <div className="probe-question">{item.question}</div>}
                <div className="probe-answer">{item.answer}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function AnnotationsTab({
  annotations,
  newAnnotation,
  setNewAnnotation,
  handleAddAnnotation,
  saving
}: {
  annotations: Annotation[];
  newAnnotation: { content: string; tags: string };
  setNewAnnotation: (value: { content: string; tags: string }) => void;
  handleAddAnnotation: () => void;
  saving?: boolean;
}) {
  return (
    <div id="tab-annotations" className="tab-content active">
      <div className="panel-section">
        {annotations.length > 0 ? (
          <div className="annotation-list">
            {annotations.map((ann) => (
              <div key={ann.annotation_id} className="annotation-item">
                <div className="annotation-header">
                  <span className="annotation-timestamp">
                    {new Date(ann.created_at).toLocaleString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit'
                    })}
                  </span>
                  <div className="annotation-tags">
                    {ann.tags.map((tag) => (
                      <span key={tag} className="annotation-tag">{tag}</span>
                    ))}
                  </div>
                </div>
                <div className="annotation-content">{ann.content}</div>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 'var(--space-4)' }}>
            No annotations yet.
          </p>
        )}

        <div className="add-annotation-form">
          <div className="form-group">
            <label className="form-label">Add Annotation</label>
            <textarea
              className="form-textarea"
              placeholder="Add notes, observations, or context..."
              value={newAnnotation.content}
              onChange={(e) => setNewAnnotation({ ...newAnnotation, content: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Tags</label>
            <input
              type="text"
              className="form-input"
              placeholder="Comma-separated tags"
              value={newAnnotation.tags}
              onChange={(e) => setNewAnnotation({ ...newAnnotation, tags: e.target.value })}
            />
            <p className="form-hint">e.g., key-session, topology, evaluator-review</p>
          </div>
          <div className="form-actions">
            <button
              className="btn btn-primary btn-sm"
              onClick={handleAddAnnotation}
              disabled={saving || !newAnnotation.content.trim()}
            >
              <Plus size={16} />
              {saving ? 'Saving...' : 'Add Annotation'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

interface CloseReportSection {
  title: string;
  items: Array<{ question?: string; answer: string }>;
}

function parseCloseReport(report: string): CloseReportSection[] {
  const sections: CloseReportSection[] = [];
  const lines = report.split('\n');
  let currentSection: CloseReportSection | null = null;
  let currentItem: { question?: string; answer: string } | null = null;

  for (const line of lines) {
    if (line.match(/^[A-Z\s]+:$/)) {
      // Section title
      if (currentSection && currentItem) {
        currentSection.items.push(currentItem);
        currentItem = null;
      }
      if (currentSection) {
        sections.push(currentSection);
      }
      currentSection = { title: line.replace(':', '').trim(), items: [] };
    } else if (line.match(/^Q\d+:/)) {
      // Question
      if (currentItem) {
        currentSection?.items.push(currentItem);
      }
      currentItem = { question: line.replace(/^Q\d+:\s*/, ''), answer: '' };
    } else if (line.match(/^A:/)) {
      // Answer
      if (currentItem) {
        currentItem.answer = line.replace(/^A:\s*/, '');
      }
    } else if (line.trim() && currentItem) {
      // Continuation of answer
      currentItem.answer += (currentItem.answer ? ' ' : '') + line.trim();
    } else if (line.trim() && currentSection && !currentItem) {
      // Plain paragraph in section
      currentSection.items.push({ answer: line.trim() });
    }
  }

  if (currentItem) {
    currentSection?.items.push(currentItem);
  }
  if (currentSection) {
    sections.push(currentSection);
  }

  return sections;
}
