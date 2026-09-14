import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../context/AuthContext';
import { errorMessage } from '../lib/contracts';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/');
    } catch (err) {
      setError(errorMessage(err, 'Login failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <motion.div className="login-card" initial={{ opacity: 0, y: 24, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.45, ease: 'easeOut' }}>
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <div style={{
            width: 54, height: 54, margin: '0 auto 16px',
            background: 'var(--bg-secondary)', border: '1px solid var(--border-copper)',
            borderRadius: 'var(--radius-md)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 26, boxShadow: 'var(--shadow-glow-copper)', color: 'var(--accent-copper)'
          }}>🛡️</div>
        </div>
        <h1>ARGUS</h1>
        <p className="subtitle">Crypto Fraud Attribution System<br />Forensic Intelligence Console for Law Enforcement</p>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Authorized Gov Email</label>
            <input className="form-input" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="officer@cyberpolice.gov.in" required />
          </div>
          <div className="form-group">
            <label>Security Key</label>
            <input className="form-input" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" required />
          </div>
          {error && <p className="form-error" style={{ marginBottom: 12 }}>⚠️ {error}</p>}
          <button className="btn btn-primary btn-lg" style={{ width: '100%', justifyContent: 'center' }} disabled={loading}>
            {loading ? '⏳ Authenticating Credentials...' : '🔐 Secure LEA Access'}
          </button>
        </form>
      </motion.div>
    </div>
  );
}
