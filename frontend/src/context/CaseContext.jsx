import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import api from '../lib/api';
import { items, errorMessage, normalizeGraph } from '../lib/contracts';
import { useAuth } from './AuthContext';

const CaseContext = createContext();

export function CaseProvider({ children }) {
  const [activeCaseId, setActiveCaseId] = useState('');
  const [activeCase, setActiveCase] = useState(null);
  const [activeGraph, setActiveGraph] = useState({ nodes: [], edges: [] });
  const [casesList, setCasesList] = useState([]);
  const [loadingCase, setLoadingCase] = useState(false);
  const [caseError, setCaseError] = useState('');
  const [graphState, setGraphState] = useState('empty');
  // Default to "all evidence": Money Trail doesn't expose this filter itself, so
  // whatever default is used here is what appears the instant a trace completes.
  // "post_report" silently hides everything when a case's report timestamp (often
  // "now", for quick/manual traces) postdates the real transfers just discovered.
  const [graphFilters, setGraphFilters] = useState({ temporal_view: 'all', boundary: 'exclusive', include_context: false });
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const { user } = useAuth();
  const requestSequence = useRef(0);

  const loadCaseData = useCallback(async (cId) => {
    if (!user || !cId) {
      setActiveCase(null);
      setActiveGraph(normalizeGraph(null));
      setGraphState('empty');
      return;
    }
    const sequence = ++requestSequence.current;
    setLoadingCase(true);
    setCaseError('');
    try {
      const cRes = await api.get(`/api/v1/cases/${cId}`);
      if (sequence !== requestSequence.current) return;
      setActiveCase(cRes.data);
      try {
        const effective = cRes.data.primary_report_event_id
          ? { ...graphFilters, report_event_id: cRes.data.primary_report_event_id }
          : { temporal_view: 'all' };
        const gRes = await api.get(`/api/v1/cases/${cId}/graph`, { params: effective });
        if (sequence !== requestSequence.current) return;
        const graph = normalizeGraph(gRes.data);
        setActiveGraph(graph);
        setGraphState(graph.edges.length ? graph.coverage?.state || 'complete' : graph.coverage?.state || 'empty');
      } catch (graphError) {
        if (sequence !== requestSequence.current) return;
        setActiveGraph(normalizeGraph(null));
        setGraphState('error');
        setCaseError(errorMessage(graphError, 'Graph evidence is unavailable.'));
      }
    } catch (error) {
      if (sequence !== requestSequence.current) return;
      setActiveCase(null);
      setActiveGraph(normalizeGraph(null));
      setCaseError(errorMessage(error, 'Case data is unavailable.'));
    } finally {
      if (sequence === requestSequence.current) setLoadingCase(false);
    }
  }, [user, graphFilters]);

  useEffect(() => {
    if (activeCaseId) {
      loadCaseData(activeCaseId);
    } else {
      setActiveCase(null);
      setActiveGraph(normalizeGraph(null));
      setGraphState('empty');
    }
  }, [activeCaseId, loadCaseData]);

  const fetchCases = useCallback(async () => {
    if (!user) { setCasesList([]); return; }
    try {
      const res = await api.get('/api/v1/cases', { params: { page_size: 100 } });
      const list = items(res.data, 'cases');
      setCasesList(list);
    } catch (error) {
      setCaseError(errorMessage(error, 'Cases are unavailable.'));
    }
  }, [user]);

  useEffect(() => {
    if (!user) {
      setCasesList([]); setActiveCase(null); setActiveGraph(normalizeGraph(null));
      return;
    }
    fetchCases();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const selectCase = useCallback((cId) => setActiveCaseId(cId), []);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <CaseContext.Provider value={{
      activeCaseId,
      activeCase,
      activeGraph,
      casesList,
      loadingCase,
      caseError,
      graphState,
      graphFilters,
      setGraphFilters,
      selectCase,
      reloadActiveCase: (overrideId) => loadCaseData(overrideId || activeCaseId),
      reloadCasesList: fetchCases,
      isCommandPaletteOpen,
      setIsCommandPaletteOpen,
    }}>
      {children}
    </CaseContext.Provider>
  );
}

export function useCase() {
  return useContext(CaseContext);
}
