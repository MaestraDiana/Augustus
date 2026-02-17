import { useState, useMemo } from 'react';
import { ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea } from 'recharts';
import { BasinSnapshot } from '../../types';
import { BASIN_COLOR_HEX } from '../../utils/constants';

/** Simple string hash → positive integer. */
function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

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

  // Build a stable name→hex color map for every basin in this chart.
  // Uses deterministic hashing so the same basin name always gets the
  // same color, but also avoids collisions within a single chart by
  // assigning sequentially when hashes collide.
  const colorMap = useMemo(() => {
    const map: Record<string, string> = {};
    const usedIndices = new Set<number>();

    for (const name of basinNames) {
      let idx = hashName(name) % BASIN_COLOR_HEX.length;
      // If this index is already taken by another basin in the chart,
      // walk forward to find the next unused slot.
      while (usedIndices.has(idx)) {
        idx = (idx + 1) % BASIN_COLOR_HEX.length;
      }
      usedIndices.add(idx);
      map[name] = BASIN_COLOR_HEX[idx];
    }
    return map;
  }, [basinNames]);

  // Group snapshots by session, preserving backend chronological order.
  // The backend returns snapshots ordered by session start_time ASC, so
  // we track insertion order rather than attempting to parse timestamps.
  const sessionOrder: string[] = [];
  const sessionGroups: Record<string, any> = {};
  for (const snapshot of trajectoryData) {
    if (!sessionGroups[snapshot.session_id]) {
      sessionGroups[snapshot.session_id] = {
        session_id: snapshot.session_id,
      };
      sessionOrder.push(snapshot.session_id);
    }
    sessionGroups[snapshot.session_id][snapshot.basin_name] = snapshot.alpha;
  }

  const chartData = sessionOrder.map(sid => sessionGroups[sid]);

  // Detect emergence points: the first session where each basin has data,
  // but only if it's NOT the very first session in the chart (those aren't emergent).
  const emergenceIndices = useMemo(() => {
    const map: Record<string, number> = {};
    for (const basinName of basinNames) {
      for (let i = 0; i < chartData.length; i++) {
        if (chartData[i][basinName] !== undefined) {
          // Only mark as emergence if it doesn't start at session 0
          if (i > 0) map[basinName] = i;
          break;
        }
      }
    }
    return map;
  }, [basinNames, chartData]);

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
                  style={{ background: colorMap[p.dataKey] }}
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
        <ResponsiveContainer width="100%" height={460}>
          <ComposedChart data={chartData} margin={{ top: 20, right: 30, left: 10, bottom: 5 }}>
            {/* Full chart background */}
            <ReferenceArea y1={0} y2={1} fill="var(--chart-bg)" fillOpacity={1} />

            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />

            {/* Emphasis bands — layered over base background */}
            <ReferenceArea y1={0.8} y2={1.0} fill="var(--emphasis-band-high)" fillOpacity={1} />
            <ReferenceArea y1={0.6} y2={0.8} fill="var(--emphasis-band-mid)" fillOpacity={1} />
            <ReferenceArea y1={0.4} y2={0.6} fill="var(--emphasis-band-low)" fillOpacity={1} />

            <XAxis
              dataKey="session_id"
              tick={{ fill: 'var(--text-secondary)', fontSize: 11, fontFamily: 'var(--font-data)' }}
              tickLine={{ stroke: 'var(--border-color)' }}
              axisLine={{ stroke: 'var(--border-color)' }}
              tickFormatter={(sid: string) => {
                // Extract session number from IDs like "qlaude-015-20260215-225348".
                // The session number is the first short digit group (typically 3 digits)
                // after the agent name prefix, NOT the 8-digit date or 6-digit time.
                const match = sid.match(/-(\d{2,4})-\d{8}/);
                if (match) return `Session ${match[1]}`;
                // Fallback: first 3-digit group that isn't 8+ digits (date)
                const fallback = sid.match(/(?<!\d)(\d{2,4})(?!\d)/);
                return fallback ? `Session ${fallback[1]}` : sid;
              }}
              angle={-45}
              textAnchor="end"
              height={60}
            />

            <YAxis
              domain={[0, 1]}
              tick={{ fill: 'var(--text-secondary)', fontSize: 12, fontFamily: 'var(--font-data)' }}
              tickLine={{ stroke: 'var(--border-color)' }}
              axisLine={{ stroke: 'var(--border-color)' }}
            />

            <Tooltip content={<CustomTooltip />} cursor={{ stroke: 'var(--accent-primary)', strokeWidth: 1 }} />

            {/* Basin lines */}
            {basinNames.map((basinName) => {
              const emergeIdx = emergenceIndices[basinName];
              return (
                <Line
                  key={basinName}
                  type="monotone"
                  dataKey={basinName}
                  stroke={colorMap[basinName]}
                  strokeWidth={visibleBasins.has(basinName) ? 2.5 : 0}
                  dot={emergeIdx !== undefined ? (props: any) => {
                    if (props.index !== emergeIdx) return <g key={props.key} />;
                    return (
                      <g key={props.key}>
                        <circle
                          cx={props.cx}
                          cy={props.cy}
                          r={5}
                          fill={colorMap[basinName]}
                          stroke="var(--bg-surface)"
                          strokeWidth={2}
                        />
                        <title>{`${basinName} emerged — ${chartData[emergeIdx]?.session_id}`}</title>
                      </g>
                    );
                  } : false}
                  activeDot={{
                    r: 5,
                    fill: colorMap[basinName],
                    stroke: 'var(--bg-surface)',
                    strokeWidth: 2,
                  }}
                  opacity={hoveredBasin ? (hoveredBasin === basinName ? 1 : 0.3) : 1}
                  isAnimationActive={false}
                />
              );
            })}
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
              style={{ background: colorMap[basinName] }}
            />
            <span className="legend-label">{basinName}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
