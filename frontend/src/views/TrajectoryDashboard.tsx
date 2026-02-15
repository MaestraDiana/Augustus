import { useState, useEffect, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { Check, BarChart3, GitMerge } from 'lucide-react';
import { api } from '../api/client';
import TrajectoryChart from '../components/charts/TrajectoryChart';
import BasinDrawer from '../components/charts/BasinDrawer';
import EmptyState from '../components/ui/EmptyState';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import type { BasinConfig, BasinSnapshot } from '../types';

interface ConvergencePair {
  basin_a: string;
  basin_b: string;
  current_gap: number;
  trend: 'converging' | 'diverging' | 'stable';
  sessions_observed: number;
}

function detectConvergences(
  basins: BasinConfig[],
  trajectoryData: BasinSnapshot[],
  gapThreshold = 0.10,
  minSessions = 3,
): ConvergencePair[] {
  const pairs: ConvergencePair[] = [];
  if (basins.length < 2) return pairs;

  // Group snapshots by basin name, ordered by session sequence
  const byBasin: Record<string, BasinSnapshot[]> = {};
  for (const snap of trajectoryData) {
    if (!byBasin[snap.basin_name]) byBasin[snap.basin_name] = [];
    byBasin[snap.basin_name].push(snap);
  }

  // Get the unique session IDs in order to align basins
  const sessionOrder: string[] = [];
  const seen = new Set<string>();
  for (const snap of trajectoryData) {
    if (!seen.has(snap.session_id)) {
      seen.add(snap.session_id);
      sessionOrder.push(snap.session_id);
    }
  }

  // Build per-basin alpha maps keyed by session_id
  const alphaBySession: Record<string, Record<string, number>> = {};
  for (const [name, snaps] of Object.entries(byBasin)) {
    alphaBySession[name] = {};
    for (const s of snaps) {
      alphaBySession[name][s.session_id] = s.alpha;
    }
  }

  // Check every unique pair
  for (let i = 0; i < basins.length; i++) {
    for (let j = i + 1; j < basins.length; j++) {
      const a = basins[i].name;
      const b = basins[j].name;
      const alphaA = alphaBySession[a];
      const alphaB = alphaBySession[b];
      if (!alphaA || !alphaB) continue;

      // Get gap over the last N common sessions
      const commonSessions = sessionOrder.filter(
        sid => alphaA[sid] !== undefined && alphaB[sid] !== undefined
      );
      if (commonSessions.length < minSessions) continue;

      const recent = commonSessions.slice(-Math.max(minSessions, 5));
      const gaps = recent.map(sid => Math.abs(alphaA[sid] - alphaB[sid]));
      const currentGap = gaps[gaps.length - 1];

      if (currentGap > gapThreshold) continue;

      // Determine trend: is the gap shrinking over these sessions?
      let shrinkCount = 0;
      for (let k = 1; k < gaps.length; k++) {
        if (gaps[k] < gaps[k - 1]) shrinkCount++;
      }

      const shrinkRatio = shrinkCount / (gaps.length - 1);
      let trend: ConvergencePair['trend'] = 'stable';
      if (shrinkRatio >= 0.6) trend = 'converging';
      else if (shrinkRatio <= 0.3) trend = 'diverging';

      if (trend === 'converging' || currentGap <= 0.05) {
        pairs.push({
          basin_a: a,
          basin_b: b,
          current_gap: Math.round(currentGap * 1000) / 1000,
          trend,
          sessions_observed: recent.length,
        });
      }
    }
  }

  return pairs.sort((a, b) => a.current_gap - b.current_gap);
}

type TimeRange = 10 | 25 | 50 | 100 | 'all';

export default function TrajectoryDashboard() {
  const { agentId } = useParams<{ agentId: string }>();
  const [timeRange, setTimeRange] = useState<TimeRange>(25);
  const [basins, setBasins] = useState<BasinConfig[]>([]);
  const [trajectoryData, setTrajectoryData] = useState<BasinSnapshot[]>([]);
  const [coActivation, setCoActivation] = useState<Record<string, Array<{ name: string; count: number }>>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [visibleBasins, setVisibleBasins] = useState<Set<string>>(new Set());
  const [showFlags, setShowFlags] = useState(true);
  const [showAnnotations, setShowAnnotations] = useState(true);
  const [showProposals, setShowProposals] = useState(true);
  const [selectedBasin, setSelectedBasin] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) return;

    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        // Fetch agent and trajectory data (required), co-activation is optional
        const [agentData, trajectories] = await Promise.all([
          api.agents.get(agentId),
          api.trajectories.get(agentId, timeRange === 'all' ? 200 : timeRange),
        ]);

        let coactivationData: { edges?: Array<{ source: string; target: string; count: number }> } = {};
        try {
          coactivationData = await api.coactivation.get(agentId);
        } catch (err) {
          console.warn('Failed to load co-activation data:', err);
        }

        setBasins(agentData.basins);
        setVisibleBasins(new Set(agentData.basins.map(b => b.name)));

        // Transform backend trajectory response to flat BasinSnapshot array
        const snapshots: BasinSnapshot[] = [];
        if (trajectories.trajectories) {
          for (const [basinName, basinData] of Object.entries(trajectories.trajectories)) {
            const typedBasinData = basinData as any;
            if (typedBasinData.points) {
              for (const point of typedBasinData.points) {
                snapshots.push({
                  basin_name: basinName,
                  alpha: point.alpha_end,
                  relevance_score: point.relevance_score,
                  delta: point.delta,
                  session_id: point.session_id,
                  timestamp: point.session_id, // Backend doesn't include timestamp in trajectory points
                });
              }
            }
          }
        }
        setTrajectoryData(snapshots);

        // Transform co-activation edges to basin-centric map
        const coactivationMap: Record<string, Array<{ name: string; count: number }>> = {};
        if (coactivationData.edges) {
          for (const edge of coactivationData.edges) {
            if (!coactivationMap[edge.source]) {
              coactivationMap[edge.source] = [];
            }
            if (!coactivationMap[edge.target]) {
              coactivationMap[edge.target] = [];
            }
            coactivationMap[edge.source].push({ name: edge.target, count: edge.count });
            coactivationMap[edge.target].push({ name: edge.source, count: edge.count });
          }
        }
        setCoActivation(coactivationMap);
      } catch (err) {
        console.error('Failed to load trajectory data:', err);
        setError(err instanceof Error ? err.message : 'Failed to load trajectory data');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [agentId, timeRange]);

  // Filter trajectory data by time range
  const filteredData = timeRange === 'all'
    ? trajectoryData
    : trajectoryData.slice(-timeRange * 5); // 5 data points per session

  const handleBasinClick = (basinName: string) => {
    setSelectedBasin(basinName);
  };

  const convergences = useMemo(
    () => detectConvergences(basins, trajectoryData),
    [basins, trajectoryData],
  );

  const selectedBasinConfig = basins.find(b => b.name === selectedBasin) || null;
  const selectedBasinHistory = selectedBasin
    ? trajectoryData.filter(s => s.basin_name === selectedBasin)
    : [];
  const selectedBasinCoactivation = selectedBasin
    ? coActivation[selectedBasin] || []
    : [];

  if (loading) {
    return (
      <div style={{ padding: 'var(--space-6)' }}>
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <LoadingSkeleton height="40px" width="300px" />
        </div>
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <LoadingSkeleton height="400px" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--space-4)' }}>
          <LoadingSkeleton height="100px" />
          <LoadingSkeleton height="100px" />
          <LoadingSkeleton height="100px" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 'var(--space-6)' }}>
        <EmptyState
          icon={<BarChart3 size={48} style={{ color: 'var(--text-tertiary)' }} />}
          title="Failed to load trajectory data"
          message={error}
        />
      </div>
    );
  }

  if (basins.length === 0 || trajectoryData.length === 0) {
    return (
      <div style={{ padding: 'var(--space-6)' }}>
        <EmptyState
          icon={<BarChart3 size={48} style={{ color: 'var(--text-tertiary)' }} />}
          title="No trajectory data yet"
          message="Data will appear after sessions are completed."
        />
      </div>
    );
  }

  return (
    <div className="trajectory-container">
      {/* Chart Controls */}
      <div className="chart-controls">
        <div className="chart-controls-left">
          <div className="range-buttons">
            <button
              className={`range-btn ${timeRange === 10 ? 'active' : ''}`}
              onClick={() => setTimeRange(10)}
            >
              Last 10
            </button>
            <button
              className={`range-btn ${timeRange === 25 ? 'active' : ''}`}
              onClick={() => setTimeRange(25)}
            >
              Last 25
            </button>
            <button
              className={`range-btn ${timeRange === 50 ? 'active' : ''}`}
              onClick={() => setTimeRange(50)}
            >
              Last 50
            </button>
            <button
              className={`range-btn ${timeRange === 100 ? 'active' : ''}`}
              onClick={() => setTimeRange(100)}
            >
              Last 100
            </button>
            <button
              className={`range-btn ${timeRange === 'all' ? 'active' : ''}`}
              onClick={() => setTimeRange('all')}
            >
              All
            </button>
          </div>
        </div>

        <div className="chart-controls-right">
          <div className="marker-toggles">
            <label className="marker-toggle">
              <input
                type="checkbox"
                checked={showFlags}
                onChange={() => setShowFlags(!showFlags)}
              />
              <div className="marker-toggle-box">
                <Check size={12} />
              </div>
              <span>Flags</span>
            </label>

            <label className="marker-toggle">
              <input
                type="checkbox"
                checked={showAnnotations}
                onChange={() => setShowAnnotations(!showAnnotations)}
              />
              <div className="marker-toggle-box">
                <Check size={12} />
              </div>
              <span>Annotations</span>
            </label>

            <label className="marker-toggle">
              <input
                type="checkbox"
                checked={showProposals}
                onChange={() => setShowProposals(!showProposals)}
              />
              <div className="marker-toggle-box">
                <Check size={12} />
              </div>
              <span>Proposals</span>
            </label>
          </div>
        </div>
      </div>

      {/* Trajectory Chart */}
      <TrajectoryChart
        basinNames={basins.map(b => b.name)}
        trajectoryData={filteredData}
        visibleBasins={visibleBasins}
        onBasinClick={handleBasinClick}
        showFlags={showFlags}
        showAnnotations={showAnnotations}
        showProposals={showProposals}
      />

      {/* Convergence Detection */}
      {convergences.length > 0 && (
        <div className="convergence-panel">
          <div className="convergence-header">
            <GitMerge size={16} style={{ color: 'var(--brand-verdigris)' }} />
            <span>Convergence Detected</span>
          </div>
          <div className="convergence-list">
            {convergences.map(c => (
              <div
                key={`${c.basin_a}-${c.basin_b}`}
                className="convergence-item"
              >
                <span className="convergence-pair">
                  <button
                    className="convergence-basin-link"
                    onClick={() => handleBasinClick(c.basin_a)}
                  >
                    {c.basin_a}
                  </button>
                  {' '}
                  <span style={{ color: 'var(--text-tertiary)' }}>&harr;</span>
                  {' '}
                  <button
                    className="convergence-basin-link"
                    onClick={() => handleBasinClick(c.basin_b)}
                  >
                    {c.basin_b}
                  </button>
                </span>
                <span className="convergence-meta">
                  <span className={`convergence-trend convergence-trend--${c.trend}`}>
                    {c.trend}
                  </span>
                  <span className="convergence-gap">
                    {'\u0394'}{c.current_gap.toFixed(3)}
                  </span>
                  <span className="convergence-sessions">
                    {c.sessions_observed}s
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Basin Detail Drawer */}
      <BasinDrawer
        basin={selectedBasinConfig}
        alphaHistory={selectedBasinHistory}
        coActivationPartners={selectedBasinCoactivation}
        isOpen={selectedBasin !== null}
        onClose={() => setSelectedBasin(null)}
      />
    </div>
  );
}
