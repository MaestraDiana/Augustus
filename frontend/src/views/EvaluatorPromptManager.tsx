import { useState, useEffect, useRef } from 'react';
import { Check, FileText, Plus } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { EvaluatorPrompt } from '../types';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import EmptyState from '../components/ui/EmptyState';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';

function computeSimpleDiff(oldText: string, newText: string) {
  const oldLines = oldText.split('\n');
  const newLines = newText.split('\n');
  const maxLen = Math.max(oldLines.length, newLines.length);

  const diff: Array<{ type: 'added' | 'removed' | 'unchanged'; content: string; lineNum: number }> = [];

  for (let i = 0; i < maxLen; i++) {
    const oldLine = oldLines[i];
    const newLine = newLines[i];

    if (oldLine === newLine) {
      diff.push({ type: 'unchanged', content: oldLine || '', lineNum: i + 1 });
    } else {
      if (oldLine !== undefined) {
        diff.push({ type: 'removed', content: oldLine, lineNum: i + 1 });
      }
      if (newLine !== undefined) {
        diff.push({ type: 'added', content: newLine, lineNum: i + 1 });
      }
    }
  }

  return diff;
}

export default function EvaluatorPromptManager() {
  const [prompts, setPrompts] = useState<EvaluatorPrompt[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'editor' | 'diff'>('editor');
  const [editedPrompt, setEditedPrompt] = useState('');
  const [editedVersion, setEditedVersion] = useState('');
  const [editedRationale, setEditedRationale] = useState('');
  const [diffVersionA, setDiffVersionA] = useState('');
  const [diffVersionB, setDiffVersionB] = useState('');
  const [lineNumbers, setLineNumbers] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { data: fetchedPrompts, loading: isLoading, error } = useApi<EvaluatorPrompt[]>(
    () => api.evaluatorPrompts.list(),
    [],
  );

  // Sync fetched prompts into local state and initialize selections
  useEffect(() => {
    if (fetchedPrompts) {
      setPrompts(fetchedPrompts);
      if (fetchedPrompts.length > 0) {
        const active = fetchedPrompts.find((p) => p.is_active);
        setSelectedVersion(active?.version_id || fetchedPrompts[0].version_id);
        setDiffVersionA(fetchedPrompts[fetchedPrompts.length - 1]?.version_id || '');
        setDiffVersionB(active?.version_id || fetchedPrompts[0].version_id);
      }
    }
  }, [fetchedPrompts]);

  useEffect(() => {
    if (selectedVersion) {
      const prompt = prompts.find((p) => p.version_id === selectedVersion);
      if (prompt) {
        setEditedPrompt(prompt.prompt_text);
        setEditedVersion(prompt.version_id);
        setEditedRationale(prompt.change_rationale);
        updateLineNumbers(prompt.prompt_text);
      }
    }
  }, [selectedVersion, prompts]);

  useEffect(() => {
    updateLineNumbers(editedPrompt);
  }, [editedPrompt]);

  function updateLineNumbers(text: string) {
    const lines = text.split('\n');
    const nums = lines.map((_, i) => (i + 1).toString());
    setLineNumbers(nums);
  }

  function handleTextareaScroll(e: React.UIEvent<HTMLTextAreaElement>) {
    const lineNumsDiv = document.querySelector('.line-numbers');
    if (lineNumsDiv) {
      lineNumsDiv.scrollTop = e.currentTarget.scrollTop;
    }
  }

  function startCreating() {
    setCreating(true);
    setSelectedVersion(null);
    setEditedPrompt('');
    setEditedVersion('');
    setEditedRationale('');
    setActiveTab('editor');
    updateLineNumbers('');
  }

  async function saveAsNewVersion() {
    if (!editedPrompt || !editedRationale) {
      alert('Please fill in all fields');
      return;
    }

    try {
      const isFirst = prompts.length === 0;
      const newPrompt = await api.evaluatorPrompts.create({
        prompt_text: editedPrompt,
        change_rationale: editedRationale,
        set_active: isFirst, // Auto-activate the first prompt
      });
      setPrompts([...prompts, newPrompt]);
      setSelectedVersion(newPrompt.version_id);
      setCreating(false);
    } catch (err) {
      console.error('Failed to save evaluator prompt:', err);
      alert('Failed to save evaluator prompt. Please try again.');
    }
  }

  async function setAsActive() {
    if (!selectedVersion) return;
    try {
      await api.evaluatorPrompts.activate(selectedVersion);
      setPrompts(
        prompts.map((p) => ({
          ...p,
          is_active: p.version_id === selectedVersion,
        }))
      );
    } catch (err) {
      console.error('Failed to activate evaluator prompt:', err);
      alert('Failed to activate evaluator prompt. Please try again.');
    }
  }

  const selectedPrompt = prompts.find((p) => p.version_id === selectedVersion);
  const isActiveVersion = selectedPrompt?.is_active;

  const charCount = editedPrompt.length;
  const tokenCount = Math.ceil(charCount / 4); // Rough token estimate

  const diffPromptA = prompts.find((p) => p.version_id === diffVersionA);
  const diffPromptB = prompts.find((p) => p.version_id === diffVersionB);
  const diffLines = diffPromptA && diffPromptB
    ? computeSimpleDiff(diffPromptA.prompt_text, diffPromptB.prompt_text)
    : [];

  return (
    <div className="main-content">
      {isLoading ? (
        <div style={{ padding: 'var(--space-6)' }}>
          <LoadingSkeleton height="40px" width="200px" />
          <div style={{ marginTop: 'var(--space-4)' }}>
            <LoadingSkeleton height="80px" />
          </div>
          <div style={{ marginTop: 'var(--space-3)' }}>
            <LoadingSkeleton height="80px" />
          </div>
          <div style={{ marginTop: 'var(--space-3)' }}>
            <LoadingSkeleton height="80px" />
          </div>
        </div>
      ) : error ? (
        <div style={{ padding: 'var(--space-6)' }}>
          <div style={{
            padding: 'var(--space-4)',
            backgroundColor: 'var(--color-danger-bg)',
            border: '1px solid var(--color-danger)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--color-danger)'
          }}>
            <strong>Error:</strong> {error}
          </div>
        </div>
      ) : prompts.length === 0 && !creating ? (
        <EmptyState
          icon={<FileText size={48} style={{ color: 'var(--color-text-tertiary)' }} />}
          title="No Evaluator Prompts"
          message="No evaluator prompts configured. Create your first prompt version to begin."
          actionLabel="Create Prompt"
          onAction={startCreating}
        />
      ) : (
        <div className="epm-layout">
          {/* Left panel: Version list */}
          <div className="epm-version-list">
            <div className="epm-version-list-header">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h2 className="epm-version-list-title">Prompt Versions</h2>
                <Button variant="ghost" size="sm" onClick={startCreating}>
                  <Plus size={14} />
                  New
                </Button>
              </div>
              <p className="epm-version-list-subtitle">
                {prompts.length} version{prompts.length !== 1 ? 's' : ''}
              </p>
            </div>
            <div className="epm-version-list-body">
              {prompts.map((prompt) => (
                <div
                  key={prompt.version_id}
                  className={`epm-version-item ${
                    selectedVersion === prompt.version_id ? 'selected' : ''
                  } ${prompt.is_active ? 'active-version' : ''}`}
                  onClick={() => setSelectedVersion(prompt.version_id)}
                >
                  <div className="epm-version-row">
                    <span className="epm-version-id">{prompt.version_id}</span>
                    {prompt.is_active && (
                      <Badge variant="active">
                        <Check size={12} />
                        Active
                      </Badge>
                    )}
                  </div>
                  <div className="epm-version-date">
                    {new Date(prompt.created_at).toLocaleDateString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}
                  </div>
                  <div className="epm-version-rationale">{prompt.change_rationale}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Right panel: Editor */}
          <div className="epm-editor">
            <div className="epm-editor-header">
              <div className="epm-editor-tabs">
                <button
                  className={`epm-editor-tab ${activeTab === 'editor' ? 'active' : ''}`}
                  onClick={() => setActiveTab('editor')}
                >
                  Editor
                </button>
                <button
                  className={`epm-editor-tab ${activeTab === 'diff' ? 'active' : ''}`}
                  onClick={() => setActiveTab('diff')}
                >
                  Diff
                </button>
              </div>
              <div className="epm-editor-actions">
                {creating && (
                  <Button variant="ghost" size="sm" onClick={() => {
                    setCreating(false);
                    if (prompts.length > 0) {
                      const active = prompts.find(p => p.is_active);
                      setSelectedVersion(active?.version_id || prompts[0].version_id);
                    }
                  }}>
                    Cancel
                  </Button>
                )}
                <Button
                  variant={creating ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={saveAsNewVersion}
                  disabled={!editedPrompt || !editedRationale}
                >
                  {creating ? 'Create Version' : 'Save as New Version'}
                </Button>
                {!creating && !isActiveVersion && selectedPrompt && (
                  <Button variant="primary" size="sm" onClick={setAsActive}>
                    Set as Active
                  </Button>
                )}
              </div>
            </div>

            <div className="epm-editor-body">
              {/* Editor Panel */}
              <div className={`epm-panel ${activeTab === 'editor' ? 'active' : ''}`}>
                <div className="epm-form-row">
                  <div className="form-group">
                    <label className="form-label">Version ID</label>
                    <input
                      type="text"
                      className="form-input mono"
                      value={editedVersion}
                      disabled={true}
                      placeholder="Auto-generated"
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Change Rationale</label>
                    <input
                      type="text"
                      className="form-input"
                      value={editedRationale}
                      onChange={(e) => setEditedRationale(e.target.value)}
                      placeholder="Brief description of changes"
                    />
                  </div>
                </div>

                <div className="form-group" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                  <label className="form-label">Prompt Text</label>
                  <div className="code-editor-wrapper">
                    <div className="line-numbers">
                      {lineNumbers.map((num, i) => (
                        <div key={i}>{num}</div>
                      ))}
                    </div>
                    <textarea
                      ref={textareaRef}
                      className="code-textarea"
                      value={editedPrompt}
                      onChange={(e) => setEditedPrompt(e.target.value)}
                      onScroll={handleTextareaScroll}
                      placeholder="Enter evaluator prompt text..."
                    />
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div className="token-counter ok">
                    {charCount.toLocaleString()} chars · ~{tokenCount.toLocaleString()} tokens
                  </div>
                </div>
              </div>

              {/* Diff Panel */}
              <div className={`epm-panel ${activeTab === 'diff' ? 'active' : ''}`}>
                <div className="diff-controls">
                  <div className="diff-selector">
                    <span className="diff-selector-label">Compare:</span>
                    <select
                      className="form-select"
                      style={{ width: '180px' }}
                      value={diffVersionA}
                      onChange={(e) => setDiffVersionA(e.target.value)}
                    >
                      {prompts.map((p) => (
                        <option key={p.version_id} value={p.version_id}>
                          {p.version_id}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="diff-selector">
                    <span className="diff-selector-label">with:</span>
                    <select
                      className="form-select"
                      style={{ width: '180px' }}
                      value={diffVersionB}
                      onChange={(e) => setDiffVersionB(e.target.value)}
                    >
                      {prompts.map((p) => (
                        <option key={p.version_id} value={p.version_id}>
                          {p.version_id}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="diff-container">
                  <div className="diff-panel">
                    <div className="diff-panel-header">{diffVersionA}</div>
                    <div className="diff-panel-body">
                      {diffLines
                        .filter((line) => line.type !== 'added')
                        .map((line, i) => (
                          <div key={i} className={`diff-line ${line.type}`}>
                            <span className="diff-line-number">{line.lineNum}</span>
                            <span className="diff-line-content">{line.content || ' '}</span>
                          </div>
                        ))}
                    </div>
                  </div>
                  <div className="diff-panel">
                    <div className="diff-panel-header">{diffVersionB}</div>
                    <div className="diff-panel-body">
                      {diffLines
                        .filter((line) => line.type !== 'removed')
                        .map((line, i) => (
                          <div key={i} className={`diff-line ${line.type}`}>
                            <span className="diff-line-number">{line.lineNum}</span>
                            <span className="diff-line-content">{line.content || ' '}</span>
                          </div>
                        ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
