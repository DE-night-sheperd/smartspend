import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  downloadMonthlyAuditPdf,
  getGeminiKeyStatus,
  getMonthBreakdown,
  getMonthlyAnalytics,
  listPoints,
} from '../api/endpoints';
import type { GeminiKeyStatus, LoyaltyPointsRow, MonthBreakdown, MonthlyAnalytics } from '../types';
import { useAuth } from '../context/AuthContext';
import AnimatedNumber from '../components/AnimatedNumber';
import { celebrate } from '../lib/celebrate';

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const DONUT_COLORS = ['#1fae63', '#e8a200', '#e8483a', '#3546e0', '#7a5cff', '#0ea5a5', '#c96f4a', '#5c6a5f'];

const fmtRand = (v: number | string) =>
  Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function daysUntil(iso: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((new Date(iso).getTime() - today.getTime()) / 86_400_000);
}

export default function Dashboard() {
  const { user } = useAuth();
  const [rows, setRows] = useState<MonthlyAnalytics[]>([]);
  const [breakdown, setBreakdown] = useState<MonthBreakdown | null>(null);
  const [cursor, setCursor] = useState(() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() + 1 };
  });
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [points, setPoints] = useState<LoyaltyPointsRow[]>([]);
  const [gemini, setGemini] = useState<GeminiKeyStatus | null>(null);
  const [geminiBannerDismissed, setGeminiBannerDismissed] = useState(false);
  const celebrated = useRef(false);

  useEffect(() => {
    getMonthlyAnalytics().then(setRows).catch(() => setRows([]));
  }, []);

  useEffect(() => {
    listPoints().then(setPoints).catch(() => setPoints([]));
  }, []);

  // Prompt users to connect their own Gemini key (BYOK) until they do —
  // Google only issues keys inside the user's own AI Studio account, so the
  // nudge points at Settings where the paste-and-verify flow lives.
  useEffect(() => {
    getGeminiKeyStatus().then(setGemini).catch(() => setGemini({ connected: false, key_hint: '' }));
  }, []);

  const loadBreakdown = useCallback((year: number, month: number) => {
    setLoading(true);
    getMonthBreakdown(year, month)
      .then(setBreakdown)
      .catch(() => setBreakdown(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadBreakdown(cursor.year, cursor.month);
  }, [cursor, loadBreakdown]);

  function shiftMonth(delta: number) {
    setCursor(({ year, month }) => {
      const d = new Date(year, month - 1 + delta, 1);
      return { year: d.getFullYear(), month: d.getMonth() + 1 };
    });
  }

  const latest = rows[0];
  useEffect(() => {
    if (!latest || celebrated.current) return;
    if (Number(latest.budget_variance) >= 0) {
      celebrated.current = true;
      const t = setTimeout(() => celebrate(), 600);
      return () => clearTimeout(t);
    }
  }, [latest]);

  const isCurrentMonth =
    cursor.year === new Date().getFullYear() && cursor.month === new Date().getMonth() + 1;

  const spent = breakdown ? Number(breakdown.total_spent) : 0;
  const budget = breakdown ? Number(breakdown.budget_limit) : Number(user?.monthly_budget_limit ?? 0);
  const variance = breakdown ? Number(breakdown.budget_variance) : 0;
  const impulse = breakdown ? Number(breakdown.impulse_spend) : 0;
  const essential = breakdown ? Number(breakdown.essential_spend) : 0;
  const over = variance < 0;
  const pct = budget > 0 ? (spent / budget) * 100 : 0;

  const chartRows = rows.map((r) => ({
    month: new Date(r.audit_month).toLocaleDateString(undefined, { month: 'short', year: '2-digit' }),
    'Total spent': Number(r.total_spent),
    'Impulse spend': Number(r.impulse_spend),
  }));

  const dailyData = breakdown
    ? Object.entries(breakdown.daily_totals).map(([day, total]) => ({
        day: new Date(day).getDate(),
        'Spent': Number(total),
      }))
    : [];

  const donutData =
    breakdown?.categories.slice(0, 8).map((c) => ({
      name: c.category_name,
      value: Number(c.total),
    })) ?? [];

  const hasReceipts = rows.length > 0;

  // Loyalty points about to lapse — the same 7-day warning the reminder
  // email uses, shown where the user actually starts their session.
  const expiringPoints = points.filter((p) => {
    if (!p.expires_at) return false;
    const days = daysUntil(p.expires_at);
    return days >= 0 && days <= 7;
  });
  const expiringTotal = expiringPoints.reduce((sum, p) => sum + p.points, 0);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Monthly Financial Audit</h1>
          <p className="page-subtitle">
            Welcome back{user ? `, ${user.first_name}` : ''} — here's the running tally.
          </p>
        </div>
        {hasReceipts && (
          <button onClick={() => handleDownload(cursor)} disabled={downloading}>
            {downloading ? 'Printing…' : '🧾 Print audit PDF'}
          </button>
        )}
      </div>

      {expiringPoints.length > 0 && (
        <motion.div
          className="points-alert"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
        >
          ⏰ {expiringTotal.toLocaleString()} points expire within 7 days ({expiringPoints.map((p) => `${p.store_name}: ${p.points.toLocaleString()}`).join(', ')}).{' '}
          <Link to="/points">Spend them before they lapse</Link>
        </motion.div>
      )}

      {gemini && !gemini.connected && !geminiBannerDismissed && (
        <motion.div
          className="gemini-banner"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <span>
            🔑 Scans currently use SmartSpend's shared AI reader.{' '}
            <Link to="/settings">Connect your own free Gemini key</Link> so receipts use your quota
            instead.
          </span>
          <button
            type="button"
            className="link-button"
            aria-label="Dismiss"
            onClick={() => setGeminiBannerDismissed(true)}
          >
            ✕
          </button>
        </motion.div>
      )}

      {/* Month switcher */}
      <div className="month-nav">
        <button className="month-arrow" onClick={() => shiftMonth(-1)} aria-label="Previous month">
          ←
        </button>
        <span className="month-label">
          {MONTH_NAMES[cursor.month - 1]} {cursor.year}
          {isCurrentMonth && <em> · this month</em>}
        </span>
        <button
          className="month-arrow"
          onClick={() => shiftMonth(1)}
          disabled={isCurrentMonth}
          aria-label="Next month"
        >
          →
        </button>
      </div>

      {loading && <p>Tallying receipts…</p>}

      {!loading && !breakdown && (
        <p className="empty-state">
          Nothing recorded for {MONTH_NAMES[cursor.month - 1]} {cursor.year}.
          {hasReceipts ? ' Try another month, or' : ' Scan a receipt on the'}{' '}
          <Link to="/receipts">Receipts page</Link> to get your first audit.
        </p>
      )}

      {!loading && breakdown && (
        <>
          {/* Hero: budget thermometer */}
          <motion.div
            className="hero-card"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          >
            <p className="hero-eyebrow">{MONTH_NAMES[cursor.month - 1]} {cursor.year}, so far</p>
            <p className={`hero-figure ${over ? 'over' : 'under'}`}>
              <AnimatedNumber value={spent} prefix="R" />
            </p>
            <p className="hero-caption">
              of your R{fmtRand(budget)} budget —{' '}
              {over ? (
                <strong className="over-text">R{fmtRand(Math.abs(variance))} over.</strong>
              ) : (
                <>
                  <strong className="under-text">R{fmtRand(variance)}</strong> left.
                </>
              )}
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
              <span>R{fmtRand(budget)}</span>
            </div>
            {budget === 0 && (
              <p className="hero-budget-hint">
                No budget set — <Link to="/settings">set one in Settings</Link> to unlock variance tracking.
              </p>
            )}
          </motion.div>

          {/* Stat cards */}
          <motion.div
            className="stat-row"
            initial="hidden"
            animate="show"
            variants={{ hidden: {}, show: { transition: { staggerChildren: 0.08 } } }}
          >
            <StatCard label="Impulse / non-essential" value={impulse} tone={impulse > 0 ? 'warn' : 'good'} />
            <StatCard label="Budget variance" value={variance} tone={over ? 'bad' : 'good'} signed />
            <StatCard label="Receipts this month" value={receiptCount(breakdown)} plain />
          </motion.div>

          {/* Charts */}
          <div className="chart-grid">
            {dailyData.length > 0 && (
              <motion.div
                className="chart-card"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.25 }}
              >
                <h2 className="chart-title">Daily spending spikes</h2>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={dailyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e3d9b8" />
                    <XAxis dataKey="day" tick={{ fontFamily: 'IBM Plex Mono', fontSize: 12 }} />
                    <YAxis tick={{ fontFamily: 'IBM Plex Mono', fontSize: 12 }} />
                    <Tooltip contentStyle={{ fontFamily: 'IBM Plex Mono', borderRadius: 8 }} />
                    <Bar dataKey="Spent" fill="#c96f4a" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </motion.div>
            )}

            {donutData.length > 0 && (
              <motion.div
                className="chart-card"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.35 }}
              >
                <h2 className="chart-title">Where it went</h2>
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie data={donutData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>
                      {donutData.map((entry, i) => (
                        <Cell key={entry.name} fill={DONUT_COLORS[i % DONUT_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value) => `R${fmtRand(Number(value))}`}
                      contentStyle={{ fontFamily: 'IBM Plex Mono', borderRadius: 8 }}
                    />
                    <Legend wrapperStyle={{ fontFamily: 'Space Grotesk', fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
              </motion.div>
            )}
          </div>

          {/* Trend + lists */}
          {chartRows.length > 1 && (
            <motion.div
              className="chart-card"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.4 }}
            >
              <h2 className="chart-title">Month-over-month</h2>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={[...chartRows].reverse()}>
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
          )}

          <div className="breakdown-grid">
            <motion.div
              className="list-card"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.45 }}
            >
              <h2 className="chart-title">Top categories</h2>
              <ol className="ranked-list">
                {breakdown.categories.slice(0, 6).map((c) => (
                  <li key={c.category_name}>
                    <span>
                      {c.category_name}
                      <small> · {c.item_count} item{c.item_count === 1 ? '' : 's'}</small>
                      {!c.is_essential && <span className="category-badge impulse">non-essential</span>}
                    </span>
                    <strong className="num-tick">R{fmtRand(c.total)}</strong>
                  </li>
                ))}
                {breakdown.categories.length === 0 && <li className="muted">No items this month.</li>}
              </ol>
              {breakdown.biggest_purchase && (
                <p className="biggest-note">
                  Biggest single buy: <strong>{breakdown.biggest_purchase.item_name}</strong> at{' '}
                  {breakdown.biggest_purchase.store_name} — R{fmtRand(breakdown.biggest_purchase.line_total)}
                </p>
              )}
            </motion.div>

            <motion.div
              className="list-card"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.5 }}
            >
              <h2 className="chart-title">Top stores & channels</h2>
              <ol className="ranked-list">
                {breakdown.stores.slice(0, 6).map((s) => (
                  <li key={s.store_name}>
                    <span>
                      {s.store_name}
                      <small> · {s.receipt_count} receipt{s.receipt_count === 1 ? '' : 's'}</small>
                      <span className={`category-badge ${s.channel_type === 'Online_Ecommerce' ? 'impulse' : ''}`}>
                        {s.channel_type === 'Online_Ecommerce' ? 'online' : 'in-store'}
                      </span>
                    </span>
                    <strong className="num-tick">R{fmtRand(s.total)}</strong>
                  </li>
                ))}
                {breakdown.stores.length === 0 && <li className="muted">No stores this month.</li>}
              </ol>
              <p className="biggest-note">
                Essential: <strong className="num-tick">R{fmtRand(essential)}</strong> · Impulse:{' '}
                <strong className="num-tick">R{fmtRand(impulse)}</strong>
              </p>
            </motion.div>
          </div>
        </>
      )}
    </div>
  );

  async function handleDownload(target: { year: number; month: number }) {
    setDownloading(true);
    try {
      await downloadMonthlyAuditPdf(target.year, target.month);
    } finally {
      setDownloading(false);
    }
  }
}

function receiptCount(b: MonthBreakdown): number {
  return b.stores.reduce((sum, s) => sum + s.receipt_count, 0);
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
  tone?: 'good' | 'bad' | 'warn';
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
