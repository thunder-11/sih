import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { ForensicGraph } from '../ForensicGraph';

// ── Data Transform: backend graph → ForensicGraph format ───────
function transformToForensicGraph(graphData, nodeStyle = 'cards') {
  if (!graphData?.nodes?.length) return { nodes: [], edges: [] };

  const nodes = graphData.nodes || [];
  const edges = graphData.edges || [];

  // Sort nodes by hop, then assign positions
  const hopGroups = {};
  nodes.forEach(n => {
    const hop = n.hop ?? 0;
    if (!hopGroups[hop]) hopGroups[hop] = [];
    hopGroups[hop].push(n);
  });

  const HORIZONTAL_SPACING = nodeStyle === 'circular' ? 260 : 310;
  const VERTICAL_SPACING   = nodeStyle === 'circular' ? 160 : 120;
  const CENTER_Y            = nodeStyle === 'circular' ? 260 : 200;

  // Compute node amount aggregation from transaction flows
  const fNodes = nodes.map(n => {
    const hop    = n.hop ?? 0;
    const group  = hopGroups[hop] || [n];
    const idx    = group.findIndex(g => g.id === n.id);
    const count  = group.length;
    const yOff   = (idx - (count - 1) / 2) * VERTICAL_SPACING;

    const isVasp   = n.node_type?.includes('VASP') || n.node_type?.includes('EXCHANGE');
    const isMixer  = n.node_type === 'MIXER' || n.node_type?.includes('HIGH_RISK');
    const isBridge = n.node_type === 'BRIDGE';
    const isOrigin = n.node_type === 'ORIGIN_VICTIM' || (n.hop ?? 0) === 0;

    const color = isOrigin ? '#06b6d4'
                : isMixer  ? '#f43f5e'
                : isBridge ? '#f59e0b'
                : isVasp   ? '#10b981'
                :             '#818cf8';

    const type  = isOrigin ? 'VICTIM'
                : isMixer  ? 'MIXER'
                : isBridge ? 'BRIDGE'
                : isVasp   ? 'VASP'
                :             'MULE';

    const label = n.vasp_name || n.label || n.id.substring(0, 10);
    const sub   = n.id.substring(0, 18) + '...';

    // Calculate actual real flow amount & token unit for this node
    let computedAmount = n.total_received || 0;
    const inTxs = edges.filter(e => e.target === n.id);
    const outTxs = edges.filter(e => e.source === n.id);
    if (!computedAmount) {
      if (isOrigin && outTxs.length > 0) {
        computedAmount = outTxs.reduce((sum, e) => sum + (Number(e.amount) || 0), 0);
      } else if (inTxs.length > 0) {
        computedAmount = inTxs.reduce((sum, e) => sum + (Number(e.amount) || 0), 0);
      } else if (outTxs.length > 0) {
        computedAmount = outTxs.reduce((sum, e) => sum + (Number(e.amount) || 0), 0);
      }
    }

    let nodeUnit = n.asset || n.unit || n.token_symbol || null;
    if (!nodeUnit) {
      if (outTxs.length > 0) nodeUnit = outTxs[0].asset || outTxs[0].token || outTxs[0].token_symbol;
      else if (inTxs.length > 0) nodeUnit = inTxs[0].asset || inTxs[0].token || inTxs[0].token_symbol;
      else nodeUnit = (n.chain === 'TRON' ? 'TRX' : 'ETH');
    }

    return {
      id:                 n.id,
      x:                  hop * HORIZONTAL_SPACING + 120,
      y:                  CENTER_Y + yOff,
      radius:             isOrigin ? 30 : isVasp ? 32 : 26,
      w:                  isVasp ? 190 : 175,
      h:                  isVasp ? 76  : 68,
      label,
      sub,
      type,
      amount:             computedAmount,
      unit:               nodeUnit,
      color,
      riskScore:          n.risk_score ?? 0,
      vasp_name:          n.vasp_name ?? null,
      node_type:          n.node_type,
      chain:              n.chain ?? 'TRON',
      activationProgress: 0,
    };
  });

  // Hop lookup map
  const nodeHopMap = new Map(nodes.map(n => [n.id, n.hop ?? 0]));
  const maxHop = Math.max(1, ...nodes.map(n => n.hop ?? 0));
  const stageDuration = 1.0 / maxHop;

  // Assign Flow-Wise Topological Timeline for each edge
  const fEdges = edges.map((e, i) => {
    const fromHop = nodeHopMap.get(e.source) ?? 0;
    const toHop   = nodeHopMap.get(e.target) ?? (fromHop + 1);

    let startP, endP;
    if (toHop > fromHop) {
      startP = fromHop * stageDuration;
      endP   = toHop * stageDuration;
    } else {
      startP = fromHop * stageDuration + stageDuration * 0.1;
      endP   = (fromHop + 1) * stageDuration;
    }

    startP = Math.max(0, Math.min(0.95, startP));
    endP   = Math.max(startP + 0.05, Math.min(1.0, endP));

    return {
      id:        e.id || `edge-${i}`,
      from:      e.source,
      to:        e.target,
      amount:    Number(e.amount) ?? 0,
      unit:      e.asset || e.token || e.token_symbol || (e.chain === 'TRON' ? 'TRX' : 'USDT'),
      curvature: e.is_peeling ? 0.22 : 0.0,
      startP,
      endP,
      is_peeling: !!e.is_peeling,
      is_bridge:  !!e.is_bridge_tx,
      txHash:     e.tx_hash,
    };
  });

  // Assign activationProgress to each node based on the arrival of incoming edges
  fNodes.forEach(fn => {
    const isOrigin = fn.type === 'VICTIM' || (nodeHopMap.get(fn.id) ?? 0) === 0;
    if (isOrigin) {
      fn.activationProgress = 0.0;
    } else {
      const inEdges = fEdges.filter(e => e.to === fn.id);
      if (inEdges.length > 0) {
        fn.activationProgress = Math.min(...inEdges.map(e => e.endP));
      } else {
        const outEdges = fEdges.filter(e => e.from === fn.id);
        fn.activationProgress = outEdges.length > 0 ? outEdges[0].startP : 0.0;
      }
    }
  });

  return { nodes: fNodes, edges: fEdges };
}

export default function MoneyTrailVisualizer({
  caseData,
  graphData,
  onRunTrace,
  tracing,
  currentHop,
  setCurrentHop,
  isPlaying,
  setIsPlaying,
  onSelectNode,
  selectedNodeId,
}) {
  const containerRef = useRef(null);
  const graphRef     = useRef(null);

  // Visualizer controls state
  const [nodeStyle, setNodeStyle]       = useState('cards'); // 'cards' | 'circular'
  const [showCurved, setShowCurved]     = useState(true);
  const [showBeams, setShowBeams]       = useState(true);
  const [isViewLocked, setIsViewLocked] = useState(false);
  const [speed, setSpeed]               = useState(1.0);
  const [progress, setProgress]         = useState(0);

  const totalHops = useMemo(() => {
    if (!graphData?.edges?.length) return 0;
    return graphData.edges.length;
  }, [graphData]);

  const maxHopDepth = useMemo(() => {
    if (!graphData?.nodes?.length) return 1;
    return Math.max(1, ...graphData.nodes.map(n => n.hop ?? 0));
  }, [graphData]);

  // Dataset transformed for ForensicGraph
  const forensicData = useMemo(() => {
    return transformToForensicGraph(graphData, nodeStyle);
  }, [graphData, nodeStyle]);

  // ── Mount ForensicGraph Engine ──────────────────────────────
  useEffect(() => {
    if (!containerRef.current || !forensicData.nodes.length) return;
    let fg = null;
    let rafId = null;

    rafId = requestAnimationFrame(() => {
      if (!containerRef.current) return;

      if (graphRef.current) {
        graphRef.current.destroy();
        graphRef.current = null;
      }

      fg = new ForensicGraph(containerRef.current, {
        nodeStyle,
        showCurved,
        showBeams,
        isViewLocked,
        playSpeed: speed,
        autoCamera: true,
        onProgressUpdate: (p) => {
          setProgress(p);
          // Sync with external hop state
          if (totalHops > 0) {
            const h = Math.min(totalHops - 1, Math.floor(p * totalHops));
            if (h !== currentHop && setCurrentHop) {
              setCurrentHop(h);
            }
          }
        },
        onNodeSelect: (node) => {
          if (onSelectNode) onSelectNode(node.id, node);
        },
      });

      graphRef.current = fg;
      fg.resize();
      fg.loadData(forensicData);

      // Set initial progress if hopping
      if (currentHop > 0 && maxHopDepth > 0) {
        fg.setProgress(currentHop / maxHopDepth);
      }
    });

    return () => {
      cancelAnimationFrame(rafId);
      if (graphRef.current) {
        graphRef.current.destroy();
        graphRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forensicData]);

  // ── Sync control options without remounting ─────────────────
  useEffect(() => {
    if (!graphRef.current) return;
    graphRef.current.setCurved(showCurved);
  }, [showCurved]);

  useEffect(() => {
    if (!graphRef.current) return;
    graphRef.current.setParticles(showBeams);
  }, [showBeams]);

  useEffect(() => {
    if (!graphRef.current) return;
    graphRef.current.setSpeed(speed);
  }, [speed]);

  useEffect(() => {
    if (!graphRef.current) return;
    graphRef.current.setViewLocked(isViewLocked);
  }, [isViewLocked]);

  // ── Sync external play state ────────────────────────────────
  useEffect(() => {
    if (!graphRef.current) return;
    if (isPlaying) {
      graphRef.current.play();
    } else {
      graphRef.current.pause();
    }
  }, [isPlaying]);

  // ── Sync external hop change (e.g. hop scrubber clicks) ─────
  useEffect(() => {
    if (!graphRef.current || isPlaying) return;
    if (maxHopDepth > 0) {
      const targetP = Math.min(1.0, currentHop / maxHopDepth);
      graphRef.current.setProgress(targetP);
      setProgress(targetP);
    }
  }, [currentHop, maxHopDepth, isPlaying]);

  // ── Control Actions ──────────────────────────────────────────
  const togglePlay = () => {
    if (!graphRef.current) return;
    const nowPlaying = graphRef.current.togglePlay();
    if (setIsPlaying) setIsPlaying(nowPlaying);
  };

  const handleRestart = () => {
    if (!graphRef.current) return;
    graphRef.current.setProgress(0);
    setProgress(0);
    if (setCurrentHop) setCurrentHop(0);
    graphRef.current.play();
    if (setIsPlaying) setIsPlaying(true);
  };

  const handleStepForward = () => {
    if (!graphRef.current) return;
    graphRef.current.pause();
    if (setIsPlaying) setIsPlaying(false);
    if (currentHop < totalHops - 1) {
      const nextHop = currentHop + 1;
      if (setCurrentHop) setCurrentHop(nextHop);
      const p = nextHop / maxHopDepth;
      graphRef.current.setProgress(p);
      setProgress(p);
    }
  };

  const handleStepBack = () => {
    if (!graphRef.current) return;
    graphRef.current.pause();
    if (setIsPlaying) setIsPlaying(false);
    if (currentHop > 0) {
      const prevHop = currentHop - 1;
      if (setCurrentHop) setCurrentHop(prevHop);
      const p = prevHop / maxHopDepth;
      graphRef.current.setProgress(p);
      setProgress(p);
    } else {
      graphRef.current.setProgress(0);
      setProgress(0);
      if (setCurrentHop) setCurrentHop(0);
    }
  };

  const handleRecenter = () => {
    if (!graphRef.current) return;
    graphRef.current.recenter();
  };

  const handleRearrange = () => {
    if (!graphRef.current) return;
    graphRef.current.rearrange();
  };

  // Empty state if no trace data yet
  if (!graphData?.edges?.length) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '56px 24px', background: 'var(--bg-card)', border: '1px solid var(--border-default)' }}>
        {tracing ? (
          <div>
            <div className="spinner" style={{ width: 44, height: 44, margin: '0 auto 16px', borderColor: 'rgba(200, 109, 59, 0.2)', borderTopColor: 'var(--accent-copper)' }}></div>
            <p style={{ fontSize: '1.2rem', fontWeight: 900, color: 'var(--text-primary)' }}>
               Value-Weighted BFS Forward Tracing Active
            </p>
            <p style={{ color: 'var(--accent-copper-light)', fontSize: '0.85rem', marginTop: 6, fontFamily: 'var(--font-mono)' }}>
              Traversing on-chain transactions across TRON, ETH & BSC nodes...
            </p>
          </div>
        ) : (
          <div>
            <div style={{ fontSize: '2.5rem', marginBottom: 12 }}></div>
            <p style={{ fontSize: '1.2rem', fontWeight: 900, color: 'var(--text-primary)' }}>
              No Active Money Trail Traced Yet
            </p>
            <p style={{ color: 'var(--text-secondary)', marginTop: 6, marginBottom: 24, maxWidth: 460, margin: '6px auto 24px' }}>
              Click "Execute Real-Time Trace" to begin automated forward hop traversal, peeling chain detection, and VASP deposit attribution.
            </p>
            <button className="btn btn-primary btn-lg" onClick={onRunTrace} style={{ padding: '12px 28px', fontSize: '0.95rem' }}>
               Execute Real-Time Trace
            </button>
          </div>
        )}
      </div>
    );
  }

  const isAtNode0 = currentHop === 0 && progress === 0;

  return (
    <div className="canvas-stage-wrapper">
      {/* Canvas Header Bar */}
      <div className="canvas-stage-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: '0.85rem', fontWeight: 900, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
             Forensic Money-Trail Stage
          </span>
          <span className={`badge ${isAtNode0 ? 'badge-primary' : 'badge-info'}`}>
            {isAtNode0 ? 'NODE 0: ORIGIN WALLET' : `HOP ${currentHop + 1} OF ${totalHops}`}
          </span>
          <span style={{ fontSize: '0.725rem', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
            {Math.round(progress * 100)}% TRACED
          </span>
        </div>

        {/* Toolbar Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {/* Rearrange Graph Action */}
          <button
            className="btn btn-primary"
            onClick={handleRearrange}
            style={{ padding: '4px 10px', fontSize: '0.725rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 4, background: 'linear-gradient(135deg, #0ea5e9, #0284c7)', border: 'none', boxShadow: '0 0 12px rgba(14, 165, 233, 0.4)' }}
            title="Automatically rearrange nodes into an optimal, clean, readable left-to-right flow"
          >
            🔀 Rearrange Graph
          </button>

          {/* Node Style Toggle */}
          <button
            className={`btn ${nodeStyle === 'cards' ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setNodeStyle('cards')}
            style={{ padding: '3px 8px', fontSize: '0.7rem' }}
          >
            ▬ Cards
          </button>
          <button
            className={`btn ${nodeStyle === 'circular' ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setNodeStyle('circular')}
            style={{ padding: '3px 8px', fontSize: '0.7rem' }}
          >
            ⬤ Circular
          </button>

          {/* Curved / Straight */}
          <button
            className={`btn ${showCurved ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setShowCurved(c => !c)}
            style={{ padding: '3px 8px', fontSize: '0.7rem' }}
            title="Toggle between smooth cubic Bezier curves and direct straight lines"
          >
            {showCurved ? '⌒ Curved' : '— Straight'}
          </button>

          {/* Lock / Free View */}
          <button
            className={`btn ${isViewLocked ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setIsViewLocked(l => !l)}
            style={{ padding: '3px 8px', fontSize: '0.7rem' }}
            title={isViewLocked ? 'View is locked. Click to enable free camera pan.' : 'View is free (drag background to pan). Click to lock view.'}
          >
            {isViewLocked ? '🔒 View Locked' : '🔓 Free View'}
          </button>

          {/* Particles */}
          <button
            className={`btn ${showBeams ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setShowBeams(b => !b)}
            style={{ padding: '3px 8px', fontSize: '0.7rem' }}
          >
            ✦ Particles
          </button>

          {/* Recenter */}
          <button
            className="btn btn-outline"
            onClick={handleRecenter}
            style={{ padding: '3px 8px', fontSize: '0.7rem' }}
          >
            ⊕ Recenter
          </button>
        </div>
      </div>

      {/* Forensic Canvas Stage Viewport (Native ForensicGraph canvas injected here) */}
      <div
        className="canvas-stage-viewport"
        ref={containerRef}
        style={{
          position: 'relative',
          width: '100%',
          height: 480,
          background: '#080c14',
          overflow: 'hidden',
        }}
      />

      {/* Scrubber & Controls Deck */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 18px', background: 'var(--bg-secondary)', borderTop: '1px solid var(--border-default)',
        flexWrap: 'wrap', gap: 10
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button className="btn btn-outline" onClick={handleStepBack} style={{ padding: '5px 10px', fontSize: '0.75rem' }} title="Step Back">
            ⏮ Step Back
          </button>

          <button className="btn btn-primary" onClick={togglePlay} style={{ minWidth: 110, justifyContent: 'center', padding: '5px 14px' }}>
            {isPlaying ? '⏸ Pause' : '▶ Play Trail'}
          </button>

          <button className="btn btn-outline" onClick={handleStepForward} style={{ padding: '5px 10px', fontSize: '0.75rem' }} title="Step Forward">
            Step Forward ⏭
          </button>

          <button className="btn btn-outline" onClick={handleRestart} style={{ padding: '5px 10px', fontSize: '0.75rem' }}>
            ↺ Replay
          </button>
        </div>

        {/* Live Scrubber Slider */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, maxWidth: 360, margin: '0 12px' }}>
          <span style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>0%</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={progress}
            onChange={(e) => {
              const p = parseFloat(e.target.value);
              setProgress(p);
              if (graphRef.current) graphRef.current.setProgress(p);
            }}
            style={{ flex: 1, accentColor: 'var(--accent-copper)', cursor: 'pointer' }}
          />
          <span style={{ fontSize: '0.7rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>100%</span>
        </div>

        {/* Speed Multipliers */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-muted)', marginRight: 4 }}>SPEED:</span>
          {[0.5, 1.0, 2.0, 4.0].map(s => (
            <button
              key={s}
              className={`btn ${speed === s ? 'btn-primary' : 'btn-outline'}`}
              onClick={() => setSpeed(s)}
              style={{ padding: '2px 7px', fontSize: '0.7rem', minWidth: 34, justifyContent: 'center' }}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
