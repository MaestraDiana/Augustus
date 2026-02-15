import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { ZoomIn } from 'lucide-react';
import ForceGraph, { GraphNode, GraphEdge } from '../components/charts/ForceGraph';
import EmptyState from '../components/ui/EmptyState';
import Checkbox from '../components/ui/Checkbox';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { CoActivationEntry } from '../types';

interface CoActivationResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
  coActivationData: CoActivationEntry[];
  totalSessions: number;
}

async function buildNodesFromAgent(agentId: string, extraNames: Set<string>): Promise<GraphNode[]> {
  try {
    const agentData = await api.agents.get(agentId);
    const builtNodes: GraphNode[] = agentData.basins.map((b: any) => ({
      id: b.name,
      name: b.name,
      alpha: b.alpha || 0.5,
      class: (b.class || b.basin_class || 'peripheral') as 'core' | 'peripheral',
      tier: b.tier || 3,
    }));
    extraNames.forEach((name) => {
      if (!builtNodes.find((n) => n.id === name)) {
        builtNodes.push({ id: name, name, alpha: 0.5, class: 'peripheral', tier: 3 });
      }
    });
    return builtNodes;
  } catch {
    return Array.from(extraNames).map((name) => ({
      id: name, name, alpha: 0.5, class: 'peripheral' as const, tier: 3,
    }));
  }
}

async function fetchCoActivation(agentId: string): Promise<CoActivationResult> {
  let resultNodes: GraphNode[] = [];
  let resultEdges: GraphEdge[] = [];
  let resultCoActivation: CoActivationEntry[] = [];
  let resultTotalSessions = 0;

  try {
    const data = await api.coactivation.get(agentId);

    if (data.nodes && data.edges) {
      const nodeNames: string[] = data.nodes;
      resultNodes = await buildNodesFromAgent(agentId, new Set(nodeNames));
      resultEdges = data.edges;
    } else if ((data as any).co_activation_entries || (data as any).entries) {
      const entries: CoActivationEntry[] = (data as any).co_activation_entries || (data as any).entries || [];
      resultCoActivation = entries;

      const nodeSet = new Set<string>();
      entries.forEach((entry: CoActivationEntry) => {
        nodeSet.add(entry.pair[0]);
        nodeSet.add(entry.pair[1]);
        resultEdges.push({
          source: entry.pair[0],
          target: entry.pair[1],
          count: entry.count,
          character: (entry.character || 'uncharacterized') as GraphEdge['character'],
        });
      });

      resultNodes = await buildNodesFromAgent(agentId, nodeSet);
    } else {
      resultNodes = await buildNodesFromAgent(agentId, new Set());
    }

    try {
      const sessionsData = await api.sessions.list(agentId, 1, 0);
      resultTotalSessions = sessionsData.total || 0;
    } catch {
      resultTotalSessions = 0;
    }
  } catch {
    resultNodes = await buildNodesFromAgent(agentId, new Set());
  }

  return {
    nodes: resultNodes,
    edges: resultEdges,
    coActivationData: resultCoActivation,
    totalSessions: resultTotalSessions,
  };
}

export default function CoActivationNetwork() {
  const { agentId } = useParams<{ agentId: string }>();
  const [sessionRange, setSessionRange] = useState<number>(25);
  const [colorMode, setColorMode] = useState<'class' | 'tier'>('class');
  const [minCount, setMinCount] = useState<number>(1);
  const [showLabels, setShowLabels] = useState<boolean>(true);
  const [showUncharacterized, setShowUncharacterized] = useState<boolean>(true);
  const [scale, setScale] = useState<number>(50);
  const [detailPanelOpen, setDetailPanelOpen] = useState<boolean>(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [coActivationData, setCoActivationData] = useState<CoActivationEntry[]>([]);
  const [totalSessions, setTotalSessions] = useState(0);

  const { data: fetchedData, loading } = useApi<CoActivationResult>(
    () => fetchCoActivation(agentId!),
    [agentId],
  );

  // Sync fetched data into local state
  useEffect(() => {
    if (fetchedData) {
      setNodes(fetchedData.nodes);
      setEdges(fetchedData.edges);
      setCoActivationData(fetchedData.coActivationData);
      setTotalSessions(fetchedData.totalSessions);
    }
  }, [fetchedData]);

  const handleNodeClick = (node: GraphNode) => {
    setSelectedNode(node);
    setSelectedEdge(null);
    setDetailPanelOpen(true);
  };

  const handleEdgeClick = (edge: GraphEdge) => {
    setSelectedEdge(edge);
    setSelectedNode(null);
    setDetailPanelOpen(true);
  };

  const closeDetailPanel = () => {
    setDetailPanelOpen(false);
    setSelectedNode(null);
    setSelectedEdge(null);
  };

  const getEdgeData = (edge: GraphEdge) => {
    return coActivationData.find(
      (ca) =>
        (ca.pair[0] === edge.source && ca.pair[1] === edge.target) ||
        (ca.pair[1] === edge.source && ca.pair[0] === edge.target)
    );
  };

  const getNodePartners = (nodeId: string) => {
    return coActivationData
      .filter((ca) => ca.pair[0] === nodeId || ca.pair[1] === nodeId)
      .map((ca) => ({
        partner: ca.pair[0] === nodeId ? ca.pair[1] : ca.pair[0],
        count: ca.count,
        character: ca.character,
      }));
  };

  const getCharacterBadgeClass = (character: string | null) => {
    if (!character) return 'character-badge uncharacterized';
    return `character-badge ${character}`;
  };

  const sessionPresets = [10, 25, totalSessions > 0 ? totalSessions : 0].filter((v) => v > 0);

  if (loading) {
    return (
      <div style={{ padding: 'var(--space-6)', color: 'var(--text-secondary)' }}>
        Loading co-activation network...
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden', height: '100%' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', height: '100%' }}>
        {/* Controls */}
        <div style={{
          display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-4)',
          padding: 'var(--space-4) var(--space-5)', borderBottom: '1px solid var(--border-color)',
          background: 'var(--bg-surface)', flexShrink: 0,
        }}>
          {sessionPresets.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
              <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Sessions</span>
              <div style={{ display: 'flex', gap: 'var(--space-1)' }}>
                {sessionPresets.map((val) => (
                  <button key={val} onClick={() => setSessionRange(val)} style={{
                    padding: 'var(--space-1) var(--space-3)', borderRadius: 'var(--radius-sm)',
                    background: sessionRange === val ? 'var(--accent-primary-dim)' : 'var(--bg-raised)',
                    border: `1px solid ${sessionRange === val ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                    color: sessionRange === val ? 'var(--accent-primary)' : 'var(--text-secondary)',
                    fontFamily: 'var(--font-data)', fontSize: '13px', cursor: 'pointer',
                    transition: 'all var(--transition-color)',
                  }}>
                    {val === totalSessions ? 'All' : `Last ${val}`}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Color by</span>
            <select value={colorMode} onChange={(e) => setColorMode(e.target.value as 'class' | 'tier')} style={{
              padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-md)',
              background: 'var(--bg-input)', border: '1px solid var(--border-color)',
              color: 'var(--text-primary)', fontFamily: 'var(--font-body)', fontSize: '14px',
              cursor: 'pointer', minWidth: '140px',
            }}>
              <option value="class">Basin Class</option>
              <option value="tier">Tier</option>
            </select>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Min Count</span>
            <input type="range" min="1" max="15" value={minCount} onChange={(e) => setMinCount(Number(e.target.value))} style={{ width: '80px', height: '4px', cursor: 'pointer' }} />
            <span style={{ fontFamily: 'var(--font-data)', fontSize: '13px', color: 'var(--text-secondary)', minWidth: '24px', textAlign: 'right' }}>{minCount}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Scale</span>
            <input type="range" min="1" max="100" value={scale} onChange={(e) => setScale(Number(e.target.value))} style={{ width: '100px', height: '4px', cursor: 'pointer' }} />
            <span style={{ fontFamily: 'var(--font-data)', fontSize: '13px', color: 'var(--text-secondary)', minWidth: '36px', textAlign: 'right' }}>{scale}%</span>
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
            <Checkbox checked={showLabels} onChange={setShowLabels} label="Labels" />
            <Checkbox checked={showUncharacterized} onChange={setShowUncharacterized} label="Uncharacterized" />
          </div>
        </div>

        {/* Graph Canvas — targets ~75% of viewport height */}
        <div style={{ flex: 1, position: 'relative', background: 'var(--bg-base)', overflow: 'hidden', minHeight: 'calc(75vh - 160px)' }}>
          {nodes.length === 0 ? (
            <EmptyState
              icon={<ZoomIn size={56} />}
              title="No Co-Activation Data"
              message="Co-activation data will appear here after sessions with evaluator output."
            />
          ) : (
            <ForceGraph
              nodes={nodes}
              edges={edges}
              colorMode={colorMode}
              showLabels={showLabels}
              minCount={minCount}
              showUncharacterized={showUncharacterized}
              scale={scale}
              onNodeClick={handleNodeClick}
              onEdgeClick={handleEdgeClick}
            />
          )}
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-4)', padding: 'var(--space-3) var(--space-5)', borderTop: '1px solid var(--border-color)', background: 'var(--bg-surface)', fontSize: '13px', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>Edges:</span>
            <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text-secondary)' }}>
                <div style={{ width: '20px', height: '3px', borderRadius: '2px', background: 'var(--accent-success)' }}></div>Reinforcing
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text-secondary)' }}>
                <div style={{ width: '20px', height: '2px', background: 'repeating-linear-gradient(90deg, var(--accent-alert) 0, var(--accent-alert) 4px, transparent 4px, transparent 8px)' }}></div>Tensional
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text-secondary)' }}>
                <div style={{ width: '20px', height: '3px', borderRadius: '2px', background: '#2E7D9B' }}></div>Serving →
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text-secondary)' }}>
                <div style={{ width: '20px', height: '2px', background: 'repeating-linear-gradient(90deg, var(--accent-attention) 0, var(--accent-attention) 4px, transparent 4px, transparent 8px)' }}></div>Competing
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text-secondary)' }}>
                <div style={{ width: '20px', height: '2px', background: 'repeating-linear-gradient(90deg, var(--text-muted) 0, var(--text-muted) 2px, transparent 2px, transparent 5px)' }}></div>Uncharacterized
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>Nodes:</span>
            <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text-secondary)' }}>
                <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: 'var(--accent-primary)' }}></div>Core
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--text-secondary)' }}>
                <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: 'var(--accent-attention)' }}></div>Peripheral
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Detail Panel */}
      {detailPanelOpen && (
        <div style={{ width: '340px', borderLeft: '1px solid var(--border-color)', background: 'var(--bg-surface)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 'var(--space-4) var(--space-5)', borderBottom: '1px solid var(--border-color)' }}>
            <span style={{ fontFamily: 'var(--font-voice)', fontWeight: 600, fontSize: '16px' }}>
              {selectedNode ? 'Basin Detail' : 'Edge Detail'}
            </span>
            <button onClick={closeDetailPanel} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px', display: 'flex', alignItems: 'center' }}>
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ width: '18px', height: '18px' }}>
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 'var(--space-5)' }}>
            {selectedNode && (
              <>
                <div style={{ marginBottom: 'var(--space-5)' }}>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 'var(--space-3)' }}>Basin Info</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-3)' }}>
                    <div style={{ background: 'var(--bg-raised)', padding: 'var(--space-3)', borderRadius: 'var(--radius-md)' }}>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>Alpha</div>
                      <div style={{ fontFamily: 'var(--font-data)', fontSize: '16px', fontWeight: 500 }}>{selectedNode.alpha.toFixed(2)}</div>
                    </div>
                    <div style={{ background: 'var(--bg-raised)', padding: 'var(--space-3)', borderRadius: 'var(--radius-md)' }}>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>Class</div>
                      <div style={{ fontFamily: 'var(--font-data)', fontSize: '16px', fontWeight: 500 }}>{selectedNode.class}</div>
                    </div>
                    <div style={{ background: 'var(--bg-raised)', padding: 'var(--space-3)', borderRadius: 'var(--radius-md)' }}>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>Tier</div>
                      <div style={{ fontFamily: 'var(--font-data)', fontSize: '16px', fontWeight: 500 }}>{selectedNode.tier}</div>
                    </div>
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 'var(--space-3)' }}>Co-Activation Partners</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                    {getNodePartners(selectedNode.id).length === 0 ? (
                      <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>No co-activation partners recorded.</div>
                    ) : (
                      getNodePartners(selectedNode.id).map((p, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 'var(--space-2) var(--space-3)', background: 'var(--bg-raised)', borderRadius: 'var(--radius-sm)', fontSize: '14px' }}>
                          <span style={{ fontFamily: 'var(--font-data)', color: 'var(--text-primary)' }}>{p.partner}</span>
                          <span style={{ fontFamily: 'var(--font-data)', color: 'var(--text-muted)' }}>{p.count}×</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </>
            )}
            {selectedEdge && (() => {
              const edgeData = getEdgeData(selectedEdge);
              return (
                <>
                  <div style={{ marginBottom: 'var(--space-5)' }}>
                    <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 'var(--space-3)' }}>Pair</div>
                    <div style={{ fontFamily: 'var(--font-data)', fontSize: '14px', marginBottom: 'var(--space-3)' }}>{selectedEdge.source} ↔ {selectedEdge.target}</div>
                    <div style={{ marginBottom: 'var(--space-3)' }}>
                      <span className={getCharacterBadgeClass(selectedEdge.character)} style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)', padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-md)', fontSize: '14px', fontWeight: 500 }}>
                        {selectedEdge.character || 'uncharacterized'}
                      </span>
                    </div>
                  </div>
                  <div style={{ marginBottom: 'var(--space-5)' }}>
                    <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 'var(--space-3)' }}>Count</div>
                    <div style={{ fontFamily: 'var(--font-data)', fontSize: '18px', fontWeight: 500 }}>{selectedEdge.count} co-activations</div>
                  </div>
                  {edgeData && edgeData.sessions.length > 0 && (
                    <div>
                      <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 'var(--space-3)' }}>Recent Sessions</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', maxHeight: '200px', overflowY: 'auto' }}>
                        {edgeData.sessions.slice(0, 5).map((sid, i) => (
                          <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 'var(--space-2) var(--space-3)', background: 'var(--bg-raised)', borderRadius: 'var(--radius-sm)', fontSize: '13px', cursor: 'pointer', transition: 'background var(--transition-color)' }}>
                            <span style={{ fontFamily: 'var(--font-data)', color: 'var(--accent-primary)' }}>{sid}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}
