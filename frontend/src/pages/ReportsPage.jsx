import React, { useEffect, useState } from 'react';
import { useCase } from '../context/CaseContext';
import { useAuth } from '../context/AuthContext';
import api from '../lib/api';
import { items, errorMessage, downloadBase64Pdf } from '../lib/contracts';

export default function ReportsPage() {
  const { casesList, activeCaseId } = useCase();
  const { user } = useAuth();
  const [selectedCase, setSelectedCase] = useState(activeCaseId || '');
  const [reportType, setReportType] = useState('court');
  const [vasps, setVasps] = useState([]);
  const [selectedVasp, setSelectedVasp] = useState('');
  const [reports, setReports] = useState([]);
  const [generating, setGenerating] = useState(false);
  const [verifying, setVerifying] = useState(null);
  const [expandedReport, setExpandedReport] = useState(null);
  const [manifest, setManifest] = useState({});
  const [message, setMessage] = useState('');

  const loadReports = async () => {
    try {
      const res = await api.get('/api/v1/reports', { params: { page_size: 100 } });
      setReports(items(res.data, 'reports'));
    } catch (err) {
      setMessage(errorMessage(err, 'Report history is unavailable.'));
    }
  };

  useEffect(() => { loadReports(); }, []);
  useEffect(() => { if (!selectedCase && activeCaseId) setSelectedCase(activeCaseId); }, [activeCaseId, selectedCase]);
  useEffect(() => {
    api.get('/api/v1/vasp/directory', { params: { page_size: 100 } }).then(res => setVasps(items(res.data, 'vasps'))).catch(() => setVasps([]));
  }, []);

  const generate = async () => {
    if (!selectedCase) return;
    setGenerating(true); setMessage('');
    try {
      const caseRow = casesList.find(c => c.id === selectedCase);
      let res;
      if (reportType === 'court') {
        res = await api.post(`/api/v1/cases/${selectedCase}/generate-court-report`, {});
      } else {
        res = await api.post(`/api/v1/cases/${selectedCase}/generate-freeze-notice`, {
          vasp_id: selectedVasp || undefined,
          police_station: user?.police_station,
          officer_name: user?.full_name,
          fir_cr_number: caseRow?.external_complaint_id,
          designation: user?.role,
        });
      }
      if (res.data.pdf_base64) downloadBase64Pdf(res.data, `${reportType}-${selectedCase}.pdf`);
      setMessage(`${reportType === 'court' ? 'Court report' : 'Freeze notice'} generated. Human review and signature required.`);
      await loadReports();
    } catch (err) {
      setMessage(errorMessage(err, 'Report generation failed.'));
    } finally {
      setGenerating(false);
    }
  };

  const download = async (report) => {
    try {
      const res = await api.get(`/api/v1/reports/${report.id}/download`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data);
      const link = document.createElement('a');
      link.href = url; link.download = `${report.reference || report.id}.pdf`; link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setMessage(errorMessage(err, 'Download failed.'));
    }
  };

  const verify = async (report) => {
    setVerifying(report.id); setMessage('');
    try {
      const res = await api.post(`/api/v1/reports/${report.id}/verify`);
      setMessage(`Integrity verification: ${res.data?.verified ? '✅ Hash matches original' : '⚠️ Hash mismatch — file may be tampered'}`);
    } catch (err) {
      setMessage(errorMessage(err, 'Verification failed.'));
    } finally {
      setVerifying(null);
    }
  };

  const loadManifest = async (report) => {
    if (expandedReport === report.id) { setExpandedReport(null); return; }
    setExpandedReport(report.id);
    if (manifest[report.id]) return;
    try {
      const res = await api.get(`/api/v1/reports/${report.id}/manifest`);
      setManifest(prev => ({ ...prev, [report.id]: res.data }));
    } catch {
      setManifest(prev => ({ ...prev, [report.id]: { error: 'Manifest unavailable.' } }));
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div className="page-header" style={{ margin: 0 }}>
        <div><h1>📑 Reports &amp; Legal Drafts</h1><p className="subtitle">Immutable evidence reports; human review and signature required before use in proceedings</p></div>
      </div>

      <div className="card" style={{ padding: 20 }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
          {[['court', '📑 Sec 63 BSA Court Report'], ['freeze', '📄 Sec 94 BNSS Freeze Notice']].map(([k, lbl]) => (
            <button key={k} className={`btn ${reportType === k ? 'btn-primary' : 'btn-outline'}`} onClick={() => setReportType(k)}>{lbl}</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <select className="form-select" value={selectedCase} onChange={e => setSelectedCase(e.target.value)} style={{ flex: 1, minWidth: 220 }}>
            <option value="">Select case</option>
            {casesList.map(c => <option key={c.id} value={c.id}>{c.external_complaint_id} — {c.victim_name || c.id}</option>)}
          </select>
          {reportType === 'freeze' && (
            <select className="form-select" value={selectedVasp} onChange={e => setSelectedVasp(e.target.value)} style={{ flex: 1, minWidth: 220 }}>
              <option value="">Select target VASP</option>
              {vasps.map(v => <option key={v.id} value={v.id}>{v.vasp_name}</option>)}
            </select>
          )}
          <button className="btn btn-primary" onClick={generate} disabled={!selectedCase || generating}>
            {generating ? '⏳ Generating…' : `Generate ${reportType === 'court' ? 'Court Report' : 'Freeze Notice'}`}
          </button>
        </div>
      </div>

      {message && <div className="card" style={{ padding: 12, color: message.includes('⚠️') ? 'var(--accent-crimson)' : 'var(--accent-gold)' }}>{message}</div>}

      <div className="panel" style={{ margin: 0 }}>
        <div className="panel-header"><h3>Report History ({reports.length})</h3></div>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead><tr><th>Reference</th><th>Case</th><th>Type</th><th>SHA-256</th><th>Generated</th><th>Actions</th></tr></thead>
            <tbody>
              {reports.map(r => (
                <React.Fragment key={r.id}>
                  <tr>
                    <td className="mono" style={{ color: 'var(--accent-copper-light)' }}>{r.reference || r.id}</td>
                    <td className="mono" style={{ fontSize: '0.8rem' }}>{r.case_id}</td>
                    <td><span className="badge badge-info">{r.report_type || r.type || 'COURT'}</span></td>
                    <td className="mono" style={{ fontSize: '0.7rem', color: 'var(--text-muted)', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.sha256 || r.content_hash || '—'}</td>
                    <td style={{ fontSize: '0.8rem' }}>{r.generated_at?.substring(0, 19).replace('T', ' ') || '—'}</td>
                    <td>
                      <div style={{ display: 'flex', gap: 5 }}>
                        <button className="btn btn-outline" style={{ padding: '2px 8px', fontSize: '0.7rem' }} onClick={() => download(r)}>⬇ Download</button>
                        <button className="btn btn-outline" style={{ padding: '2px 8px', fontSize: '0.7rem' }} disabled={verifying === r.id} onClick={() => verify(r)}>{verifying === r.id ? '…' : '🔐 Verify'}</button>
                        <button className="btn btn-outline" style={{ padding: '2px 8px', fontSize: '0.7rem' }} onClick={() => loadManifest(r)}>{expandedReport === r.id ? '▲ Hide' : '📋 Manifest'}</button>
                      </div>
                    </td>
                  </tr>
                  {expandedReport === r.id && (
                    <tr key={`${r.id}-manifest`}>
                      <td colSpan={6} style={{ padding: 0, background: 'var(--bg-secondary)' }}>
                        <div style={{ padding: '12px 20px', fontSize: '0.8rem' }}>
                          {manifest[r.id]?.error
                            ? <span style={{ color: 'var(--text-muted)' }}>{manifest[r.id].error}</span>
                            : <pre style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{JSON.stringify(manifest[r.id], null, 2)}</pre>}
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
              {!reports.length && <tr><td colSpan={6} style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)' }}>No reports available.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
