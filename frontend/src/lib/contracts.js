export function items(payload, legacyKey) {
  if (!payload || typeof payload !== 'object') return [];
  if (Array.isArray(payload.items)) return payload.items;
  return Array.isArray(payload[legacyKey]) ? payload[legacyKey] : [];
}

export function errorMessage(error, fallback = 'The request could not be completed.') {
  const body = error?.response?.data;
  if (typeof body?.error?.message === 'string') return body.error.message;
  if (typeof body?.detail === 'string') return body.detail;
  if (Array.isArray(body?.detail)) return body.detail.map(item => item.msg).filter(Boolean).join('; ') || fallback;
  if (typeof body?.message === 'string') return body.message;
  return error?.message || fallback;
}

export function normalizeGraph(payload) {
  const rawEdges = payload?.edges || [];
  // The backend annotates each edge with the hop depth it was discovered at,
  // but not the nodes themselves — derive each node's hop as the shallowest
  // depth any edge reaches it at (roots, never a target, default to hop 0).
  const hopByNodeId = new Map();
  rawEdges.forEach(edge => {
    const hop = edge.hop ?? 0;
    const existing = hopByNodeId.get(edge.target);
    if (existing === undefined || hop < existing) hopByNodeId.set(edge.target, hop);
  });
  const nodes = (payload?.nodes || []).map(node => ({
    ...node,
    address: node.address || node.id,
    label: node.label || node.address || node.id,
    node_type: node.node_type || 'WALLET',
    hop: node.hop ?? hopByNodeId.get(node.id) ?? 0,
  }));
  const edges = rawEdges.map(edge => ({
    ...edge,
    token: edge.token || edge.asset || null,
    timestamp: edge.timestamp || edge.event_time || null,
    amount: edge.amount ?? null,
  }));
  return {
    ...(payload || {}),
    nodes,
    edges,
    context_nodes: payload?.context_nodes || [],
    context_edges: payload?.context_edges || [],
    coverage: payload?.coverage || { state: 'unknown' },
  };
}

export function formatAmount(value, asset) {
  if (value === null || value === undefined || value === '') return 'Unknown';
  return `${String(value)}${asset ? ` ${asset}` : ''}`;
}

export function downloadBase64Pdf(payload, fallbackName) {
  const bytes = Uint8Array.from(atob(payload.pdf_base64), c => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = payload.pdf_filename || fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
