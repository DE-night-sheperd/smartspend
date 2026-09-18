import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/** Gate for every authenticated route. Signed-out visitors are bounced to
 * /login with ?returnTo=<where they were going>, so sign-in drops them
 * right back where they intended to be. */
export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <div className="page">Loading…</div>;
  if (!user) {
    const target = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?returnTo=${encodeURIComponent(target)}`} replace />;
  }
  return <>{children}</>;
}
