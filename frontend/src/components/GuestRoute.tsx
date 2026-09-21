import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/** Inverse of ProtectedRoute for the public auth surfaces (landing, login,
 * register). A signed-in user has no business on these pages — they are sent
 * straight to the dashboard, so signup/login CTAs never reach someone who is
 * already in. Renders nothing while the session check is in flight to avoid
 * flashing auth forms at returning users. */
export default function GuestRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) return null;
  if (user) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}
