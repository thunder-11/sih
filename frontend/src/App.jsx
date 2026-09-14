import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { CaseProvider } from './context/CaseContext';
import AppShell from './components/AppShell';

import LoginPage from './pages/LoginPage';
import OverviewPage from './pages/OverviewPage';
import CasesPage from './pages/CasesPage';
import NewCasePage from './pages/NewCasePage';
import CaseWorkspacePage from './pages/CaseWorkspacePage';
import TransactionGraphPage from './pages/TransactionGraphPage';
import WalletIntelligencePage from './pages/WalletIntelligencePage';
import EntitiesPage from './pages/EntitiesPage';
import CrossChainPage from './pages/CrossChainPage';
import AlertsPage from './pages/AlertsPage';
import AnalyticsPage from './pages/AnalyticsPage';
import ReportsPage from './pages/ReportsPage';
import SystemStatusPage from './pages/SystemStatusPage';
import SettingsPage from './pages/SettingsPage';
import MLOpsPage from './pages/MLOpsPage';

function ProtectedRoute({ children, roles }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="loading-overlay"><div className="spinner"></div></div>;
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <AppShell><div className="card" style={{ padding: 24 }}>Access restricted to: {roles.join(', ')}.</div></AppShell>;
  return <AppShell>{children}</AppShell>;
}

function AppRoutes() {
  const { user } = useAuth();

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />

      <Route path="/" element={<ProtectedRoute><OverviewPage /></ProtectedRoute>} />
      <Route path="/cases" element={<ProtectedRoute><CasesPage /></ProtectedRoute>} />
      <Route path="/new-case" element={<ProtectedRoute><NewCasePage /></ProtectedRoute>} />
      <Route path="/money-trail" element={<ProtectedRoute><CaseWorkspacePage /></ProtectedRoute>} />
      <Route path="/case/:caseId" element={<ProtectedRoute><CaseWorkspacePage /></ProtectedRoute>} />
      <Route path="/graph" element={<ProtectedRoute><TransactionGraphPage /></ProtectedRoute>} />
      <Route path="/wallets" element={<ProtectedRoute><WalletIntelligencePage /></ProtectedRoute>} />
      <Route path="/entities" element={<ProtectedRoute><EntitiesPage /></ProtectedRoute>} />
      <Route path="/cross-chain" element={<ProtectedRoute><CrossChainPage /></ProtectedRoute>} />
      <Route path="/alerts" element={<ProtectedRoute><AlertsPage /></ProtectedRoute>} />
      <Route path="/analytics" element={<ProtectedRoute><AnalyticsPage /></ProtectedRoute>} />
      <Route path="/reports" element={<ProtectedRoute><ReportsPage /></ProtectedRoute>} />
      <Route path="/system-status" element={<ProtectedRoute><SystemStatusPage /></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
      <Route path="/ml-ops" element={<ProtectedRoute roles={['admin']}><MLOpsPage /></ProtectedRoute>} />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <CaseProvider>
          <AppRoutes />
        </CaseProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
