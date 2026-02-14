/**
 * Timestamp utilities.
 *
 * Backend timestamps are UTC ISO-8601 strings produced by Python's
 * `datetime.utcnow().isoformat()`.  These lack a timezone suffix, so
 * `new Date(ts)` treats them as **local time** — which produces wrong
 * results (including negative "ago" values) for anyone not in UTC.
 *
 * `parseUTC` normalises the string before parsing.
 */

/** Parse a backend timestamp as UTC, regardless of whether it has a Z suffix. */
export function parseUTC(timestamp: string): Date {
  if (!timestamp) return new Date(0);
  // If it looks like a bare ISO datetime (no Z, no +/- offset after the time), append Z
  const normalized = /\d{4}-\d{2}-\d{2}T[\d:.]+$/.test(timestamp)
    ? timestamp + 'Z'
    : timestamp;
  return new Date(normalized);
}

/** Human-friendly relative time ("3 minutes ago", "2 hours ago"). */
export function timeAgo(timestamp: string): string {
  if (!timestamp) return '—';
  const diff = Date.now() - parseUTC(timestamp).getTime();
  if (diff < 0) return 'just now'; // clock skew guard

  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return 'just now';

  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;

  const hours = Math.floor(diff / 3_600_000);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;

  const days = Math.floor(diff / 86_400_000);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

/** Format a timestamp as a locale string (e.g. "Feb 13, 5:04 PM"). */
export function formatTimestamp(timestamp: string): string {
  if (!timestamp) return '—';
  const date = parseUTC(timestamp);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

/** Short date display (e.g. "Jan 5", "Feb 13"). */
export function formatDate(dateStr: string): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** Duration between two UTC timestamps as "Xm Ys" or "Xh Ym". */
export function formatDuration(startTime: string, endTime: string): string {
  if (!startTime || !endTime) return '—';
  const diff = parseUTC(endTime).getTime() - parseUTC(startTime).getTime();
  if (diff < 0) return '—';

  const totalSeconds = Math.floor(diff / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}
