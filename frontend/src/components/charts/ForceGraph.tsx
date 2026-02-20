import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';

export interface GraphNode {
  id: string;
  name: string;
  alpha: number;
  class: 'core' | 'peripheral';
  tier: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  count: number;
  character: 'reinforcing' | 'tensional' | 'serving' | 'competing' | 'uncharacterized';
}

interface ForceGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  colorMode: 'class' | 'tier';
  showLabels: boolean;
  minCount: number;
  showUncharacterized: boolean;
  scale?: number;
  onNodeClick?: (node: GraphNode) => void;
  onEdgeClick?: (edge: GraphEdge) => void;
}

interface D3Node extends d3.SimulationNodeDatum, GraphNode {
  x?: number;
  y?: number;
}

interface D3Edge {
  source: D3Node;
  target: D3Node;
  count: number;
  character: 'reinforcing' | 'tensional' | 'serving' | 'competing' | 'uncharacterized';
}

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  node: D3Node | null;
}

export default function ForceGraph({
  nodes,
  edges,
  colorMode,
  showLabels,
  minCount,
  showUncharacterized,
  scale = 50,
  onNodeClick,
  onEdgeClick
}: ForceGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const gRef = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({ visible: false, x: 0, y: 0, node: null });

  useEffect(() => {
    if (!svgRef.current) return;

    const svg = d3.select(svgRef.current);
    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;

    svg.selectAll('*').remove();

    // Filter edges
    const filteredEdges = edges.filter(e => {
      if (e.count < minCount) return false;
      if (!showUncharacterized && e.character === 'uncharacterized') return false;
      return true;
    });

    // Create D3 nodes with proper typing
    const d3Nodes: D3Node[] = nodes.map(n => ({ ...n }));
    const nodeMap = new Map(d3Nodes.map(n => [n.id, n]));

    // Create D3 edges with proper references
    const d3Edges: D3Edge[] = filteredEdges
      .map(e => {
        const source = nodeMap.get(e.source);
        const target = nodeMap.get(e.target);
        if (!source || !target) return null;
        return { ...e, source, target };
      })
      .filter((e): e is D3Edge => e !== null);

    // Setup force simulation
    const simulation = d3.forceSimulation<D3Node>(d3Nodes)
      .force('link', d3.forceLink<D3Node, D3Edge>(d3Edges)
        .id(d => d.id)
        .distance(120))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(d => (d as D3Node).alpha * 30 + 20));

    const g = svg.append('g');
    gRef.current = g;

    // Add zoom
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 5])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });
    zoomRef.current = zoom;
    svg.call(zoom);

    // Apply initial scale from prop (50 = 1.0x, 100 = 2.0x, 1 = 0.2x)
    const initialScale = 0.2 + (scale / 100) * 1.8;
    const initialTransform = d3.zoomIdentity
      .translate(width / 2, height / 2)
      .scale(initialScale)
      .translate(-width / 2, -height / 2);
    svg.call(zoom.transform, initialTransform);

    // Edge color mapping
    const edgeColors: Record<string, string> = {
      reinforcing: 'var(--accent-success)',
      tensional: 'var(--accent-alert)',
      serving: '#2E7D9B',
      competing: 'var(--accent-attention)',
      uncharacterized: 'var(--text-muted)'
    };

    // Draw edges
    const link = g.append('g')
      .selectAll('line')
      .data(d3Edges)
      .join('line')
      .attr('stroke', d => edgeColors[d.character] || edgeColors.uncharacterized)
      .attr('stroke-width', d => Math.sqrt(d.count) * 1.5)
      .attr('stroke-dasharray', d => {
        if (d.character === 'tensional' || d.character === 'competing') return '5,3';
        if (d.character === 'uncharacterized') return '2,2';
        return '0';
      })
      .attr('marker-end', d => d.character === 'serving' ? 'url(#arrowhead)' : '')
      .style('cursor', 'pointer')
      .on('click', (event, d) => {
        event.stopPropagation();
        if (onEdgeClick) {
          const originalEdge = edges.find(e =>
            e.source === d.source.id && e.target === d.target.id
          );
          if (originalEdge) onEdgeClick(originalEdge);
        }
      });

    // Node color mapping
    const getNodeColor = (node: D3Node) => {
      if (colorMode === 'class') {
        return node.class === 'core' ? 'var(--accent-primary)' : 'var(--accent-attention)';
      } else {
        if (node.tier === 1) return 'var(--accent-alert)';
        if (node.tier === 2) return 'var(--accent-identity)';
        return 'var(--text-secondary)';
      }
    };

    // Draw nodes
    const node = g.append('g')
      .selectAll('circle')
      .data(d3Nodes)
      .join('circle')
      .attr('r', d => d.alpha * 30 + 10)
      .attr('fill', getNodeColor)
      .attr('stroke', 'var(--bg-base)')
      .attr('stroke-width', 2)
      .style('cursor', 'pointer')
      .on('mousemove', (event, d) => {
        if (!containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        setTooltip({
          visible: true,
          x: event.clientX - rect.left + 12,
          y: event.clientY - rect.top - 8,
          node: d,
        });
      })
      .on('mouseleave', () => {
        setTooltip(t => ({ ...t, visible: false }));
      })
      .on('click', (event, d) => {
        event.stopPropagation();
        if (onNodeClick) onNodeClick(d);
      })
      .call(d3.drag<SVGCircleElement, D3Node>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }) as any);

    // Add labels
    const labels = g.append('g')
      .selectAll('text')
      .data(d3Nodes)
      .join('text')
      .attr('text-anchor', 'middle')
      .attr('dy', d => d.alpha * 30 + 24)
      .attr('font-family', 'var(--font-data)')
      .attr('font-size', '12px')
      .attr('fill', 'var(--text-primary)')
      .style('pointer-events', 'none')
      .style('opacity', showLabels ? 1 : 0)
      .text(d => d.name);

    // Update positions on simulation tick
    simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x || 0)
        .attr('y1', d => d.source.y || 0)
        .attr('x2', d => d.target.x || 0)
        .attr('y2', d => d.target.y || 0);

      node
        .attr('cx', d => d.x || 0)
        .attr('cy', d => d.y || 0);

      labels
        .attr('x', d => d.x || 0)
        .attr('y', d => d.y || 0);
    });

    // Cleanup
    return () => {
      simulation.stop();
    };
  }, [nodes, edges, colorMode, showLabels, minCount, showUncharacterized, onNodeClick, onEdgeClick]);

  // Update zoom level when scale prop changes (without re-creating the graph)
  useEffect(() => {
    if (!svgRef.current || !zoomRef.current) return;
    const svg = d3.select(svgRef.current);
    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;
    const newScale = 0.2 + (scale / 100) * 1.8;
    const transform = d3.zoomIdentity
      .translate(width / 2, height / 2)
      .scale(newScale)
      .translate(-width / 2, -height / 2);
    svg.transition().duration(200).call(zoomRef.current.transform, transform);
  }, [scale]);

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative' }}>
      <svg
        ref={svgRef}
        style={{ width: '100%', height: '100%' }}
      >
        <defs>
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon
              points="0 0, 10 3.5, 0 7"
              fill="#2E7D9B"
            />
          </marker>
        </defs>
      </svg>

      {/* Node tooltip */}
      {tooltip.visible && tooltip.node && (
        <div
          style={{
            position: 'absolute',
            left: tooltip.x,
            top: tooltip.y,
            pointerEvents: 'none',
            background: 'var(--bg-raised)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)',
            padding: '8px 12px',
            fontSize: '13px',
            lineHeight: 1.5,
            color: 'var(--text-primary)',
            boxShadow: 'var(--shadow-card)',
            zIndex: 100,
            minWidth: '160px',
            whiteSpace: 'nowrap',
          }}
        >
          <div style={{ fontWeight: 600, fontFamily: 'var(--font-data)', marginBottom: '4px', color: 'var(--accent-primary)' }}>
            {tooltip.node.name}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: '8px', rowGap: '2px', color: 'var(--text-secondary)' }}>
            <span style={{ color: 'var(--text-muted)' }}>α</span>
            <span style={{ fontFamily: 'var(--font-data)' }}>{tooltip.node.alpha.toFixed(3)}</span>
            <span style={{ color: 'var(--text-muted)' }}>class</span>
            <span style={{ fontFamily: 'var(--font-data)' }}>{tooltip.node.class}</span>
            <span style={{ color: 'var(--text-muted)' }}>tier</span>
            <span style={{ fontFamily: 'var(--font-data)' }}>{tooltip.node.tier}</span>
          </div>
        </div>
      )}
    </div>
  );
}
