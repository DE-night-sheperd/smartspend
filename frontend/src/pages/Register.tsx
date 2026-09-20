import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { register } from '../api/endpoints';
import { useAuth } from '../context/AuthContext';

export default function Register() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnTo = searchParams.get('returnTo') ?? '/dashboard';
  const [form, setForm] = useState({
    email: '',
    first_name: '',
    last_name: '',
    password: '',
  });
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function update<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register(form);
      await login(form.email, form.password);
      navigate(returnTo, { replace: true });
    } catch (err: unknown) {
      const data = (err as { response?: { data?: Record<string, unknown> } })?.response?.data;
      const detail = data?.detail;
      if (typeof detail === 'string' && detail) {
        setError(detail);
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
        <h1>Create your account</h1>
        <p className="auth-lede">Snap receipts, tame impulse buys, and close every month in the green.</p>

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
          {submitting ? 'Creating account…' : 'Sign up'}
        </button>
        <p className="auth-switch">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </motion.form>
    </div>
  );
}
