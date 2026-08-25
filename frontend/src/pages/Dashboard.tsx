import { useEffect, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getMonthlyAnalytics } from '../api/endpoints';
import type { MonthlyAnalytics } from '../types';
import { useAuth } from '../context/AuthContext';

export default function Dashboard() {
  const { user } = useAuth();
  const [rows, setRows] = useState<MonthlyAnalytics[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getMonthlyAnalytics()
      .then(setRows)
      .finally(() => setLoading(false));
  }, []);

  const chartData = rows.map((r) => ({
    month: new Date(r.audit_month).toLocaleDateString(undefined, { month: 'short', year: '2-digit' }),
    'Total spent': Number(r.total_spent),
    'Impulse spend': Number(r.impulse_spend),
  }));

  const latest = rows[0];

  return (
    <div className="page">
      <h1>Monthly Financial Audit</h1>
      <p className="page-subtitle">
        Welcome back{user ? `, ${user.first_name}` : ''}. Budget limit: R{user?.monthly_budget_limit ?? '—'} / month.
      </p>

      {loading && <p>Loading analytics…</p>}
      {!loading && rows.length === 0 && (
        <p className="empty-state">No receipts logged yet. Add one on the Receipts page to see your audit here.</p>
      )}

      {!loading && rows.length > 0 && (
        <>
          <div className="stat-row">
            <StatCard label="This month's spend" value={`R${latest.total_spent}`} />
            <StatCard label="Impulse / non-essential" value={`R${latest.impulse_spend}`} />
            <StatCard
              label="Budget variance"
              value={`R${latest.budget_variance}`}
              tone={Number(latest.budget_variance) >= 0 ? 'good' : 'bad'}
            />
          </div>

          <div className="chart-card">
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={[...chartData].reverse()}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="Total spent" fill="#2f6f4f" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Impulse spend" fill="#c96f4a" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'bad' }) {
  return (
    <div className={`stat-card ${tone ?? ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}
