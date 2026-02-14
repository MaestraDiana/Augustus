import { useState, useMemo, useCallback } from 'react';
import { Search, ChevronUp, ChevronDown, ChevronRight, Lock, Wrench, Download } from 'lucide-react';

// Content can be a string OR an array of Anthropic content blocks
type ContentBlock =
  | { type: 'text'; text: string }
  | { type: 'tool_use'; id: string; name: string; input: any }
  | { type: 'tool_result'; tool_use_id: string; content: string | ContentBlock[] };

interface TranscriptMessage {
  role: string;
  content: string | ContentBlock[];
  timestamp?: string;
  tool_calls?: Array<{
    type: string;
    id: string;
    name: string;
    input: any;
  }>;
  tool_call_id?: string;
}

interface TranscriptPanelProps {
  transcript: TranscriptMessage[];
  sessionId?: string;
  agentId?: string;
  startTime?: string;
  endTime?: string;
  model?: string;
  turnCount?: number;
}

/** Extract plain text from content (string or content block array). */
function extractText(content: string | ContentBlock[]): string {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return String(content ?? '');
  return content
    .map((block) => {
      if (typeof block === 'string') return block;
      if (block.type === 'text') return block.text;
      if (block.type === 'tool_use') return `[Tool: ${block.name}]`;
      if (block.type === 'tool_result') {
        const inner = block.content;
        if (typeof inner === 'string') return inner;
        if (Array.isArray(inner)) return extractText(inner);
        return '[tool result]';
      }
      return '';
    })
    .filter(Boolean)
    .join('\n\n');
}

/** Extract tool_use blocks from content array. */
function extractToolUses(content: string | ContentBlock[]): Array<{ type: string; id: string; name: string; input: any }> {
  if (typeof content === 'string' || !Array.isArray(content)) return [];
  return content
    .filter((block): block is Extract<ContentBlock, { type: 'tool_use' }> => typeof block === 'object' && block !== null && block.type === 'tool_use')
    .map((block) => ({ type: block.type, id: block.id, name: block.name, input: block.input }));
}

export default function TranscriptPanel({ transcript, sessionId, agentId, startTime, endTime, model, turnCount }: TranscriptPanelProps) {
  const [expandAll, setExpandAll] = useState(true);
  const [collapsedTurns, setCollapsedTurns] = useState<Set<number>>(new Set());
  const [systemPromptExpanded, setSystemPromptExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentMatch, setCurrentMatch] = useState(0);

  const systemPrompt = transcript.find(msg => msg.role === 'system');
  const conversationTurns = transcript.filter(msg => msg.role !== 'system');

  const matchingIndices = useMemo(() => {
    if (!searchQuery) return [];
    const indices: number[] = [];
    conversationTurns.forEach((msg, idx) => {
      const text = extractText(msg.content);
      if (text.toLowerCase().includes(searchQuery.toLowerCase())) {
        indices.push(idx);
      }
    });
    return indices;
  }, [searchQuery, conversationTurns]);

  const toggleTurn = (index: number) => {
    const newCollapsed = new Set(collapsedTurns);
    if (newCollapsed.has(index)) {
      newCollapsed.delete(index);
    } else {
      newCollapsed.add(index);
    }
    setCollapsedTurns(newCollapsed);
  };

  const handleExpandAllChange = () => {
    if (expandAll) {
      // Collapse all
      const allIndices = conversationTurns.map((_, idx) => idx);
      setCollapsedTurns(new Set(allIndices));
    } else {
      // Expand all
      setCollapsedTurns(new Set());
    }
    setExpandAll(!expandAll);
  };

  const navigateSearch = (direction: 'next' | 'prev') => {
    if (matchingIndices.length === 0) return;
    if (direction === 'next') {
      setCurrentMatch((currentMatch + 1) % matchingIndices.length);
    } else {
      setCurrentMatch((currentMatch - 1 + matchingIndices.length) % matchingIndices.length);
    }
  };

  const downloadMarkdown = useCallback(() => {
    const md = generateTranscriptMarkdown(transcript, { sessionId, agentId, startTime, endTime, model, turnCount });
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${sessionId || 'transcript'}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [transcript, sessionId, agentId, startTime, endTime, model, turnCount]);

  const highlightText = (text: string) => {
    if (!searchQuery) return text;
    const parts = text.split(new RegExp(`(${searchQuery})`, 'gi'));
    return parts.map((part, idx) => {
      if (part.toLowerCase() === searchQuery.toLowerCase()) {
        return <mark key={idx} className="search-highlight">{part}</mark>;
      }
      return part;
    });
  };

  return (
    <div className="transcript-panel">
      <div className="transcript-header">
        <div className="transcript-header-left">
          <h2 className="transcript-title">Transcript</h2>
        </div>
        <div className="transcript-header-right">
          <button
            className="btn btn-ghost btn-sm"
            title="Download as Markdown"
            onClick={downloadMarkdown}
          >
            <Download size={14} />
          </button>
          <label className="expand-toggle" onClick={handleExpandAllChange}>
            <input type="checkbox" checked={expandAll} readOnly />
            <span className="expand-label">Expand all</span>
          </label>
          <div className="transcript-search">
            <Search size={14} />
            <input
              type="text"
              placeholder="Search transcript..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <div className="search-nav">
              <span className="search-count">
                {matchingIndices.length > 0 ? `${currentMatch + 1}/${matchingIndices.length}` : ''}
              </span>
              <button className="search-nav-btn" onClick={() => navigateSearch('prev')} disabled={matchingIndices.length === 0}>
                <ChevronUp size={12} />
              </button>
              <button className="search-nav-btn" onClick={() => navigateSearch('next')} disabled={matchingIndices.length === 0}>
                <ChevronDown size={12} />
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="transcript-body">
        {/* System Prompt */}
        {systemPrompt && (
          <div className={`system-prompt ${systemPromptExpanded ? 'expanded' : ''}`}>
            <div className="system-prompt-header" onClick={() => setSystemPromptExpanded(!systemPromptExpanded)}>
              <span className="system-prompt-label">
                <Lock size={14} />
                System Prompt
              </span>
              <span className="system-prompt-toggle">
                <ChevronDown size={16} />
              </span>
            </div>
            <div className="system-prompt-content">
              {extractText(systemPrompt.content)}
            </div>
          </div>
        )}

        {/* Conversation Turns */}
        <div className="turns-container">
          {conversationTurns.map((msg, idx) => {
            const turnNumber = Math.floor(idx / 2) + 1;
            const isCollapsed = collapsedTurns.has(idx);

            return (
              <div key={idx} className={`turn ${msg.role} ${isCollapsed ? 'collapsed' : ''}`} data-turn={turnNumber}>
                <div className="turn-number">{msg.role === 'tool' ? '•' : turnNumber}</div>
                <div className="turn-content">
                  <div className="turn-header">
                    <span className="turn-role">{msg.role === 'tool' ? 'Tool Result' : msg.role.charAt(0).toUpperCase() + msg.role.slice(1)}</span>
                    {msg.timestamp && <span className="turn-timestamp">{msg.timestamp}</span>}
                    <button className="turn-collapse-btn" onClick={() => toggleTurn(idx)}>
                      <ChevronDown size={14} />
                    </button>
                  </div>
                  <div className="turn-body">
                    {extractText(msg.content).split('\n\n').filter(Boolean).map((para, pIdx) => (
                      <p key={pIdx}>{highlightText(para)}</p>
                    ))}

                    {/* Tool Use Blocks — from explicit tool_calls field OR from content block array */}
                    {[...(msg.tool_calls || []), ...extractToolUses(msg.content)].map((tool, tIdx) => (
                      <ToolUseBlock key={tIdx} tool={tool} />
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

interface ToolUseBlockProps {
  tool: {
    type: string;
    id: string;
    name: string;
    input: any;
  };
}

function ToolUseBlock({ tool }: ToolUseBlockProps) {
  const [inputExpanded, setInputExpanded] = useState(false);

  return (
    <div className="tool-use-block">
      <div className="tool-use-header">
        <Wrench className="tool-use-icon" size={16} />
        <span className="tool-use-name">{tool.name}</span>
        <span className="tool-use-status success">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          Success
        </span>
      </div>
      <div className="tool-use-content">
        <div className="tool-use-section">
          <div className="tool-use-section-label">
            Input
            <button
              className="tool-use-toggle-btn"
              onClick={() => setInputExpanded(!inputExpanded)}
              style={{ marginLeft: '8px', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
            >
              <ChevronRight size={12} style={{ transform: inputExpanded ? 'rotate(90deg)' : 'none', transition: 'transform 150ms ease' }} />
            </button>
          </div>
          {inputExpanded && (
            <div className="code-block">
              {formatToolInput(tool.input)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function formatToolInput(input: any): string {
  if (typeof input === 'string') return input;
  return JSON.stringify(input, null, 2);
}

/** Convert a content block array to markdown text. */
function contentToMarkdown(content: string | ContentBlock[]): string {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return String(content ?? '');
  return content
    .map((block) => {
      if (typeof block === 'string') return block;
      if (block.type === 'text') return block.text;
      if (block.type === 'tool_use') {
        const inputStr = typeof block.input === 'string' ? block.input : JSON.stringify(block.input, null, 2);
        return `> **Tool Use:** \`${block.name}\`\n>\n> \`\`\`json\n> ${inputStr.split('\n').join('\n> ')}\n> \`\`\``;
      }
      if (block.type === 'tool_result') {
        const inner = block.content;
        if (typeof inner === 'string') return `> **Tool Result:**\n>\n> ${inner}`;
        if (Array.isArray(inner)) return `> **Tool Result:**\n>\n> ${contentToMarkdown(inner)}`;
        return '> **Tool Result**';
      }
      return '';
    })
    .filter(Boolean)
    .join('\n\n');
}

interface MarkdownMeta {
  sessionId?: string;
  agentId?: string;
  startTime?: string;
  endTime?: string;
  model?: string;
  turnCount?: number;
}

function generateTranscriptMarkdown(transcript: TranscriptMessage[], meta: MarkdownMeta): string {
  const lines: string[] = [];

  // Header
  lines.push(`# Session Transcript`);
  if (meta.sessionId) lines.push(`**Session:** ${meta.sessionId}`);
  if (meta.agentId) lines.push(`**Agent:** ${meta.agentId}`);
  if (meta.startTime) lines.push(`**Date:** ${new Date(meta.startTime).toLocaleString()}`);
  if (meta.model) lines.push(`**Model:** ${meta.model}`);
  if (meta.turnCount != null) lines.push(`**Turns:** ${meta.turnCount}`);
  lines.push('');
  lines.push('---');
  lines.push('');

  const systemPrompt = transcript.find(msg => msg.role === 'system');
  const conversationTurns = transcript.filter(msg => msg.role !== 'system');

  // System prompt
  if (systemPrompt) {
    lines.push('<details>');
    lines.push('<summary>System Prompt</summary>');
    lines.push('');
    lines.push(extractText(systemPrompt.content));
    lines.push('');
    lines.push('</details>');
    lines.push('');
    lines.push('---');
    lines.push('');
  }

  // Conversation turns
  conversationTurns.forEach((msg, idx) => {
    const turnNumber = Math.floor(idx / 2) + 1;
    const roleLabel = msg.role === 'tool'
      ? 'Tool Result'
      : msg.role.charAt(0).toUpperCase() + msg.role.slice(1);

    lines.push(`## ${roleLabel} (Turn ${turnNumber})`);
    lines.push('');
    lines.push(contentToMarkdown(msg.content));

    // Render tool_calls from the explicit field (content block tool_uses already rendered by contentToMarkdown)
    if (msg.tool_calls && msg.tool_calls.length > 0) {
      for (const tool of msg.tool_calls) {
        const inputStr = typeof tool.input === 'string' ? tool.input : JSON.stringify(tool.input, null, 2);
        lines.push('');
        lines.push(`> **Tool Use:** \`${tool.name}\``);
        lines.push('>');
        lines.push('> ```json');
        inputStr.split('\n').forEach(l => lines.push(`> ${l}`));
        lines.push('> ```');
      }
    }

    lines.push('');
  });

  return lines.join('\n');
}
