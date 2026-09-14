import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useCase } from '../context/CaseContext';
import { ForensicGraph } from '../ForensicGraph';
import AnimatedNumber from '../components/AnimatedNumber';
import api from '../lib/api';

// ── Data Transform: backend graph → ForensicGraph format ───────
function transformToForensicGraph(graphData, nodeStyle = 'circular', entityFilter = 'ALL') {
  if (!graphData?.nodes?.length) return { nodes: [], edges: [] };

  const allNodes = graphData.nodes || [];
  const allEdges = graphData.edges || [];

  const typeOf = (n) => {
    const isVasp = n.node_type?.includes('VASP') || n.node_type?.includes('EXCHANGE');
    const isMixer = n.node_type === 'MIXER' || n.node_type?.includes('HIGH_RISK');
    const isBridge = n.node_type === 'BRIDGE';
    const isOrigin = n.node_type === 'ORIGIN_VICTIM' || (n.hop ?? 0) === 0;
    return isOrigin ? 'VICTIM' : isMixer ? 'MIXER' : isBridge ? 'BRIDGE' : isVasp ? 'VASP' : 'MULE';
  };

  const nodes = entityFilter === 'ALL' ? allNodes : allNodes.filter(n => typeOf(n) === entityFilter);
  const visibleIds = new Set(nodes.map(n => n.id));
  const edges = allEdges.filter(e => visibleIds.has(e.source) && visibleIds.has(e.target));

  // Sort nodes by hop, then assign positions
  const hopGroups = {};
  nodes.forEach(n => {
    const hop = n.hop ?? 0;
    if (!hopGroups[hop]) hopGroups[hop] = [];
    hopGroups[hop].push(n);
  });

  const HORIZONTAL_SPACING = nodeStyle === 'circular' ? 260 : 310;
  const VERTICAL_SPACING = nodeStyle === 'circular' ? 160 : 120;
  const CENTER_Y = nodeStyle === 'circular' ? 280 : 220;

  const fNodes = nodes.map(n => {
    const hop = n.hop ?? 0;
    const group = hopGroups[hop] || [n];
    const idx = group.findIndex(g => g.id === n.id);
    const count = group.length;
    const yOff = (idx - (count - 1) / 2) * VERTICAL_SPACING;

    const isVasp = n.node_type?.includes('VASP') || n.node_type?.includes('EXCHANGE');
    const isMixer = n.node_type === 'MIXER' || n.node_type?.includes('HIGH_RISK');
    const isBridge = n.node_type === 'BRIDGE';
    const isOrigin = n.node_type === 'ORIGIN_VICTIM' || (n.hop ?? 0) === 0;

    const color = isOrigin ? '#06b6d4' : isMixer ? '#f43f5e' : isBridge ? '#f59e0b' : isVasp ? '#10b981' : '#818cf8';
    const type = typeOf(n);
    const label = n.vasp_name || n.label || n.id.substring(0, 10);
    const sub = n.id.substring(0, 18) + '...';

    let computedAmount = n.total_received || 0;
    if (!computedAmount) {
      const inTxs = edges.filter(e => e.target === n.id);
      const outTxs = edges.filter(e => e.source === n.id);
      if (isOrigin && outTxs.length > 0) computedAmount = outTxs.reduce((sum, e) => sum + (Number(e.amount) || 0), 0);
      else if (inTxs.length > 0) computedAmount = inTxs.reduce((sum, e) => sum + (Number(e.amount) || 0), 0);
      else if (outTxs.length > 0) computedAmount = outTxs.reduce((sum, e) => sum + (Number(e.amount) || 0), 0);
    }

    let nodeUnit = n.asset || n.unit || n.token_symbol || null;
    if (!nodeUnit) {
      if (outTxs.length > 0) nodeUnit = outTxs[0].asset || outTxs[0].token || outTxs[0].token_symbol;
      else if (inTxs.length > 0) nodeUnit = inTxs[0].asset || inTxs[0].token || inTxs[0].token_symbol;
      else nodeUnit = (n.chain === 'TRON' ? 'TRX' : 'ETH');
    }

    return {
      id: n.id, x: hop * HORIZONTAL_SPACING + 120, y: CENTER_Y + yOff,
      radius: isOrigin ? 30 : isVasp ? 32 : 26, w: isVasp ? 190 : 175, h: isVasp ? 76 : 68,
      label, sub, type, amount: computedAmount, unit: nodeUnit, color,
      riskScore: n.risk_score ?? 0, vasp_name: n.vasp_name ?? null, node_type: n.node_type,
      chain: n.chain ?? 'TRON', activationProgress: 0,
    };
  });

  const nodeHopMap = new Map(nodes.map(n => [n.id, n.hop ?? 0]));
  const maxHop = Math.max(1, ...nodes.map(n => n.hop ?? 0));
  const stageDuration = 1.0 / maxHop;

  const fEdges = edges.map((e, i) => {
    const fromHop = nodeHopMap.get(e.source) ?? 0;
    const toHop = nodeHopMap.get(e.target) ?? (fromHop + 1);
    let startP, endP;
    if (toHop > fromHop) {
      startP = fromHop * stageDuration;
      endP = toHop * stageDuration;
    } else {
      startP = fromHop * stageDuration + stageDuration * 0.1;
      endP = (fromHop + 1) * stageDuration;
    }
    startP = Math.max(0, Math.min(0.95, startP));
    endP = Math.max(startP + 0.05, Math.min(1.0, endP));
    return {
      id: e.id || `edge-${i}`, from: e.source, to: e.target,
      amount: Number(e.amount) || 0, unit: e.asset || e.token || e.token_symbol || (e.chain === 'TRON' ? 'TRX' : 'USDT'),
      curvature: e.is_peeling ? 0.22 : 0.0, startP, endP,
      is_peeling: !!e.is_peeling, is_bridge: !!e.is_bridge_tx,
    };
  });

  fNodes.forEach(fn => {
    const isOrigin = fn.type === 'VICTIM' || (nodeHopMap.get(fn.id) ?? 0) === 0;
    if (isOrigin) {
      fn.activationProgress = 0.0;
    } else {
      const inEdges = fEdges.filter(e => e.to === fn.id);
      if (inEdges.length > 0) fn.activationProgress = Math.min(...inEdges.map(e => e.endP));
      else {
        const outEdges = fEdges.filter(e => e.from === fn.id);
        fn.activationProgress = outEdges.length > 0 ? outEdges[0].startP : 0.0;
      }
    }
  });

  return { nodes: fNodes, edges: fEdges };
}

const LEGEND = [
  { type: 'VICTIM', color: '#06b6d4', label: 'Origin / Victim' },
  { type: 'MULE', color: '#818cf8', label: 'Mule Layer' },
  { type: 'MIXER', color: '#f43f5e', label: 'Privacy Mixer' },
  { type: 'BRIDGE', color: '#f59e0b', label: 'Cross-Chain' },
  { type: 'VASP', color: '#10b981', label: 'VASP / Exchange' },
];

export default function TransactionGraphPage() {
  const [searchParams] = useSearchParams();
  const caseIdFromUrl = searchParams.get('case');
  const { activeCaseId, activeCase, activeGraph, casesList, selectCase, graphFilters, setGraphFilters, graphState, caseError, reloadActiveCase } = useCase();
  const navigate = useNavigate();

  const [nodeStyle, setNodeStyleState] = useState('circular');
  const [showCurved, setShowCurved] = useState(true);
  const [showBeams, setShowBeams] = useState(true);
  const [isViewLocked, setIsViewLocked] = useState(false);
  const [speed, setSpeed] = useState(1.0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [selectedNode, setSelectedNode] = useState(null);
  const [entityFilter, setEntityFilter] = useState('ALL');
  const [caseRiskData, setCaseRiskData] = useState(null);

  const containerRef = useRef(null);
  const graphRef = useRef(null);

  useEffect(() => {
    if (caseIdFromUrl && caseIdFromUrl !== activeCaseId) {
      selectCase(caseIdFromUrl);
    }
  }, [caseIdFromUrl, activeCaseId, selectCase]);

  // Fetch or ensure fresh risk assessment for the active case
  useEffect(() => {
    if (!activeCaseId) return;
    api.get(`/api/v1/cases/${activeCaseId}/risk`)
      .then(res => setCaseRiskData(res.data))
      .catch(() => setCaseRiskData(null));
  }, [activeCaseId, activeGraph]);

  const forensicData = useMemo(() => transformToForensicGraph(activeGraph, nodeStyle, entityFilter), [activeGraph, nodeStyle, entityFilter]);

  useEffect(() => {
    if (!containerRef.current) return;
    let rafId = null;
    rafId = requestAnimationFrame(() => {
      if (!containerRef.current) return;
      if (graphRef.current) { graphRef.current.destroy(); graphRef.current = null; }
      const fg = new ForensicGraph(containerRef.current, {
        nodeStyle, showCurved, showBeams, isViewLocked, playSpeed: speed, autoCamera: true,
        onProgressUpdate: (p) => setProgress(p),
        onNodeSelect: (node) => setSelectedNode(node),
      });
      graphRef.current = fg;
      fg.resize();
      if (forensicData.nodes.length > 0) {
        fg.loadData(forensicData);
        // Automatically start the dynamic stream visualization
        const playing = fg.togglePlay();
        setIsPlaying(playing);
      }
    });
    return () => {
      cancelAnimationFrame(rafId);
      if (graphRef.current) { graphRef.current.destroy(); graphRef.current = null; }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forensicData]);

  useEffect(() => { if (graphRef.current) graphRef.current.setCurved(showCurved); }, [showCurved]);
  useEffect(() => { if (graphRef.current) graphRef.current.setParticles(showBeams); }, [showBeams]);
  useEffect(() => { if (graphRef.current) graphRef.current.setSpeed(speed); }, [speed]);
  useEffect(() => { if (graphRef.current) graphRef.current.setViewLocked(isViewLocked); }, [isViewLocked]);

  const handlePlayPause = useCallback(() => {
    if (!graphRef.current) return;
    setIsPlaying(graphRef.current.togglePlay());
  }, []);
  const handleRewind = useCallback(() => {
    if (!graphRef.current) return;
    graphRef.current.setProgress(0); graphRef.current.pause();
    setIsPlaying(false); setProgress(0);
  }, []);
  const handleRecenter = useCallback(() => { graphRef.current?.recenter(); }, []);
  const handleScrub = useCallback((e) => {
    const p = parseFloat(e.target.value);
    setProgress(p);
    graphRef.current?.setProgress(p);
  }, []);

  const progressPct = Math.round(progress * 100);
  const displayRiskScore = caseRiskData?.score ?? activeCase?.risk_score ?? 0;
  const displayRiskTier = (caseRiskData?.tier || activeCase?.risk_tier || 'ASSESSED').toUpperCase();

  return (
    <motion.div
      style={{ display: 'flex', flexDirection: 'column', gap: 14 }}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <div className="page-header" style={{ margin: 0 }}>
        <div>
          <h1>🕸️ Forensic Transaction Graph</h1>
          <p className="subtitle">Canvas-native visualization · Progressive edge trails · Sonar ripple · Photon sync</p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          {activeCase && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px',
              background: 'var(--bg-card)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)'
            }}>
              <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)' }}>CASE RISK:</span>
              <span className={`badge ${
                displayRiskTier === 'CRITICAL' ? 'badge-critical' :
                displayRiskTier === 'HIGH' ? 'badge-high' :
                displayRiskTier === 'MEDIUM' ? 'badge-medium' : 'badge-info'
              }`} style={{ fontSize: '0.75rem', fontWeight: 900 }}>
                🛡️ <AnimatedNumber value={displayRiskScore} suffix=" / 100" /> ({displayRiskTier})
              </span>
            </div>
          )}
          <select className="form-select" value={activeCaseId || ''} onChange={e => selectCase(e.target.value)}
            style={{ fontSize: '0.8rem', padding: '5px 10px', minWidth: 220, fontWeight: 700 }}>
            {casesList.map(c => (
              <option key={c.id} value={c.id}>{c.external_complaint_id} — {c.reported_loss_amount?.toLocaleString()} {c.loss_currency} {c.risk_score != null ? `(Risk: ${c.risk_score})` : ''}</option>
            ))}
          </select>
          <button className="btn btn-outline" onClick={() => navigate('/money-trail')}>💸 Money Trail View</button>
        </div>
      </div>

      {(caseError || ['partial', 'unavailable', 'not_traced'].includes(graphState)) && (
        <div className="card" style={{ padding: 12, color: 'var(--accent-amber)' }}>
          {caseError || `Evidence coverage is ${graphState.replace('_', ' ')}.`}
        </div>
      )}

      <div className="card" style={{ padding: '10px 16px', display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button className="btn btn-outline" onClick={handleRewind} style={{ padding: '4px 8px', fontSize: '0.75rem' }} title="Rewind">⏮</button>
          <button className={`btn ${isPlaying ? 'btn-danger' : 'btn-primary'}`} onClick={handlePlayPause} style={{ padding: '4px 14px', fontSize: '0.8rem', minWidth: 80 }}>
            {isPlaying ? '⏸ Pause' : '▶ Play'}
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 180 }}>
          <span style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>PROGRESS</span>
          <input type="range" min={0} max={1} step={0.005} value={progress} onChange={handleScrub} style={{ flex: 1, accentColor: 'var(--accent-copper)' }} />
          <span style={{ fontSize: '0.8rem', fontWeight: 900, color: 'var(--accent-copper-light)', fontFamily: 'var(--font-mono)', minWidth: 34 }}>{progressPct}%</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-muted)' }}>SPEED</span>
          {[0.5, 1.0, 2.0].map(s => (
            <button key={s} onClick={() => setSpeed(s)} className={`btn ${speed === s ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}>{s}×</button>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-muted)' }}>STYLE</span>
          <button onClick={() => setNodeStyleState('circular')} className={`btn ${nodeStyle === 'circular' ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}>⬤ Circular</button>
          <button onClick={() => setNodeStyleState('cards')} className={`btn ${nodeStyle === 'cards' ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}>▬ Cards</button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button onClick={() => setShowCurved(v => !v)} className={`btn ${showCurved ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}
            title="Toggle between smooth cubic Bezier curves and direct straight lines">
            {showCurved ? '⌒ Curved' : '— Straight'}
          </button>
          <button onClick={() => setShowBeams(v => !v)} className={`btn ${showBeams ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}>✦ Particles</button>
          <button onClick={() => setIsViewLocked(v => !v)} className={`btn ${isViewLocked ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}
            title={isViewLocked ? 'View is locked to center. Click to enable free panning.' : 'View is free (drag background to pan). Click to lock.'}>
            {isViewLocked ? '🔒 View Locked' : '🔓 Free View'}
          </button>
          <button onClick={() => { if (graphRef.current) graphRef.current.rearrange(); }} className="btn btn-primary" style={{ padding: '4px 10px', fontSize: '0.725rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 4, background: 'linear-gradient(135deg, #0ea5e9, #0284c7)', border: 'none' }} title="Automatically rearrange nodes into an optimal readable layout">
            🔀 Rearrange Graph
          </button>
          <button onClick={handleRecenter} className="btn btn-outline" style={{ padding: '3px 8px', fontSize: '0.7rem' }}>⊕ Recenter</button>
        </div>

        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginLeft: 'auto' }}>
          <strong><AnimatedNumber value={forensicData.nodes.length} /></strong> Nodes ·{' '}
          <strong><AnimatedNumber value={forensicData.edges.length} /></strong> Edges
        </div>
      </div>

      <div className="card" style={{ padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-muted)' }}>TEMPORAL:</span>
        <select className="form-select" value={graphFilters.temporal_view}
          onChange={e => setGraphFilters(current => ({ ...current, temporal_view: e.target.value }))} style={{ fontSize: '0.75rem', padding: '4px 8px' }}>
          <option value="post_report">Post-report</option>
          <option value="pre_report">Pre-report</option>
          <option value="all">All evidence</option>
        </select>
        <select className="form-select" value={graphFilters.boundary}
          onChange={e => setGraphFilters(current => ({ ...current, boundary: e.target.value }))} style={{ fontSize: '0.75rem', padding: '4px 8px' }}>
          <option value="exclusive">After T0</option>
          <option value="inclusive">At/after T0</option>
        </select>
        <label style={{ fontSize: '0.75rem' }}>
          <input type="checkbox" checked={graphFilters.include_context}
            onChange={e => setGraphFilters(current => ({ ...current, include_context: e.target.checked }))} /> Context
        </label>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: selectedNode ? '1fr 320px' : '1fr', gap: 14 }}>
        <div className="panel" style={{ margin: 0, padding: 0, position: 'relative', height: 580, overflow: 'hidden' }}>
          <div style={{
            position: 'absolute', top: 14, left: 14, zIndex: 10, display: 'flex', flexDirection: 'column', gap: 6,
            background: 'rgba(8,12,20,0.82)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)',
            padding: '10px 14px', pointerEvents: 'none',
          }}>
            {LEGEND.map(l => (
              <div key={l.type} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: '0.68rem', fontWeight: 700 }}>
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: l.color, display: 'inline-block', flexShrink: 0 }} />
                <span style={{ color: l.color }}>{l.type}</span>
                <span style={{ color: 'var(--text-muted)' }}>{l.label}</span>
              </div>
            ))}
          </div>

          <div style={{
            position: 'absolute', top: 14, right: 14, zIndex: 10, background: 'rgba(8,12,20,0.82)',
            borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)', padding: '8px 14px',
            display: 'flex', alignItems: 'center', gap: 8, pointerEvents: 'none',
          }}>
            <span className={`status-dot ${isPlaying ? 'pulse' : ''}`} style={{ background: isPlaying ? 'var(--accent-copper)' : progressPct === 100 ? 'var(--accent-gold)' : 'var(--text-muted)' }} />
            <span style={{ fontSize: '0.7rem', fontWeight: 900, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
              {progressPct === 100 ? 'TRACE COMPLETE' : isPlaying ? 'TRACING...' : `${progressPct}% TRACED`}
            </span>
          </div>

          {forensicData.nodes.length === 0 && (
            <div className="loading-overlay" style={{ height: '100%', position: 'absolute', inset: 0 }}>
              <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>No graph nodes match the active filters — run a trace first, or widen the filter criteria.</p>
              <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => navigate('/money-trail')}>💸 Go to Money Trail →</button>
            </div>
          )}

          <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
        </div>

        <AnimatePresence>
          {selectedNode && (
            <motion.div
              key="inspector"
              initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 30 }}
              transition={{ duration: 0.3 }} className="intel-panel" style={{ height: 'fit-content', alignSelf: 'start' }}
            >
              <div className="intel-panel-header">
                <h4>🔎 Entity Inspector</h4>
                <button className="btn btn-outline" onClick={() => setSelectedNode(null)} style={{ padding: '2px 6px', fontSize: '0.65rem' }}>✕ Close</button>
              </div>
              <div className="intel-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: selectedNode.color, flexShrink: 0 }} />
                  <span className="badge badge-info" style={{ fontSize: '0.65rem' }}>{selectedNode.type}</span>
                  <span className="badge badge-info" style={{ fontSize: '0.65rem' }}>{selectedNode.chain}</span>
                </div>

                <div>
                  <div className="dossier-label">WALLET / CONTRACT ADDRESS</div>
                  <div className="mono" style={{ fontSize: '0.72rem', color: 'var(--accent-copper-light)', wordBreak: 'break-all', marginTop: 2 }}>{selectedNode.id}</div>
                </div>

                <div className="dossier-grid">
                  <div className="dossier-card">
                    <div className="dossier-label">RECEIVED</div>
                    <div className="dossier-val" style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-copper-light)' }}>
                      <AnimatedNumber value={selectedNode.amount || 0} toLocaleString={true} />
                    </div>
                  </div>
                  {selectedNode.riskScore > 0 && (
                    <div className="dossier-card">
                      <div className="dossier-label">RISK SCORE</div>
                      <div className="dossier-val" style={{ fontFamily: 'var(--font-mono)', color: selectedNode.riskScore > 75 ? '#E57373' : selectedNode.riskScore > 30 ? '#F0A742' : '#7BC497' }}>
                        <AnimatedNumber value={selectedNode.riskScore} suffix=" / 100" />
                      </div>
                    </div>
                  )}
                </div>

                {selectedNode.vasp_name && (
                  <div style={{ background: 'rgba(212,163,89,0.10)', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-gold)' }}>
                    <div className="dossier-label" style={{ color: 'var(--accent-gold)' }}>ATTRIBUTED VASP</div>
                    <div style={{ fontSize: '1rem', fontWeight: 900, color: 'var(--text-gold)', marginTop: 2 }}>{selectedNode.vasp_name}</div>
                    <div style={{ fontSize: '0.7rem', color: '#7BC497', marginTop: 4 }}>✓ FIU-IND Compliance Registered</div>
                  </div>
                )}

                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                  <div className="dossier-label" style={{ marginBottom: 4 }}>LABEL</div>
                  <div style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{selectedNode.label}</div>
                  <div className="mono" style={{ marginTop: 2, fontSize: '0.68rem' }}>{selectedNode.sub}</div>
                </div>

                <button className="btn btn-primary" onClick={() => navigate(`/wallets?address=${selectedNode.id}&chain=${selectedNode.chain || 'TRON'}`)} style={{ width: '100%', justifyContent: 'center', marginTop: 4 }}>
                  🔎 Deep-Dive Wallet Intelligence →
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="card" style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-muted)' }}>ENTITY FILTER:</span>
        {['ALL', 'VICTIM', 'MULE', 'MIXER', 'BRIDGE', 'VASP'].map(f => (
          <button key={f} onClick={() => setEntityFilter(f)} className={`btn ${entityFilter === f ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 9px', fontSize: '0.7rem' }}>{f}</button>
        ))}
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>Drag to pan · Scroll to zoom · Click node to inspect</span>
      </div>
    </motion.div>
  );
}
