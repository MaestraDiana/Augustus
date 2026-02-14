import { useState, useRef, type DragEvent } from 'react';
import { Upload, FileText, AlertTriangle, AlertCircle, Check, ChevronLeft } from 'lucide-react';
import { api } from '../api/client';
import Modal from './ui/Modal';
import Button from './ui/Button';
import type { AgentFormData, ParseYamlResponse } from '../types';

interface ImportYamlModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImport: (data: Partial<AgentFormData>) => void;
}

type InputMode = 'paste' | 'upload';
type Step = 'input' | 'preview';

interface SectionCheck {
  key: string;
  label: string;
  preview: string;
  checked: boolean;
}

export default function ImportYamlModal({ isOpen, onClose, onImport }: ImportYamlModalProps) {
  const [inputMode, setInputMode] = useState<InputMode>('paste');
  const [yamlText, setYamlText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<Step>('input');
  const [parseResult, setParseResult] = useState<ParseYamlResponse | null>(null);
  const [sections, setSections] = useState<SectionCheck[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setYamlText('');
    setFileName(null);
    setStep('input');
    setParseResult(null);
    setSections([]);
    setLoading(false);
    setDragOver(false);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const readFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result;
      if (typeof text === 'string') {
        setYamlText(text);
        setFileName(file.name);
      }
    };
    reader.readAsText(file);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) readFile(file);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file && (file.name.endsWith('.yaml') || file.name.endsWith('.yml'))) {
      readFile(file);
    }
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => setDragOver(false);

  const buildSections = (result: ParseYamlResponse): SectionCheck[] => {
    const items: SectionCheck[] = [];

    if (result.identity_core) {
      const preview = result.identity_core.length > 120
        ? result.identity_core.slice(0, 120) + '...'
        : result.identity_core;
      items.push({ key: 'identity_core', label: 'Identity Core', preview, checked: true });
    }

    if (result.session_task) {
      const preview = result.session_task.length > 120
        ? result.session_task.slice(0, 120) + '...'
        : result.session_task;
      items.push({ key: 'session_task', label: 'Session Task', preview, checked: true });
    }

    if (result.close_protocol) {
      const preview = result.close_protocol.length > 120
        ? result.close_protocol.slice(0, 120) + '...'
        : result.close_protocol;
      items.push({ key: 'close_protocol', label: 'Close Protocol', preview, checked: true });
    }

    if (result.max_turns != null) {
      items.push({
        key: 'max_turns',
        label: 'Max Turns',
        preview: String(result.max_turns),
        checked: true,
      });
    }

    if (result.basins && result.basins.length > 0) {
      const names = result.basins.map((b) => b.name).join(', ');
      items.push({
        key: 'basins',
        label: `Basins (${result.basins.length})`,
        preview: names,
        checked: true,
      });
    }

    if (result.capabilities && result.capabilities.length > 0) {
      const enabled = result.capabilities.filter((c) => c.enabled).map((c) => c.name).join(', ');
      items.push({
        key: 'capabilities',
        label: `Capabilities (${result.capabilities.length})`,
        preview: `Enabled: ${enabled || 'none'}`,
        checked: true,
      });
    }

    return items;
  };

  const handleParse = async () => {
    if (!yamlText.trim()) return;
    setLoading(true);
    try {
      const result = await api.agents.parseYaml(yamlText);
      setParseResult(result);

      if (result.errors.length > 0) {
        // Stay on input step but show errors
        setSections([]);
      } else {
        setSections(buildSections(result));
        setStep('preview');
      }
    } catch (err: any) {
      setParseResult({
        max_turns: null,
        identity_core: null,
        session_task: null,
        close_protocol: null,
        capabilities: null,
        basins: null,
        warnings: [],
        errors: [err?.message || 'Failed to parse YAML'],
      });
    } finally {
      setLoading(false);
    }
  };

  const toggleSection = (index: number) => {
    setSections((prev) =>
      prev.map((s, i) => (i === index ? { ...s, checked: !s.checked } : s))
    );
  };

  const handleImport = () => {
    if (!parseResult) return;

    const checkedKeys = new Set(sections.filter((s) => s.checked).map((s) => s.key));
    const imported: Partial<AgentFormData> = {};

    if (checkedKeys.has('identity_core') && parseResult.identity_core) {
      imported.identity_core = parseResult.identity_core;
    }
    if (checkedKeys.has('session_task') && parseResult.session_task) {
      imported.session_task = parseResult.session_task;
    }
    if (checkedKeys.has('close_protocol') && parseResult.close_protocol) {
      imported.close_protocol = parseResult.close_protocol;
    }
    if (checkedKeys.has('max_turns') && parseResult.max_turns != null) {
      imported.max_turns = parseResult.max_turns;
    }
    if (checkedKeys.has('basins') && parseResult.basins) {
      imported.basins = parseResult.basins;
    }
    if (checkedKeys.has('capabilities') && parseResult.capabilities) {
      imported.capabilities = parseResult.capabilities;
    }

    onImport(imported);
    handleClose();
  };

  const hasErrors = parseResult?.errors && parseResult.errors.length > 0;
  const hasWarnings = parseResult?.warnings && parseResult.warnings.length > 0;
  const anyChecked = sections.some((s) => s.checked);

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Import YAML" width="620px">
      {step === 'input' && (
        <>
          {/* Mode toggle */}
          <div className="yaml-import-toggle">
            <button
              className={inputMode === 'paste' ? 'active' : ''}
              onClick={() => setInputMode('paste')}
            >
              Paste Text
            </button>
            <button
              className={inputMode === 'upload' ? 'active' : ''}
              onClick={() => setInputMode('upload')}
            >
              Upload File
            </button>
          </div>

          {inputMode === 'paste' ? (
            <textarea
              className="form-input"
              style={{
                fontFamily: 'var(--font-data)',
                fontSize: '13px',
                minHeight: '280px',
                resize: 'vertical',
              }}
              placeholder="Paste your YAML instruction file here..."
              value={yamlText}
              onChange={(e) => setYamlText(e.target.value)}
            />
          ) : (
            <>
              <div
                className={`yaml-dropzone ${dragOver ? 'dragover' : ''}`}
                onClick={() => fileInputRef.current?.click()}
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
              >
                {fileName ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--space-2)' }}>
                    <FileText size={20} />
                    <span style={{ color: 'var(--text-primary)' }}>{fileName}</span>
                  </div>
                ) : (
                  <>
                    <Upload size={24} style={{ marginBottom: 'var(--space-2)' }} />
                    <div>Drop a .yaml or .yml file here, or click to browse</div>
                  </>
                )}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".yaml,.yml"
                style={{ display: 'none' }}
                onChange={handleFileSelect}
              />
            </>
          )}

          {/* Errors from a failed parse attempt */}
          {hasErrors && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              {parseResult!.errors.map((err, i) => (
                <div key={i} className="yaml-error">
                  <AlertCircle size={14} />
                  {err}
                </div>
              ))}
            </div>
          )}

          {/* Footer */}
          <div style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 'var(--space-3)',
            marginTop: 'var(--space-4)',
            paddingTop: 'var(--space-4)',
            borderTop: '1px solid var(--border-color)',
          }}>
            <Button variant="ghost" onClick={handleClose}>Cancel</Button>
            <Button
              variant="primary"
              onClick={handleParse}
              disabled={!yamlText.trim() || loading}
            >
              {loading ? 'Parsing...' : 'Parse'}
            </Button>
          </div>
        </>
      )}

      {step === 'preview' && parseResult && (
        <>
          {/* Warnings */}
          {hasWarnings && (
            <div style={{ marginBottom: 'var(--space-4)' }}>
              {parseResult.warnings.map((w, i) => (
                <div key={i} className="yaml-warning">
                  <AlertTriangle size={14} style={{ flexShrink: 0 }} />
                  {w}
                </div>
              ))}
            </div>
          )}

          {/* Section checkboxes */}
          {sections.length > 0 ? (
            <div>
              <div style={{
                fontSize: '13px',
                color: 'var(--text-muted)',
                marginBottom: 'var(--space-3)',
              }}>
                Select which sections to import into the form:
              </div>
              {sections.map((section, i) => (
                <div
                  key={section.key}
                  className="yaml-preview-section"
                  onClick={() => toggleSection(i)}
                  style={{ cursor: 'pointer' }}
                >
                  <div style={{
                    width: '20px',
                    height: '20px',
                    borderRadius: 'var(--radius-sm)',
                    border: section.checked
                      ? '2px solid var(--accent-primary)'
                      : '2px solid var(--border-color)',
                    background: section.checked ? 'var(--accent-primary)' : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    transition: 'all 150ms ease',
                  }}>
                    {section.checked && <Check size={12} color="var(--bg-base)" />}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontWeight: 600,
                      fontSize: '14px',
                      color: 'var(--text-primary)',
                      marginBottom: '2px',
                    }}>
                      {section.label}
                    </div>
                    <div className="preview-text">{section.preview}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{
              padding: 'var(--space-6)',
              textAlign: 'center',
              color: 'var(--text-muted)',
            }}>
              No importable fields found in the YAML.
            </div>
          )}

          {/* Footer */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: 'var(--space-4)',
            paddingTop: 'var(--space-4)',
            borderTop: '1px solid var(--border-color)',
          }}>
            <Button variant="ghost" onClick={() => setStep('input')}>
              <ChevronLeft size={16} />
              Back
            </Button>
            <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
              <Button variant="ghost" onClick={handleClose}>Cancel</Button>
              <Button
                variant="primary"
                onClick={handleImport}
                disabled={!anyChecked}
              >
                Import Selected
              </Button>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
