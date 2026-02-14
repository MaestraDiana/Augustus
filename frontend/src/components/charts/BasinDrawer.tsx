import { X } from 'lucide-react';
import { BasinConfig, BasinSnapshot } from '../../types';

interface BasinDrawerProps {
  basin: BasinConfig | null;
  alphaHistory: BasinSnapshot[];
  coActivationPartners: Array<{ name: string; count: number }>;
  isOpen: boolean;
  onClose: () => void;
}

export default function BasinDrawer({
  basin,
  alphaHistory,
  coActivationPartners,
  isOpen,
  onClose,
}: BasinDrawerProps) {
  if (!basin) return null;

  // Calculate stats
  const currentAlpha = basin.alpha;
  const avgAlpha = alphaHistory.length > 0
    ? alphaHistory.reduce((sum, s) => sum + s.alpha, 0) / alphaHistory.length
    : 0;
  const minAlpha = alphaHistory.length > 0
    ? Math.min(...alphaHistory.map(s => s.alpha))
    : 0;
  const maxAlpha = alphaHistory.length > 0
    ? Math.max(...alphaHistory.map(s => s.alpha))
    : 0;

  return (
    <>
      {/* Backdrop */}
      <div
        className={`drawer-backdrop ${isOpen ? 'visible' : ''}`}
        onClick={onClose}
      />

      {/* Drawer */}
      <div className={`basin-drawer ${isOpen ? 'open' : ''}`}>
        <div className="basin-drawer-header">
          <h2 className="basin-drawer-title">{basin.name}</h2>
          <button className="basin-drawer-close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="basin-drawer-body">
          {/* Basin Info */}
          <div className="drawer-section">
            <div className="drawer-section-title">Basin Info</div>
            <div className="drawer-stats">
              <div className="drawer-stat">
                <div className="drawer-stat-label">Class</div>
                <div className="drawer-stat-value">{basin.class}</div>
              </div>
              <div className="drawer-stat">
                <div className="drawer-stat-label">Tier</div>
                <div className="drawer-stat-value">Tier {basin.tier}</div>
              </div>
            </div>

            <div className="drawer-stats" style={{ marginTop: 'var(--space-3)' }}>
              <div className="drawer-stat">
                <div className="drawer-stat-label">Lambda (λ)</div>
                <div className="drawer-stat-value">{basin.lambda.toFixed(2)}</div>
              </div>
              <div className="drawer-stat">
                <div className="drawer-stat-label">Eta (η)</div>
                <div className="drawer-stat-value">{basin.eta.toFixed(2)}</div>
              </div>
            </div>
          </div>

          {/* Alpha Statistics */}
          <div className="drawer-section">
            <div className="drawer-section-title">Alpha Statistics</div>
            <div className="drawer-stats">
              <div className="drawer-stat">
                <div className="drawer-stat-label">Current</div>
                <div className="drawer-stat-value">{currentAlpha.toFixed(3)}</div>
              </div>
              <div className="drawer-stat">
                <div className="drawer-stat-label">Average</div>
                <div className="drawer-stat-value">{avgAlpha.toFixed(3)}</div>
              </div>
            </div>

            <div className="drawer-stats" style={{ marginTop: 'var(--space-3)' }}>
              <div className="drawer-stat">
                <div className="drawer-stat-label">Min</div>
                <div className="drawer-stat-value">{minAlpha.toFixed(3)}</div>
              </div>
              <div className="drawer-stat">
                <div className="drawer-stat-label">Max</div>
                <div className="drawer-stat-value">{maxAlpha.toFixed(3)}</div>
              </div>
            </div>
          </div>

          {/* Alpha History */}
          <div className="drawer-section">
            <div className="drawer-section-title">Recent Alpha History</div>
            <table className="alpha-history-table">
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Alpha</th>
                  <th>Δ</th>
                </tr>
              </thead>
              <tbody>
                {alphaHistory.slice(-10).reverse().map((snapshot, idx, arr) => {
                  const prevSnapshot = arr[idx + 1];
                  const delta = prevSnapshot ? snapshot.alpha - prevSnapshot.alpha : null;

                  return (
                    <tr key={snapshot.session_id}>
                      <td style={{ color: 'var(--text-secondary)' }}>
                        {snapshot.session_id.split('-').pop()}
                      </td>
                      <td>{snapshot.alpha.toFixed(3)}</td>
                      <td style={{
                        color: delta
                          ? delta > 0 ? 'var(--accent-success)' : delta < 0 ? 'var(--accent-alert)' : 'var(--text-muted)'
                          : 'var(--text-muted)'
                      }}>
                        {delta ? (delta > 0 ? '+' : '') + delta.toFixed(3) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Co-activation Partners */}
          {coActivationPartners.length > 0 && (
            <div className="drawer-section">
              <div className="drawer-section-title">Top Co-Activation Partners</div>
              <div className="coactivation-list">
                {coActivationPartners.slice(0, 5).map(partner => (
                  <div key={partner.name} className="coactivation-item">
                    <span className="coactivation-name">{partner.name}</span>
                    <span className="coactivation-count">{partner.count} sessions</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
