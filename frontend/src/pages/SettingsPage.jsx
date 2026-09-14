import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../lib/api';
import { items, errorMessage } from '../lib/contracts';

export default function SettingsPage() {
  const { user } = useAuth();
  const [configuration, setConfiguration] = useState(null);
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [policyForm, setPolicyForm] = useState({ policy_name: '', version: '', effective_at: '', thresholds: '{}', preferences: '{}', change_reason: '' });
  const [auditLogs, setAuditLogs] = useState([]);
  const [logsLoading, setLogsLoading] = useState(false);

  useEffect(() => {
    if (user?.role !== 'admin') return;
    api.get('/api/v1/admin/settings')
      .then(res => setConfiguration(res.data))
      .catch(err => setMessage(errorMessage(err, 'Settings are unavailable.')));
  }, [user]);

  const savePolicy = async () => {
    setSaving(true); setMessage('');
    let thresholds, preferences;
    try {
      thresholds = JSON.parse(policyForm.thresholds);
      preferences = JSON.parse(policyForm.preferences);
    } catch {
      setMessage('Thresholds and preferences must be valid JSON.');
      setSaving(false);
      return;
    }
    try {
      await api.post('/api/v1/admin/settings', {
        policy_name: policyForm.policy_name,
        version: policyForm.version,
        effective_at: policyForm.effective_at || new Date().toISOString(),
        thresholds,
        preferences,
        change_reason: policyForm.change_reason,
      });
      setMessage('✅ Policy saved successfully.');
      const res = await api.get('/api/v1/admin/settings');
      setConfiguration(res.data);
    } catch (err) {
      setMessage(errorMessage(err, 'Save failed.'));
    } finally {
      setSaving(false);
    }
  };

  const loadAuditLogs = async () => {
    setLogsLoading(true);
    try {
      const res = await api.get('/api/v1/audit-logs', { params: { page_size: 100 } });
      setAuditLogs(items(res.data, 'logs'));
    } catch (err) {
      setMessage(errorMessage(err, 'Audit logs unavailable.'));
    } finally {
      setLogsLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 900 }}>
      <div className="page-header" style={{ margin: 0 }}>
        <div><h1>⚙️ Settings &amp; Administration</h1><p className="subtitle">Profile defaults, provider &amp; policy configuration, and audit trail</p></div>
      </div>

      {message && <div className="card" style={{ padding: 12, color: message.startsWith('✅') ? 'var(--accent-gold)' : 'var(--accent-amber)' }}>{message}</div>}

      <div className="panel" style={{ margin: 0 }}>
        <div className="panel-header"><h3>👤 Current Profile</h3></div>
        <div className="panel-body">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            {[
              ['Full Name', user?.full_name],
              ['Email', user?.email],
              ['Role', user?.role],
              ['Badge Number', user?.badge_number || '—'],
              ['Police Station', user?.police_station || 'Not configured'],
              ['Permissions', (user?.permissions || []).join(', ') || '—'],
            ].map(([label, val]) => (
              <div key={label} style={{ padding: '10px 12px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-muted)', marginBottom: 2 }}>{label.toUpperCase()}</div>
                <div style={{ fontSize: '0.9rem', color: 'var(--text-primary)', fontWeight: 600 }}>{val}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {user?.role !== 'admin' ? (
        <div className="card" style={{ padding: 16 }}>Provider and policy settings are restricted to administrators. Credentials are never stored in the browser.</div>
      ) : (
        <>
          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-header"><h3>🔌 Provider &amp; Policy Configuration</h3></div>
            <div className="panel-body">
              {configuration ? (
                <pre style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', marginBottom: 16 }}>{JSON.stringify(configuration, null, 2)}</pre>
              ) : (
                <div style={{ color: 'var(--text-muted)', marginBottom: 16 }}>Loading configuration…</div>
              )}

              <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: 14 }}>
                <div style={{ fontSize: '0.8rem', fontWeight: 800, marginBottom: 10, color: 'var(--accent-copper-light)' }}>➕ New Policy Setting</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label>Policy Name</label>
                    <input className="form-input" value={policyForm.policy_name} onChange={e => setPolicyForm(p => ({ ...p, policy_name: e.target.value }))} placeholder="risk_thresholds" />
                  </div>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label>Version</label>
                    <input className="form-input" value={policyForm.version} onChange={e => setPolicyForm(p => ({ ...p, version: e.target.value }))} placeholder="v1" />
                  </div>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label>Effective At (ISO, optional — defaults to now)</label>
                    <input className="form-input mono" value={policyForm.effective_at} onChange={e => setPolicyForm(p => ({ ...p, effective_at: e.target.value }))} placeholder="2026-09-14T00:00:00Z" />
                  </div>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label>Change Reason</label>
                    <input className="form-input" value={policyForm.change_reason} onChange={e => setPolicyForm(p => ({ ...p, change_reason: e.target.value }))} placeholder="Quarterly threshold review" />
                  </div>
                </div>
                <div className="form-group">
                  <label>Thresholds (JSON)</label>
                  <textarea className="form-textarea mono" rows={3} value={policyForm.thresholds} onChange={e => setPolicyForm(p => ({ ...p, thresholds: e.target.value }))} />
                </div>
                <div className="form-group">
                  <label>Preferences (JSON)</label>
                  <textarea className="form-textarea mono" rows={3} value={policyForm.preferences} onChange={e => setPolicyForm(p => ({ ...p, preferences: e.target.value }))} />
                </div>
                <button className="btn btn-primary" onClick={savePolicy} disabled={saving || !policyForm.policy_name || !policyForm.version}>{saving ? 'Saving…' : '💾 Save Policy'}</button>
              </div>
            </div>
          </div>

          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-header">
              <h3>📋 Audit Logs</h3>
              <button className="btn btn-outline" onClick={loadAuditLogs} disabled={logsLoading} style={{ padding: '4px 10px', fontSize: '0.8rem' }}>{logsLoading ? '…' : 'Load Audit Trail'}</button>
            </div>
            {auditLogs.length > 0 && (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead><tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Resource</th><th>Case</th></tr></thead>
                  <tbody>
                    {auditLogs.slice(0, 100).map((log, i) => (
                      <tr key={i}>
                        <td style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{log.created_at?.substring(0, 19).replace('T', ' ') || '—'}</td>
                        <td style={{ fontSize: '0.8rem' }}>{log.actor_id || '—'}</td>
                        <td><span className="badge badge-info" style={{ fontSize: '0.65rem' }}>{log.action}</span></td>
                        <td style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{log.resource_type}/{log.resource_id}</td>
                        <td className="mono" style={{ fontSize: '0.75rem', color: 'var(--accent-copper-light)' }}>{log.case_id || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {auditLogs.length === 0 && !logsLoading && <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>Click "Load Audit Trail" to fetch logs.</div>}
          </div>
        </>
      )}
    </div>
  );
}
