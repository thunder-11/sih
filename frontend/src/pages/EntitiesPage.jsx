import { useState, useEffect } from 'react';
import api from '../lib/api';
import { items, errorMessage } from '../lib/contracts';
import { useAuth } from '../context/AuthContext';

export default function EntitiesPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState('directory');
  const [vasps, setVasps] = useState([]);
  const [entityGraph, setEntityGraph] = useState([]);
  const [vaspAddresses, setVaspAddresses] = useState([]);
  const [selectedVasp, setSelectedVasp] = useState(null);
  const [vaspLabels, setVaspLabels] = useState([]);
  const [filterFiu, setFilterFiu] = useState('ALL');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [newAddr, setNewAddr] = useState({ address: '', chain: 'TRON', vasp_id: '', address_tag: '' });
  const [adding, setAdding] = useState(false);

  const [importPayload, setImportPayload] = useState({ source_name: '', source_uri: '', reviewed: false, entitiesJson: '[]' });
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState('');

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [dirRes, entRes, addrRes] = await Promise.allSettled([
        api.get('/api/v1/vasp/directory', { params: { page_size: 100 } }),
        api.get('/api/v1/entities', { params: { page_size: 100 } }),
        api.get('/api/v1/vasp/addresses', { params: { page_size: 100 } }),
      ]);
      if (dirRes.status === 'fulfilled') setVasps(items(dirRes.value.data, 'vasps'));
      if (entRes.status === 'fulfilled') setEntityGraph(items(entRes.value.data, 'entities'));
      if (addrRes.status === 'fulfilled') setVaspAddresses(items(addrRes.value.data, 'addresses'));
    } catch (err) {
      setError(errorMessage(err, 'Entity directory is unavailable.'));
    } finally {
      setLoading(false);
    }
  };

  const selectVasp = async (id) => {
    if (id === selectedVasp) { setSelectedVasp(null); setVaspLabels([]); return; }
    setSelectedVasp(id);
    try {
      const res = await api.get(`/api/v1/entities/${id}`);
      setVaspLabels((res.data.labels || []).map(l => ({ ...l, vasp_id: id, address_tag: l.label, is_verified: l.review_status === 'reviewed' })));
    } catch { setVaspLabels([]); }
  };

  const handleAddAddress = async () => {
    if (!newAddr.address || !newAddr.chain) return;
    setAdding(true);
    try {
      await api.post('/api/v1/vasp/addresses', newAddr);
      const res = await api.get('/api/v1/vasp/addresses', { params: { page_size: 100 } });
      setVaspAddresses(items(res.data, 'addresses'));
      setNewAddr({ address: '', chain: 'TRON', vasp_id: '', address_tag: '' });
    } catch (err) {
      alert(errorMessage(err, 'Failed to add address.'));
    } finally { setAdding(false); }
  };

  const handleDeleteAddress = async (address, chain) => {
    if (!confirm(`Remove ${address} (${chain}) from the directory?`)) return;
    try {
      await api.delete(`/api/v1/vasp/addresses/${encodeURIComponent(address)}/${chain}`);
      setVaspAddresses(prev => prev.filter(a => !(a.address === address && a.chain === chain)));
    } catch (err) {
      alert(errorMessage(err, 'Delete failed.'));
    }
  };

  const handleImport = async () => {
    setImportMessage('');
    let entities;
    try { entities = JSON.parse(importPayload.entitiesJson); } catch { setImportMessage('Entities must be valid JSON array.'); return; }
    setImporting(true);
    try {
      await api.post('/api/v1/directory/imports', {
        source_name: importPayload.source_name,
        source_uri: importPayload.source_uri || undefined,
        reviewed: importPayload.reviewed,
        entities,
      });
      setImportMessage('✅ Import accepted.');
      fetchAll();
    } catch (err) {
      setImportMessage(errorMessage(err, 'Import failed.'));
    } finally {
      setImporting(false);
    }
  };

  const filteredVasps = vasps.filter(v => filterFiu === 'ALL' ? true : filterFiu === 'FIU' ? v.is_fiu_ind_registered : !v.is_fiu_ind_registered);

  if (loading) return <div className="loading-overlay"><div className="spinner" /><p>Loading Entity Directory…</p></div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div className="page-header" style={{ margin: 0 }}>
        <div><h1>🏦 Entity &amp; VASP Intelligence Directory</h1><p className="subtitle">FIU-IND Registered VASPs, Global Exchanges, Mixers &amp; Bridge Protocols</p></div>
      </div>
      {error && <div className="card" style={{ padding: 12, color: 'var(--accent-amber)' }}>{error}</div>}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {[
          { key: 'directory', label: '🏦 VASP Directory' },
          { key: 'entities', label: '🕸️ Graph Entities' },
          { key: 'addresses', label: '📍 Known Addresses' },
          ...(user?.role === 'admin' ? [{ key: 'imports', label: '📥 Directory Imports' }] : []),
        ].map(t => (
          <button key={t.key} className={`btn ${tab === t.key ? 'btn-primary' : 'btn-outline'}`} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>

      {tab === 'directory' && (
        <>
          <div className="card" style={{ padding: '12px 18px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)' }}>FILTER:</span>
            {['ALL', 'FIU', 'GLOBAL'].map(f => (
              <button key={f} onClick={() => setFilterFiu(f)} className={`btn ${filterFiu === f ? 'btn-primary' : 'btn-outline'}`} style={{ padding: '3px 8px', fontSize: '0.7rem' }}>
                {f === 'FIU' ? '🇮🇳 FIU-IND' : f === 'GLOBAL' ? '🌐 Global' : 'All'}
              </button>
            ))}
            <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{filteredVasps.length} VASPs</span>
          </div>

          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-header"><h3>VASP &amp; Exchange Directory</h3></div>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead><tr><th>Exchange / Entity</th><th>Legal Name</th><th>FIU-IND</th><th>Jurisdiction</th><th>Nodal Officer</th><th>SLA (hrs)</th><th>Notes</th></tr></thead>
                <tbody>
                  {filteredVasps.map(v => (
                    <tr key={v.id} onClick={() => selectVasp(v.id)} style={{ cursor: 'pointer', background: selectedVasp === v.id ? 'rgba(200,109,59,0.08)' : 'transparent' }}>
                      <td style={{ fontWeight: 800 }}>{v.vasp_name}</td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{v.legal_entity_name || '—'}</td>
                      <td>{v.is_fiu_ind_registered ? <span className="badge badge-fiu">🇮🇳 REGISTERED</span> : <span className="badge badge-low">UNREGISTERED</span>}</td>
                      <td>{v.jurisdiction || '—'}</td>
                      <td className="mono" style={{ color: 'var(--accent-copper-light)', fontSize: '0.8rem' }}>{v.nodal_officer_email || '—'}</td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 800 }}>{v.sla_freeze_hours ?? '—'}</td>
                      <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)', maxWidth: 200 }}>{v.notes || '—'}</td>
                    </tr>
                  ))}
                  {filteredVasps.length === 0 && <tr><td colSpan={7} style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)' }}>No VASPs found.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          {selectedVasp && (
            <div className="panel" style={{ margin: 0 }}>
              <div className="panel-header"><h3>Known Clusters for {vasps.find(v => v.id === selectedVasp)?.vasp_name}</h3></div>
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead><tr><th>Address</th><th>Chain</th><th>Tag</th><th>Verification</th></tr></thead>
                  <tbody>
                    {vaspLabels.map(a => (
                      <tr key={a.address + a.chain}>
                        <td className="mono" style={{ color: 'var(--accent-copper-light)' }}>{a.address}</td>
                        <td><span className="badge badge-info">{a.chain}</span></td>
                        <td>{a.address_tag}</td>
                        <td>{a.is_verified ? <span style={{ color: '#7BC497', fontWeight: 800 }}>✓ Verified</span> : <span style={{ color: 'var(--text-muted)' }}>Heuristic</span>}</td>
                      </tr>
                    ))}
                    {vaspLabels.length === 0 && <tr><td colSpan={4} style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)' }}>No clusters available. Select a row to load.</td></tr>}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {tab === 'entities' && (
        <div className="panel" style={{ margin: 0 }}>
          <div className="panel-header"><h3>Graph Attribution Entities ({entityGraph.length})</h3></div>
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead><tr><th>ID</th><th>Canonical Name</th><th>Legal Name</th><th>FIU Status</th><th>Jurisdiction</th><th>Contact</th></tr></thead>
              <tbody>
                {entityGraph.map(e => (
                  <tr key={e.id}>
                    <td className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{e.id}</td>
                    <td style={{ fontWeight: 800 }}>{e.canonical_name}</td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{e.legal_name || '—'}</td>
                    <td>{e.fiu_status === 'registered' ? <span className="badge badge-fiu">🇮🇳 REGISTERED</span> : <span className="badge badge-low">{(e.fiu_status || 'UNKNOWN').toUpperCase()}</span>}</td>
                    <td>{e.jurisdiction || '—'}</td>
                    <td className="mono" style={{ color: 'var(--accent-copper-light)', fontSize: '0.8rem' }}>{e.contact_email || '—'}</td>
                  </tr>
                ))}
                {entityGraph.length === 0 && <tr><td colSpan={6} style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)' }}>No graph entities loaded.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'addresses' && (
        <>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: '0.8rem', fontWeight: 800, marginBottom: 10, color: 'var(--accent-copper-light)' }}>➕ Register New Known Address</div>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr auto', gap: 10, alignItems: 'end' }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label>Address</label>
                <input className="form-input mono" value={newAddr.address} placeholder="T..., 0x..., bc1..." onChange={e => setNewAddr(p => ({ ...p, address: e.target.value }))} />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>Chain</label>
                <select className="form-select" value={newAddr.chain} onChange={e => setNewAddr(p => ({ ...p, chain: e.target.value }))}>
                  <option value="TRON">TRON</option><option value="ETH">ETH</option><option value="BTC">BTC</option><option value="BSC">BSC</option><option value="POLYGON">POLYGON</option>
                </select>
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>VASP ID</label>
                <input className="form-input" value={newAddr.vasp_id} placeholder="vasp-coindcx" onChange={e => setNewAddr(p => ({ ...p, vasp_id: e.target.value }))} />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>Tag</label>
                <input className="form-input" value={newAddr.address_tag} placeholder="Hot Wallet 1" onChange={e => setNewAddr(p => ({ ...p, address_tag: e.target.value }))} />
              </div>
              <button className="btn btn-primary" onClick={handleAddAddress} disabled={adding}>{adding ? '…' : 'Add'}</button>
            </div>
          </div>

          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-header"><h3>VASP Known Addresses ({vaspAddresses.length})</h3></div>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead><tr><th>Address</th><th>Chain</th><th>VASP</th><th>Tag</th><th>Action</th></tr></thead>
                <tbody>
                  {vaspAddresses.map(a => (
                    <tr key={`${a.address}-${a.chain}`}>
                      <td className="mono" style={{ color: 'var(--accent-copper-light)', fontSize: '0.8rem' }}>{a.address}</td>
                      <td><span className="badge badge-info">{a.chain}</span></td>
                      <td style={{ fontSize: '0.8rem' }}>{a.vasp_id || '—'}</td>
                      <td style={{ fontSize: '0.8rem' }}>{a.address_tag || '—'}</td>
                      <td><button className="btn btn-outline" style={{ padding: '2px 8px', fontSize: '0.7rem', color: 'var(--accent-crimson)' }} onClick={() => handleDeleteAddress(a.address, a.chain)}>🗑 Remove</button></td>
                    </tr>
                  ))}
                  {vaspAddresses.length === 0 && <tr><td colSpan={5} style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)' }}>No addresses registered.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {tab === 'imports' && (
        <div className="card" style={{ padding: 20, maxWidth: 700 }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: 14, color: 'var(--accent-copper-light)' }}>📥 Bulk Entity Directory Import (Admin)</div>
          <div className="form-group">
            <label>Source Name</label>
            <input className="form-input" value={importPayload.source_name} onChange={e => setImportPayload(p => ({ ...p, source_name: e.target.value }))} placeholder="FIU-IND Registered VASP List" />
          </div>
          <div className="form-group">
            <label>Source URI (optional)</label>
            <input className="form-input mono" value={importPayload.source_uri} onChange={e => setImportPayload(p => ({ ...p, source_uri: e.target.value }))} placeholder="https://fiuindia.gov.in/..." />
          </div>
          <div className="form-group">
            <label><input type="checkbox" checked={importPayload.reviewed} onChange={e => setImportPayload(p => ({ ...p, reviewed: e.target.checked }))} /> Human-reviewed source</label>
          </div>
          <div className="form-group">
            <label>Entities (JSON array, each with labels[])</label>
            <textarea className="form-textarea mono" rows={8} value={importPayload.entitiesJson} onChange={e => setImportPayload(p => ({ ...p, entitiesJson: e.target.value }))} />
          </div>
          {importMessage && <p style={{ marginBottom: 12, color: importMessage.startsWith('✅') ? 'var(--accent-gold)' : 'var(--accent-crimson)' }}>{importMessage}</p>}
          <button className="btn btn-primary" onClick={handleImport} disabled={importing || !importPayload.source_name}>{importing ? 'Importing…' : 'Submit Import'}</button>
        </div>
      )}
    </div>
  );
}
