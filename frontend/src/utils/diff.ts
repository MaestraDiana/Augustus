/**
 * Lightweight line-based diff using Longest Common Subsequence (LCS).
 * Produces a unified diff suitable for rendering added/removed/unchanged lines.
 */

export type DiffLineType = 'added' | 'removed' | 'unchanged';

export interface DiffLine {
  type: DiffLineType;
  content: string;
  oldLineNumber: number | null;
  newLineNumber: number | null;
}

/**
 * Compute a line-by-line diff between two texts using LCS.
 * Returns an array of DiffLine objects suitable for rendering.
 */
export function computeDiff(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split('\n');
  const newLines = newText.split('\n');

  const m = oldLines.length;
  const n = newLines.length;

  // Build LCS table
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // Backtrack to produce diff (build in reverse, then flip)
  const stack: DiffLine[] = [];
  let i = m;
  let j = n;

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      stack.push({
        type: 'unchanged',
        content: oldLines[i - 1],
        oldLineNumber: i,
        newLineNumber: j,
      });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      stack.push({
        type: 'added',
        content: newLines[j - 1],
        oldLineNumber: null,
        newLineNumber: j,
      });
      j--;
    } else {
      stack.push({
        type: 'removed',
        content: oldLines[i - 1],
        oldLineNumber: i,
        newLineNumber: null,
      });
      i--;
    }
  }

  return stack.reverse();
}

/**
 * Summarize a diff result — counts of added, removed, and unchanged lines.
 */
export function diffSummary(lines: DiffLine[]): {
  added: number;
  removed: number;
  unchanged: number;
} {
  let added = 0;
  let removed = 0;
  let unchanged = 0;
  for (const line of lines) {
    if (line.type === 'added') added++;
    else if (line.type === 'removed') removed++;
    else unchanged++;
  }
  return { added, removed, unchanged };
}
