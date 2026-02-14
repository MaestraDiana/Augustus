import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { Check, BarChart3 } from 'lucide-react';
import { api } from '../api/client';
import TrajectoryChart from '../components/charts/TrajectoryChart';
import BasinDrawer from '../components/charts/BasinDrawer';
import EmptyState from '../components/ui/EmptyState';
import LoadingSkeleton from '../components/ui/LoadingSkeleton';
import type { BasinConfig, BasinSnapshot } from '../types';

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
