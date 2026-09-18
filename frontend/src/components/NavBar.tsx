import { useRef, useState, useLayoutEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../context/AuthContext';

const TABS = [
  { to: '/', label: 'Dashboard' },
  { to: '/receipts', label: 'Receipts' },
  { to: '/settings', label: 'Settings' },
];

export default function NavBar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const linkRefs = useRef<Record<string, HTMLAnchorElement | null>>({});
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const active = TABS.find((t) => (t.to === '/' ? location.pathname === '/' : location.pathname.startsWith(t.to)));
    const el = active ? linkRefs.current[active.to] : null;
    if (el) {
      setIndicator({ left: el.offsetLeft, width: el.offsetWidth });
    }
  }, [location.pathname]);

  if (!user) return null;

  return (
    <nav className="navbar">
      <span className="brand">
        <span className="brand-mark">R:</span>
        SmartSpend
      </span>
      <div className="nav-links">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === '/'}
            ref={(el) => {
              linkRefs.current[tab.to] = el;
            }}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            {tab.label}
          </NavLink>
        ))}
        {indicator && (
          <motion.div
            className="nav-underline"
            animate={{ left: indicator.left, width: indicator.width }}
            transition={{ type: 'spring', stiffness: 500, damping: 40 }}
          />
        )}
      </div>
      <div className="nav-spacer" />
      <button
        className="link-button"
        onClick={() => {
          logout();
          navigate('/login');
        }}
      >
        Log out
      </button>
    </nav>
  );
}
