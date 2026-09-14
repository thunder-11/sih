import { NavLink, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../context/AuthContext';

const navListV = { hidden: {}, visible: { transition: { staggerChildren: 0.045 } } };
const navItemV = { hidden: { opacity: 0, x: -12 }, visible: { opacity: 1, x: 0, transition: { duration: 0.3 } } };

const NAV_SECTIONS = [
  {
    title: 'INVESTIGATE',
    items: [
      { label: 'Overview', path: '/', icon: '📊', end: true },
      { label: 'Cases', path: '/cases', icon: '📁' },
      { label: 'New Case', path: '/new-case', icon: '➕' },
      { label: 'Money Trail', path: '/money-trail', icon: '💸', badge: 'HERO' },
      { label: 'Transaction Graph', path: '/graph', icon: '🕸️' },
      { label: 'Wallet Intelligence', path: '/wallets', icon: '🔎' },
    ],
  },
  {
    title: 'INTELLIGENCE',
    items: [
      { label: 'Entities / VASP', path: '/entities', icon: '🏦' },
      { label: 'Cross-Chain', path: '/cross-chain', icon: '⚡' },
      { label: 'Risk & Alerts', path: '/alerts', icon: '🚨' },
      { label: 'Analytics', path: '/analytics', icon: '📈' },
    ],
  },
  {
    title: 'OUTPUT',
    items: [
      { label: 'Reports', path: '/reports', icon: '📑' },
    ],
  },
  {
    title: 'SYSTEM',
    items: [
      { label: 'System Status', path: '/system-status', icon: '🟢' },
      { label: 'Settings', path: '/settings', icon: '⚙️' },
      { label: 'ML Operations', path: '/ml-ops', icon: '🧠', roles: ['admin'] },
    ],
  },
];

export default function Sidebar({ isCollapsed, setIsCollapsed, isMobileOpen, setIsMobileOpen }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <>
      {isMobileOpen && (
        <div
          className="mobile-backdrop"
          onClick={() => setIsMobileOpen(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', zIndex: 998, display: 'none' }}
        />
      )}

      <aside className={`app-sidebar ${isCollapsed ? 'collapsed' : ''} ${isMobileOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-brand-header">
          <div className="brand-logo-icon">🛡️</div>
          {!isCollapsed && (
            <div className="brand-text-block">
              <div className="brand-name">ARGUS</div>
              <div className="brand-tag">CRYPTO FRAUD ATTRIBUTION</div>
            </div>
          )}
          <button className="sidebar-collapse-btn" onClick={() => setIsCollapsed(!isCollapsed)} title={isCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}>
            {isCollapsed ? '▶' : '◀'}
          </button>
        </div>

        <div className="sidebar-nav-scroll">
          {NAV_SECTIONS.map((sec, idx) => {
            const visibleItems = sec.items.filter(item => !item.roles || item.roles.includes(user?.role));
            if (!visibleItems.length) return null;
            return (
              <div key={idx} className="sidebar-section">
                {!isCollapsed && <div className="sidebar-section-title">{sec.title}</div>}
                <motion.ul className="sidebar-nav-list" variants={navListV} initial="hidden" animate="visible">
                  {visibleItems.map((item, itemIdx) => (
                    <motion.li key={itemIdx} variants={navItemV}>
                      <NavLink
                        to={item.path}
                        end={item.end}
                        className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
                        onClick={() => setIsMobileOpen(false)}
                        title={isCollapsed ? item.label : undefined}
                      >
                        <span className="nav-icon">{item.icon}</span>
                        {!isCollapsed && <span className="nav-label">{item.label}</span>}
                        {!isCollapsed && item.badge && <span className="nav-badge-tag">{item.badge}</span>}
                      </NavLink>
                    </motion.li>
                  ))}
                </motion.ul>
              </div>
            );
          })}
        </div>

        <div className="sidebar-footer">
          <div className="user-mini-card">
            <div className="user-avatar-badge">{user?.full_name ? user.full_name.charAt(0) : 'O'}</div>
            {!isCollapsed && (
              <div className="user-info-block">
                <div className="user-name">{user?.full_name || 'Officer'}</div>
                <div className="user-role-tag">{user?.role?.toUpperCase() || 'INVESTIGATOR'}</div>
              </div>
            )}
          </div>
          <button className="sidebar-logout-btn" onClick={handleLogout} title="Logout Session">
            ⏻ {!isCollapsed && <span>Logout</span>}
          </button>
        </div>
      </aside>
    </>
  );
}
