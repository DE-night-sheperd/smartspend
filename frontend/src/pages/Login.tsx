import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { requestLoginCode } from '../api/endpoints';
import { useAuth } from '../context/AuthContext';

type Step = 'email' | 'code';

export default function Login() {
  const { loginWithCode } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);

  async function handleRequestCode(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await requestLoginCode(email);
      setDevCode(result.dev_code ?? null);
      setStep('code');
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Could not send a code to that email. Try again.';
      setError(detail);
    } finally {
      setBusy(false);
    }
  }

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await loginWithCode(email, code);
      navigate('/', { replace: true });
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'That code did not work. Request a new one if it expired.';
      setError(detail);
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <motion.div
        key={step}
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
        style={{ width: '100%', maxWidth: 380 }}
      >
        {step === 'email' ? (
          <form className="auth-card" onSubmit={handleRequestCode}>
            <span className="auth-brand">R:</span>
            <h1>Log in to SmartSpend</h1>
            <p className="auth-lede">We email you a one-time code — no password to remember.</p>

            <label>
              Email
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
              />
            </label>

            {error && <p className="form-error">{error}</p>}

            <button type="submit" disabled={busy}>
              {busy ? 'Sending code…' : 'Email me a login code'}
            </button>

            <p className="auth-switch">
              New here? <Link to="/register">Create an account</Link>
              {' · '}
              <Link to="/login-password">Use a password</Link>
            </p>
          </form>
        ) : (
          <form className="auth-card" onSubmit={handleVerify}>
            <h1>Check your inbox</h1>
            <p className="auth-lede">
              We sent a 6-digit code to <strong>{email}</strong>. It expires in 10 minutes.
            </p>

            <label>
              Login code
              <input
                className="code-input"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                pattern="\d{6}"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                placeholder="······"
                required
              />
            </label>

            {error && <p className="form-error">{error}</p>}

            <button type="submit" disabled={busy || code.length !== 6}>
              {busy ? 'Verifying…' : 'Verify & log in'}
            </button>

            {devCode && (
              <p className="dev-code-hint">
                Dev mode: your code is <strong>{devCode}</strong>
              </p>
            )}

            <p className="auth-switch">
              Wrong address?{' '}
              <button type="button" className="linklike" onClick={() => setStep('email')}>
                Start over
              </button>
            </p>
          </form>
        )}
      </motion.div>
    </div>
  );
}
