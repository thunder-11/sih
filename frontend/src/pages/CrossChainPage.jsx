import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCase } from '../context/CaseContext';
import { formatAmount } from '../lib/contracts';

export default function CrossChainPage() {
  const { activeCaseId, activeGraph, graphState } = useCase();
  const navigate = useNavigate();
  const events = useMemo(() => {
    const nodes = new Map([...(activeGraph?.nodes || []), ...(activeGraph?.context_nodes || [])].map(node => [node.id, node]));
    return [...(activeGraph?.edges || []), ...(activeGraph?.context_edges || [])].filter(edge => {
      const source = nodes.get(edge.source); const target = nodes.get(edge.target);
      return edge.is_bridge_tx || edge.edge_type === 'cross_chain' || (source?.chain && target?.chain && source.chain !== target.chain);
    }).map(edge => ({ ...edge, sourceChain: nodes.get(edge.source)?.chain || edge.chain, targetChain: nodes.get(edge.target)?.chain || edge.target_chain }));
  }, [activeGraph]);

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
    <div className="page-header" style={{ margin: 0 }}><div><h1>⚡ Cross-Chain Intelligence & Bridge Lanes</h1><p className="subtitle">Evidence-backed continuity for the selected case</p></div></div>
    {['partial', 'unavailable'].includes(graphState) && <div className="card" style={{ padding: 14 }}>Coverage is {graphState}; missing events are not treated as zero activity.</div>}
    <div className="panel" style={{ margin: 0 }}><div className="panel-header"><h3>Supported Cross-Chain Events</h3></div><div style={{ overflowX: 'auto' }}>
      <table className="data-table"><thead><tr><th>Transaction</th><th>Source</th><th>Destination</th><th>Amount</th><th>Time</th><th>Continuity</th></tr></thead><tbody>
        {events.map(event => <tr key={event.id}><td className="mono">{event.tx_hash}</td><td>{event.sourceChain || 'Unknown'}</td><td>{event.targetChain || 'Unknown'}</td><td>{formatAmount(event.amount, event.asset || event.token)}</td><td>{event.event_time || event.timestamp || 'Unknown'}</td><td>{event.continuity || 'Evidence attached'}</td></tr>)}
      </tbody></table>
      {!events.length && <div style={{ padding: 30, textAlign: 'center' }}>No supported cross-chain continuity is present in the selected graph. No demo event is substituted.</div>}
    </div></div>
    {activeCaseId && <button className="btn btn-outline" onClick={() => navigate(`/graph?case=${activeCaseId}`)}>Inspect selected graph →</button>}
  </div>;
}
