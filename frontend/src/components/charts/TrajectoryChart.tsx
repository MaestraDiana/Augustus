import { useState, useMemo } from 'react';
import { ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea, Customized } from 'recharts';
import { BasinSnapshot } from '../../types';
import { BASIN_COLOR_HEX } from '../../utils/constants';
import type { SessionEventInfo, SessionEventsMap } from '../../views/TrajectoryDashboard';

/** Simple string hash → positive integer. */
function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/** Marker colors for each event type. */
const MARKER_COLORS: Record<string, string> = {
  flag: '#e05252',       // alert red
  annotation: '#5b9fd6', // info blue
  proposal: '#a87fd4',   // accent purple
};

/** Marker shapes rendered as SVG paths centered at (0, 0). */
function MarkerShape({ type, x, y, size = 5 }: { type: string; x: number; y: number; size?: number }) {
  const color = MARKER_COLORS[type] || '#888';
  if (type === 'flag') {
    // Diamond
    return (
      <polygon
        points={`${x},${y - size} ${x + size},${y} ${x},${y + size} ${x - size},${y}`}
        fill={color}
        stroke="var(--bg-base)"
        strokeWidth={1}
      />
    );
  }
  if (type === 'annotation') {
    // Circle
    return <circle cx={x} cy={y} r={size - 1} fill={color} stroke="var(--bg-base)" strokeWidth={1} />;
  }
  // Proposal: square
  const half = size - 1;
  return (
    <rect
      x={x - half}
      y={y - half}
      width={half * 2}
      height={half * 2}
      fill={color}
      stroke="var(--bg-base)"
      strokeWidth={1}
      rx={1}
    />
  );
}

interface MarkerLaneProps {
  formattedGraphicalItems?: any[];
  xAxisMap?: any;
  yAxisMap?: any;
  offset?: any;
  sessionEvents: SessionEventsMap;
  showFlags: boolean;
  showAnnotations: boolean;
  showProposals: boolean;
  chartData: Array<Record<string, any>>;
  hoveredMarkerSession: string | null;
  onMarkerHover: (sessionId: string | null, events?: SessionEventInfo[]) => void;
}

/** Renders event markers in a lane at y=0.02 (bottom of chart). */
function MarkerLane({
  xAxisMap,
  sessionEvents,
  showFlags,
  showAnnotations,
  showProposals,
  chartData,
  hoveredMarkerSession,
  onMarkerHover,
}: MarkerLaneProps) {
  if (!xAxisMap) return null;
  const xAxis = Object.values(xAxisMap)[0] as any;
  if (!xAxis || !xAxis.scale) return null;

  const markers: JSX.Element[] = [];
  const MARKER_Y_BASE = 12; // pixels from top of chart area (within the top margin)

  for (let i = 0; i < chartData.length; i++) {
    const sid = chartData[i].session_id;
    const events = sessionEvents[sid];
    if (!events || events.length === 0) continue;

    // Filter by toggle state
    const visible = events.filter(e =>
      (e.type === 'flag' && showFlags) ||
      (e.type === 'annotation' && showAnnotations) ||
      (e.type === 'proposal' && showProposals)
    );
    if (visible.length === 0) continue;

    const x = xAxis.scale(sid) + (xAxis.bandSize ? xAxis.bandSize / 2 : 0);
    if (typeof x !== 'number' || isNaN(x)) continue;

    // Deduplicate types for this session
    const types = [...new Set(visible.map(e => e.type))];
    const isHovered = hoveredMarkerSession === sid;
    const totalWidth = types.length * 12;
    const startX = x - totalWidth / 2 + 6;

    markers.push(
      <g
        key={`marker-group-${sid}`}
        style={{ cursor: 'pointer' }}
        onMouseEnter={() => onMarkerHover(sid, visible)}
        onMouseLeave={() => onMarkerHover(null)}
      >
        {/* Invisible hit area */}
        <rect
          x={startX - 6}
          y={MARKER_Y_BASE - 8}
          width={totalWidth + 4}
          height={16}
          fill="transparent"
        />
        {types.map((type, idx) => (
          <MarkerShape
            key={`${sid}-${type}`}
            type={type}
            x={startX + idx * 12}
            y={MARKER_Y_BASE}
            size={isHovered ? 7 : 5}
          />
        ))}
      </g>
    );
  }

  return <g className="marker-lane">{markers}</g>;
}

interface TrajectoryChartProps {
  basinNames: string[];
  trajectoryData: BasinSnapshot[];
  visibleBasins: Set<string>;
  onBasinClick: (basinName: string) => void;
  showFlags?: boolean;
  showAnnotations?: boolean;
  showProposals?: boolean;
  sessionEvents?: SessionEventsMap;
  onMarkerClick?: (sessionId: string, type: 'flag' | 'annotation' | 'proposal') => void;
}

export default function TrajectoryChart({
  basinNames,
  trajectoryData,
  visibleBasins,
  onBasinClick,
  showFlags = true,
  showAnnotations = true,
  showProposals = true,
  sessionEvents = {},
  onMarkerClick: _onMarkerClick,
}: TrajectoryChartProps) {
  const [hoveredBasin, setHoveredBasin] = useState<string | null>(null);
  const [hoveredMarkerSession, setHoveredMarkerSession] = useState<string | null>(null);
  const [hoveredMarkerEvents, setHoveredMarkerEvents] = useState<SessionEventInfo[]>([]);

  // Build a stable name→hex color map for every basin in this chart.
  const colorMap = useMemo(() => {
    const map: Record<string, string> = {};
    const usedIndices = new Set<number>();

    for (const name of basinNames) {
      let idx = hashName(name) % BASIN_COLOR_HEX.length;
      while (usedIndices.has(idx)) {
        idx = (idx + 1) % BASIN_COLOR_HEX.length;
      }
      usedIndices.add(idx);
      map[name] = BASIN_COLOR_HEX[idx];
    }
    return map;
  }, [basinNames]);

  // Group snapshots by session, preserving backend chronological order.
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

  // Check if there are any visible session events
  const hasEvents = useMemo(() => {
    for (const sid of sessionOrder) {
      const events = sessionEvents[sid];
      if (!events) continue;
      for (const e of events) {
        if ((e.type === 'flag' && showFlags) ||
            (e.type === 'annotation' && showAnnotations) ||
            (e.type === 'proposal' && showProposals)) {
          return true;
        }
      }
    }
    return false;
  }, [sessionOrder, sessionEvents, showFlags, showAnnotations, showProposals]);

  // Detect emergence points
  const emergenceIndices = useMemo(() => {
    const map: Record<string, number> = {};
    for (const basinName of basinNames) {
      for (let i = 0; i < chartData.length; i++) {
        if (chartData[i][basinName] !== undefined) {
          if (i > 0) map[basinName] = i;
          break;
        }
      }
    }
    return map;
  }, [basinNames, chartData]);

  const handleMarkerHover = (sessionId: string | null, events?: SessionEventInfo[]) => {
    setHoveredMarkerSession(sessionId);
    setHoveredMarkerEvents(events || []);
  };

  // Custom tooltip
  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload || payload.length === 0) return null;

    const sid = payload[0].payload.session_id;
    const events = sessionEvents[sid] || [];
    const visibleEvents = events.filter(e =>
      (e.type === 'flag' && showFlags) ||
      (e.type === 'annotation' && showAnnotations) ||
      (e.type === 'proposal' && showProposals)
    );

    return (
      <div className="chart-tooltip visible">
        <div className="tooltip-header">{sid}</div>
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
        {visibleEvents.length > 0 && (
          <div className="tooltip-events">
            {visibleEvents.map(e => (
              <div key={e.id} className="tooltip-event-row">
                <span
                  className="tooltip-event-dot"
                  style={{ background: MARKER_COLORS[e.type] }}
                />
                <span className="tooltip-event-text">{e.detail}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="chart-wrapper">
      <div className="chart-area">
        <ResponsiveContainer width="100%" height={460}>
          <ComposedChart data={chartData} margin={{ top: hasEvents ? 28 : 20, right: 30, left: 10, bottom: 5 }}>
            {/* Full chart background */}
            <ReferenceArea y1={0} y2={1} fill="var(--chart-bg)" fillOpacity={1} />

            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" />

            {/* Emphasis bands */}
            <ReferenceArea y1={0.8} y2={1.0} fill="var(--emphasis-band-high)" fillOpacity={1} />
            <ReferenceArea y1={0.6} y2={0.8} fill="var(--emphasis-band-mid)" fillOpacity={1} />
            <ReferenceArea y1={0.4} y2={0.6} fill="var(--emphasis-band-low)" fillOpacity={1} />

            <XAxis
              dataKey="session_id"
              tick={{ fill: 'var(--text-secondary)', fontSize: 11, fontFamily: 'var(--font-data)' }}
              tickLine={{ stroke: 'var(--border-color)' }}
              axisLine={{ stroke: 'var(--border-color)' }}
              tickFormatter={(sid: string) => {
                const match = sid.match(/-(\d{2,4})-\d{8}/);
                if (match) return `Session ${match[1]}`;
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

            {/* Event marker lane — rendered in the chart's top margin area */}
            {hasEvents && (
              <Customized
                component={(props: any) => (
                  <MarkerLane
                    {...props}
                    sessionEvents={sessionEvents}
                    showFlags={showFlags}
                    showAnnotations={showAnnotations}
                    showProposals={showProposals}
                    chartData={chartData}
                    hoveredMarkerSession={hoveredMarkerSession}
                    onMarkerHover={handleMarkerHover}
                  />
                )}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>

        {/* Emphasis labels */}
        <div className="emphasis-labels">
          <div className="emphasis-label">High Emphasis</div>
          <div className="emphasis-label">Medium</div>
          <div className="emphasis-label">Low</div>
        </div>
      </div>

      {/* Marker tooltip (positioned above chart when hovering markers) */}
      {hoveredMarkerSession && hoveredMarkerEvents.length > 0 && (
        <div className="marker-tooltip">
          {hoveredMarkerEvents.map(e => (
            <div key={e.id} className="marker-tooltip-row">
              <span className="marker-tooltip-dot" style={{ background: MARKER_COLORS[e.type] }} />
              <span className="marker-tooltip-type">{e.type}</span>
              <span className="marker-tooltip-detail">{e.detail}</span>
            </div>
          ))}
        </div>
      )}

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
