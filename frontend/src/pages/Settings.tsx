import { useEffect, useState, type FormEvent } from 'react';
import { motion } from 'framer-motion';
import {
  changePassword,
  connectGeminiKey,
  disconnectGeminiKey,
  exportReceiptsCsv,
  getGeminiKeyStatus,
  updateMe,
} from '../api/endpoints';
import { useAuth } from '../context/AuthContext';
import { playSound } from '../lib/sounds';
import type { GeminiKeyStatus, User } from '../types';

export default function Settings() {
  const { user, refreshUser } = useAuth();
  const [form, setForm] = useState({
    first_name: user?.first_name ?? '',
    last_name: user?.last_name ?? '',
    email: user?.email ?? '',
    phone: user?.phone ?? '',
    monthly_budget_limit: String(user?.monthly_budget_limit ?? '0'),
  });
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [error, setError] = useState<string | null>(null);

  // BYOK Gemini connection
  const [gemini, setGemini] = useState<GeminiKeyStatus | null>(null);
  const [geminiKeyInput, setGeminiKeyInput] = useState('');
  const [geminiBusy, setGeminiBusy] = useState(false);
  const [geminiMessage, setGeminiMessage] = useState<string | null>(null);
  const [geminiError, setGeminiError] = useState<string | null>(null);

  // Change password
  const [pwForm, setPwForm] = useState({ old_password: '', new_password: '', confirm: '' });
  const [pwStatus, setPwStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [pwError, setPwError] = useState<string | null>(null);

  function update<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
    setStatus('idle');
  }

  useEffect(() => {
    getGeminiKeyStatus().then(setGemini).catch(() => setGemini({ connected: false, key_hint: '' }));
  }, []);

  async function handleGeminiConnect(e: FormEvent) {
    e.preventDefault();
    setGeminiBusy(true);
    setGeminiError(null);
    setGeminiMessage(null);
    try {
      const result = await connectGeminiKey(geminiKeyInput.trim());
      setGemini({ connected: true, key_hint: result.key_hint });
      setGeminiKeyInput('');
      setGeminiMessage(result.detail);
      playSound('success');
    } catch (err: unknown) {
      playSound('error');
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setGeminiError(typeof detail === 'string' ? detail : 'Could not connect that key. Try again.');
    } finally {
      setGeminiBusy(false);
    }
  }

  async function handleGeminiDisconnect() {
    setGeminiBusy(true);
    setGeminiError(null);
    setGeminiMessage(null);
    try {
      await disconnectGeminiKey();
      setGemini({ connected: false, key_hint: '' });
      setGeminiMessage('Disconnected. Scans fall back to the built-in reader.');
    } catch {
      setGeminiError('Could not disconnect. Try again.');
    } finally {
      setGeminiBusy(false);
    }
  }

  async function handlePasswordChange(e: FormEvent) {
    e.preventDefault();
    setPwError(null);
    if (pwForm.new_password !== pwForm.confirm) {
      setPwError('The two new passwords do not match.');
      return;
    }
    setPwStatus('saving');
    try {
      await changePassword(pwForm.old_password, pwForm.new_password);
      setPwForm({ old_password: '', new_password: '', confirm: '' });
      setPwStatus('saved');
      playSound('success');
    } catch (err: unknown) {
      playSound('error');
      const detail = (err as { response?: { data?: { old_password?: string[]; new_password?: string[] } } })
        ?.response?.data;
      const msg = detail?.old_password?.[0] ?? detail?.new_password?.[0];
      setPwError(msg ?? 'Could not change your password. Try again.');
      setPwStatus('idle');
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setStatus('saving');
    try {
      const payload: Partial<User> = {
        first_name: form.first_name,
        last_name: form.last_name,
        monthly_budget_limit: form.monthly_budget_limit,
      };
      // Email/phone are editable; only patch them when changed so a plain
      // save doesn't accidentally trigger a re-verification code.
      if (user && form.email !== user.email) {
        payload.email = form.email;
      }
      if (form.phone !== (user?.phone ?? '')) {
        payload.phone = form.phone;
      }
      await updateMe(payload);
      await refreshUser();
      setStatus('saved');
      playSound('success');
    } catch {
      playSound('error');
      setError('Could not save your settings. Check the values and try again.');
      setStatus('idle');
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p className="page-subtitle">Your details and the number the whole app is graded against.</p>
        </div>
      </div>

      <motion.form
        className="settings-card"
        onSubmit={handleSubmit}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <h2>Profile</h2>
        <div className="form-row">
          <label>
            First name
            <input value={form.first_name} onChange={(e) => update('first_name', e.target.value)} />
          </label>
          <label>
            Last name
            <input value={form.last_name} onChange={(e) => update('last_name', e.target.value)} />
          </label>
        </div>
        <label>
          Email
          <input type="email" value={form.email} onChange={(e) => update('email', e.target.value)} />
        </label>
        <label>
          Phone (for SMS login codes)
          <input
            type="tel"
            value={form.phone}
            onChange={(e) => update('phone', e.target.value)}
            placeholder="082 123 4567"
          />
        </label>
        <p className="field-hint">
          {user?.email
            ? 'Changing your email or phone re-sends a verification code to the new destination.'
            : ''}
        </p>

        <h2>Budget</h2>
        <label>
          Monthly budget limit (R)
          <input
            type="number"
            step="0.01"
            min="0"
            value={form.monthly_budget_limit}
            onChange={(e) => update('monthly_budget_limit', e.target.value)}
            required
          />
        </label>
        <p className="field-hint">
          Every dashboard stat, the thermometer, and the variance report are measured against this number.
        </p>

        {error && <p className="form-error">{error}</p>}

        <button type="submit" disabled={status === 'saving'}>
          {status === 'saving' ? 'Saving…' : status === 'saved' ? 'Saved ✓' : 'Save settings'}
        </button>
      </motion.form>

      <motion.section
        className="settings-card"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.05 }}
      >
        <h2>Password</h2>
        <p className="field-hint">
          Used when you log in with a password. Email-code logins keep working either way.
        </p>
        <form onSubmit={handlePasswordChange}>
          <label>
            Current password
            <input
              type="password"
              autoComplete="current-password"
              value={pwForm.old_password}
              onChange={(e) => {
                setPwForm((f) => ({ ...f, old_password: e.target.value }));
                setPwStatus('idle');
              }}
              required
            />
          </label>
          <label>
            New password (min 8 characters)
            <input
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={pwForm.new_password}
              onChange={(e) => {
                setPwForm((f) => ({ ...f, new_password: e.target.value }));
                setPwStatus('idle');
              }}
              required
            />
          </label>
          <label>
            Confirm new password
            <input
              type="password"
              autoComplete="new-password"
              value={pwForm.confirm}
              onChange={(e) => {
                setPwForm((f) => ({ ...f, confirm: e.target.value }));
                setPwStatus('idle');
              }}
              required
            />
          </label>
          {pwError && <p className="form-error">{pwError}</p>}
          <button type="submit" disabled={pwStatus === 'saving'}>
            {pwStatus === 'saving' ? 'Updating…' : pwStatus === 'saved' ? 'Password updated ✓' : 'Change password'}
          </button>
        </form>
      </motion.section>

      <motion.section
        className="settings-card"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.06 }}
      >
        <h2>AI scanning (Gemini)</h2>
        <p className="field-hint">
          Connect your own free Gemini key so receipt scans use <strong>your</strong> quota instead
          of SmartSpend's shared one. Google creates keys only inside your own AI Studio account —
          grab one while signed in, paste it here, and we verify and store it encrypted. It is never
          shown again and can be removed anytime.
        </p>
        {gemini?.connected ? (
          <div className="gemini-status">
            <span className="points-badge points-ok">Connected · {gemini.key_hint}</span>
            <button
              type="button"
              className="button-secondary"
              onClick={() => void handleGeminiDisconnect()}
              disabled={geminiBusy}
            >
              Disconnect
            </button>
          </div>
        ) : (
          <form className="gemini-connect" onSubmit={handleGeminiConnect}>
            <a
              className="gemini-studio-link"
              href="https://aistudio.google.com/app/apikey"
              target="_blank"
              rel="noreferrer"
            >
              1. Get your free key at Google AI Studio ↗
            </a>
            <label>
              2. Paste your Gemini API key
              <input
                type="password"
                autoComplete="off"
                placeholder="AIza…"
                value={geminiKeyInput}
                onChange={(e) => setGeminiKeyInput(e.target.value)}
                required
              />
            </label>
            <button type="submit" disabled={geminiBusy || geminiKeyInput.trim().length < 20}>
              {geminiBusy ? 'Verifying…' : 'Connect Gemini'}
            </button>
          </form>
        )}
        {geminiMessage && <p className="field-hint">{geminiMessage}</p>}
        {geminiError && <p className="form-error">{geminiError}</p>}
      </motion.section>

      <motion.section
        className="settings-card"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.08 }}
      >
        <h2>Your data</h2>
        <p className="field-hint">Download every receipt and line item as a CSV file.</p>
        <button type="button" className="button-secondary" onClick={() => void exportReceiptsCsv()}>
          ⤓ Export receipts (CSV)
        </button>
      </motion.section>
    </div>
  );
}
