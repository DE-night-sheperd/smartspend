import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function NavBar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) return null;

  return (
    <nav className="navbar">
      <span className="brand">SmartSpend</span>
      <NavLink to="/" end>
        Dashboard
      </NavLink>
      <NavLink to="/receipts">Receipts</NavLink>
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
