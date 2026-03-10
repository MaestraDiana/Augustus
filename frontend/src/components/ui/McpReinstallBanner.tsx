import { AlertTriangle, X } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

const DISMISS_KEY = 'augustus-mcp-reinstall-dismissed';

export default function McpReinstallBanner() {
  const navigate = useNavigate();
  const [needsReinstall, setNeedsReinstall] = useState(false);
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === 'true';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    // Only check in Electron where the bridge is available
    if (!window.augustus?.claudeExtension) return;

    window.augustus.claudeExtension.check().then((status) => {
      if (status.claudeDesktopFound && !status.installed) {
        setNeedsReinstall(true);
      }
    }).catch(() => {
      // Can't check — don't show banner
    });
  }, []);

  if (dismissed || !needsReinstall) return null;

  const handleDismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, 'true');
    } catch {
      // localStorage unavailable
    }
  };

  const handleInstallNow = () => {
    navigate('/settings#integration');
  };

  return (
    <div className="mcp-reinstall-banner">
      <div className="update-banner-content">
        <AlertTriangle size={14} />
        <span>
          Due to an Anthropic update, MCP reinstall is needed.{' '}
          <button className="mcp-reinstall-link" onClick={handleInstallNow}>
            Install now
          </button>
        </span>
      </div>
      <button
        className="update-banner-dismiss"
        onClick={handleDismiss}
        title="Dismiss"
      >
        <X size={14} />
      </button>
    </div>
  );
}
