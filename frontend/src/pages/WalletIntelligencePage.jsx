import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useCase } from '../context/CaseContext';
import api from '../lib/api';
import { items, errorMessage, formatAmount } from '../lib/contracts';

export default function WalletIntelligencePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { activeCaseId, activeCase } = useCase();
  const [address, setAddress] = useState(searchParams.get('address') || '');
  const [chain, setChain] = useState(searchParams.get('chain') || '');
  const [transfers, setTransfers] = useState([]);
  const [risk, setRisk] = useState(null);
  const [state, setState] = useState('idle');
  const [message, setMessage] = useState('');

  const inspectWallet = async (nextAddress = address, nextChain = chain) => {
    if (!activeCaseId || !nextAddress || !nextChain) {
      setMessage('Select an active case and provide both a wallet address and network.');
      return;
    }
    setState('loading'); setMessage('');
    try {
      await api.post('/api/v1/wallets/validate', { address: nextAddress, chain: nextChain });
      const [txResponse, riskResponse] = await Promise.all([
        api.get(`/api/v1/cases/${activeCaseId}/transactions`, { params: { temporal_view: 'all', chain: nextChain } }),
        api.get(`/api/v1/cases/${activeCaseId}/risk`).catch(() => ({ data: null })),
      ]);
      const all = items(txResponse.data, 'transactions');
      setTransfers(all.filter(tx => tx.source_address === nextAddress || tx.target_address === nextAddress));
      setRisk(riskResponse.data);
      setState(all.length ? 'ready' : 'empty');
      setSearchParams({ address: nextAddress, chain: nextChain });
    } catch (error) {
      setTransfers([]); setRisk(null); setState('error'); setMessage(errorMessage(error, 'Wallet evidence is unavailable.'));
    }
  };

  useEffect(() => {
    const initialAddress = searchParams.get('address');
    const initialChain = searchParams.get('chain');
    if (initialAddress && initialChain && activeCaseId) inspectWallet(initialAddress, initialChain);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCaseId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div className="page-header" style={{ margin: 0 }}><div><h1>🔎 Wallet & Contract Intelligence Dossier</h1><p className="subtitle">Case-scoped on-chain evidence and independently labeled risk outputs</p></div></div>
      <div className="card" style={{ padding: '16px 20px' }}>
        <form onSubmit={event => { event.preventDefault(); inspectWallet(); }} style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <input className="form-input mono" value={address} onChange={e => setAddress(e.target.value)} placeholder="Wallet address" style={{ flex: 1, minWidth: 240 }} />
          <select className="form-select" value={chain} onChange={e => setChain(e.target.value)} style={{ width: 170 }}>
            <option value="">Select network</option><option value="BTC">Bitcoin</option><option value="ETH">Ethereum</option><option value="TRON">TRON</option><option value="BSC">BSC</option><option value="POLYGON">Polygon</option>
          </select>
          <button className="btn btn-primary" disabled={state === 'loading'}>{state === 'loading' ? 'Loading…' : 'Inspect Wallet'}</button>
        </form>
      </div>
      {message && <div className="card" style={{ padding: 14, color: 'var(--accent-amber)' }}>{message}</div>}
      {state === 'empty' && <div className="card" style={{ padding: 30, textAlign: 'center' }}>No case-scoped transfers were found for this wallet. This is not a claim that the wallet has no history.</div>}
      {transfers.length > 0 && (
        <div className="panel" style={{ margin: 0 }}>
          <div className="panel-header"><h3>Validated Transfers ({transfers.length})</h3></div>
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead><tr><th>Hash</th><th>Direction</th><th>Counterparty</th><th>Amount</th><th>Event time</th><th>Finality</th></tr></thead>
              <tbody>
                {transfers.map(tx => {
                  const outgoing = tx.source_address === address;
                  return (
                    <tr key={tx.id}>
                      <td className="mono">{tx.tx_hash}</td>
                      <td>{outgoing ? 'Outgoing' : 'Incoming'}</td>
                      <td className="mono">{outgoing ? tx.target_address : tx.source_address}</td>
                      <td className="mono">{formatAmount(tx.amount, tx.asset)}</td>
                      <td>{tx.event_time || 'Unknown'}</td>
                      <td>{tx.finality_state || 'Unknown'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {risk && (
        <div className="intel-panel">
          <div className="intel-panel-header"><h4>Case Risk Context</h4></div>
          <div className="intel-panel-body">
            <div className="risk-gauge"><div className="gauge-value">{risk.score ?? '—'}</div><div className="gauge-label">{risk.tier || 'unknown'}</div></div>
            <p style={{ color: 'var(--text-secondary)', marginTop: 12 }}>{risk.assessment_state === 'assessed' ? 'Deterministic case-level decision support; not a wallet-owner verdict or ML probability.' : 'Risk has not been assessed for the selected trace.'}</p>
          </div>
        </div>
      )}
      {!activeCase && <div className="card" style={{ padding: 20 }}>No active case is available.</div>}
    </div>
  );
}
