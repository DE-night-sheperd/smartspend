import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { register } from '../api/endpoints';
import { useAuth } from '../context/AuthContext';
import { warmUpApi } from '../api/client';
import { playSound } from '../lib/sounds';

export default function Register() {
  const { login, user, claimAccount, loginAsGuest } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnTo = searchParams.get('returnTo') ?? '/dashboard';
  // A guest session signs up differently: the SAME account is upgraded in
  // place (email + password attached) so nothing they scanned is lost.
  const isClaiming = Boolean(user?.is_guest);
  const [form, setForm] = useState({
    email: '',
    first_name: '',
    last_name: '',
    password: '',
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [guestBusy, setGuestBusy] = useState(false);

  function update<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleGuest() {
    setError(null);
    setGuestBusy(true);
    warmUpApi();
    try {
      await loginAsGuest();
      playSound('beep');
      navigate(returnTo, { replace: true });
    } catch (err: unknown) {
      playSound('error');
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Could not start a guest session. Try again.');
      setGuestBusy(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    warmUpApi(); // the sign-up click is also a wake trigger
    try {
      if (isClaiming) {
        // Guest → account: same user row, receipts intact. Tokens already
        // exist, so there is no second login step.
        await claimAccount(form);
        playSound('success');
        navigate(returnTo, { replace: true });
        return;
      }
      await register(form);
      try {
        await login(form.email, form.password);
        playSound('success');
        navigate(returnTo, { replace: true });
        return;
      } catch {
        // The account EXISTS now — auto-login may still have raced a waking
        // server, but the user must never be stranded at "signup failed".
        // Land them on the login page pre-filled, where a one-time code
        // always works.
        playSound('beep');
        navigate(
          `/login?returnTo=${encodeURIComponent(returnTo)}&email=${encodeURIComponent(form.email)}`,
          { replace: true },
        );
        return;
      }
    } catch (err: unknown) {
      playSound('error');
      const status = (err as { response?: { status?: number } })?.response?.status;
      const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data;
      const detail = data?.detail;
      if (typeof detail === 'string' && detail) {
        setError(detail);
      } else if (status === 502 || status === 503 || status === 504 || err instanceof TypeError) {
        // Gateway error or the network itself failed — a transient hiccup,
        // never the user's details. Keep the language ordinary.
        setError('Taking longer than usual — one more tap should do it.');
      } else if (data && typeof data === 'object') {
        // DRF validation errors arrive as {field: [messages]} — show them
        // as the readable sentences they are (e.g. a taken email address).
        const messages = Object.entries(data).flatMap(([, value]) =>
          Array.isArray(value) ? value.map(String) : [String(value)],
        );
        const emailTaken = messages.some((m) => m.toLowerCase().includes('already exists'));
        setError(
          emailTaken
            ? 'That email is already registered. Try logging in instead — or use a one-time code.'
            : messages.join(' '),
        );
      } else if (status) {
        setError(`Could not create your account (server error ${status}). Please try again.`);
      } else {
        setError('Could not create your account. Check your details and try again.');
      }
      setSubmitting(false);
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
        <h1>{isClaiming ? 'Save your session' : 'Create your account'}</h1>
        <p className="auth-lede">
          {isClaiming
            ? 'Add an email and password to keep everything you scanned as a guest.'
            : 'Snap receipts, tame impulse buys, and close every month in the green.'}
        </p>

        <div className="form-row">
          <label>
            First name
            <input value={form.first_name} onChange={(e) => update('first_name', e.target.value)} required />
          </label>
          <label>
            Last name
            <input value={form.last_name} onChange={(e) => update('last_name', e.target.value)} required />
          </label>
        </div>
        <label>
          Email
          <input type="email" value={form.email} onChange={(e) => update('email', e.target.value)} required />
        </label>
        <label>
          Password
          <input
            type="password"
            minLength={8}
            value={form.password}
            onChange={(e) => update('password', e.target.value)}
            required
          />
        </label>
        {error && (
          <p className="form-error">
            {error}
            {error.toLowerCase().includes('already registered') && (
              <>
                {' '}
                <Link to="/login">Go to log in</Link>
              </>
            )}
          </p>
        )}
        <button type="submit" disabled={submitting}>
          {submitting
            ? isClaiming
              ? 'Saving…'
              : 'Creating account…'
            : isClaiming
              ? 'Create my account'
              : 'Sign up'}
        </button>
        <p className="auth-switch">
          {isClaiming ? (
            <>
              Just looking around? <Link to="/dashboard">Back to the app</Link>
            </>
          ) : (
            <>
              Already have an account? <Link to="/login">Log in</Link>
            </>
          )}
        </p>
        {!isClaiming && (
          <>
            <div className="auth-divider" aria-hidden="true">
              <span>or</span>
            </div>
            <button
              type="button"
              className="button-secondary"
              onClick={() => void handleGuest()}
              disabled={guestBusy}
            >
              {guestBusy ? 'Starting…' : 'Continue as guest →'}
            </button>
          </>
        )}
      </motion.form>
    </div>
  );
}
