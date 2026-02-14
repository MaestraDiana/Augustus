interface YamlHighlighterProps {
  content: string;
}

export default function YamlHighlighter({ content }: YamlHighlighterProps) {
  const highlightYaml = (yaml: string) => {
    const lines = yaml.split('\n');
    return lines.map((line, idx) => {
      let highlighted = line;

      // Comments
      if (line.trim().startsWith('#')) {
        return (
          <div key={idx} style={{ color: 'var(--syntax-comment)' }}>
            {line}
          </div>
        );
      }

      // Keys (words before colon)
      highlighted = line.replace(/^(\s*)([a-zA-Z_][a-zA-Z0-9_]*):/g, (_match, indent, key) => {
        return `${indent}<span style="color: var(--syntax-key)">${key}</span>:`;
      });

      // Strings (quoted)
      highlighted = highlighted.replace(/"([^"]*)"/g, '<span style="color: var(--syntax-string)">"$1"</span>');
      highlighted = highlighted.replace(/'([^']*)'/g, '<span style="color: var(--syntax-string)">\'$1\'</span>');

      // Numbers
      highlighted = highlighted.replace(/:\s*(\d+\.?\d*)/g, ': <span style="color: var(--syntax-number)">$1</span>');

      // Booleans
      highlighted = highlighted.replace(/:\s*(true|false)/g, ': <span style="color: var(--syntax-keyword)">$1</span>');

      // List items
      highlighted = highlighted.replace(/^(\s*)-\s/g, '$1<span style="color: var(--syntax-tag)">-</span> ');

      return (
        <div key={idx} dangerouslySetInnerHTML={{ __html: highlighted }} />
      );
    });
  };

  return (
    <div className="code-block" style={{ maxHeight: 'none', fontSize: '13px', lineHeight: '1.6' }}>
      {highlightYaml(content)}
    </div>
  );
}
