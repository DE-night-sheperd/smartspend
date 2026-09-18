import { useState, type FormEvent } from 'react';
import { motion } from 'framer-motion';
import { updateMe } from '../api/endpoints';
import { useAuth } from '../context/AuthContext';
import type { User } from '../types';

export default function Settings() {
  const { user, refreshUser } = useAuth();
  const [form, setForm] = useState({
    first_name: user?.first_name ?? '',
    last_name: user?.last_name ?? '',
    email: user?.email ?? '',
    monthly_budget_limit: String(user?.monthly_budget_limit ?? '0'),
  });
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [error, setError] = useState<string | null>(null);

  function update<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
    setStatus('idle');
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
      // Email is shown read-only for code-login users; only patch it if changed.
      if (user && form.email !== user.email) {
        payload.email = form.email;
      }
      await updateMe(payload);
      await refreshUser();
      setStatus('saved');
    } catch {
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
        <p className="field-hint">
          {user?.email
            ? 'Changing this updates where future login codes are sent — use it with care.'
            : ''}
        </p>

        {error && <p className="form-error">{error}</p>}

        <button type="submit" disabled={status === 'saving'}>
          {status === 'saving' ? 'Saving…' : status === 'saved' ? 'Saved ✓' : 'Save settings'}
        </button>
      </motion.form>
    </div>
  );
}
