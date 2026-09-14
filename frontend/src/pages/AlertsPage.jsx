import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useCase } from '../context/CaseContext';
import AnimatedNumber from '../components/AnimatedNumber';
import api from '../lib/api';
import { items, errorMessage } from '../lib/contracts';

const SEV_COLOR = { CRITICAL: 'var(--accent-crimson)', HIGH: 'var(--accent-amber)', MEDIUM: 'var(--accent-gold)' };

export default function AlertsPage() {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [severityFilter, setSeverityFilter] = useState('ALL');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const { selectCase } = useCase();
  const navigate = useNavigate();

  useEffect(() => { fetchAlerts(); }, []);

  const fetchAlerts = async () => {
    try {
      const res = await api.get('/api/v1/alerts', { params: { page_size: 100 } });
      setAlerts(items(res.data, 'alerts'));
    } catch (err) {
      console.error(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleAlertClick = async (alert) => {
    try {
      await api.put(`/api/v1/alerts/${alert.id}/read`);
      setAlerts(prev => prev.map(a => a.id === alert.id ? { ...a, is_read: true } : a));
    } catch { /* ignore */ }
    if (alert.case_id) {
      selectCase(alert.case_id);
      navigate(`/money-trail?case=${alert.case_id}`);
    }
  };

  const markAllRead = async () => {
    const unread = alerts.filter(a => !a.is_read);
    await Promise.allSettled(unread.map(a => api.put(`/api/v1/alerts/${a.id}/read`)));
    setAlerts(prev => prev.map(a => ({ ...a, is_read: true })));
  };

  const alertTypes = ['ALL', ...new Set(alerts.map(a => a.alert_type).filter(Boolean))];
  const filteredAlerts = alerts.filter(a => {
    const matchSev = severityFilter === 'ALL' || a.severity === severityFilter;
    const matchType = typeFilter === 'ALL' || a.alert_type === typeFilter;
    return matchSev && matchType;
  });
  const unreadCount = alerts.filter(a => !a.is_read).length;

  if (loading) return <div className="loading-overlay"><div className="spinner" /><p>Dispatching Intelligence Alerts…</p></div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div className="page-header" style={{ margin: 0 }}>
        <div><h1>🚨 Risk &amp; Alerts Intelligence Dispatch</h1><p className="subtitle">Real-Time Syndicate Detections, Mixer Interceptions &amp; VASP Attribution Alerts</p></div>
        {unreadCount > 0 && <button className="btn btn-outline" onClick={markAllRead}>✓ Mark All Read ({unreadCount})</button>}
      </div>

      <div className="card" style={{ padding: '12px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)' }}>SEVERITY:</span>
            {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM'].map(sev => (
              <button key={sev} onClick={() => setSeverityFilter(sev)} className={`btn ${severityFilter === sev ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}>{sev}</button>
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)' }}>TYPE:</span>
            {alertTypes.slice(0, 5).map(t => (
              <button key={t} onClick={() => setTypeFilter(t)} className={`btn ${typeFilter === t ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}>{t === 'ALL' ? 'All Types' : t.replace(/_/g, ' ')}</button>
            ))}
          </div>
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
          Showing <strong><AnimatedNumber value={filteredAlerts.length} /></strong> alerts &nbsp;·&nbsp;
          <strong style={{ color: unreadCount > 0 ? 'var(--accent-crimson)' : 'var(--text-muted)' }}><AnimatedNumber value={unreadCount} /> unread</strong>
        </div>
      </div>

      <div style={{ display: 'grid', gap: 12 }}>
        {filteredAlerts.map((alert, idx) => (
          <motion.div key={alert.id} onClick={() => handleAlertClick(alert)} className="card"
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: Math.min(idx, 20) * 0.04 }}
            style={{ padding: '16px 20px', borderLeft: `4px solid ${SEV_COLOR[alert.severity] || 'var(--border-default)'}`, background: alert.is_read ? 'var(--bg-card)' : 'rgba(200,109,59,0.08)', cursor: alert.case_id ? 'pointer' : 'default', transition: 'all 0.2s ease' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: '1rem' }}>{alert.severity === 'CRITICAL' ? '🚨' : '⚠️'}</span>
                <span style={{ fontSize: '0.95rem', fontWeight: 800, color: 'var(--text-primary)' }}>{alert.title}</span>
                {!alert.is_read && <span className="badge badge-info" style={{ fontSize: '0.65rem' }}>NEW</span>}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {alert.alert_type && <span className="badge badge-medium" style={{ fontSize: '0.65rem' }}>{alert.alert_type}</span>}
                <span className={`badge ${alert.severity === 'CRITICAL' ? 'badge-critical' : 'badge-high'}`}>{alert.severity}</span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{alert.created_at ? alert.created_at.substring(0, 19).replace('T', ' ') : 'Just now'}</span>
              </div>
            </div>
            <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', marginTop: 4, lineHeight: 1.5 }}>{alert.message}</p>
            {alert.case_id && <div style={{ marginTop: 10, fontSize: '0.75rem', color: 'var(--accent-copper-light)', fontWeight: 700 }}>Inspect linked case trail →</div>}
          </motion.div>
        ))}
        {filteredAlerts.length === 0 && <div className="card" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No alerts found matching the selected filters.</div>}
      </div>
    </div>
  );
}
