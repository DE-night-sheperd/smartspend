import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/** Inverse of ProtectedRoute for the public auth surfaces (landing, login,
 * register). A signed-in user has no business on these pages — they are sent
 * straight to the dashboard, so signup/login CTAs never reach someone who is
 * already in.
 *
 * Guest sessions are the exception: they are signed in, but their whole point
 * is to be upgradable — a guest must still reach /register to claim the
 * session with an email + password, and the landing page to see both paths.
 * Only fully signed-in (non-guest) users get bounced. Renders nothing while
 * the session check is in flight to avoid flashing auth forms at returning
 * users. */
export default function GuestRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) return null;
  if (user && !user.is_guest) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}
