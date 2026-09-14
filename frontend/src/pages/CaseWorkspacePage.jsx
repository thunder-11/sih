import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate, useParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useCase } from '../context/CaseContext';
import { useAuth } from '../context/AuthContext';
import MoneyTrailVisualizer from '../components/MoneyTrailVisualizer';
import AnimatedNumber from '../components/AnimatedNumber';
import api from '../lib/api';
import { errorMessage, items, downloadBase64Pdf } from '../lib/contracts';

// ── Temp Case Management (localStorage) ──────────────────────────────────
const TEMP_CASES_KEY = 'argus_temp_case_ids';
function getTempCaseIds() {
  try { return new Set(JSON.parse(localStorage.getItem(TEMP_CASES_KEY) || '[]')); }
  catch { return new Set(); }
}
function addTempCaseId(id) {
  const s = getTempCaseIds(); s.add(id);
  localStorage.setItem(TEMP_CASES_KEY, JSON.stringify([...s]));
}
function removeTempCaseId(id) {
  const s = getTempCaseIds(); s.delete(id);
  localStorage.setItem(TEMP_CASES_KEY, JSON.stringify([...s]));
}

// ── Risk helpers ──────────────────────────────────────────────────────────
function estimateNodeRisk(node) {
  if (!node) return 0;
  if (node.risk_score && node.risk_score > 0) return Math.round(node.risk_score);
  const t = node.node_type || '';
  if (t === 'MIXER' || t.includes('HIGH_RISK')) return 85;
  if (t === 'BRIDGE') return 45;
  if (t.includes('VASP') || t.includes('EXCHANGE')) return 35;
  if (t === 'MULE' || t === 'WALLET') return 30;
  return 15;
}
function riskColor(score) {
  if (score >= 75) return '#E57373';
  if (score >= 40) return '#F0A742';
  return '#7BC497';
}
function riskLabel(score) {
  if (score >= 75) return 'CRITICAL';
  if (score >= 40) return 'HIGH';
  if (score >= 20) return 'MEDIUM';
  return 'LOW';
}

const TYPOLOGY_LABELS = {
  TASK_BASED_SCAM: '📱 Task-Based Scam',
  INVESTMENT_PONZI_SCAM: '📈 Investment Ponzi',
  DIGITAL_ARREST_EXTORTION: '🚔 Digital Arrest',
  SEXTORTION_BLACKMAIL: '📸 Sextortion',
  RANSOMWARE_PAYMENT: '🔒 Ransomware',
  PHISHING_DRAINER: '🎣 Phishing Drainer',
  DARKNET_FINANCIAL_CRIME: '🕸️ Darknet Crime',
};

const TAB_LIST = [
  ['dossier', '🔍 Dossier'],
  ['risk', '🛡️ Risk'],
  ['notes', '📝 Notes'],
  ['history', '🧾 History'],
  ['related', '🔗 Related'],
  ['clusters', '🧬 Clusters'],
];

export default function CaseWorkspacePage() {
  const [searchParams] = useSearchParams();
  const { caseId: caseIdFromPath } = useParams();
  const caseIdFromUrl = caseIdFromPath || searchParams.get('case');
  const { activeCaseId, selectCase, activeCase, activeGraph, casesList, reloadActiveCase, reloadCasesList, caseError, graphState } = useCase();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [currentHop, setCurrentHop] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [traceStatus, setTraceStatus] = useState('idle');
  const [traceError, setTraceError] = useState(null);
  const [generating, setGenerating] = useState('');
  const [copiedText, setCopiedText] = useState('');
  const [noticeId, setNoticeId] = useState(null);
  const [dispatching, setDispatching] = useState(false);
  const [notes, setNotes] = useState([]);
  const [newNote, setNewNote] = useState('');
  const [savingNote, setSavingNote] = useState(false);
  const [relatedCases, setRelatedCases] = useState([]);
  const [attributions, setAttributions] = useState([]);
  const [risk, setRisk] = useState(null);
  const [clusters, setClusters] = useState(null);
  const [history, setHistory] = useState([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [sidebarTab, setSidebarTab] = useState('dossier');
  const [walletInput, setWalletInput] = useState('');
  const [walletChain, setWalletChain] = useState('');
  const [walletSubmitting, setWalletSubmitting] = useState(false);
  const [walletError, setWalletError] = useState('');
  const [isTempInvestigation, setIsTempInvestigation] = useState(false);
  const [savedCaseLabel, setSavedCaseLabel] = useState('');
  const [savingCase, setSavingCase] = useState(false);
  const [trailRiskScore, setTrailRiskScore] = useState(0);

  // ── Real Investigation Progress Overlay State ──
  const [overlayActive, setOverlayActive] = useState(false);
  const [overlayProgress, setOverlayProgress] = useState(0);
  const [overlayMessage, setOverlayMessage] = useState('');
  const [overlayTargetWallet, setOverlayTargetWallet] = useState('');
  const [overlayTargetChain, setOverlayTargetChain] = useState('');

  const pollingRef = useRef(null);

  // Sync temp flag when active case changes
  useEffect(() => {
    setIsTempInvestigation(activeCaseId ? getTempCaseIds().has(activeCaseId) : false);
  }, [activeCaseId]);

  useEffect(() => {
    if (caseIdFromUrl && caseIdFromUrl !== activeCaseId) selectCase(caseIdFromUrl);
  }, [caseIdFromUrl, activeCaseId, selectCase]);

  const targetCaseId = activeCaseId;

  const structuredHops = useMemo(() => {
    if (!activeGraph?.edges?.length) return [];
    const nodesMap = new Map((activeGraph.nodes || []).map(n => [n.id, n]));
    const sortedEdges = [...activeGraph.edges].sort((a, b) => (nodesMap.get(a.source)?.hop ?? 0) - (nodesMap.get(b.source)?.hop ?? 0));
    return sortedEdges.map((edge, idx) => {
      const sourceNode = nodesMap.get(edge.source) || {};
      const targetNode = nodesMap.get(edge.target) || {};
      const isTerminal = targetNode.node_type?.includes('VASP');
      const isMixer = targetNode.node_type === 'MIXER';
      const isBridge = targetNode.node_type === 'BRIDGE' || edge.is_bridge_tx;
      const isPeeling = edge.is_peeling;
      const evidence = [`Verified transfer ${edge.tx_hash}`];
      if (edge.temporal_partition) evidence.push(`Temporal partition: ${edge.temporal_partition}`);
      if (isPeeling) evidence.push('Deterministic peeling finding attached to this transfer');
      if (isMixer) evidence.push('Reviewed privacy-protocol label attached to destination');
      if (isBridge) evidence.push('Supported bridge evidence attached to this transfer');
      if (isTerminal) evidence.push(`Reviewed ${targetNode.vasp_name || 'VASP'} attribution attached to destination`);
      const nodeRisk = estimateNodeRisk(targetNode);
      return {
        index: idx, id: edge.id,
        from: edge.source_address || edge.source,
        to: edge.target_address || edge.target,
        amount: edge.amount || 0,
        token: edge.asset || edge.token || edge.token_symbol || (edge.chain === 'TRON' ? 'TRX' : 'USDT'),
        chain: sourceNode.chain || targetNode.chain || edge.chain || 'TRON',
        targetChain: targetNode.chain || sourceNode.chain || edge.chain || 'TRON',
        txHash: edge.tx_hash,
        timestamp: (edge.event_time || edge.timestamp)
          ? (edge.event_time || edge.timestamp).substring(0, 19).replace('T', ' ')
          : 'Unknown',
        fromNode: sourceNode, toNode: targetNode, isPeeling, isBridge,
        confidence: targetNode.attribution_score ?? null,
        riskScore: nodeRisk, evidence,
      };
    });
  }, [activeGraph]);

  const totalHops = structuredHops.length;

  const originNode = useMemo(() => {
    if (!structuredHops.length) return null;
    const firstHop = structuredHops[0];
    const originRaw = (activeGraph?.nodes || []).find(n => n.id === firstHop.from);
    return { id: firstHop.from, address: firstHop.from, chain: firstHop.chain, token: firstHop.token, amount: firstHop.amount, rawNode: firstHop.fromNode, riskScore: estimateNodeRisk(originRaw) };
  }, [structuredHops, activeGraph]);

  // Live trail risk: max risk seen across hops traversed so far
  useEffect(() => {
    if (!structuredHops.length) { setTrailRiskScore(0); return; }
    const traversed = structuredHops.slice(0, Math.max(1, currentHop + 1));
    setTrailRiskScore(traversed.reduce((max, h) => Math.max(max, h.riskScore || 0), 0));
  }, [currentHop, structuredHops]);

  const isOriginSelected = selectedNodeId === originNode?.id || (selectedNodeId === null && currentHop === 0 && !isPlaying);
  const currentHopData = structuredHops[currentHop] || structuredHops[0] || null;
  const vaspNode = activeGraph?.nodes?.find(n => n.node_type?.includes('VASP'));
  const hasAttribution = !!vaspNode;

  const pollTrace = useCallback((traceId, specificCaseId) => {
    const cid = specificCaseId || targetCaseId;
    if (pollingRef.current) clearInterval(pollingRef.current);
    let pollCount = 0;
    const MAX_POLLS = 120; // 120 × 600ms ≈ 72 seconds max
    pollingRef.current = setInterval(async () => {
      pollCount++;
      if (pollCount > MAX_POLLS) {
        clearInterval(pollingRef.current); pollingRef.current = null;
        setTraceStatus('error');
        setOverlayActive(false);
        setTraceError('Trace timed out. The provider may be unavailable — please try again.');
        return;
      }
      try {
        const res = await api.get(`/api/v1/traces/${traceId}`);
        const state = (res.data?.state || res.data?.status || '').toLowerCase();

        if (res.data?.message) {
          setOverlayMessage(res.data.message);
        }
        if (res.data?.progress_percent != null && res.data.progress_percent > 0) {
          const mapped = Math.min(88, 25 + Math.round(res.data.progress_percent * 0.63));
          setOverlayProgress(prev => Math.max(prev, mapped));
        } else {
          setOverlayProgress(prev => Math.min(85, prev + 2));
        }

        if (['complete', 'completed', 'done', 'succeeded', 'partial'].includes(state)) {
          clearInterval(pollingRef.current); pollingRef.current = null;
          setOverlayProgress(92);
          setOverlayMessage('Trace completed on-chain. Constructing forensic money-trail network…');
          await reloadActiveCase(cid);
          await loadRiskAndAttributions(cid);
          // Don't call reloadCasesList for temp cases — keeps them hidden
          if (!getTempCaseIds().has(cid)) await reloadCasesList();
          setOverlayProgress(100);
          setOverlayMessage('Forensic money-trail graph ready.');
          setTraceStatus('complete'); setCurrentHop(0); setIsPlaying(true);
        } else if (['failed', 'error'].includes(state)) {
          clearInterval(pollingRef.current); pollingRef.current = null;
          setTraceStatus('error');
          setOverlayActive(false);
          setTraceError(res.data?.error_message || res.data?.error || 'Trace failed on the backend.');
        }
        // 'retrying', 'running', 'queued' → keep polling
      } catch { /* keep polling */ }
    }, 600);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetCaseId, reloadActiveCase, reloadCasesList]);


  useEffect(() => () => { if (pollingRef.current) clearInterval(pollingRef.current); }, []);

  const handleRunTrace = async () => {
    if (!targetCaseId) return;
    setTraceStatus('starting'); setTraceError(null);
    if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }

    const targetAddr = activeCase?.wallets?.[0]?.wallet_address || activeCase?.external_complaint_id || targetCaseId;
    const targetNet = activeCase?.wallets?.[0]?.chain || 'TRON';
    setOverlayTargetWallet(targetAddr);
    setOverlayTargetChain(targetNet);
    setOverlayActive(true);
    setOverlayProgress(12);
    setOverlayMessage('Initializing multi-hop BFS forward trace across blockchain nodes…');

    try {
      setTraceStatus('loading');
      setOverlayProgress(25);
      setOverlayMessage('Submitting forensic trace job to queue worker…');
      const res = await api.post(`/api/v1/cases/${targetCaseId}/trace`, {}, { headers: { 'Idempotency-Key': crypto.randomUUID() } });
      const traceId = res.data?.trace_id;
      setTraceStatus('polling');
      setOverlayProgress(35);
      setOverlayMessage('Traversing transaction hops & exchange deposit records…');
      if (traceId) pollTrace(traceId);
      else {
        setOverlayProgress(92);
        setOverlayMessage('Constructing money-trail graph…');
        await reloadActiveCase();
        await loadRiskAndAttributions();
        setOverlayProgress(100);
        setOverlayMessage('Forensic money-trail graph ready.');
        setTraceStatus('complete'); setCurrentHop(0); setIsPlaying(true);
      }
    } catch (err) {
      setTraceStatus('error');
      setOverlayActive(false);
      setTraceError(errorMessage(err, 'Trace failed due to a provider or wallet error'));
    }
  };

  const handleRunAnalytics = async () => {
    if (!targetCaseId) return;
    setAnalyzing(true);
    try {
      await api.post(`/api/v1/cases/${targetCaseId}/analytics`, {});
      await loadRiskAndAttributions();
    } catch (err) {
      alert(errorMessage(err, 'Analytics run failed.'));
    } finally {
      setAnalyzing(false);
    }
  };

  const handleGenerateNotice = async () => {
    setGenerating('notice');
    try {
      const res = await api.post(`/api/v1/cases/${targetCaseId}/generate-freeze-notice`, {
        vasp_id: vaspNode?.vasp_id,
        police_station: user?.police_station,
        officer_name: user?.full_name,
        fir_cr_number: activeCase?.external_complaint_id,
        designation: user?.role,
      });
      if (res.data?.notice_id) setNoticeId(res.data.notice_id);
      downloadBase64Pdf(res.data, `Sec94_BNSS_Freeze_Notice_${activeCase?.external_complaint_id || targetCaseId}.pdf`);
    } catch (err) {
      alert('Failed to generate freeze notice: ' + errorMessage(err));
    } finally {
      setGenerating('');
    }
  };

  const handleDispatchNotice = async () => {
    if (!noticeId) return;
    setDispatching(true);
    try {
      await api.post(`/api/v1/notices/${noticeId}/dispatch`, { channel: 'email', simulate: true, reason: 'Investigator-triggered dispatch' });
      alert('Notice dispatched to VASP compliance nodal officer.');
    } catch (err) {
      alert('Dispatch failed (live dispatch is disabled outside fixture/simulate mode): ' + errorMessage(err));
    } finally {
      setDispatching(false);
    }
  };

  const handleGenerateReport = async () => {
    setGenerating('report');
    try {
      const res = await api.post(`/api/v1/cases/${targetCaseId}/generate-court-report`, {});
      downloadBase64Pdf(res.data, `Sec63_BSA_Forensic_Report_${activeCase?.external_complaint_id || targetCaseId}.pdf`);
    } catch (err) {
      alert('Failed to generate forensic court report: ' + errorMessage(err));
    } finally {
      setGenerating('');
    }
  };

  const copyToClipboard = (text, label) => {
    navigator.clipboard.writeText(text);
    setCopiedText(label);
    setTimeout(() => setCopiedText(''), 2000);
  };

  const summaryMetrics = useMemo(() => {
    const totalFunds = activeGraph?.summary?.selected_amount ?? null;
    const chainsSet = new Set(structuredHops.map(h => h.chain));
    const entitiesCount = (activeGraph.nodes || []).length;
    
    const vaspNode = (activeGraph.nodes || []).find(n => n.node_type === 'VASP_DEPOSIT' || n.vasp_name || n.attribution_score > 0);
    const topAttribution = attributions && attributions.length > 0 ? attributions[0] : null;

    let confidence = null;
    let attributionLabel = 'Unattributed (Private Wallet)';

    if (vaspNode) {
      confidence = vaspNode.attribution_score || 95;
      attributionLabel = `${vaspNode.vasp_name || 'VASP'} (${confidence}%)`;
    } else if (topAttribution && (topAttribution.score || topAttribution.confidence)) {
      confidence = topAttribution.score || topAttribution.confidence;
      attributionLabel = `${topAttribution.vasp_name || topAttribution.entity_name || 'Entity'} (${confidence}%)`;
    } else if (entitiesCount > 0) {
      attributionLabel = 'Unattributed (Private Wallet)';
    } else {
      attributionLabel = 'Pending Trace';
    }

    const tokenSymbol = structuredHops[0]?.token || activeCase?.loss_currency || (activeCase?.wallets?.[0]?.chain === 'TRON' ? 'TRX' : 'USDT');
    return { totalFunds, hopsCount: structuredHops.length, chainsCount: Math.max(chainsSet.size, 1), entitiesCount, confidence, attributionLabel, token: tokenSymbol };
  }, [structuredHops, activeGraph, attributions, activeCase]);

  useEffect(() => {
    if (!targetCaseId || !activeCase) return;
    api.get(`/api/v1/cases/${targetCaseId}/notes`).then(res => setNotes(items(res.data, 'notes'))).catch(() => setNotes([]));
  }, [targetCaseId, activeCase]);

  useEffect(() => {
    if (!targetCaseId || !activeCase) return;
    api.get(`/api/v1/cases/${targetCaseId}/history`).then(res => setHistory(items(res.data, 'history'))).catch(() => setHistory([]));
  }, [targetCaseId, activeCase]);

  const loadRiskAndAttributions = useCallback(async (specificCaseId) => {
    const cid = specificCaseId || (activeCase ? targetCaseId : null);
    if (!cid) return;
    api.get(`/api/v1/cases/${cid}/attributions`).then(res => setAttributions(items(res.data, 'attributions'))).catch(() => setAttributions([]));
    api.get(`/api/v1/cases/${cid}/risk`).then(res => {
      setRisk(res.data);
      if (res.data?.assessment_state === 'not_assessed' && res.data?.trace_id) {
        api.post(`/api/v1/cases/${cid}/analytics`, {})
          .then(() => api.get(`/api/v1/cases/${cid}/risk`).then(r => setRisk(r.data)).catch(() => {}))
          .catch(() => {});
      }
    }).catch(() => setRisk(null));
    api.get(`/api/v1/cases/${cid}/clusters`).then(res => setClusters(res.data)).catch(() => setClusters(null));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetCaseId, activeCase]);
  useEffect(() => { if (activeCase) loadRiskAndAttributions(); }, [activeCase, loadRiskAndAttributions]);

  useEffect(() => {
    if (!targetCaseId || !activeCase) return;
    api.get(`/api/v1/cases/${targetCaseId}/related`).then(res => setRelatedCases(items(res.data, 'related_cases'))).catch(() => setRelatedCases([]));
  }, [targetCaseId, activeCase]);

  const handleAddNote = async () => {
    if (!newNote.trim() || !targetCaseId) return;
    setSavingNote(true);
    try {
      const res = await api.post(`/api/v1/cases/${targetCaseId}/notes`, { content: newNote });
      setNotes(prev => [...prev, res.data]);
      setNewNote('');
    } catch (err) {
      alert(errorMessage(err, 'Failed to save note.'));
    } finally {
      setSavingNote(false);
    }
  };

  const autoDetectChain = (addr) => {
    if (/^T[a-zA-Z0-9]{33}$/.test(addr)) return 'TRON';
    if (/^0x[a-fA-F0-9]{40}$/.test(addr)) return 'ETH';
    if (/^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}$/.test(addr)) return 'BTC';
    return '';
  };

  const handleWalletInputChange = (val) => {
    setWalletInput(val);
    const detected = autoDetectChain(val.trim());
    if (detected) setWalletChain(detected);
  };

  const handleTraceNewWallet = async () => {
    const address = walletInput.trim();
    if (!address) { setWalletError('Enter a wallet address to trace.'); return; }
    const detectedChain = walletChain || autoDetectChain(address) || 'TRON';
    setWalletError(''); setWalletSubmitting(true);
    setTraceStatus('starting');

    setOverlayTargetWallet(address);
    setOverlayTargetChain(detectedChain);
    setOverlayActive(true);
    setOverlayProgress(10);
    setOverlayMessage(`Validating target wallet address on-chain (${detectedChain})...`);

    try {
      await api.post('/api/v1/wallets/validate', { address, chain: walletChain || null });
      setTraceStatus('loading');
      setOverlayProgress(25);
      setOverlayMessage('Address validated. Dispatching automated multi-hop forensic trace...');
      // Use a TEMP- prefix so we can identify and hide these from the cases list
      const tempId = `TEMP-${address.substring(0, 8)}-${Date.now()}`;
      const res = await api.post('/api/v1/complaints', {
        complaint_source: 'manual_fir',
        external_complaint_id: tempId,
        fraud_typology: 'TASK_BASED_SCAM',
        reported_loss_amount: 0,
        suspect_wallets: [{ address, chain: walletChain || null }],
        auto_start: true,
      }, { headers: { 'Idempotency-Key': crypto.randomUUID() } });
      const newCaseId = res.data.case_id;
      const traceId = res.data.trace_id;
      // Mark as temp — NOT added to visible cases list
      addTempCaseId(newCaseId);
      setIsTempInvestigation(true);
      setSavedCaseLabel(address);
      selectCase(newCaseId);  // load case data without reloading case list
      setWalletInput(''); setWalletChain('');
      setTraceStatus('polling');
      setOverlayProgress(35);
      setOverlayMessage('Tracing forward transaction hops & exchange deposit records...');
      if (traceId) {
        pollTrace(traceId, newCaseId);
      } else {
        setOverlayProgress(92);
        setOverlayMessage('Constructing money-trail graph…');
        await reloadActiveCase(newCaseId);
        await loadRiskAndAttributions(newCaseId);
        setOverlayProgress(100);
        setOverlayMessage('Forensic money-trail graph ready.');
        setTraceStatus('complete'); setCurrentHop(0); setIsPlaying(true);
      }
      navigate(`/money-trail?case=${newCaseId}`);
    } catch (err) {
      setWalletError(errorMessage(err, 'Wallet trace failed to start.'));
      setTraceStatus('idle');
      setOverlayActive(false);
    } finally {
      setWalletSubmitting(false);
    }
  };

  // Explicitly save temp investigation as a permanent Case
  const handleSaveAsCase = async () => {
    if (!targetCaseId || !isTempInvestigation) return;
    setSavingCase(true);
    try {
      removeTempCaseId(targetCaseId);
      setIsTempInvestigation(false);
      await reloadCasesList();
    } catch (err) {
      alert(errorMessage(err, 'Failed to save investigation as case.'));
    } finally { setSavingCase(false); }
  };

  // Cases list filtered to exclude temp cases
  const visibleCasesList = useMemo(() => {
    const tempIds = getTempCaseIds();
    return casesList.filter(c => !tempIds.has(c.id));
  }, [casesList]);

  const getTraceButtonLabel = () => {
    switch (traceStatus) {
      case 'starting': return '⚡ INITIALIZING TRACE...';
      case 'loading': return '📡 SUBMITTING TRACE JOB...';
      case 'polling': return '🔄 POLLING TRACE STATUS...';
      case 'complete': return '✓ TRACE COMPLETE — Re-run';
      case 'error': return '⚠️ RETRY TRACE';
      default: return '🚀 EXECUTE REAL-TIME TRACE';
    }
  };

  return (
    <motion.div className="workstation-container" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
      {/* ── Command Bar ──────────────────────────────────────────────── */}
      <div className="workstation-command-bar">
        <div className="command-bar-left">
          {isTempInvestigation ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--accent-amber)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                🔍 TEMPORARY INVESTIGATION
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-secondary)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {savedCaseLabel || activeCase?.external_complaint_id}
              </span>
              <button
                className="btn btn-primary"
                onClick={handleSaveAsCase}
                disabled={savingCase}
                style={{ padding: '5px 14px', fontSize: '0.8rem', fontWeight: 800, background: 'linear-gradient(135deg, #10b981, #059669)', border: 'none', whiteSpace: 'nowrap' }}
              >
                {savingCase ? '⏳ Saving...' : '💾 Add to Cases'}
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)' }}>CASE:</span>
              <select className="form-select" value={targetCaseId || ''}
                onChange={e => {
                  const val = e.target.value;
                  selectCase(val);
                  setIsTempInvestigation(val ? getTempCaseIds().has(val) : false);
                  setTraceStatus('idle'); setTraceError(null); setCurrentHop(0); setSelectedNodeId(null);
                  if (val) {
                    navigate(`/money-trail?case=${val}`);
                  } else {
                    navigate('/money-trail');
                  }
                }}
                style={{ padding: '5px 10px', fontSize: '0.8rem', minWidth: 240, fontWeight: 700 }}>
                <option value="">-- Select an Investigation Case --</option>
                {visibleCasesList.map(c => (
                  <option key={c.id} value={c.id}>{c.external_complaint_id} — {TYPOLOGY_LABELS[c.fraud_typology] || c.fraud_typology} ({c.reported_loss_amount?.toLocaleString()})</option>
                ))}
              </select>
            </div>
          )}
          <span className={`status-beacon ${hasAttribution ? 'attributed' : traceStatus === 'polling' || traceStatus === 'loading' ? 'active' : 'idle'}`}>
            <span className={`status-dot ${traceStatus === 'polling' ? 'pulse' : ''}`} style={{ background: hasAttribution ? 'var(--accent-gold)' : traceStatus === 'polling' ? 'var(--accent-copper)' : 'var(--text-muted)' }}></span>
            {hasAttribution ? 'ATTRIBUTION CONFIRMED' : traceStatus === 'polling' ? 'TRACING HOPS...' : isTempInvestigation ? 'TEMP INVESTIGATION' : targetCaseId ? 'READY FOR TRACE' : 'NO CASE SELECTED'}
          </span>
        </div>
        <div className="command-bar-actions">
          <button className="btn btn-outline" onClick={handleRunAnalytics} disabled={analyzing || !targetCaseId}>
            {analyzing ? '⏳ Analyzing...' : '🧮 Run Deterministic Analytics'}
          </button>
          <button className="btn btn-outline" onClick={() => navigate(targetCaseId ? `/graph?case=${targetCaseId}` : '/graph')}>🕸️ Switch to Graph View</button>
          <button className={`btn ${traceStatus === 'error' ? 'btn-danger' : 'btn-primary'}`} onClick={handleRunTrace}
            disabled={traceStatus === 'starting' || traceStatus === 'loading' || traceStatus === 'polling' || !targetCaseId}>
            {getTraceButtonLabel()}
          </button>
        </div>
      </div>

      {/* ── Wallet Search Bar ─────────────────────────────────────────── */}
      <div className="card" style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>🔎 INVESTIGATE WALLET:</span>
        <input
          className="form-input mono"
          value={walletInput}
          onChange={e => handleWalletInputChange(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleTraceNewWallet(); }}
          placeholder="Paste a wallet address — T..., 0x..., bc1..., 1..., 3..."
          style={{ flex: '1 1 260px', minWidth: 220, padding: '7px 12px', fontSize: '0.82rem' }}
        />
        <select className="form-select" value={walletChain} onChange={e => setWalletChain(e.target.value)} style={{ width: 140, padding: '7px 8px', fontSize: '0.8rem' }}>
          <option value="">Auto-detect</option>
          <option value="TRON">TRON</option>
          <option value="ETH">Ethereum</option>
          <option value="BSC">BSC</option>
          <option value="BTC">Bitcoin</option>
          <option value="POLYGON">Polygon</option>
        </select>
        <button className="btn btn-primary" onClick={handleTraceNewWallet} disabled={walletSubmitting || !walletInput.trim()} style={{ whiteSpace: 'nowrap' }}>
          {walletSubmitting ? '⏳ Starting…' : '🚀 Investigate'}
        </button>
        {isTempInvestigation && (
          <div style={{ fontSize: '0.72rem', color: 'var(--accent-amber)', display: 'flex', alignItems: 'center', gap: 5, padding: '4px 10px', background: 'rgba(240,167,66,0.08)', borderRadius: 6, border: '1px solid rgba(240,167,66,0.25)' }}>
            ⚠️ Temporary — click <strong style={{ margin: '0 3px' }}>💾 Add to Cases</strong> to save permanently.
          </div>
        )}
      </div>
      {walletError && <div className="card" style={{ padding: 10, color: 'var(--accent-crimson)', fontSize: '0.82rem' }}>⚠️ {walletError}</div>}

      {(traceError || caseError) && (
        <div style={{ padding: '12px 16px', background: 'rgba(189, 74, 74, 0.15)', border: '1px solid var(--border-crimson)', borderRadius: 'var(--radius-sm)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: '1.2rem' }}>⚠️</span>
            <div>
              <div style={{ fontSize: '0.85rem', fontWeight: 800, color: '#E57373' }}>Trace Error Encountered</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{traceError || caseError}</div>
            </div>
          </div>
          <button className="btn btn-danger" onClick={handleRunTrace} style={{ padding: '4px 10px', fontSize: '0.75rem' }}>Retry Trace</button>
        </div>
      )}

      {['partial', 'unavailable', 'not_traced'].includes(graphState) && (
        <div className="card" style={{ padding: 12, color: 'var(--accent-amber)' }}>
          Evidence coverage is {graphState.replace('_', ' ')}. Displayed totals include only backend-validated transfers.
        </div>
      )}

      {!targetCaseId && (
        <div className="card" style={{ padding: '48px 24px', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}>
          <div style={{ fontSize: '3rem' }}>📁</div>
          <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '1.2rem' }}>No Investigation Case Selected</h3>
          <p style={{ color: 'var(--text-secondary)', maxWidth: 480, margin: 0, fontSize: '0.88rem', lineHeight: 1.5 }}>
            Select an existing case from the <strong>CASE</strong> dropdown above to inspect its forensic money trail, or paste any wallet address into the investigation bar above to start tracing funds.
          </p>
          <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
            <button className="btn btn-primary" onClick={() => navigate('/cases')}>📋 View Case Registry</button>
            <button className="btn btn-outline" onClick={() => navigate('/new-case')}>➕ Create New Case</button>
          </div>
        </div>
      )}

      {targetCaseId && (
        <div className="workstation-grid">
          {/* minWidth: 0 overrides the flex/grid default of not shrinking below content size —
              without it, a case with hundreds of hop-pills below forces this whole column (and
              the canvas riding at width:100% of it) to grow to an unusable, unrenderable width. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
            <MoneyTrailVisualizer
              caseData={activeCase} graphData={activeGraph} onRunTrace={handleRunTrace}
              tracing={traceStatus === 'starting' || traceStatus === 'loading' || traceStatus === 'polling' || walletSubmitting}
              currentHop={currentHop} setCurrentHop={setCurrentHop}
              isPlaying={isPlaying} setIsPlaying={setIsPlaying}
              onSelectNode={(id) => setSelectedNodeId(id)} selectedNodeId={selectedNodeId}
              loadingActive={overlayActive}
              loadingProgress={overlayProgress}
              loadingMessage={overlayMessage}
              targetWallet={overlayTargetWallet}
              targetChain={overlayTargetChain}
              isError={!!traceError || !!walletError}
              onLoadingComplete={() => {
                setOverlayActive(false);
              }}
            />

            {structuredHops.length > 0 && (
              <div className="panel" style={{ margin: 0, padding: 14 }}>
                <div style={{ fontSize: '0.7rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--text-muted)', marginBottom: 8 }}>
                  📍 Interactive Hop Timeline
                </div>
                <div className="timeline-scrubber-bar" style={{ padding: 0, border: 'none', background: 'transparent' }}>
                  {originNode && (
                    <div onClick={() => { setIsPlaying(false); setCurrentHop(0); setSelectedNodeId(originNode.id); }}
                      className={`hop-pill ${currentHop === 0 && (selectedNodeId === originNode.id || !isPlaying) ? 'active' : 'settled'}`}
                      style={{ borderLeft: '3px solid var(--text-primary)' }}>
                      <span>🔵</span><span>STARTING POINT</span>
                      <span style={{ fontSize: '0.675rem', fontFamily: 'var(--font-mono)', opacity: 0.8 }}>{originNode.amount?.toLocaleString()}</span>
                      {originNode.riskScore > 0 && (
                        <span style={{ marginLeft: 'auto', fontSize: '0.6rem', fontWeight: 800, color: riskColor(originNode.riskScore), background: 'rgba(0,0,0,0.25)', padding: '1px 5px', borderRadius: 4 }}>{originNode.riskScore}</span>
                      )}
                    </div>
                  )}
                  {structuredHops.map((hop, idx) => {
                    const isActive = idx === currentHop && selectedNodeId !== originNode?.id;
                    const isSettled = idx < currentHop;
                    const isTerminal = hop.toNode?.node_type?.includes('VASP');
                    return (
                      <div key={hop.id} onClick={() => { setIsPlaying(false); setCurrentHop(idx); setSelectedNodeId(hop.to); }}
                        className={`hop-pill ${isActive ? 'active' : isSettled ? 'settled' : ''} ${isTerminal ? 'vasp' : ''}`}>
                        <span>{isTerminal ? '🎯' : isSettled ? '✓' : `Hop ${idx + 1}`}</span>
                        <span>{hop.toNode?.vasp_name || hop.toNode?.label || hop.to.substring(0, 8)}</span>
                        <span style={{ fontSize: '0.675rem', fontFamily: 'var(--font-mono)', opacity: 0.8 }}>{hop.amount?.toLocaleString()}</span>
                        {hop.riskScore > 0 && (
                          <span style={{ marginLeft: 'auto', fontSize: '0.6rem', fontWeight: 800, color: riskColor(hop.riskScore), background: 'rgba(0,0,0,0.25)', padding: '1px 5px', borderRadius: 4 }}>{hop.riskScore}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {activeGraph?.edges?.length > 0 && (
              <div className="panel" style={{ margin: 0 }}>
                <div className="panel-header"><h3>📋 Forensic Transaction Trail ({activeGraph.edges.length} Hops)</h3></div>
                <div style={{ overflowX: 'auto' }}>
                  <table className="data-table">
                    <thead><tr><th>#</th><th>Sender</th><th>Recipient</th><th>Amount</th><th>Token</th><th>Risk</th><th>Tx Hash</th><th>Timestamp</th></tr></thead>
                    <tbody>
                      {activeGraph.edges.map((e, i) => {
                        const toNode = (activeGraph.nodes || []).find(n => n.id === e.target);
                        const nodeRisk = estimateNodeRisk(toNode);
                        return (
                        <motion.tr key={e.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.3, delay: Math.min(i, 20) * 0.04 }}
                          style={{ background: i === currentHop ? 'rgba(200, 109, 59, 0.08)' : 'transparent' }}>
                          <td>{i + 1}</td>
                          <td className="mono">{e.source?.substring(0, 14)}...</td>
                          <td className="mono">{e.target?.substring(0, 14)}...</td>
                          <td style={{ fontWeight: 800, color: 'var(--accent-copper-light)', fontFamily: 'var(--font-mono)' }}>
                            <AnimatedNumber value={Number(e.amount) || 0} toLocaleString={true} />
                          </td>
                          <td><span className="badge badge-info">{e.token}</span></td>
                          <td><span style={{ fontSize: '0.7rem', fontWeight: 800, color: riskColor(nodeRisk), fontFamily: 'var(--font-mono)' }}>{nodeRisk}</span></td>
                          <td className="mono">{e.tx_hash?.substring(0, 16)}...</td>
                          <td style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{e.timestamp?.substring(0, 19)}</td>
                        </motion.tr>
                      )})}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          <div className="intel-sidebar">
            <div style={{ display: 'flex', gap: 4, marginBottom: 4, flexWrap: 'wrap' }}>
              {TAB_LIST.map(([k, lbl]) => (
                <button key={k} onClick={() => setSidebarTab(k)} className={`btn ${sidebarTab === k ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 7px', fontSize: '0.65rem', flex: '1 1 30%' }}>{lbl}</button>
              ))}
            </div>

            {/* ── Live Trail Risk Banner ─────────────────────────── */}
            {structuredHops.length > 0 && (
              <AnimatePresence>
                <motion.div key={trailRiskScore} initial={{ opacity: 0.7, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.3 }}
                  style={{ padding: '10px 14px', borderRadius: 'var(--radius-sm)', marginBottom: 8,
                    background: `linear-gradient(135deg, ${riskColor(trailRiskScore)}15, rgba(8,12,20,0.95))`,
                    border: `1px solid ${riskColor(trailRiskScore)}50` }}>
                  <div style={{ fontSize: '0.62rem', fontWeight: 800, color: 'var(--text-muted)', letterSpacing: '0.6px', marginBottom: 4 }}>
                    LIVE TRAIL RISK — HOP {Math.min(currentHop + 1, totalHops)}/{totalHops}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{ fontSize: '1.75rem', fontWeight: 900, color: riskColor(trailRiskScore), fontFamily: 'var(--font-mono)', lineHeight: 1 }}>
                      <AnimatedNumber value={trailRiskScore} />
                    </div>
                    <div>
                      <div style={{ fontSize: '0.65rem', fontWeight: 800, color: riskColor(trailRiskScore) }}>{riskLabel(trailRiskScore)} RISK</div>
                      <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)', marginTop: 2 }}>{currentHopData?.toNode?.node_type || 'WALLET'}</div>
                    </div>
                    <div style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                      <motion.div animate={{ width: `${trailRiskScore}%` }} transition={{ duration: 0.5 }}
                        style={{ height: '100%', background: riskColor(trailRiskScore), borderRadius: 3 }} />
                    </div>
                  </div>
                </motion.div>
              </AnimatePresence>
            )}

            <div className="intel-panel">
              <div className="intel-panel-header"><h4>⚡ Statutory LEA Actions</h4></div>
              <div className="intel-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <button className="btn btn-danger" onClick={handleGenerateNotice} disabled={generating === 'notice'} style={{ width: '100%', justifyContent: 'center' }}>
                  {generating === 'notice' ? '⏳ Generating...' : '📄 Sec 94 BNSS Freeze Notice (PDF)'}
                </button>
                {noticeId && (
                  <button className="btn btn-outline" onClick={handleDispatchNotice} disabled={dispatching} style={{ width: '100%', justifyContent: 'center', fontSize: '0.8rem' }}>
                    {dispatching ? '📨 Dispatching...' : '📨 Dispatch Notice to VASP'}
                  </button>
                )}
                <button className="btn btn-primary" onClick={handleGenerateReport} disabled={generating === 'report'} style={{ width: '100%', justifyContent: 'center' }}>
                  {generating === 'report' ? '⏳ Generating...' : '📑 Sec 63 BSA Court Report (PDF)'}
                </button>
              </div>
            </div>

            {sidebarTab === 'dossier' && (
              <>
                {isOriginSelected && originNode ? (
                  <div className="intel-panel" style={{ borderColor: 'var(--text-muted)' }}>
                    <div className="intel-panel-header"><h4>🔵 Starting Point Dossier (Node 0)</h4><span className="badge badge-primary">ORIGIN WALLET</span></div>
                    <div className="intel-panel-body">
                      <div className="dossier-grid">
                        <div className="dossier-card"><div className="dossier-label">REPORTED THEFT LOSS</div><div className="dossier-val" style={{ color: 'var(--accent-copper-light)', fontFamily: 'var(--font-mono)' }}>{originNode.amount ?? 'Unknown'} {originNode.token || ''}</div></div>
                        <div className="dossier-card"><div className="dossier-label">ORIGIN RISK</div><div className="dossier-val" style={{ color: riskColor(originNode.riskScore), fontFamily: 'var(--font-mono)' }}><AnimatedNumber value={originNode.riskScore} suffix=" / 100" /></div></div>
                      </div>
                      <div style={{ background: 'var(--bg-secondary)', padding: '10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)', marginBottom: 12 }}>
                        <div className="dossier-label">REPORTED VICTIM WALLET ADDRESS</div>
                        <div className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-primary)', wordBreak: 'break-all', marginTop: 4 }}>{originNode.address}</div>
                        <button className="btn btn-outline" onClick={() => copyToClipboard(originNode.address, 'origin')} style={{ padding: '2px 6px', fontSize: '0.65rem', marginTop: 6 }}>
                          {copiedText === 'origin' ? '✅ Copied' : '📋 Copy Address'}
                        </button>
                      </div>
                    </div>
                  </div>
                ) : currentHopData ? (
                  <AnimatePresence mode="wait">
                  <motion.div key={currentHop} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.22 }} className="intel-panel">
                    <div className="intel-panel-header"><h4>🔎 Hop Dossier ({currentHop + 1}/{totalHops})</h4><span className="badge badge-info">{currentHopData.chain}</span></div>
                    <div className="intel-panel-body">
                      <div className="dossier-grid">
                        <div className="dossier-card"><div className="dossier-label">TRANSFER AMOUNT</div><div className="dossier-val" style={{ color: 'var(--accent-copper-light)', fontFamily: 'var(--font-mono)' }}>{currentHopData.amount ?? 'Unknown'} {currentHopData.token || ''}</div></div>
                        <div className="dossier-card"><div className="dossier-label">NODE RISK</div><div className="dossier-val" style={{ color: riskColor(currentHopData.riskScore), fontFamily: 'var(--font-mono)' }}><AnimatedNumber value={currentHopData.riskScore} suffix=" / 100" /></div></div>
                      </div>
                      <div style={{ marginBottom: 10 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                          <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', fontWeight: 700 }}>RISK LEVEL</span>
                          <span style={{ fontSize: '0.62rem', fontWeight: 800, color: riskColor(currentHopData.riskScore) }}>{riskLabel(currentHopData.riskScore)}</span>
                        </div>
                        <div style={{ height: 5, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                          <motion.div key={currentHop} initial={{ width: 0 }} animate={{ width: `${currentHopData.riskScore}%` }} transition={{ duration: 0.4 }}
                            style={{ height: '100%', background: riskColor(currentHopData.riskScore), borderRadius: 3 }} />
                        </div>
                      </div>
                      <div style={{ display: 'grid', gap: 8, marginBottom: 12 }}>
                        <div style={{ background: 'var(--bg-secondary)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
                          <div className="dossier-label">FROM (SENDER)</div>
                          <div className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-primary)', wordBreak: 'break-all', marginTop: 2 }}>{currentHopData.from}</div>
                        </div>
                        <div style={{ background: currentHopData.toNode?.node_type?.includes('VASP') ? 'rgba(212, 163, 89, 0.08)' : 'var(--bg-secondary)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: `1px solid ${currentHopData.toNode?.node_type?.includes('VASP') ? 'var(--border-gold)' : 'var(--border-default)'}` }}>
                          <div className="dossier-label" style={{ color: currentHopData.toNode?.node_type?.includes('VASP') ? 'var(--accent-gold)' : 'var(--text-muted)' }}>TO (RECIPIENT) {currentHopData.toNode?.node_type?.includes('VASP') && '• TARGET VASP'}</div>
                          <div className="mono" style={{ fontSize: '0.75rem', color: currentHopData.toNode?.node_type?.includes('VASP') ? 'var(--text-gold)' : 'var(--text-primary)', wordBreak: 'break-all', marginTop: 2 }}>{currentHopData.to}</div>
                        </div>
                      </div>
                      <ul className="evidence-list">
                        {currentHopData.evidence.map((ev, ei) => <li key={ei} className="evidence-item"><span className="check">✓</span><span>{ev}</span></li>)}
                      </ul>
                    </div>
                  </motion.div>
                  </AnimatePresence>
                ) : null}

                {hasAttribution && vaspNode && (
                  <div className="intel-panel" style={{ borderColor: 'var(--border-gold)' }}>
                    <div className="intel-panel-header" style={{ background: '#181510' }}><h4 style={{ color: 'var(--text-gold)' }}>🎯 Attributed Exchange Terminal</h4><span className="badge badge-fiu">FIU-IND</span></div>
                    <div className="intel-panel-body">
                      <div style={{ fontSize: '1.2rem', fontWeight: 900, color: 'var(--text-gold)', marginBottom: 4 }}>{vaspNode.vasp_name}</div>
                      {vaspNode.nodal_email && (
                        <div style={{ background: 'var(--bg-secondary)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)', fontSize: '0.75rem' }}>
                          <div className="dossier-label">COMPLIANCE NODAL OFFICER</div>
                          <div className="mono" style={{ color: 'var(--accent-copper-light)', marginTop: 2 }}>{vaspNode.nodal_email}</div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}

            {sidebarTab === 'risk' && (
              <div className="intel-panel">
                <div className="intel-panel-header"><h4>🛡️ Deterministic Risk Assessment</h4></div>
                <div className="intel-panel-body">
                  {/* Live hop trail risk */}
                  {structuredHops.length > 0 && (
                    <div style={{ marginBottom: 14, padding: '10px 12px', background: `${riskColor(trailRiskScore)}10`, border: `1px solid ${riskColor(trailRiskScore)}35`, borderRadius: 'var(--radius-sm)' }}>
                      <div style={{ fontSize: '0.62rem', fontWeight: 800, color: 'var(--text-muted)', marginBottom: 6 }}>TRAIL RISK — HOP {Math.min(currentHop+1,totalHops)}/{totalHops}</div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 900, fontSize: '1.3rem', color: riskColor(trailRiskScore) }}><AnimatedNumber value={trailRiskScore} suffix=" / 100" /></span>
                        <span style={{ fontSize: '0.7rem', fontWeight: 800, color: riskColor(trailRiskScore) }}>{riskLabel(trailRiskScore)}</span>
                      </div>
                      {/* Per-hop bars */}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                        {structuredHops.map((hop, idx) => (
                          <div key={idx} onClick={() => { setCurrentHop(idx); setSelectedNodeId(hop.to); setIsPlaying(false); }}
                            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 5px', borderRadius: 4, cursor: 'pointer', background: idx === currentHop ? `${riskColor(hop.riskScore)}12` : 'transparent' }}>
                            <span style={{ fontSize: '0.58rem', fontWeight: 800, color: 'var(--text-muted)', minWidth: 36, fontFamily: 'var(--font-mono)' }}>HOP {idx+1}</span>
                            <div style={{ flex: 1, height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
                              <div style={{ height: '100%', width: `${hop.riskScore}%`, background: riskColor(hop.riskScore), borderRadius: 2 }} />
                            </div>
                            <span style={{ fontSize: '0.62rem', fontWeight: 900, color: riskColor(hop.riskScore), fontFamily: 'var(--font-mono)', minWidth: 22 }}>{hop.riskScore}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {risk?.assessment_state === 'not_assessed' || !risk ? (
                    <div style={{ padding: 12, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                      <div className="spinner" style={{ margin: '0 auto 8px auto', width: 20, height: 20 }}></div>
                      Evaluating deterministic risk &amp; typology heuristics...
                    </div>
                  ) : (
                    <>
                      <div className="risk-gauge" style={{ marginBottom: 14 }}>
                        <div className="gauge-value" style={{ color: (risk.score || 0) >= 75 ? '#E57373' : (risk.score || 0) >= 30 ? '#F0A742' : '#7BC497' }}>
                          <AnimatedNumber value={risk.score ?? 0} suffix=" / 100" />
                        </div>
                        <div className="gauge-label" style={{ fontWeight: 800, letterSpacing: '0.05em' }}>
                          {(risk.tier || 'ASSESSED').toUpperCase()} RISK (CASE LEVEL)
                        </div>
                      </div>

                      <div style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)', marginBottom: 8 }}>
                        EVIDENCE SIGNALS &amp; ATTRIBUTION RULES:
                      </div>

                      {(risk.findings || []).map((f, i) => {
                        const isTriggered = f.assessment_state === 'triggered' || (f.contribution && f.contribution > 0);
                        return (
                          <div key={i} style={{
                            background: isTriggered ? 'rgba(200, 109, 59, 0.08)' : 'var(--bg-secondary)',
                            border: `1px solid ${isTriggered ? 'var(--border-copper)' : 'var(--border-default)'}`,
                            padding: '8px 10px',
                            borderRadius: 'var(--radius-sm)',
                            marginBottom: 6,
                            fontSize: '0.78rem'
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span style={{ fontWeight: 700, color: isTriggered ? 'var(--accent-copper-light)' : 'var(--text-secondary)' }}>
                                {f.rule_id ? f.rule_id.replace(/_/g, ' ').toUpperCase() : f.description || `Rule #${i+1}`}
                              </span>
                              {f.contribution ? (
                                <span className="badge badge-critical" style={{ fontSize: '0.65rem' }}>+{f.contribution} pts</span>
                              ) : (
                                <span className="badge badge-info" style={{ fontSize: '0.65rem' }}>{f.assessment_state || 'checked'}</span>
                              )}
                            </div>
                            {f.measured_values && Object.keys(f.measured_values).length > 0 && (
                              <div className="mono" style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 4 }}>
                                {JSON.stringify(f.measured_values).substring(0, 100)}
                              </div>
                            )}
                          </div>
                        );
                      })}
                      {!(risk.findings || []).length && (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No rule signals triggered.</div>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}

            {sidebarTab === 'notes' && (
              <div className="intel-panel">
                <div className="intel-panel-header"><h4>📝 Investigator Notes</h4></div>
                <div className="intel-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <textarea className="form-textarea" value={newNote} onChange={e => setNewNote(e.target.value)} placeholder="Add an investigator note…" rows={3} style={{ flex: 1, fontSize: '0.8rem', resize: 'vertical' }} />
                  <button className="btn btn-primary" onClick={handleAddNote} disabled={savingNote || !newNote.trim()} style={{ fontSize: '0.8rem' }}>{savingNote ? 'Saving…' : '+ Add Note'}</button>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4, maxHeight: 300, overflowY: 'auto' }}>
                    {notes.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No notes yet.</div>}
                    {notes.map((n, i) => (
                      <div key={n.id || i} style={{ background: 'var(--bg-secondary)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 2 }}>{n.created_at?.substring(0, 19).replace('T', ' ')} · {n.author_name || n.created_by || 'Officer'}</div>
                        <div style={{ fontSize: '0.8rem', color: 'var(--text-primary)' }}>{n.content || '[protected — re-open list to view your own note above]'}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {sidebarTab === 'history' && (
              <div className="intel-panel">
                <div className="intel-panel-header"><h4>🧾 Case Audit History</h4></div>
                <div className="intel-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 400, overflowY: 'auto' }}>
                  {history.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No events logged yet.</div>}
                  {history.map((ev, i) => (
                    <div key={i} style={{ background: 'var(--bg-secondary)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)', fontSize: '0.78rem' }}>
                      <div style={{ color: 'var(--accent-copper-light)', fontWeight: 700 }}>{ev.event_type || ev.type}</div>
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem', fontFamily: 'var(--font-mono)' }}>{ev.created_at?.substring(0, 19).replace('T', ' ')}</div>
                      {ev.reason && <div style={{ color: 'var(--text-secondary)', marginTop: 2 }}>{ev.reason}</div>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {sidebarTab === 'related' && (
              <div className="intel-panel">
                <div className="intel-panel-header"><h4>🔗 Related Cases &amp; Syndicate Links</h4></div>
                <div className="intel-panel-body">
                  {relatedCases.length === 0
                    ? <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No related cases identified.</div>
                    : relatedCases.map((rc, i) => (
                      <div key={i} style={{ background: 'var(--bg-secondary)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)', marginBottom: 6, cursor: 'pointer' }}
                        onClick={() => navigate(`/money-trail?case=${rc.id || rc.case_id}`)}>
                        <div style={{ fontWeight: 800, color: 'var(--accent-copper-light)', fontSize: '0.8rem' }}>{rc.external_complaint_id || rc.id}</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{rc.link_reason || rc.overlap_type || 'Shared wallet overlap'}</div>
                      </div>
                    ))}
                </div>
              </div>
            )}

            {sidebarTab === 'clusters' && (
              <div className="intel-panel">
                <div className="intel-panel-header"><h4>🧬 Address Clusters &amp; Attributions</h4></div>
                <div className="intel-panel-body">
                  {attributions.length === 0 && !clusters && <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No clustering results recorded for this case.</div>}
                  {attributions.map((a, i) => (
                    <div key={i} style={{ background: 'var(--bg-secondary)', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-gold)', marginBottom: 6 }}>
                      <div style={{ fontWeight: 800, color: 'var(--text-gold)', fontSize: '0.8rem' }}>{a.entity_name || a.vasp_name || a.label || 'Unknown Entity'}</div>
                      <div className="mono" style={{ fontSize: '0.7rem', color: 'var(--text-muted)', wordBreak: 'break-all' }}>{a.address}</div>
                      {a.confidence != null && <div style={{ fontSize: '0.75rem', marginTop: 4, color: 'var(--accent-gold)' }}>{a.confidence}%</div>}
                    </div>
                  ))}
                  {clusters && (
                    <pre style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', marginTop: 8 }}>{JSON.stringify(clusters, null, 2)}</pre>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {targetCaseId && (
        <div className="telemetry-strip">
          <div className="telemetry-metric copper">
            <span className="metric-label">TOTAL FUNDS TRACED</span>
            <span className="metric-value">{summaryMetrics.totalFunds == null ? 'Unknown' : <AnimatedNumber value={Number(summaryMetrics.totalFunds) || 0} toLocaleString={true} />} {summaryMetrics.token || ''}</span>
          </div>
          <div className="telemetry-metric"><span className="metric-label">HOPS TRAVERSED</span><span className="metric-value"><AnimatedNumber value={summaryMetrics.hopsCount} /> Hops</span></div>
          <div className="telemetry-metric"><span className="metric-label">CHAINS CROSSED</span><span className="metric-value"><AnimatedNumber value={summaryMetrics.chainsCount} /> Blockchains</span></div>
          <div className="telemetry-metric"><span className="metric-label">ENTITIES IDENTIFIED</span><span className="metric-value"><AnimatedNumber value={summaryMetrics.entitiesCount} /> Wallets</span></div>
          <div className="telemetry-metric" style={{ borderLeft: `2px solid ${riskColor(trailRiskScore)}` }}>
            <span className="metric-label">TRAIL RISK</span>
            <span className="metric-value" style={{ color: riskColor(trailRiskScore), fontFamily: 'var(--font-mono)' }}>
              <AnimatedNumber value={trailRiskScore} suffix=" / 100" /> · {riskLabel(trailRiskScore)}
            </span>
          </div>
          <div className="telemetry-metric gold">
            <span className="metric-label">ATTRIBUTION STATUS</span>
            <span className="metric-value" style={{ fontSize: summaryMetrics.confidence ? '1rem' : '0.85rem', color: summaryMetrics.confidence ? 'var(--accent-gold)' : '#94a3b8' }}>
              {summaryMetrics.attributionLabel}
            </span>
          </div>
        </div>
      )}
    </motion.div>
  );
}
