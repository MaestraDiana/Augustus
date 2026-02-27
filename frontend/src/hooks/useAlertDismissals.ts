import { useState, useCallback, useEffect } from 'react';

const STORAGE_KEY = 'dismissed-alerts';
const DISMISSED_EVENT = 'alert-dismissed-changed';

export function alertDismissKey(linkType?: string, agentId?: string, sessionId?: string | null): string {
  return `alert-dismissed:${linkType ?? ''}:${agentId ?? ''}:${sessionId ?? ''}`;
}

function readDismissed(): Set<string> {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    return stored ? new Set(JSON.parse(stored)) : new Set();
  } catch { return new Set(); }
}

function writeDismissed(dismissed: Set<string>) {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...dismissed])); } catch {}
}

/** Dismiss an alert from outside a React component (e.g. SessionDetail sync). */
export function dismissAlertKey(key: string) {
  const dismissed = readDismissed();
  dismissed.add(key);
  writeDismissed(dismissed);
  window.dispatchEvent(new CustomEvent(DISMISSED_EVENT));
}

export function useAlertDismissals() {
  const [dismissed, setDismissed] = useState<Set<string>>(readDismissed);

  // Stay in sync when another component dismisses an alert.
  useEffect(() => {
    const handler = () => setDismissed(readDismissed());
    window.addEventListener(DISMISSED_EVENT, handler);
    return () => window.removeEventListener(DISMISSED_EVENT, handler);
  }, []);

  const dismiss = useCallback((key: string) => {
    setDismissed(prev => {
      const next = new Set(prev);
      next.add(key);
      writeDismissed(next);
      window.dispatchEvent(new CustomEvent(DISMISSED_EVENT));
      return next;
    });
  }, []);

  return { dismissed, dismiss };
}
