import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCase } from '../context/CaseContext';
import api from '../lib/api';
import { items } from '../lib/contracts';

const NAV_COMMANDS = [
  { title: 'Overview — Intelligence Command Center', category: 'Navigation', icon: '📊', path: '/' },
  { title: 'Cases — Investigation Case Registry', category: 'Navigation', icon: '📁', path: '/cases' },
  { title: 'New Case — Complaint / Trace Intake', category: 'Navigation', icon: '➕', path: '/new-case' },
  { title: 'Money Trail — Hero Fund Flow Stage', category: 'Navigation', icon: '💸', path: '/money-trail' },
  { title: 'Transaction Graph — Network Explorer', category: 'Navigation', icon: '🕸️', path: '/graph' },
  { title: 'Wallet Intelligence — Address Inspector', category: 'Navigation', icon: '🔎', path: '/wallets' },
  { title: 'Entity & VASP Intelligence — Exchange Directory', category: 'Navigation', icon: '🏦', path: '/entities' },
  { title: 'Cross-Chain Intelligence — Bridge Lanes', category: 'Navigation', icon: '⚡', path: '/cross-chain' },
  { title: 'Risk & Alerts — Intelligence Dispatch', category: 'Navigation', icon: '🚨', path: '/alerts' },
  { title: 'Analytics — Forensic Metrics', category: 'Navigation', icon: '📈', path: '/analytics' },
  { title: 'Reports — Legal Drafts Archive', category: 'Navigation', icon: '📑', path: '/reports' },
  { title: 'System Status — Services & Providers', category: 'System', icon: '🟢', path: '/system-status' },
  { title: 'Settings — Profile & Administration', category: 'System', icon: '⚙️', path: '/settings' },
];

export default function CommandPalette() {
  const { isCommandPaletteOpen, setIsCommandPaletteOpen, casesList, selectCase } = useCase();
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [serverResults, setServerResults] = useState([]);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (isCommandPaletteOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isCommandPaletteOpen]);

  useEffect(() => {
    if (!isCommandPaletteOpen || query.trim().length < 2) { setServerResults([]); return; }
    const controller = new AbortController();
    const timer = setTimeout(() => api.get('/api/v1/search', { params: { q: query.trim() }, signal: controller.signal })
      .then(response => setServerResults(items(response.data, 'items'))).catch(() => {}), 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [isCommandPaletteOpen, query]);

  const searchedCases = serverResults.length ? serverResults : casesList;
  const caseCommands = (searchedCases || []).map(c => ({
    title: `Open Case: ${c.external_complaint_id} (${c.fraud_typology || 'Case'})`,
    subtitle: `Loss: ${c.reported_loss_amount?.toLocaleString()} ${c.loss_currency} • Risk: ${c.risk_tier}`,
    category: 'Cases',
    icon: '🕵️',
    action: () => {
      selectCase(c.id);
      navigate(`/money-trail?case=${c.id}`);
      setIsCommandPaletteOpen(false);
    },
  }));

  const allItems = [...NAV_COMMANDS, ...caseCommands];
  const filteredItems = query.trim() === ''
    ? allItems
    : allItems.filter(item =>
        item.title.toLowerCase().includes(query.toLowerCase()) ||
        (item.subtitle && item.subtitle.toLowerCase().includes(query.toLowerCase())) ||
        item.category.toLowerCase().includes(query.toLowerCase())
      );

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') setIsCommandPaletteOpen(false);
    else if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIndex(prev => (prev + 1) % Math.max(filteredItems.length, 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIndex(prev => (prev - 1 + filteredItems.length) % Math.max(filteredItems.length, 1)); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const selected = filteredItems[selectedIndex];
      if (selected) {
        if (selected.action) selected.action();
        else if (selected.path) { navigate(selected.path); setIsCommandPaletteOpen(false); }
      }
    }
  };

  if (!isCommandPaletteOpen) return null;

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(5, 7, 10, 0.8)', backdropFilter: 'blur(8px)', zIndex: 9999, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '12vh' }}
      onClick={() => setIsCommandPaletteOpen(false)}
    >
      <div
        style={{ width: '100%', maxWidth: '640px', background: 'var(--bg-card)', border: '1px solid var(--border-copper)', borderRadius: 'var(--radius-lg)', boxShadow: '0 20px 40px rgba(0, 0, 0, 0.7), 0 0 20px rgba(200, 109, 59, 0.2)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', borderBottom: '1px solid var(--border-default)', background: 'var(--bg-secondary)' }}>
          <span style={{ fontSize: '1.2rem', color: 'var(--accent-copper)' }}>⚡</span>
          <input
            ref={inputRef}
            value={query}
            onChange={e => { setQuery(e.target.value); setSelectedIndex(0); }}
            onKeyDown={handleKeyDown}
            placeholder="Search cases, wallets, navigation, or commands... (Type or use ↑↓)"
            style={{ width: '100%', background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-primary)', fontFamily: 'var(--font-sans)', fontSize: '0.95rem', fontWeight: 600 }}
          />
          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', background: 'var(--bg-card)', padding: '3px 7px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-default)', fontFamily: 'var(--font-mono)' }}>ESC</span>
        </div>

        <div style={{ maxHeight: '380px', overflowY: 'auto', padding: '8px' }}>
          {filteredItems.length === 0 ? (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>No matching investigations or commands found.</div>
          ) : (
            filteredItems.map((item, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={idx}
                  onClick={() => { if (item.action) item.action(); else if (item.path) { navigate(item.path); setIsCommandPaletteOpen(false); } }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', borderRadius: 'var(--radius-sm)', cursor: 'pointer', background: isSelected ? 'rgba(200, 109, 59, 0.15)' : 'transparent', border: `1px solid ${isSelected ? 'var(--border-copper)' : 'transparent'}`, transition: 'all 0.15s ease' }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: '1.1rem' }}>{item.icon}</span>
                    <div>
                      <div style={{ fontSize: '0.85rem', fontWeight: 800, color: isSelected ? 'var(--accent-copper-light)' : 'var(--text-primary)' }}>{item.title}</div>
                      {item.subtitle && <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: 2 }}>{item.subtitle}</div>}
                    </div>
                  </div>
                  <span style={{ fontSize: '0.675rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--text-muted)', background: 'var(--bg-secondary)', padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border-default)' }}>{item.category}</span>
                </div>
              );
            })
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 16px', borderTop: '1px solid var(--border-default)', background: 'var(--bg-secondary)', fontSize: '0.725rem', color: 'var(--text-muted)' }}>
          <div>Use ↑ ↓ to navigate, Enter to select</div>
          <div style={{ color: 'var(--accent-copper)' }}>ARGUS Command Deck</div>
        </div>
      </div>
    </div>
  );
}
