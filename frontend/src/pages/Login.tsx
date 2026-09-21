import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  appleSignIn,
  confirmPasswordReset,
  getAuthConfig,
  requestLoginCode,
  requestPasswordReset,
  requestSmsCode,
  requestWhatsappCode,
  verifyPasswordResetCode,
} from '../api/endpoints';
import { useAuth } from '../context/AuthContext';

type Step = 'input' | 'code';
type Channel = 'email' | 'sms' | 'whatsapp';
type Mode = 'login' | 'forgot';

const APPLE_JS_URL =
  'https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js';

const CHANNEL_LABELS: Record<Channel, string> = {
  email: '✉️ Email',
  sms: '📱 SMS',
  whatsapp: '💬 WhatsApp',
};

// OTP screens show a standard "Resend code in 0:59" countdown (like banking
// apps) so the request always feels alive; resending is allowed once it hits 0.
const RESEND_SECONDS = 60;

function formatCountdown(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** The forgot-password flow: email → reset code → new password. Rendered
 * inside the login page so "Forgot password?" never leaves the context. */
function ForgotPassword() {
  const [stage, setStage] = useState<'email' | 'code' | 'newPassword'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [resendIn, setResendIn] = useState(0);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setInterval(() => {
      setResendIn((s) => (s > 0 ? s - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [resendIn > 0]);

  async function requestReset() {
    setError(null);
    setBusy(true);
    try {
      await requestPasswordReset(email);
      setStage('code');
      setResendIn(RESEND_SECONDS);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Could not send a reset code. Check the address and try again.');
    } finally {
      setBusy(false);
    }
  }

  async function checkCode() {
    setError(null);
    setBusy(true);
    try {
      await verifyPasswordResetCode(email, code);
      setStage('newPassword');
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'That code did not work. Request a new one if it expired.');
    } finally {
      setBusy(false);
    }
  }

  async function savePassword(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError('Passwords need at least 8 characters.');
      return;
    }
    setBusy(true);
    try {
      await confirmPasswordReset(email, code, password);
      setDone(true);
    } catch (err: unknown) {
      const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data;
      const messages = data
        ? Object.entries(data).flatMap(([, v]) => (Array.isArray(v) ? v.map(String) : [String(v)]))
        : [];
      setError(messages.join(' ') || 'Could not set the new password. Try again.');
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="auth-card">
        <h1>Password updated</h1>
        <p className="auth-lede">
          Your new password is set. Log in with it — or with a one-time code — as usual.
        </p>
        <Link className="button-link" to="/login-password">
          Log in with a password
        </Link>
      </div>
    );
  }

  return (
    <motion.div
      key={stage}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      style={{ width: '100%', maxWidth: 380 }}
    >
      <form
        className="auth-card"
        onSubmit={(e) => {
          e.preventDefault();
          if (stage === 'email') void requestReset();
          else if (stage === 'code') void checkCode();
          else void savePassword(e);
        }}
      >
        <h1>Reset your password</h1>
        {stage === 'email' && (
          <>
            <p className="auth-lede">We'll email you a 6-digit code to set a new password.</p>
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
              {busy ? 'Sending code…' : 'Email me a reset code'}
            </button>
          </>
        )}
        {stage === 'code' && (
          <>
            <p className="auth-lede">
              Enter the 6-digit code we sent to <strong>{email}</strong>. It expires in 10 minutes.
            </p>
            <label>
              Reset code
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
              {busy ? 'Checking…' : 'Verify code'}
            </button>
            <p className="auth-switch">
              Didn't get it?{' '}
              {resendIn > 0 ? (
                <span aria-live="polite">Resend code in {formatCountdown(resendIn)}</span>
              ) : (
                <button type="button" className="linklike" onClick={() => void requestReset()} disabled={busy}>
                  Resend code
                </button>
              )}
            </p>
          </>
        )}
        {stage === 'newPassword' && (
          <>
            <p className="auth-lede">Code verified — choose a new password.</p>
            <label>
              New password (min 8 characters)
              <input
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            {error && <p className="form-error">{error}</p>}
            <button type="submit" disabled={busy}>
              {busy ? 'Saving…' : 'Set new password'}
            </button>
          </>
        )}
        <p className="auth-switch">
          Remembered it?{' '}
          <Link to="/login">Back to log in</Link>
        </p>
      </form>
    </motion.div>
  );
}

export default function Login() {
  const { loginWithCode } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnTo = searchParams.get('returnTo') ?? '/dashboard';
  const [mode, setMode] = useState<Mode>('login');
  const [channel, setChannel] = useState<Channel>('email');
  const [step, setStep] = useState<Step>('input');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);
  const [appleEnabled, setAppleEnabled] = useState(false);
  const [smsEnabled, setSmsEnabled] = useState(false);
  const [whatsappEnabled, setWhatsappEnabled] = useState(false);
  const [resendIn, setResendIn] = useState(0);

  // Tick the resend countdown down once per second while it is running.
  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setInterval(() => {
      setResendIn((s) => (s > 0 ? s - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [resendIn > 0]);

  const destination = channel === 'email' ? email : phone;
  useEffect(() => {
    // The Apple button and SMS/WhatsApp channel tabs only appear when the
    // backend has them configured — an unconfigured option would just fail.
    getAuthConfig()
      .then((config) => {
        setAppleEnabled(config.apple_enabled);
        setSmsEnabled(config.sms_enabled);
        setWhatsappEnabled(config.whatsapp_enabled);
      })
      .catch(() => setAppleEnabled(false));
  }, []);

  async function sendCode() {
    setError(null);
    setBusy(true);
    try {
      const result =
        channel === 'email'
          ? await requestLoginCode(email)
          : channel === 'sms'
            ? await requestSmsCode(phone)
            : await requestWhatsappCode(phone);
      setDevCode(result.dev_code ?? null);
      setStep('code');
      setResendIn(RESEND_SECONDS);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      const detail =
        (err as { response?: { data?: { detail?: string; phone?: string[]; email?: string[] } } })?.response?.data;
      const unreachable = status === 502 || status === 503 || status === 504 || err instanceof TypeError;
      setError(
        detail?.detail ??
          detail?.phone?.[0] ??
          detail?.email?.[0] ??
          (unreachable
            ? 'Taking longer than usual — one more tap should do it.'
            : 'Could not send a code. Check the details and try again.'),
      );
    } finally {
      setBusy(false);
    }
  }

  function handleRequestCode(e: FormEvent) {
    e.preventDefault();
    void sendCode();
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

  async function handleAppleSignIn() {
    setError(null);
    setBusy(true);
    try {
      const w = window as unknown as { AppleID?: { auth: { init: (o: object) => void; signIn: () => Promise<AppleAuthResponse> } } };
      if (!w.AppleID) {
        await new Promise<void>((resolve, reject) => {
          const script = document.createElement('script');
          script.src = APPLE_JS_URL;
          script.onload = () => resolve();
          script.onerror = () => reject(new Error('Could not load Apple sign-in.'));
          document.head.appendChild(script);
        });
      }
      w.AppleID!.auth.init({
        clientId: import.meta.env.VITE_APPLE_CLIENT_ID ?? '',
        scope: 'name email',
        redirectURI: window.location.origin + '/login',
        usePopup: true,
      });
      const response = await w.AppleID!.auth.signIn();
      const appleName = response.user?.name
        ? `${response.user.name.firstName ?? ''} ${response.user.name.lastName ?? ''}`.trim()
        : undefined;
      const created = await appleSignIn(response.authorization.id_token, appleName || undefined);
      navigate(created ? '/settings' : returnTo, { replace: true });
    } catch (err: unknown) {
      // Closing the popup is the user changing their mind, not an error.
      if ((err as { error?: string })?.error === 'popup_closed_by_user') {
        setBusy(false);
        return;
      }
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err as { message?: string })?.message ??
        'Apple sign-in did not go through. Try again.';
      setError(detail);
      setBusy(false);
    }
  }

  function switchChannel(next: Channel) {
    if (next === channel) return;
    setChannel(next);
    setError(null);
    setStep('input');
    setResendIn(0);
  }

  const channelNoun = channel === 'email' ? 'inbox' : 'messages';

  if (mode === 'forgot') {
    return <ForgotPassword />;
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
            <p className="auth-lede">One-time code, no password. Email, SMS or WhatsApp.</p>

            <div className="channel-toggle" role="tablist" aria-label="Login method">
              {(Object.keys(CHANNEL_LABELS) as Channel[])
                .filter(
                  (c) =>
                    c === 'email' ||
                    (c === 'sms' && smsEnabled) ||
                    (c === 'whatsapp' && whatsappEnabled),
                )
                .map((c) => (
                  <button
                    key={c}
                    type="button"
                    role="tab"
                    aria-selected={channel === c}
                    className={channel === c ? 'active' : ''}
                    onClick={() => switchChannel(c)}
                  >
                    {CHANNEL_LABELS[c]}
                  </button>
                ))}
            </div>
            {!smsEnabled && (
              <p className="field-hint">
                SMS & WhatsApp codes are coming soon — use email for now.
              </p>
            )}

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
              {busy
                ? 'Sending code…'
                : channel === 'email'
                  ? 'Email me a login code'
                  : channel === 'sms'
                    ? 'Text me a login code'
                    : 'WhatsApp me a login code'}
            </button>

            {appleEnabled && (
              <>
                <div className="auth-divider" aria-hidden="true">
                  <span>or</span>
                </div>
                <button type="button" className="apple-button" onClick={handleAppleSignIn} disabled={busy}>
                   Apple | Continue with Apple
                </button>
              </>
            )}

            <p className="auth-switch">
              New here? <Link to="/register">Create an account</Link>
              {' · '}
              <Link to="/login-password">Use a password</Link>
            </p>
          </form>
        ) : (
          <form className="auth-card" onSubmit={handleVerify}>
            <h1>Check your {channelNoun}</h1>
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
              Didn't get it?{' '}
              {resendIn > 0 ? (
                <span aria-live="polite">Resend code in {formatCountdown(resendIn)}</span>
              ) : (
                <button type="button" className="linklike" onClick={() => void sendCode()} disabled={busy}>
                  Resend code
                </button>
              )}
              {' · '}
              {channel === 'email' ? 'Wrong address' : 'Wrong number'}?{' '}
              <button type="button" className="linklike" onClick={() => setStep('input')}>
                Start over
              </button>
            </p>
            {channel === 'email' && (
              <p className="auth-switch">
                Forgot your password?{' '}
                <button type="button" className="linklike" onClick={() => setMode('forgot')}>
                  Reset it by email
                </button>
              </p>
            )}
          </form>
        )}
      </motion.div>
    </div>
  );
}

interface AppleAuthResponse {
  authorization: { id_token: string; code: string };
  user?: { name?: { firstName?: string; lastName?: string }; email?: string };
}
