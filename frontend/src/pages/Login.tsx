import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  appleSignIn,
  getAuthConfig,
  requestLoginCode,
  requestSmsCode,
  requestWhatsappCode,
} from '../api/endpoints';
import { useAuth } from '../context/AuthContext';

type Step = 'input' | 'code';
type Channel = 'email' | 'sms' | 'whatsapp';

const APPLE_JS_URL =
  'https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js';

const CHANNEL_LABELS: Record<Channel, string> = {
  email: '✉️ Email',
  sms: '📱 SMS',
  whatsapp: '💬 WhatsApp',
};

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
  const [appleEnabled, setAppleEnabled] = useState(false);
  const [smsEnabled, setSmsEnabled] = useState(false);
  const [whatsappEnabled, setWhatsappEnabled] = useState(false);

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

  async function handleRequestCode(e: FormEvent) {
    e.preventDefault();
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
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      const detail =
        (err as { response?: { data?: { detail?: string; phone?: string[]; email?: string[] } } })?.response?.data;
      const waking = status === 502 || status === 503 || status === 504 || err instanceof TypeError;
      setError(
        detail?.detail ??
          detail?.phone?.[0] ??
          detail?.email?.[0] ??
          (waking
            ? 'The SmartSpend server is waking up. Wait a few seconds and try again — it usually takes under a minute.'
            : 'Could not send a code. Check the details and try again.'),
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
  }

  const channelNoun = channel === 'email' ? 'inbox' : 'messages';

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

interface AppleAuthResponse {
  authorization: { id_token: string; code: string };
  user?: { name?: { firstName?: string; lastName?: string }; email?: string };
}
