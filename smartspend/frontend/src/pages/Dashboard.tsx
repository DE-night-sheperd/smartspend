import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { downloadMonthlyAuditPdf, getMonthlyAnalytics } from '../api/endpoints';
import type { MonthlyAnalytics } from '../types';
import { useAuth } from '../context/AuthContext';
import AnimatedNumber from '../components/AnimatedNumber';
import { celebrate } from '../lib/celebrate';

export default function Dashboard() {
  const { user } = useAuth();
  const [rows, setRows] = useState<MonthlyAnalytics[]>([]);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const celebrated = useRef(false);

  useEffect(() => {
    getMonthlyAnalytics()
      .then(setRows)
      .finally(() => setLoading(false));
  }, []);

  const latest = rows[0];

  useEffect(() => {
    if (!latest || celebrated.current) return;
    if (Number(latest.budget_variance) >= 0) {
      celebrated.current = true;
      const t = setTimeout(() => celebrate(), 500);
      return () => clearTimeout(t);
    }
  }, [latest]);

  const chartData = rows.map((r) => ({
    month: new Date(r.audit_month).toLocaleDateString(undefined, { month: 'short', year: '2-digit' }),
    'Total spent': Number(r.total_spent),
    'Impulse spend': Number(r.impulse_spend),
  }));

  async function handleDownload() {
    const now = latest ? new Date(latest.audit_month) : new Date();
    setDownloading(true);
    try {
      await downloadMonthlyAuditPdf(now.getFullYear(), now.getMonth() + 1);
    } finally {
      setDownloading(false);
    }
  }

  const budget = Number(user?.monthly_budget_limit ?? 0);
  const spent = latest ? Number(latest.total_spent) : 0;
  const pct = budget > 0 ? Math.min(150, (spent / budget) * 100) : 0;
  const over = latest ? Number(latest.budget_variance) < 0 : false;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Monthly Financial Audit</h1>
          <p className="page-subtitle">
            Welcome back{user ? `, ${user.first_name}` : ''} — here's the running tally.
          </p>
        </div>
        {!loading && rows.length > 0 && (
          <button onClick={handleDownload} disabled={downloading}>
            {downloading ? 'Printing…' : '🧾 Print audit PDF'}
          </button>
        )}
      </div>

      {loading && <p>Tallying receipts…</p>}
      {!loading && rows.length === 0 && (
        <p className="empty-state">No receipts logged yet. Scan one on the Receipts page to get your first audit.</p>
      )}

      {!loading && rows.length > 0 && latest && (
        <>
          <motion.div
            className="hero-card"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          >
            <p className="hero-eyebrow">This month, so far</p>
            <p className={`hero-figure ${over ? 'over' : 'under'}`}>
              <AnimatedNumber value={spent} prefix="R" />
            </p>
            <p className="hero-caption">
              of your R{budget.toLocaleString(undefined, { minimumFractionDigits: 2 })} budget
              {over ? ' — you\u2019ve run over.' : '.'}
            </p>
            <div className="thermo-track">
              <motion.div
                className={`thermo-fill ${over ? 'over-budget' : ''}`}
                initial={{ width: 0 }}
                animate={{ width: `${Math.min(100, pct)}%` }}
                transition={{ duration: 1, ease: 'easeOut', delay: 0.15 }}
              />
            </div>
            <div className="thermo-labels">
              <span>R0</span>
              <span>R{budget.toLocaleString(undefined, { minimumFractionDigits: 0 })}</span>
            </div>
          </motion.div>

          <motion.div
            className="stat-row"
            initial="hidden"
            animate="show"
            variants={{ hidden: {}, show: { transition: { staggerChildren: 0.08 } } }}
          >
            <StatCard label="Impulse / non-essential" value={Number(latest.impulse_spend)} />
            <StatCard
              label="Budget variance"
              value={Number(latest.budget_variance)}
              tone={Number(latest.budget_variance) >= 0 ? 'good' : 'bad'}
              signed
            />
            <StatCard label="Receipts this month" value={rows.length} plain />
          </motion.div>

          <motion.div
            className="chart-card"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
          >
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={[...chartData].reverse()}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e3d9b8" />
                <XAxis dataKey="month" tick={{ fontFamily: 'IBM Plex Mono', fontSize: 12 }} />
                <YAxis tick={{ fontFamily: 'IBM Plex Mono', fontSize: 12 }} />
                <Tooltip contentStyle={{ fontFamily: 'IBM Plex Mono', borderRadius: 8 }} />
                <Legend wrapperStyle={{ fontFamily: 'Space Grotesk', fontSize: 13 }} />
                <Bar dataKey="Total spent" fill="#1fae63" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Impulse spend" fill="#e8483a" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </motion.div>
        </>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
  signed,
  plain,
}: {
  label: string;
  value: number;
  tone?: 'good' | 'bad';
  signed?: boolean;
  plain?: boolean;
}) {
  const prefix = plain ? '' : signed && value >= 0 ? '+R' : 'R';
  return (
    <motion.div
      className={`stat-card ${tone ?? ''}`}
      variants={{ hidden: { opacity: 0, y: 10 }, show: { opacity: 1, y: 0 } }}
    >
      <span className="stat-label">{label}</span>
      <span className="stat-value">
        {plain ? value : <AnimatedNumber value={value} prefix={prefix} decimals={2} />}
      </span>
    </motion.div>
  );
}
