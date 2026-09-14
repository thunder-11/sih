import { useState, useEffect } from 'react';
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

export default function OverviewPage() {
  const [stats, setStats] = useState(null);
  const [recentCases, setRecentCases] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const { selectCase } = useCase();
  const navigate = useNavigate();

  useEffect(() => {
    const fetchOverviewData = async () => {
      try {
        const [statsRes, casesRes, alertsRes] = await Promise.all([
          api.get('/api/v1/dashboard/stats'),
          api.get('/api/v1/cases', { params: { page_size: 5 } }),
          api.get('/api/v1/alerts', { params: { page_size: 5 } }).catch(() => ({ data: {} })),
        ]);
        setStats(statsRes.data);
        setRecentCases(items(casesRes.data, 'cases').slice(0, 5));
        setAlerts(items(alertsRes.data, 'alerts').slice(0, 5));
      } catch (err) {
        setError(errorMessage(err, 'Overview data is unavailable.'));
      } finally {
        setLoading(false);
      }
    };
    fetchOverviewData();
  }, []);

  const handleOpenCase = (caseId) => {
    selectCase(caseId);
    navigate(`/money-trail?case=${caseId}`);
  };

  if (loading) {
    return <div className="loading-overlay"><div className="spinner"></div><p>Aggregating Intelligence Telemetry...</p></div>;
  }

  return (
    <motion.div style={{ display: 'flex', flexDirection: 'column', gap: 20 }} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
      <div className="page-header" style={{ margin: 0 }}>
        <div>
          <h1>📊 Intelligence Command Center</h1>
          <p className="subtitle">Real-Time Cryptocurrency Fraud Attribution & Asset Recovery OS</p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-primary" onClick={() => navigate('/cases')}>📁 Case Registry</button>
          <button className="btn btn-primary" onClick={() => navigate('/new-case')}>➕ New Case</button>
        </div>
      </div>
      {error && <div className="card" style={{ padding: 12, color: 'var(--accent-amber)' }}>{error}</div>}

      {stats && (
        <div className="stats-grid" style={{ margin: 0 }}>
          <motion.div className="stat-card blue" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.02 }}>
            <div className="stat-label">Active Investigations</div>
            <div className="stat-value"><AnimatedNumber value={stats.total_cases || 0} /></div>
          </motion.div>
          <motion.div className="stat-card green" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.08 }}>
            <div className="stat-label">Attributed VASPs</div>
            <div className="stat-value"><AnimatedNumber value={stats.total_attributed || 0} /></div>
          </motion.div>
          <motion.div className="stat-card red" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.14 }}>
            <div className="stat-label">Syndicate Patterns</div>
            <div className="stat-value"><AnimatedNumber value={stats.total_syndicate_flags || 0} /></div>
          </motion.div>
          <motion.div className="stat-card amber" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.2 }}>
            <div className="stat-label">Tracked Fraud Loss</div>
            <div className="stat-value">₹<AnimatedNumber value={stats.total_loss_tracked || 0} toLocaleString={true} /></div>
          </motion.div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: 20 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-header">
              <h3>📁 Active Priority Cases ({recentCases.length})</h3>
              <button className="btn btn-outline" onClick={() => navigate('/cases')} style={{ padding: '3px 8px', fontSize: '0.75rem' }}>View All Cases →</button>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr><th>Case ID</th><th>Typology</th><th>Reported Loss</th><th>Risk Tier</th><th>Status</th><th>Action</th></tr>
                </thead>
                <tbody>
                  {recentCases.map(c => (
                    <tr key={c.id}>
                      <td className="mono" style={{ fontWeight: 800, color: 'var(--accent-copper-light)' }}>{c.external_complaint_id}</td>
                      <td style={{ fontSize: '0.8rem' }}>{TYPOLOGY_LABELS[c.fraud_typology] || c.fraud_typology}</td>
                      <td style={{ fontWeight: 800, fontFamily: 'var(--font-mono)' }}>{c.reported_loss_amount?.toLocaleString()} {c.loss_currency}</td>
                      <td><span className={`badge ${c.risk_tier === 'CRITICAL' ? 'badge-critical' : c.risk_tier === 'HIGH' ? 'badge-high' : 'badge-medium'}`}>{c.risk_tier || 'UNSCORED'} {c.risk_score != null ? `(${c.risk_score})` : ''}</span></td>
                      <td><span className={`badge ${['ATTRIBUTED', 'escalated_to_vasp'].includes(c.status) ? 'badge-fiu' : 'badge-info'}`}>{c.status}</span></td>
                      <td><button className="btn btn-outline" onClick={() => handleOpenCase(c.id)} style={{ padding: '3px 8px', fontSize: '0.725rem' }}>Investigate →</button></td>
                    </tr>
                  ))}
                  {!recentCases.length && <tr><td colSpan={6} style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)' }}>No cases yet. Start a new intake.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          {stats?.cases_by_fraud_type && (
            <div className="panel" style={{ margin: 0 }}>
              <div className="panel-header"><h3>📈 Fraud Typology Distribution</h3></div>
              <div className="panel-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
                {Object.entries(stats.cases_by_fraud_type).map(([type, count]) => (
                  <div key={type} style={{ padding: '12px 14px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
                    <div style={{ fontSize: '0.725rem', color: 'var(--text-secondary)', fontWeight: 700 }}>{TYPOLOGY_LABELS[type] || type}</div>
                    <div style={{ fontSize: '1.3rem', fontWeight: 900, color: 'var(--text-primary)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>
                      {count} <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>cases</span>
                    </div>
                  </div>
                ))}
                {!Object.keys(stats.cases_by_fraud_type).length && <div style={{ color: 'var(--text-muted)' }}>No typology distribution yet.</div>}
              </div>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-header">
              <h3>🚨 Priority Intelligence Dispatches</h3>
              <button className="btn btn-outline" onClick={() => navigate('/alerts')} style={{ padding: '3px 8px', fontSize: '0.75rem' }}>All Alerts →</button>
            </div>
            <div className="panel-body" style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
              {alerts.map(a => (
                <div key={a.id} onClick={() => a.case_id && handleOpenCase(a.case_id)}
                  style={{ padding: '10px 12px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)', cursor: a.case_id ? 'pointer' : 'default' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ fontSize: '0.8rem', fontWeight: 800, color: 'var(--text-primary)' }}>{a.title}</span>
                    <span className={`badge ${a.severity === 'CRITICAL' ? 'badge-critical' : 'badge-high'}`}>{a.severity}</span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{a.message?.substring(0, 90)}</div>
                </div>
              ))}
              {!alerts.length && <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>No unacknowledged alerts.</div>}
            </div>
          </div>

          {stats?.cases_by_status && (
            <div className="panel" style={{ margin: 0 }}>
              <div className="panel-header"><h3>🗂️ Case Status Breakdown</h3></div>
              <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {Object.entries(stats.cases_by_status).map(([status, count]) => (
                  <div key={status} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>{status.replace(/_/g, ' ')}</span>
                    <strong style={{ fontFamily: 'var(--font-mono)' }}>{count}</strong>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
