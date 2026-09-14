import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCase } from '../context/CaseContext';
import api from '../lib/api';
import { errorMessage, items } from '../lib/contracts';

export default function NewCasePage() {
  const navigate = useNavigate();
  const { selectCase, reloadCasesList } = useCase();
  const [mode, setMode] = useState('manual');
  const [address, setAddress] = useState('');
  const [chain, setChain] = useState('');
  const [loading, setLoading] = useState(false);
  const [traceStep, setTraceStep] = useState('');
  const [traceProgress, setTraceProgress] = useState(0);
  const [error, setError] = useState('');
  const pollTimerRef = useRef(null);
  const [chains, setChains] = useState([
    { id: 'TRON', name: 'TRON (TRC-20)' },
    { id: 'ETH', name: 'Ethereum (ERC-20)' },
    { id: 'BSC', name: 'BSC (BEP-20)' },
    { id: 'BTC', name: 'Bitcoin' },
    { id: 'POLYGON', name: 'Polygon' },
  ]);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  useEffect(() => {
    api.get('/api/v1/chains')
      .then(res => {
        const list = items(res.data, 'chains');
        if (list.length) {
          setChains(list
            .filter(c => (typeof c === 'string' ? c : c.network) && (typeof c === 'string' ? true : c.enabled !== false))
            .map(c => typeof c === 'string' ? { id: c, name: c } : { id: c.network, name: c.name || c.network }));
        }
      })
      .catch(() => { /* keep defaults */ });
  }, []);

  const [complaint, setComplaint] = useState({
    complaint_source: 'ncrp',
    external_complaint_id: '',
    victim_name: '',
    victim_phone: '',
    fraud_typology: 'TASK_BASED_SCAM',
    reported_loss_amount: '',
    loss_currency: 'USDT',
    complaint_text: '',
    victim_reported_at: '',
    receipt_reference: '',
  });

  const autoDetectChain = (addr) => {
    if (/^T[a-zA-Z0-9]{33}$/.test(addr)) return 'TRON';
    if (/^0x[a-fA-F0-9]{40}$/.test(addr)) return 'ETH';
    if (/^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}$/.test(addr)) return 'BTC';
    return '';
  };

  const handleAddressChange = (val) => {
    setAddress(val);
    const detected = autoDetectChain(val);
    if (detected) setChain(detected);
  };

  const waitForTraceAndGoToGraph = async (caseId, traceId) => {
    selectCase(caseId);
    if (!traceId) {
      setTraceStep('Trace initiated! Loading transaction graph...');
      setTraceProgress(100);
      await reloadCasesList();
      navigate(`/graph?case=${caseId}`);
      return;
    }

    setTraceStep('Executing real-time trace across blockchain hops...');
    setTraceProgress(30);

    let attempts = 0;
    const maxAttempts = 30; // ~15 seconds

    return new Promise((resolve) => {
      pollTimerRef.current = setInterval(async () => {
        attempts++;
        try {
          const res = await api.get(`/api/v1/traces/${traceId}`);
          const state = (res.data?.state || res.data?.status || '').toLowerCase();
          const pct = res.data?.progress_percent || Math.min(90, 30 + attempts * 5);
          setTraceProgress(pct);
          if (res.data?.message) setTraceStep(res.data.message);

          if (['complete', 'completed', 'done', 'succeeded', 'partial'].includes(state) || attempts >= maxAttempts) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
            setTraceStep('Trace complete! Opening transaction graph...');
            setTraceProgress(100);
            await reloadCasesList();
            setTimeout(() => {
              navigate(`/graph?case=${caseId}`);
              resolve();
            }, 400);
          }
        } catch {
          if (attempts >= 5) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
            await reloadCasesList();
            navigate(`/graph?case=${caseId}`);
            resolve();
          }
        }
      }, 500);
    });
  };

  const handleManualTrace = async () => {
    if (!address) { setError('Please enter a wallet address'); return; }
    setError('');
    setLoading(true);
    setTraceProgress(10);
    setTraceStep('Validating suspect wallet address on-chain...');
    try {
      await api.post('/api/v1/wallets/validate', { address, chain: chain || null });
      setTraceProgress(25);
      setTraceStep('Registering FIR intake and dispatching BFS trace worker...');
      const complaintRes = await api.post('/api/v1/complaints', {
        complaint_source: 'manual_fir',
        external_complaint_id: `MANUAL-${crypto.randomUUID()}`,
        fraud_typology: 'TASK_BASED_SCAM',
        reported_loss_amount: 0,
        suspect_wallets: [{ address, chain: chain || null }],
        auto_start: true,
      }, { headers: { 'Idempotency-Key': crypto.randomUUID() } });

      const caseId = complaintRes.data.case_id;
      const traceId = complaintRes.data.trace_id;
      await waitForTraceAndGoToGraph(caseId, traceId);
    } catch (err) {
      setError(errorMessage(err, 'Trace failed'));
      setLoading(false);
    }
  };

  const handleComplaintSubmit = async () => {
    if (!address) { setError('Please enter a suspect wallet address'); return; }
    setError('');
    setLoading(true);
    setTraceProgress(10);
    setTraceStep('Validating suspect wallet address on-chain...');
    try {
      if (!complaint.external_complaint_id.trim()) throw new Error('Complaint ID is required');
      await api.post('/api/v1/wallets/validate', { address, chain: chain || null });
      setTraceProgress(25);
      setTraceStep('Registering NCRP complaint and dispatching forensic trace...');
      const res = await api.post('/api/v1/complaints', {
        ...complaint,
        reported_loss_amount: parseFloat(complaint.reported_loss_amount) || 0,
        victim_reported_at: complaint.victim_reported_at || null,
        receipt_reference: complaint.receipt_reference || null,
        suspect_wallets: [{ address, chain: chain || null, token_symbol: complaint.loss_currency }],
        auto_start: true,
      }, { headers: { 'Idempotency-Key': crypto.randomUUID() } });

      const caseId = res.data.case_id;
      const traceId = res.data.trace_id;
      await waitForTraceAndGoToGraph(caseId, traceId);
    } catch (err) {
      setError(errorMessage(err, 'Submission failed'));
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>🔍 New Case Intake</h1>
          <p className="subtitle">Register a suspect wallet or NCRP/1930 complaint to begin real-time attribution</p>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        <button className={`btn ${mode === 'manual' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setMode('manual')}>⚡ Quick Trace</button>
        <button className={`btn ${mode === 'complaint' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setMode('complaint')}>📋 NCRP / 1930 Complaint</button>
      </div>

      <div className="card" style={{ maxWidth: 700 }}>
        <div className="form-group">
          <label>Suspect Wallet Address</label>
          <input className="form-input mono" value={address} onChange={e => handleAddressChange(e.target.value)} placeholder="T..., 0x..., bc1..., 1..., 3..." />
          {chain && <span style={{ fontSize: '0.775rem', color: 'var(--accent-copper-light)', marginTop: 6, display: 'inline-block', fontWeight: 800 }}>
            ✅ Detected Network: <span className="badge badge-info">{chain}</span>
          </span>}
        </div>

        <div className="form-group">
          <label>Blockchain Network</label>
          <select className="form-select" value={chain} onChange={e => setChain(e.target.value)}>
            <option value="">Auto-detect</option>
            {chains.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>

        {mode === 'complaint' && (
          <>
            <div style={{ borderTop: '1px solid var(--border-default)', margin: '20px 0', paddingTop: 20 }}>
              <h3 style={{ fontSize: '0.875rem', fontWeight: 800, marginBottom: 16, color: 'var(--accent-copper-light)' }}>📡 NCRP / 1930 Statutory Complaint Intake</h3>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div className="form-group">
                <label>Complaint ID</label>
                <input className="form-input mono" value={complaint.external_complaint_id} onChange={e => setComplaint({ ...complaint, external_complaint_id: e.target.value })} />
              </div>
              <div className="form-group">
                <label>Fraud Typology</label>
                <select className="form-select" value={complaint.fraud_typology} onChange={e => setComplaint({ ...complaint, fraud_typology: e.target.value })}>
                  <option value="TASK_BASED_SCAM">📱 Task-Based Scam</option>
                  <option value="INVESTMENT_PONZI_SCAM">📈 Investment Ponzi</option>
                  <option value="DIGITAL_ARREST_EXTORTION">🚔 Digital Arrest</option>
                  <option value="SEXTORTION_BLACKMAIL">📸 Sextortion</option>
                  <option value="RANSOMWARE_PAYMENT">🔒 Ransomware</option>
                  <option value="PHISHING_DRAINER">🎣 Phishing / Drainer</option>
                  <option value="DARKNET_FINANCIAL_CRIME">🕸️ Darknet Crime</option>
                </select>
              </div>
              <div className="form-group">
                <label>Victim Name</label>
                <input className="form-input" value={complaint.victim_name} onChange={e => setComplaint({ ...complaint, victim_name: e.target.value })} placeholder="Rajesh Kumar" />
              </div>
              <div className="form-group">
                <label>Victim Phone</label>
                <input className="form-input" value={complaint.victim_phone} onChange={e => setComplaint({ ...complaint, victim_phone: e.target.value })} placeholder="+91-9876543210" />
              </div>
              <div className="form-group">
                <label>Loss Amount</label>
                <input className="form-input mono" type="number" value={complaint.reported_loss_amount} onChange={e => setComplaint({ ...complaint, reported_loss_amount: e.target.value })} placeholder="12500" />
              </div>
              <div className="form-group">
                <label>Currency</label>
                <select className="form-select" value={complaint.loss_currency} onChange={e => setComplaint({ ...complaint, loss_currency: e.target.value })}>
                  <option value="USDT">USDT</option><option value="INR">INR</option><option value="BTC">BTC</option><option value="ETH">ETH</option>
                </select>
              </div>
            </div>
            <div className="form-group">
              <label>Complaint Narrative</label>
              <textarea className="form-textarea" value={complaint.complaint_text} onChange={e => setComplaint({ ...complaint, complaint_text: e.target.value })} placeholder="Describe how the fraud occurred..." rows={3} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div className="form-group">
                <label>Victim Report Receipt Time (ISO-8601 with offset)</label>
                <input className="form-input mono" value={complaint.victim_reported_at} onChange={e => setComplaint({ ...complaint, victim_reported_at: e.target.value })} placeholder="2026-09-13T10:15:00+05:30" />
              </div>
              <div className="form-group">
                <label>Receipt Reference</label>
                <input className="form-input mono" value={complaint.receipt_reference} onChange={e => setComplaint({ ...complaint, receipt_reference: e.target.value })} placeholder="NCRP receipt / diary reference" />
              </div>
            </div>
          </>
        )}

        {error && <p className="form-error" style={{ marginBottom: 12 }}>⚠️ {error}</p>}

        {loading && (
          <div style={{
            background: 'rgba(200, 109, 59, 0.08)',
            border: '1px solid var(--border-copper)',
            borderRadius: 'var(--radius-md)',
            padding: '16px',
            marginBottom: '16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '0.8rem', fontWeight: 800, color: 'var(--accent-copper-light)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="status-dot pulse" style={{ background: 'var(--accent-copper)' }}></span>
                {traceStep || 'Tracing blockchain hops...'}
              </span>
              <span style={{ fontSize: '0.85rem', fontWeight: 900, fontFamily: 'var(--font-mono)', color: 'var(--accent-gold)' }}>
                {traceProgress}%
              </span>
            </div>
            <div style={{ width: '100%', height: '6px', background: 'var(--bg-secondary)', borderRadius: '3px', overflow: 'hidden' }}>
              <div style={{
                height: '100%',
                width: `${traceProgress}%`,
                background: 'linear-gradient(90deg, var(--accent-copper), var(--accent-gold))',
                transition: 'width 0.3s ease'
              }} />
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              ⚡ Real-time BFS expansion · Identifying mule hops & VASP exchange deposit points · Auto-redirecting to Transaction Graph upon completion.
            </div>
          </div>
        )}

        <button className="btn btn-primary btn-lg" style={{ width: '100%', marginTop: 8 }}
          onClick={mode === 'manual' ? handleManualTrace : handleComplaintSubmit} disabled={loading}>
          {loading ? '⏳ Tracing & Preparing Graph...' : '🚀 Initiate Real-Time Attribution'}
        </button>
      </div>
    </div>
  );
}
