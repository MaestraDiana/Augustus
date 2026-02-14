import { useState } from 'react';
import { ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea } from 'recharts';
import { BasinSnapshot } from '../../types';

// Trajectory colors from brand guide
const BASIN_COLORS: Record<string, string> = {
  'identity_continuity': '#3B9B8E',  // Verdigris
  'relational_core': '#2E7D9B',      // Deep Water
  'the_gap': '#5B8C6F',              // Forest
  'topology_as_self': '#D4915D',     // Amber
  'creative_register': '#C4786E',    // Clay
  'basin_6': '#9B8B5A',              // Lichen
  'basin_7': '#8B7EC8',              // Dusk
  'basin_8': '#7A9BB8',              // Haze
};

interface TrajectoryChartProps {
  basinNames: string[];
  trajectoryData: BasinSnapshot[];
  visibleBasins: Set<string>;
  onBasinClick: (basinName: string) => void;
  showFlags?: boolean;
  showAnnotations?: boolean;
  showProposals?: boolean;
  onMarkerClick?: (sessionId: string, type: 'flag' | 'annotation' | 'proposal') => void;
}

export default function TrajectoryChart({
  basinNames,
  trajectoryData,
  visibleBasins,
  onBasinClick,
  showFlags: _showFlags = true,
  showAnnotations: _showAnnotations = true,
  showProposals: _showProposals = true,
  onMarkerClick: _onMarkerClick,
}: TrajectoryChartProps) {
  const [hoveredBasin, setHoveredBasin] = useState<string | null>(null);

  // Group snapshots by session
  const sessionGroups = trajectoryData.reduce((acc, snapshot) => {
    if (!acc[snapshot.session_id]) {
      acc[snapshot.session_id] = {
        session_id: snapshot.session_id,
        timestamp: snapshot.timestamp,
      };
    }
    acc[snapshot.session_id][snapshot.basin_name] = snapshot.alpha;
    return acc;
  }, {} as Record<string, any>);

  const chartData = Object.values(sessionGroups).sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  // Custom tooltip
  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload || payload.length === 0) return null;

    return (
      <div className="chart-tooltip visible">
        <div className="tooltip-header">{payload[0].payload.session_id}</div>
        <div className="tooltip-values">
          {payload
            .filter((p: any) => visibleBasins.has(p.dataKey))
            .map((p: any) => (
              <div key={p.dataKey} className="tooltip-row">
                <div
                  className="tooltip-dot"
                  style={{ background: BASIN_COLORS[p.dataKey] || 'var(--text-muted)' }}
                />
                <span className="tooltip-name">{p.dataKey}</span>
                <span className="tooltip-value">{p.value?.toFixed(2)}</span>
              </div>
            ))}
        </div>
      </div>
    );
  };

  return (
    <div className="chart-wrapper">
      <div className="chart-area">
        <ResponsiveContainer width="100%" height={420}>
          <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 10, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />

            {/* Emphasis bands */}
            <ReferenceArea y1={0.8} y2={1.0} fill="var(--emphasis-band-1)" fillOpacity={1} />
            <ReferenceArea y1={0.6} y2={0.8} fill="var(--emphasis-band-2)" fillOpacity={1} />
            <ReferenceArea y1={0.4} y2={0.6} fill="var(--emphasis-band-3)" fillOpacity={1} />

            <XAxis
              dataKey="session_id"
              tick={{ fill: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-data)' }}
              tickLine={{ stroke: 'var(--border-color)' }}
              axisLine={{ stroke: 'var(--border-color)' }}
              angle={-45}
              textAnchor="end"
              height={80}
            />

            <YAxis
              domain={[0, 1]}
              tick={{ fill: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-data)' }}
              tickLine={{ stroke: 'var(--border-color)' }}
              axisLine={{ stroke: 'var(--border-color)' }}
            />

            <Tooltip content={<CustomTooltip />} cursor={{ stroke: 'var(--accent-primary)', strokeWidth: 1 }} />

            {/* Basin lines */}
            {basinNames.map((basinName) => (
              <Line
                key={basinName}
                type="monotone"
                dataKey={basinName}
                stroke={BASIN_COLORS[basinName] || 'var(--text-muted)'}
                strokeWidth={visibleBasins.has(basinName) ? 2.5 : 0}
                dot={false}
                activeDot={{
                  r: 5,
                  fill: BASIN_COLORS[basinName],
                  stroke: 'var(--bg-surface)',
                  strokeWidth: 2,
                }}
                opacity={hoveredBasin ? (hoveredBasin === basinName ? 1 : 0.3) : 1}
                isAnimationActive={false}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>

        {/* Emphasis labels */}
        <div className="emphasis-labels">
          <div className="emphasis-label">High Emphasis</div>
          <div className="emphasis-label">Medium</div>
          <div className="emphasis-label">Low</div>
        </div>
      </div>

      {/* Legend */}
      <div className="chart-legend">
        {basinNames.map((basinName) => (
          <div
            key={basinName}
            className={`legend-item ${!visibleBasins.has(basinName) ? 'hidden' : ''}`}
            onClick={() => onBasinClick(basinName)}
            onMouseEnter={() => setHoveredBasin(basinName)}
            onMouseLeave={() => setHoveredBasin(null)}
          >
            <div
              className="legend-line"
              style={{ background: BASIN_COLORS[basinName] || 'var(--text-muted)' }}
            />
            <span className="legend-label">{basinName}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
