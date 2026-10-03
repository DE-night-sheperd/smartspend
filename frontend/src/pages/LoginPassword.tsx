import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../context/AuthContext';
import { warmUpApi } from '../api/client';
import { playSound } from '../lib/sounds';

/** The PRIMARY sign-in surface: email + password, no codes. Someone who
 * prefers a one-time code can switch to /login-code, and anyone can walk in
 * as a guest without an account at all. */
export default function LoginPassword() {
  const { login, loginAsGuest } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnTo = searchParams.get('returnTo') ?? '/dashboard';
  // Registration hands over the address it just used so nobody retypes it.
  const [email, setEmail] = useState(() => searchParams.get('email') ?? '');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [guestBusy, setGuestBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    warmUpApi(); // the sign-in click is also a wake trigger
    try {
      await login(email, password);
      playSound('success');
      navigate(returnTo, { replace: true });
    } catch (err: unknown) {
      playSound('error');
      // Prefer the API's own advice (e.g. "this account has no password
      // yet — use Forgot password?") over a generic guess.
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Incorrect email or password.');
      setSubmitting(false);
    }
  }

  async function handleGuest() {
    setError(null);
    setGuestBusy(true);
    warmUpApi();
    try {
      await loginAsGuest();
      playSound('beep');
      navigate('/dashboard', { replace: true });
    } catch (err: unknown) {
      playSound('error');
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Could not start a guest session. Try again.');
      setGuestBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <motion.form
        className="auth-card"
        onSubmit={handleSubmit}
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <span className="auth-brand">R:</span>
        <h1>Log in to SmartSpend</h1>
        <p className="auth-lede">Your email and password — no code required.</p>

        <label>
          Email
          <input
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        {error && <p className="form-error">{error}</p>}

        <button type="submit" disabled={submitting}>
          {submitting ? 'Logging in…' : 'Log in'}
        </button>

        <p className="auth-switch">
          <Link to="/login-code?mode=forgot">Forgot your password?</Link>
        </p>

        <div className="auth-divider" aria-hidden="true">
          <span>or</span>
        </div>

        <button type="button" className="button-secondary" onClick={() => void handleGuest()} disabled={guestBusy}>
          {guestBusy ? 'Starting…' : 'Continue as guest →'}
        </button>

        <p className="auth-switch">
          New here? <Link to="/register">Create an account</Link>
          {' · '}
          <Link to="/login-code">Use a one-time code</Link>
        </p>
      </motion.form>
    </div>
  );
}
