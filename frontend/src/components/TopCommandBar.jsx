import { useState, useEffect } from 'react';
import { useNavigate, NavLink } from 'react-router-dom';
import { useCase } from '../context/CaseContext';
import { readSession } from '../lib/api';
import api from '../lib/api';

export default function TopCommandBar({ onToggleMobile }) {
  const { activeCase, setIsCommandPaletteOpen } = useCase();
  const [unread, setUnread] = useState(0);
  const [showAlerts, setShowAlerts] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchAlerts = async () => {
      if (!readSession().accessToken) return;
      try {
        const res = await api.get('/api/v1/alerts', { params: { page_size: 5 } });
        setUnread(res.data.unread_count || 0);
        setAlerts((res.data.items || res.data.alerts || []).slice(0, 5));
      } catch { /* ignore */ }
    };
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 8000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="top-command-header">
      <div className="top-command-left">
        <button className="mobile-menu-trigger" onClick={onToggleMobile} title="Open Menu">☰</button>
        <div className="global-search-trigger" onClick={() => setIsCommandPaletteOpen(true)}>
          <span className="search-icon">🔍</span>
          <span className="search-placeholder">Search wallet, transaction, case or entity...</span>
          <span className="shortcut-badge">⌘K / Ctrl+K</span>
        </div>
      </div>

      {activeCase && (
        <div className="active-case-context-pill">
          <div className="context-indicator-dot pulse"></div>
          <span className="context-case-id">{activeCase.external_complaint_id}</span>
          <span className="context-divider">|</span>
          <span className="context-case-loss">
            {activeCase.reported_loss_amount?.toLocaleString()} {activeCase.loss_currency}
          </span>
          <span className="context-divider">|</span>
          <span className={`badge ${activeCase.status === 'escalated_to_vasp' || activeCase.status === 'ATTRIBUTED' ? 'badge-fiu' : 'badge-info'}`} style={{ fontSize: '0.65rem' }}>
            {activeCase.status}
          </span>
          <div className="context-quick-links">
            <NavLink to="/money-trail" title="Open Money Trail" className="context-action-btn">💸 Trail</NavLink>
            <NavLink to="/graph" title="Open Graph" className="context-action-btn">🕸️ Graph</NavLink>
          </div>
        </div>
      )}

      <div className="top-command-right">
        <div className="stream-telemetry-badge">
          <span className="stream-dot pulse"></span>
          <span className="stream-text">LIVE</span>
        </div>
        <div style={{ position: 'relative' }}>
          <button className="alert-bell-btn" onClick={() => setShowAlerts(!showAlerts)} title="System Alerts">
            🔔 {unread > 0 && <span className="alert-count-bubble">{unread}</span>}
          </button>
          {showAlerts && (
            <div className="alerts-dropdown-panel">
              <div className="alerts-dropdown-header">
                <span>System Alerts ({unread} unread)</span>
                <NavLink to="/alerts" onClick={() => setShowAlerts(false)} style={{ color: 'var(--accent-copper-light)', fontSize: '0.75rem', textDecoration: 'none' }}>
                  View All →
                </NavLink>
              </div>
              <div className="alerts-dropdown-body">
                {alerts.map(a => (
                  <div key={a.id} className="alert-dropdown-item" onClick={async () => {
                    try { await api.put(`/api/v1/alerts/${a.id}/read`); } catch { /* ignore */ }
                    if (a.case_id) navigate(`/money-trail?case=${a.case_id}`);
                    setShowAlerts(false);
                  }}>
                    <div className="alert-item-title">{a.title}</div>
                    <div className="alert-item-snippet">{a.message?.substring(0, 80)}...</div>
                  </div>
                ))}
                {alerts.length === 0 && <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>No pending alerts</div>}
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
