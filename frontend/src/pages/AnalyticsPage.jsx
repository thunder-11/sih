import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import AnimatedNumber from '../components/AnimatedNumber';
import api from '../lib/api';
import { errorMessage } from '../lib/contracts';

export default function AnalyticsPage() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await api.get('/api/v1/dashboard/stats');
        setStats(res.data);
      } catch (err) {
        setError(errorMessage(err, 'Analytics are unavailable.'));
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, []);

  if (loading) return <div className="loading-overlay"><div className="spinner"></div><p>Calculating Forensic Analytics Models...</p></div>;
  if (!stats) return <div className="card" style={{ padding: 24 }}>{error}</div>;

  return (
    <motion.div style={{ display: 'flex', flexDirection: 'column', gap: 20 }} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
      <div className="page-header" style={{ margin: 0 }}>
        <div><h1>📈 Forensic Analytics &amp; Typology Trends</h1><p className="subtitle">Agency-Scoped Aggregations, Risk Distribution &amp; Attribution Success Rates</p></div>
      </div>

      <div className="stats-grid" style={{ margin: 0 }}>
        <motion.div className="stat-card blue" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.02 }}>
          <div className="stat-label">Total Traced Loss</div><div className="stat-value">₹<AnimatedNumber value={stats.total_loss_tracked || 0} toLocaleString={true} /></div>
        </motion.div>
        <motion.div className="stat-card green" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.08 }}>
          <div className="stat-label">Attribution Rate</div>
          <div className="stat-value">{stats.total_cases > 0 ? <><AnimatedNumber value={Math.round((stats.total_attributed / stats.total_cases) * 100)} suffix="%" /></> : 'Not available'}</div>
        </motion.div>
        <motion.div className="stat-card amber" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.14 }}>
          <div className="stat-label">Unique Wallets Traced</div><div className="stat-value"><AnimatedNumber value={stats.total_wallets_traced ?? 0} /></div>
        </motion.div>
        <motion.div className="stat-card red" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.2 }}>
          <div className="stat-label">Syndicate Intersections</div><div className="stat-value"><AnimatedNumber value={stats.total_syndicate_flags ?? 0} /></div>
        </motion.div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        <div className="panel" style={{ margin: 0 }}>
          <div className="panel-header"><h3>🗂️ Cases by Status</h3></div>
          <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {Object.entries(stats.cases_by_status || {}).map(([status, count]) => (
              <div key={status} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{status.replace(/_/g, ' ')}</span>
                <strong style={{ fontFamily: 'var(--font-mono)' }}>{count}</strong>
              </div>
            ))}
            {!Object.keys(stats.cases_by_status || {}).length && <div>Status distribution is not yet available.</div>}
          </div>
        </div>

        <div className="panel" style={{ margin: 0 }}>
          <div className="panel-header"><h3>⚡ Risk Tier Classification</h3></div>
          <div className="panel-body" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div style={{ padding: 14, background: 'rgba(189, 74, 74, 0.1)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-crimson)' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--accent-crimson)' }}>CRITICAL RISK</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 900, color: '#E57373', fontFamily: 'var(--font-mono)', marginTop: 2 }}><AnimatedNumber value={stats.cases_by_risk_tier?.CRITICAL ?? 0} /></div>
            </div>
            <div style={{ padding: 14, background: 'rgba(217, 148, 59, 0.1)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(217, 148, 59, 0.4)' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--accent-amber)' }}>HIGH RISK</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 900, color: '#F0A742', fontFamily: 'var(--font-mono)', marginTop: 2 }}><AnimatedNumber value={stats.cases_by_risk_tier?.HIGH ?? 0} /></div>
            </div>
            <div style={{ padding: 14, background: 'rgba(212, 163, 89, 0.1)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-gold)' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--accent-gold)' }}>MEDIUM RISK</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 900, color: 'var(--text-gold)', fontFamily: 'var(--font-mono)', marginTop: 2 }}><AnimatedNumber value={stats.cases_by_risk_tier?.MEDIUM ?? 0} /></div>
            </div>
            <div style={{ padding: 14, background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--text-secondary)' }}>RESOLVED / LOW</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 900, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginTop: 2 }}><AnimatedNumber value={stats.cases_by_risk_tier?.LOW ?? 0} /></div>
            </div>
          </div>
        </div>
      </div>

      <div className="panel" style={{ margin: 0 }}>
        <div className="panel-header"><h3>📊 Fraud Typology Distribution</h3></div>
        <div className="panel-body" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12 }}>
          {Object.entries(stats.cases_by_fraud_type || {}).map(([type, count]) => (
            <div key={type} style={{ padding: 14, background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)' }}>
              <div style={{ fontSize: '0.725rem', color: 'var(--text-secondary)', fontWeight: 700 }}>{type.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: '1.3rem', fontWeight: 900, color: 'var(--text-primary)', marginTop: 4, fontFamily: 'var(--font-mono)' }}><AnimatedNumber value={count} /></div>
            </div>
          ))}
          {!Object.keys(stats.cases_by_fraud_type || {}).length && <div>No typology distribution is supplied yet.</div>}
        </div>
      </div>
    </motion.div>
  );
}
