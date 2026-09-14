import { useState, useEffect } from 'react';
import api from '../lib/api';
import { items, errorMessage } from '../lib/contracts';

function JsonField({ label, value, onChange, rows = 3 }) {
  return (
    <div className="form-group">
      <label>{label} (JSON)</label>
      <textarea className="form-textarea mono" rows={rows} value={value} onChange={e => onChange(e.target.value)} />
    </div>
  );
}

export default function MLOpsPage() {
  const [tab, setTab] = useState('models');
  const [modelsStatus, setModelsStatus] = useState(null);
  const [drift, setDrift] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [contracts, setContracts] = useState(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const [lifecycleForm, setLifecycleForm] = useState({ package_id: '', transition: 'shadow', reason: '', traffic_percent: '', prior_package_id: '' });
  const [driftForm, setDriftForm] = useState({ model_package_id: '', cohort: '{}', window_start: '', window_end: '', metric_name: '', metric_value: '', sample_size: '', threshold: '', trigger_reason: '' });
  const [retrainForm, setRetrainForm] = useState({ reason: '', drift_evaluation_id: '', dataset_proposal: '{}', scope: '{}' });
  const [datasetForm, setDatasetForm] = useState({ version: '', purpose: '', data_mode: 'live', task_types: 'risk_scoring', period_start: '', period_end: '', retention_policy: '', access_scope: 'admin', manifest: '{}', sources: '[]' });
  const [labelForm, setLabelForm] = useState({ subject_type: 'wallet', subject_id: '', task: '', target_class: '', group_key: '', observation_window_start: '', observation_window_end: '', label: 'unknown', maturity: 'immature', known_at: '', evidence_snapshot_ids: '[]', source_name: '', license_name: '', source_confidence: '', rationale: '', maturation_days: '' });

  useEffect(() => { loadAll(); }, []);

  const loadAll = async () => {
    api.get('/api/v1/ml/models/status').then(r => setModelsStatus(r.data)).catch(() => setModelsStatus(null));
    api.get('/api/v1/admin/ml/monitoring').then(r => setDrift(items(r.data, 'evaluations'))).catch(() => setDrift([]));
    api.get('/api/v1/ml-data/datasets', { params: { page_size: 50 } }).then(r => setDatasets(items(r.data, 'datasets'))).catch(() => setDatasets([]));
    api.get('/api/v1/ml-data/contracts').then(r => setContracts(r.data)).catch(() => setContracts(null));
  };

  const submitLifecycle = async () => {
    if (!lifecycleForm.package_id) return;
    setBusy(true); setMessage('');
    try {
      await api.post(`/api/v1/ml/models/${lifecycleForm.package_id}/lifecycle`, {
        transition: lifecycleForm.transition,
        reason: lifecycleForm.reason,
        traffic_percent: lifecycleForm.traffic_percent ? Number(lifecycleForm.traffic_percent) : undefined,
        prior_package_id: lifecycleForm.prior_package_id || undefined,
      });
      setMessage('✅ Lifecycle transition recorded.');
      loadAll();
    } catch (err) {
      setMessage(errorMessage(err, 'Lifecycle transition failed.'));
    } finally { setBusy(false); }
  };

  const submitDrift = async () => {
    setBusy(true); setMessage('');
    try {
      const cohort = JSON.parse(driftForm.cohort || '{}');
      await api.post('/api/v1/admin/ml/drift-evaluations', {
        model_package_id: driftForm.model_package_id,
        cohort,
        window_start: driftForm.window_start,
        window_end: driftForm.window_end,
        metric_name: driftForm.metric_name,
        metric_value: Number(driftForm.metric_value),
        sample_size: Number(driftForm.sample_size),
        threshold: Number(driftForm.threshold),
        trigger_reason: driftForm.trigger_reason,
      });
      setMessage('✅ Drift evaluation recorded.');
      loadAll();
    } catch (err) {
      setMessage(errorMessage(err, 'Drift evaluation submission failed. Ensure cohort is valid JSON.'));
    } finally { setBusy(false); }
  };

  const submitRetraining = async () => {
    setBusy(true); setMessage('');
    try {
      const dataset_proposal = JSON.parse(retrainForm.dataset_proposal || '{}');
      const scope = JSON.parse(retrainForm.scope || '{}');
      await api.post('/api/v1/admin/ml/retraining-requests', {
        reason: retrainForm.reason,
        drift_evaluation_id: retrainForm.drift_evaluation_id || undefined,
        dataset_proposal,
        scope,
      });
      setMessage('✅ Retraining request submitted. No automatic training or promotion occurs.');
    } catch (err) {
      setMessage(errorMessage(err, 'Retraining request failed. Ensure JSON fields are valid.'));
    } finally { setBusy(false); }
  };

  const submitDataset = async () => {
    setBusy(true); setMessage('');
    try {
      const manifest = JSON.parse(datasetForm.manifest || '{}');
      const sources = JSON.parse(datasetForm.sources || '[]');
      await api.post('/api/v1/ml-data/datasets', {
        version: datasetForm.version,
        purpose: datasetForm.purpose,
        data_mode: datasetForm.data_mode,
        task_types: datasetForm.task_types.split(',').map(s => s.trim()).filter(Boolean),
        period_start: datasetForm.period_start,
        period_end: datasetForm.period_end,
        retention_policy: datasetForm.retention_policy,
        access_scope: datasetForm.access_scope.split(',').map(s => s.trim()).filter(Boolean),
        manifest,
        sources,
      });
      setMessage('✅ Dataset snapshot created.');
      loadAll();
    } catch (err) {
      setMessage(errorMessage(err, 'Dataset creation failed. Ensure manifest/sources are valid JSON.'));
    } finally { setBusy(false); }
  };

  const submitLabel = async () => {
    setBusy(true); setMessage('');
    try {
      const evidence_snapshot_ids = JSON.parse(labelForm.evidence_snapshot_ids || '[]');
      await api.post('/api/v1/ml-data/labels', {
        subject_type: labelForm.subject_type,
        subject_id: labelForm.subject_id,
        task: labelForm.task,
        target_class: labelForm.target_class,
        group_key: labelForm.group_key,
        observation_window_start: labelForm.observation_window_start,
        observation_window_end: labelForm.observation_window_end,
        label: labelForm.label,
        maturity: labelForm.maturity,
        known_at: labelForm.known_at,
        evidence_snapshot_ids,
        source_name: labelForm.source_name,
        license_name: labelForm.license_name,
        source_confidence: labelForm.source_confidence ? Number(labelForm.source_confidence) : undefined,
        rationale: labelForm.rationale,
        maturation_days: labelForm.maturation_days ? Number(labelForm.maturation_days) : undefined,
      });
      setMessage('✅ Label recorded.');
    } catch (err) {
      setMessage(errorMessage(err, 'Label submission failed.'));
    } finally { setBusy(false); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div className="page-header" style={{ margin: 0 }}>
        <div><h1>🧠 ML Operations Console</h1><p className="subtitle">Model lifecycle, drift monitoring, retraining governance, and the fresh data/label platform</p></div>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {[['models', '📦 Models & Lifecycle'], ['drift', '📉 Drift & Retraining'], ['data', '🗃️ Datasets & Labels']].map(([k, lbl]) => (
          <button key={k} className={`btn ${tab === k ? 'btn-primary' : 'btn-outline'}`} onClick={() => setTab(k)}>{lbl}</button>
        ))}
      </div>

      {message && <div className="card" style={{ padding: 12, color: message.startsWith('✅') ? 'var(--accent-gold)' : 'var(--accent-crimson)' }}>{message}</div>}

      {tab === 'models' && (
        <>
          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-header"><h3>📦 Model Package Status</h3></div>
            <div className="panel-body">
              {modelsStatus ? <pre style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{JSON.stringify(modelsStatus, null, 2)}</pre>
                : <div style={{ color: 'var(--text-muted)' }}>No model packages registered yet.</div>}
            </div>
          </div>
          <div className="card" style={{ padding: 20, maxWidth: 700 }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: 14, color: 'var(--accent-copper-light)' }}>🔁 Lifecycle Transition</div>
            <div className="form-group"><label>Model Package ID</label><input className="form-input mono" value={lifecycleForm.package_id} onChange={e => setLifecycleForm(p => ({ ...p, package_id: e.target.value }))} /></div>
            <div className="form-group">
              <label>Transition</label>
              <select className="form-select" value={lifecycleForm.transition} onChange={e => setLifecycleForm(p => ({ ...p, transition: e.target.value }))}>
                {['shadow', 'canary', 'production', 'rollback', 'retired', 'blocked'].map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div className="form-group"><label>Reason</label><textarea className="form-textarea" rows={2} value={lifecycleForm.reason} onChange={e => setLifecycleForm(p => ({ ...p, reason: e.target.value }))} /></div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div className="form-group" style={{ margin: 0 }}><label>Traffic % (canary)</label><input className="form-input" type="number" value={lifecycleForm.traffic_percent} onChange={e => setLifecycleForm(p => ({ ...p, traffic_percent: e.target.value }))} /></div>
              <div className="form-group" style={{ margin: 0 }}><label>Prior Package ID (rollback)</label><input className="form-input mono" value={lifecycleForm.prior_package_id} onChange={e => setLifecycleForm(p => ({ ...p, prior_package_id: e.target.value }))} /></div>
            </div>
            <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: '8px 0' }}>Separation-of-duties enforced: the approver of a transition cannot be its deployer.</p>
            <button className="btn btn-primary" onClick={submitLifecycle} disabled={busy || !lifecycleForm.package_id || !lifecycleForm.reason}>{busy ? 'Submitting…' : 'Apply Transition'}</button>
          </div>
        </>
      )}

      {tab === 'drift' && (
        <>
          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-header"><h3>📉 Drift Evaluations ({drift.length})</h3></div>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead><tr><th>Model Package</th><th>Metric</th><th>Value</th><th>Threshold</th><th>Sample</th><th>Triggered</th></tr></thead>
                <tbody>
                  {drift.map((d, i) => (
                    <tr key={i}>
                      <td className="mono">{d.model_package_id}</td>
                      <td>{d.metric_name}</td>
                      <td className="mono">{d.metric_value}</td>
                      <td className="mono">{d.threshold}</td>
                      <td>{d.sample_size}</td>
                      <td>{d.triggered ? <span className="badge badge-critical">TRIGGERED</span> : <span className="badge badge-low">OK</span>}</td>
                    </tr>
                  ))}
                  {!drift.length && <tr><td colSpan={6} style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)' }}>No drift evaluations recorded.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div className="card" style={{ padding: 20 }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: 14, color: 'var(--accent-copper-light)' }}>➕ Record Drift Evaluation</div>
              <div className="form-group"><label>Model Package ID</label><input className="form-input mono" value={driftForm.model_package_id} onChange={e => setDriftForm(p => ({ ...p, model_package_id: e.target.value }))} /></div>
              <JsonField label="Cohort" value={driftForm.cohort} onChange={v => setDriftForm(p => ({ ...p, cohort: v }))} rows={2} />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <div className="form-group" style={{ margin: 0 }}><label>Window Start</label><input className="form-input mono" value={driftForm.window_start} onChange={e => setDriftForm(p => ({ ...p, window_start: e.target.value }))} placeholder="ISO datetime" /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Window End</label><input className="form-input mono" value={driftForm.window_end} onChange={e => setDriftForm(p => ({ ...p, window_end: e.target.value }))} placeholder="ISO datetime" /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Metric Name</label><input className="form-input" value={driftForm.metric_name} onChange={e => setDriftForm(p => ({ ...p, metric_name: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Metric Value</label><input className="form-input" type="number" value={driftForm.metric_value} onChange={e => setDriftForm(p => ({ ...p, metric_value: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Sample Size</label><input className="form-input" type="number" value={driftForm.sample_size} onChange={e => setDriftForm(p => ({ ...p, sample_size: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Threshold</label><input className="form-input" type="number" value={driftForm.threshold} onChange={e => setDriftForm(p => ({ ...p, threshold: e.target.value }))} /></div>
              </div>
              <div className="form-group"><label>Trigger Reason</label><textarea className="form-textarea" rows={2} value={driftForm.trigger_reason} onChange={e => setDriftForm(p => ({ ...p, trigger_reason: e.target.value }))} /></div>
              <button className="btn btn-primary" onClick={submitDrift} disabled={busy || !driftForm.model_package_id}>{busy ? 'Submitting…' : 'Record Evaluation'}</button>
            </div>

            <div className="card" style={{ padding: 20 }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: 14, color: 'var(--accent-copper-light)' }}>♻️ Retraining Request</div>
              <div className="form-group"><label>Reason</label><textarea className="form-textarea" rows={2} value={retrainForm.reason} onChange={e => setRetrainForm(p => ({ ...p, reason: e.target.value }))} /></div>
              <div className="form-group"><label>Drift Evaluation ID (optional)</label><input className="form-input mono" value={retrainForm.drift_evaluation_id} onChange={e => setRetrainForm(p => ({ ...p, drift_evaluation_id: e.target.value }))} /></div>
              <JsonField label="Dataset Proposal" value={retrainForm.dataset_proposal} onChange={v => setRetrainForm(p => ({ ...p, dataset_proposal: v }))} />
              <JsonField label="Scope" value={retrainForm.scope} onChange={v => setRetrainForm(p => ({ ...p, scope: v }))} />
              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: '8px 0' }}>Submitting never auto-trains or auto-promotes a model.</p>
              <button className="btn btn-primary" onClick={submitRetraining} disabled={busy || !retrainForm.reason}>{busy ? 'Submitting…' : 'Submit Request'}</button>
            </div>
          </div>
        </>
      )}

      {tab === 'data' && (
        <>
          {contracts && (
            <div className="panel" style={{ margin: 0 }}>
              <div className="panel-header"><h3>📜 Task Contracts (v{contracts.feature_schema_version || '—'})</h3></div>
              <div className="panel-body"><pre style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{JSON.stringify(contracts, null, 2)}</pre></div>
            </div>
          )}

          <div className="panel" style={{ margin: 0 }}>
            <div className="panel-header"><h3>🗃️ Dataset Snapshots ({datasets.length})</h3></div>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead><tr><th>Version</th><th>Purpose</th><th>Data Mode</th><th>Period</th><th>Task Types</th></tr></thead>
                <tbody>
                  {datasets.map((d, i) => (
                    <tr key={i}>
                      <td className="mono">{d.version}</td>
                      <td>{d.purpose}</td>
                      <td><span className="badge badge-info">{d.data_mode}</span></td>
                      <td style={{ fontSize: '0.75rem' }}>{d.period_start?.substring(0, 10)} → {d.period_end?.substring(0, 10)}</td>
                      <td style={{ fontSize: '0.75rem' }}>{(d.task_types || []).join(', ')}</td>
                    </tr>
                  ))}
                  {!datasets.length && <tr><td colSpan={5} style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)' }}>No dataset snapshots yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div className="card" style={{ padding: 20 }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: 14, color: 'var(--accent-copper-light)' }}>➕ New Dataset Snapshot</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <div className="form-group" style={{ margin: 0 }}><label>Version</label><input className="form-input" value={datasetForm.version} onChange={e => setDatasetForm(p => ({ ...p, version: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Purpose</label><input className="form-input" value={datasetForm.purpose} onChange={e => setDatasetForm(p => ({ ...p, purpose: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>Data Mode</label>
                  <select className="form-select" value={datasetForm.data_mode} onChange={e => setDatasetForm(p => ({ ...p, data_mode: e.target.value }))}>
                    <option value="live">live</option><option value="research">research</option><option value="synthetic">synthetic</option>
                  </select>
                </div>
                <div className="form-group" style={{ margin: 0 }}><label>Task Types (csv)</label><input className="form-input" value={datasetForm.task_types} onChange={e => setDatasetForm(p => ({ ...p, task_types: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Period Start</label><input className="form-input mono" value={datasetForm.period_start} onChange={e => setDatasetForm(p => ({ ...p, period_start: e.target.value }))} placeholder="ISO datetime" /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Period End</label><input className="form-input mono" value={datasetForm.period_end} onChange={e => setDatasetForm(p => ({ ...p, period_end: e.target.value }))} placeholder="ISO datetime" /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Retention Policy</label><input className="form-input" value={datasetForm.retention_policy} onChange={e => setDatasetForm(p => ({ ...p, retention_policy: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Access Scope (csv)</label><input className="form-input" value={datasetForm.access_scope} onChange={e => setDatasetForm(p => ({ ...p, access_scope: e.target.value }))} /></div>
              </div>
              <JsonField label="Manifest" value={datasetForm.manifest} onChange={v => setDatasetForm(p => ({ ...p, manifest: v }))} />
              <JsonField label="Sources" value={datasetForm.sources} onChange={v => setDatasetForm(p => ({ ...p, sources: v }))} />
              <button className="btn btn-primary" onClick={submitDataset} disabled={busy || !datasetForm.version}>{busy ? 'Submitting…' : 'Create Dataset'}</button>
            </div>

            <div className="card" style={{ padding: 20 }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: 14, color: 'var(--accent-copper-light)' }}>🏷️ New Label</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <div className="form-group" style={{ margin: 0 }}><label>Subject Type</label><input className="form-input" value={labelForm.subject_type} onChange={e => setLabelForm(p => ({ ...p, subject_type: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Subject ID</label><input className="form-input mono" value={labelForm.subject_id} onChange={e => setLabelForm(p => ({ ...p, subject_id: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Task</label><input className="form-input" value={labelForm.task} onChange={e => setLabelForm(p => ({ ...p, task: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Target Class</label><input className="form-input" value={labelForm.target_class} onChange={e => setLabelForm(p => ({ ...p, target_class: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Group Key</label><input className="form-input" value={labelForm.group_key} onChange={e => setLabelForm(p => ({ ...p, group_key: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>Label</label>
                  <select className="form-select" value={labelForm.label} onChange={e => setLabelForm(p => ({ ...p, label: e.target.value }))}>
                    {['positive', 'negative', 'unknown', 'disputed', 'censored'].map(l => <option key={l} value={l}>{l}</option>)}
                  </select>
                </div>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>Maturity</label>
                  <select className="form-select" value={labelForm.maturity} onChange={e => setLabelForm(p => ({ ...p, maturity: e.target.value }))}>
                    {['immature', 'mature', 'censored'].map(l => <option key={l} value={l}>{l}</option>)}
                  </select>
                </div>
                <div className="form-group" style={{ margin: 0 }}><label>Observation Start</label><input className="form-input mono" value={labelForm.observation_window_start} onChange={e => setLabelForm(p => ({ ...p, observation_window_start: e.target.value }))} placeholder="ISO datetime" /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Observation End</label><input className="form-input mono" value={labelForm.observation_window_end} onChange={e => setLabelForm(p => ({ ...p, observation_window_end: e.target.value }))} placeholder="ISO datetime" /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Known At</label><input className="form-input mono" value={labelForm.known_at} onChange={e => setLabelForm(p => ({ ...p, known_at: e.target.value }))} placeholder="ISO datetime" /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Source Name</label><input className="form-input" value={labelForm.source_name} onChange={e => setLabelForm(p => ({ ...p, source_name: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>License Name</label><input className="form-input" value={labelForm.license_name} onChange={e => setLabelForm(p => ({ ...p, license_name: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Source Confidence (0-1)</label><input className="form-input" type="number" step="0.01" value={labelForm.source_confidence} onChange={e => setLabelForm(p => ({ ...p, source_confidence: e.target.value }))} /></div>
                <div className="form-group" style={{ margin: 0 }}><label>Maturation Days</label><input className="form-input" type="number" value={labelForm.maturation_days} onChange={e => setLabelForm(p => ({ ...p, maturation_days: e.target.value }))} /></div>
              </div>
              <div className="form-group"><label>Rationale</label><textarea className="form-textarea" rows={2} value={labelForm.rationale} onChange={e => setLabelForm(p => ({ ...p, rationale: e.target.value }))} /></div>
              <JsonField label="Evidence Snapshot IDs (array)" value={labelForm.evidence_snapshot_ids} onChange={v => setLabelForm(p => ({ ...p, evidence_snapshot_ids: v }))} rows={2} />
              <button className="btn btn-primary" onClick={submitLabel} disabled={busy || !labelForm.subject_id || !labelForm.task}>{busy ? 'Submitting…' : 'Record Label'}</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
