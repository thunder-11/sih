import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useCase } from '../context/CaseContext';
import AnimatedNumber from '../components/AnimatedNumber';
import api from '../lib/api';
import { items, errorMessage } from '../lib/contracts';

const TYPOLOGY_LABELS = {
  TASK_BASED_SCAM: '📱 Task-Based Scam',
  INVESTMENT_PONZI_SCAM: '📈 Investment Ponzi',
  DIGITAL_ARREST_EXTORTION: '🚔 Digital Arrest',
  SEXTORTION_BLACKMAIL: '📸 Sextortion',
  RANSOMWARE_PAYMENT: '🔒 Ransomware',
  PHISHING_DRAINER: '🎣 Phishing Drainer',
  DARKNET_FINANCIAL_CRIME: '🕸️ Darknet Crime',
};

const TRANSITIONS = {
  new: ['investigating', 'closed'],
  investigating: ['escalated_to_vasp', 'frozen', 'closed'],
  escalated_to_vasp: ['frozen', 'closed', 'investigating'],
  frozen: ['closed', 'investigating'],
  closed: ['investigating'],
  // legacy uppercase vocabulary fallback
  NEW: ['investigating', 'closed'],
  UNDER_INVESTIGATION: ['escalated_to_vasp', 'frozen', 'closed'],
  ATTRIBUTED: ['frozen', 'closed'],
};

const NEEDS_REFERENCE = new Set(['escalated_to_vasp', 'frozen']);

const STATUS_CLASS = (status) => {
  if (['escalated_to_vasp', 'ATTRIBUTED', 'frozen', 'FROZEN'].includes(status)) return 'badge-fiu';
  if (['closed', 'CLOSED'].includes(status)) return 'badge-low';
  if (['investigating', 'UNDER_INVESTIGATION'].includes(status)) return 'badge-medium';
  return 'badge-info';
};

export default function CasesPage() {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedRisk, setSelectedRisk] = useState('ALL');
  const [expandedCase, setExpandedCase] = useState(null);
  const [caseEvents, setCaseEvents] = useState({});
  const [transitionCase, setTransitionCase] = useState(null);
  const [transitionTarget, setTransitionTarget] = useState('');
  const [transitionReason, setTransitionReason] = useState('');
  const [transitionRef, setTransitionRef] = useState('');
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState('');
  const { selectCase } = useCase();
  const navigate = useNavigate();

  useEffect(() => { fetchCases(); }, []);

  const fetchCases = async () => {
    try {
      const res = await api.get('/api/v1/cases', { params: { page_size: 100 } });
      setCases(items(res.data, 'cases'));
    } catch (err) {
      setError(errorMessage(err, 'Cases are unavailable.'));
    } finally {
      setLoading(false);
    }
  };

  const handleOpenCase = (cId, mode = 'money_trail') => {
    selectCase(cId);
    navigate(mode === 'graph' ? `/graph?case=${cId}` : `/money-trail?case=${cId}`);
  };

  const openTransition = (c, next) => {
    setTransitionCase(c);
    setTransitionTarget(next);
    setTransitionReason('');
    setTransitionRef('');
  };

  const submitTransition = async () => {
    if (!transitionCase || !transitionReason.trim()) return;
    if (NEEDS_REFERENCE.has(transitionTarget) && !transitionRef.trim()) return;
    setUpdating(true);
    try {
      const res = await api.patch(`/api/v1/cases/${transitionCase.id}`, {
        status: transitionTarget,
        reason: transitionReason.trim(),
        revision: transitionCase.revision,
        external_action_reference: transitionRef.trim() || undefined,
      });
      setCases(prev => prev.map(c => c.id === transitionCase.id ? { ...c, ...res.data } : c));
      setTransitionCase(null);
    } catch (err) {
      alert(errorMessage(err, 'Status update failed.'));
    } finally {
      setUpdating(false);
    }
  };

  const toggleHistory = async (caseId) => {
    if (expandedCase === caseId) { setExpandedCase(null); return; }
    setExpandedCase(caseId);
    if (caseEvents[caseId]) return;
    try {
      const res = await api.get(`/api/v1/cases/${caseId}/history`);
      setCaseEvents(prev => ({ ...prev, [caseId]: items(res.data, 'history') }));
    } catch {
      setCaseEvents(prev => ({ ...prev, [caseId]: [] }));
    }
  };

  const filteredCases = cases.filter(c => {
    const q = searchTerm.toLowerCase();
    const matchesSearch = !q ||
      c.external_complaint_id?.toLowerCase().includes(q) ||
      c.victim_name?.toLowerCase().includes(q) ||
      c.fraud_typology?.toLowerCase().includes(q);
    const matchesRisk = selectedRisk === 'ALL' || c.risk_tier === selectedRisk;
    return matchesSearch && matchesRisk;
  });

  if (loading) return <div className="loading-overlay"><div className="spinner" /><p>Loading Case Registry…</p></div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div className="page-header" style={{ margin: 0 }}>
        <div>
          <h1>📁 Case Investigation Registry</h1>
          <p className="subtitle">Official LEA Cyber Fraud Intake &amp; Attribution Registry</p>
        </div>
        <button className="btn btn-primary btn-lg" onClick={() => navigate('/new-case')}>⚡ New Complaint Intake / Trace</button>
      </div>

      {error && <div className="card" style={{ padding: 12, color: 'var(--accent-amber)' }}>{error}</div>}

      <div className="card" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 260 }}>
          <span style={{ color: 'var(--text-muted)' }}>🔍</span>
          <input className="form-input" value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
            placeholder="Filter by Case ID, Victim Name, or Typology..." style={{ padding: '7px 12px', fontSize: '0.85rem' }} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)' }}>RISK:</span>
          {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(rk => (
            <button key={rk} onClick={() => setSelectedRisk(rk)} className={`btn ${selectedRisk === rk ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}>{rk}</button>
          ))}
        </div>
      </div>

      <div className="panel" style={{ margin: 0 }}>
        <div className="panel-header"><h3>Active Registered Cases (<AnimatedNumber value={filteredCases.length} />)</h3></div>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr><th>Complaint ID</th><th>Victim</th><th>Typology</th><th>Reported Loss</th><th>Source</th><th>Risk</th><th>Status</th><th>Syndicate</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {filteredCases.map((c, idx) => {
                const transitions = TRANSITIONS[c.status] || [];
                const isExpanded = expandedCase === c.id;
                const events = caseEvents[c.id] || [];
                return (
                  <React.Fragment key={c.id}>
                    <motion.tr
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3, delay: Math.min(idx, 20) * 0.04 }}
                      style={{ background: isExpanded ? 'rgba(200,109,59,0.06)' : 'transparent' }}>
                      <td className="mono" style={{ fontWeight: 800, color: 'var(--accent-copper-light)' }}>{c.external_complaint_id}</td>
                      <td style={{ fontSize: '0.8rem' }}>{c.victim_name || '—'}</td>
                      <td style={{ fontSize: '0.825rem', fontWeight: 600 }}>{TYPOLOGY_LABELS[c.fraud_typology] || c.fraud_typology}</td>
                      <td style={{ fontWeight: 800, fontFamily: 'var(--font-mono)' }}>{c.reported_loss_amount?.toLocaleString()} {c.loss_currency}</td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{c.complaint_source?.toUpperCase()}</td>
                      <td><span className={`badge ${c.risk_tier === 'CRITICAL' ? 'badge-critical' : c.risk_tier === 'HIGH' ? 'badge-high' : 'badge-medium'}`}>{c.risk_tier || 'UNSCORED'} {c.risk_score != null ? `(${c.risk_score})` : ''}</span></td>
                      <td>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <span className={`badge ${STATUS_CLASS(c.status)}`}>{c.status}</span>
                          {transitions.length > 0 && (
                            <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                              {transitions.map(next => (
                                <button key={next} className="btn btn-outline" onClick={() => openTransition(c, next)} style={{ padding: '2px 6px', fontSize: '0.65rem' }}>
                                  → {next.replace(/_/g, ' ')}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </td>
                      <td>{c.possible_syndicate ? <span className="badge badge-critical">🚨 SYNDICATE</span> : <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>—</span>}</td>
                      <td>
                        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                          <button className="btn btn-primary" onClick={() => handleOpenCase(c.id, 'money_trail')} style={{ padding: '3px 8px', fontSize: '0.725rem' }}>💸 Trail</button>
                          <button className="btn btn-outline" onClick={() => handleOpenCase(c.id, 'graph')} style={{ padding: '3px 8px', fontSize: '0.725rem' }}>🕸️ Graph</button>
                          <button className="btn btn-outline" onClick={() => toggleHistory(c.id)} style={{ padding: '3px 8px', fontSize: '0.725rem' }}>{isExpanded ? '▲ Hide' : '📋 Log'}</button>
                        </div>
                      </td>
                    </motion.tr>

                    {isExpanded && (
                      <tr key={`${c.id}-events`}>
                        <td colSpan={9} style={{ padding: 0, background: 'var(--bg-secondary)' }}>
                          <div style={{ padding: '12px 20px' }}>
                            <div style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)', marginBottom: 8 }}>CASE ACTIVITY LOG</div>
                            {events.length === 0
                              ? <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No logged events for this case.</div>
                              : events.map((ev, i) => (
                                <div key={i} style={{ display: 'flex', gap: 12, padding: '5px 0', borderBottom: '1px solid var(--border-default)', fontSize: '0.8rem' }}>
                                  <span className="mono" style={{ color: 'var(--text-muted)', minWidth: 160 }}>{ev.created_at?.substring(0, 19).replace('T', ' ') || '—'}</span>
                                  <span style={{ fontWeight: 700, color: 'var(--accent-copper-light)', minWidth: 160 }}>{ev.event_type || ev.type}</span>
                                  <span style={{ color: 'var(--text-secondary)' }}>{ev.summary || ev.description || ev.reason || JSON.stringify(ev.payload || {})}</span>
                                </div>
                              ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
              {filteredCases.length === 0 && (
                <tr><td colSpan={9} style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)' }}>No cases match the selected filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {transitionCase && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(5,7,10,0.75)', backdropFilter: 'blur(4px)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setTransitionCase(null)}>
          <div className="card" style={{ width: 440, padding: 22 }} onClick={e => e.stopPropagation()}>
            <h3 style={{ marginBottom: 4 }}>Transition Case Status</h3>
            <p className="subtitle" style={{ marginBottom: 16 }}>
              {transitionCase.external_complaint_id}: <strong>{transitionCase.status}</strong> → <strong>{transitionTarget.replace(/_/g, ' ')}</strong>
            </p>
            <div className="form-group">
              <label>Reason (required)</label>
              <textarea className="form-textarea" value={transitionReason} onChange={e => setTransitionReason(e.target.value)} rows={3} placeholder="Justification for this transition..." />
            </div>
            {NEEDS_REFERENCE.has(transitionTarget) && (
              <div className="form-group">
                <label>External Action Reference (required)</label>
                <input className="form-input mono" value={transitionRef} onChange={e => setTransitionRef(e.target.value)} placeholder="Freeze notice / escalation reference" />
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <button className="btn btn-outline" onClick={() => setTransitionCase(null)} style={{ flex: 1, justifyContent: 'center' }}>Cancel</button>
              <button className="btn btn-primary" onClick={submitTransition}
                disabled={updating || !transitionReason.trim() || (NEEDS_REFERENCE.has(transitionTarget) && !transitionRef.trim())}
                style={{ flex: 1, justifyContent: 'center' }}>
                {updating ? 'Applying…' : 'Confirm Transition'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
