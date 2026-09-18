import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { requestLoginCode, requestSmsCode } from '../api/endpoints';
import { useAuth } from '../context/AuthContext';

type Step = 'input' | 'code';
type Channel = 'email' | 'sms';

export default function Login() {
  const { loginWithCode } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnTo = searchParams.get('returnTo') ?? '/dashboard';
  const [channel, setChannel] = useState<Channel>('email');
  const [step, setStep] = useState<Step>('input');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);

  const destination = channel === 'email' ? email : phone;

  async function handleRequestCode(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = channel === 'email' ? await requestLoginCode(email) : await requestSmsCode(phone);
      setDevCode(result.dev_code ?? null);
      setStep('code');
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string; phone?: string[]; email?: string[] } } })?.response?.data;
      setError(
        detail?.detail ??
          detail?.phone?.[0] ??
          detail?.email?.[0] ??
          'Could not send a code. Check the details and try again.',
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await loginWithCode(channel, destination, code);
      // Brand-new accounts go straight to Settings to set their budget.
      navigate(created ? '/settings' : returnTo, { replace: true });
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'That code did not work. Request a new one if it expired.';
      setError(detail);
      setBusy(false);
    }
  }

  function switchChannel(next: Channel) {
    if (next === channel) return;
    setChannel(next);
    setError(null);
    setStep('input');
  }

  return (
    <div className="auth-page">
      <motion.div
        key={`${channel}-${step}`}
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
        style={{ width: '100%', maxWidth: 380 }}
      >
        {step === 'input' ? (
          <form className="auth-card" onSubmit={handleRequestCode}>
            <span className="auth-brand">R:</span>
            <h1>Log in to SmartSpend</h1>
            <p className="auth-lede">One-time code, no password. Email or SMS — your pick.</p>

            <div className="channel-toggle" role="tablist" aria-label="Login method">
              <button
                type="button"
                role="tab"
                aria-selected={channel === 'email'}
                className={channel === 'email' ? 'active' : ''}
                onClick={() => switchChannel('email')}
              >
                ✉️ Email
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={channel === 'sms'}
                className={channel === 'sms' ? 'active' : ''}
                onClick={() => switchChannel('sms')}
              >
                📱 SMS
              </button>
            </div>

            {channel === 'email' ? (
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
            ) : (
              <label>
                Phone number
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="082 123 4567 or +27 82 123 4567"
                  required
                />
                <span className="field-hint">Local numbers are sent as +27…</span>
              </label>
            )}

            {error && <p className="form-error">{error}</p>}

            <button type="submit" disabled={busy}>
              {busy ? 'Sending code…' : channel === 'email' ? 'Email me a login code' : 'Text me a login code'}
            </button>

            <p className="auth-switch">
              New here? <Link to="/register">Create an account</Link>
              {' · '}
              <Link to="/login-password">Use a password</Link>
            </p>
          </form>
        ) : (
          <form className="auth-card" onSubmit={handleVerify}>
            <h1>{channel === 'email' ? 'Check your inbox' : 'Check your messages'}</h1>
            <p className="auth-lede">
              We sent a 6-digit code to <strong>{destination}</strong>. It expires in 10 minutes.
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
              {channel === 'email' ? 'Wrong address' : 'Wrong number'}?{' '}
              <button type="button" className="linklike" onClick={() => setStep('input')}>
                Start over
              </button>
            </p>
          </form>
        )}
      </motion.div>
    </div>
  );
}
