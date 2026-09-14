import { useState } from 'react';
import Sidebar from './Sidebar';
import TopCommandBar from './TopCommandBar';
import CommandPalette from './CommandPalette';

export default function AppShell({ children }) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  return (
    <div className={`os-layout ${isCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar isCollapsed={isCollapsed} setIsCollapsed={setIsCollapsed} isMobileOpen={isMobileOpen} setIsMobileOpen={setIsMobileOpen} />
      <div className="os-main-stage">
        <TopCommandBar onToggleMobile={() => setIsMobileOpen(!isMobileOpen)} />
        <main className="os-viewport-content">{children}</main>
      </div>
      <CommandPalette />
    </div>
  );
}
