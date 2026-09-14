import { useEffect, useState } from 'react';
import api from '../lib/api';
import { errorMessage } from '../lib/contracts';

export default function SystemStatusPage() {
  const [services, setServices] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [mlStatus, setMlStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [lastRefresh, setLastRefresh] = useState(null);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const results = await Promise.allSettled([
        api.get('/health/live'),
        api.get('/health/ready'),
        api.get('/api/v1/system/status'),
        api.get('/api/v1/system/metrics'),
        api.get('/api/v1/ml/models/status'),
      ]);

      const names = ['API Liveness', 'Required Dependencies', 'System Status'];
      const coreServices = results.slice(0, 3).map((result, i) =>
        result.status === 'fulfilled'
          ? { name: names[i], status: result.value.data.status || result.value.data.service_state || 'available', details: result.value.data }
          : { name: names[i], status: result.reason?.response?.status === 403 ? 'restricted' : 'unavailable', details: null }
      );
      setServices(coreServices);

      if (results[2].status === 'fulfilled') setSystemStatus(results[2].value.data);
      if (results[3].status === 'fulfilled') setMetrics(results[3].value.data);
      if (results[4].status === 'fulfilled') setMlStatus(results[4].value.data);

      setLastRefresh(new Date());
    } catch (err) {
      setMessage(errorMessage(err, 'System status is unavailable.'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStatus(); }, []);

  const ready = services.length > 0 && services.filter(s => s.status !== 'restricted').every(s => !['unavailable', 'not_ready'].includes(s.status));
  const statusColor = { available: '#7BC497', ready: '#7BC497', unavailable: '#E57373', degraded: '#F0A742', restricted: '#9E9E96' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div className="page-header" style={{ margin: 0 }}>
        <div><h1>🖥️ System Health &amp; Telemetry</h1><p className="subtitle">Backend readiness, service metrics, and ML model status</p></div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {lastRefresh && <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Last: {lastRefresh.toLocaleTimeString()}</span>}
          <span className={`badge ${ready ? 'badge-fiu' : 'badge-high'}`}>{ready ? '✅ ALL SYSTEMS OPERATIONAL' : '⚠️ DEGRADED / UNKNOWN'}</span>
          <button className="btn btn-outline" onClick={fetchStatus} disabled={loading} style={{ padding: '4px 10px', fontSize: '0.8rem' }}>{loading ? '…' : '🔄 Refresh'}</button>
        </div>
      </div>

      {message && <div className="card" style={{ padding: 12, color: 'var(--accent-amber)' }}>{message}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 }}>
        {services.map(svc => (
          <div key={svc.name} className="card" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
              <strong style={{ fontSize: '0.9rem' }}>{svc.name}</strong>
              <span className="badge badge-info" style={{ background: statusColor[svc.status] || 'var(--text-muted)', color: '#000', fontSize: '0.7rem' }}>{String(svc.status).toUpperCase()}</span>
            </div>
            {svc.details?.data_mode && <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Data mode: {svc.details.data_mode}</div>}
          </div>
        ))}
      </div>

      {systemStatus && (
        <div className="panel" style={{ margin: 0 }}>
          <div className="panel-header"><h3>⚙️ System Status Detail</h3></div>
          <div className="panel-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
            {Object.entries(systemStatus).map(([key, value]) => (
              <div key={key} style={{ padding: '10px 12px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-muted)', marginBottom: 4 }}>{key.replace(/_/g, ' ').toUpperCase()}</div>
                <div style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {metrics && (
        <div className="panel" style={{ margin: 0 }}>
          <div className="panel-header"><h3>📊 System Metrics (Admin)</h3></div>
          <div className="panel-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
            {Object.entries(metrics).map(([key, value]) => (
              <div key={key} style={{ padding: '10px 12px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-muted)', marginBottom: 4 }}>{key.replace(/_/g, ' ').toUpperCase()}</div>
                <div style={{ fontSize: '1rem', fontWeight: 900, color: 'var(--accent-copper-light)', fontFamily: 'var(--font-mono)' }}>{typeof value === 'number' ? value.toLocaleString() : String(value)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {mlStatus && (
        <div className="panel" style={{ margin: 0 }}>
          <div className="panel-header"><h3>🧠 ML Model Status</h3></div>
          <div className="panel-body">
            <pre style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{JSON.stringify(mlStatus, null, 2)}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
