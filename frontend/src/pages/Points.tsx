import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { listPoints } from '../api/endpoints';
import type { LoyaltyPointsRow } from '../types';

function daysUntil(dateStr: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((new Date(dateStr).getTime() - today.getTime()) / 86_400_000);
}

function ExpiryBadge({ expiresAt }: { expiresAt: string | null }) {
  if (!expiresAt) return <span className="points-badge points-ok">No expiry</span>;
  const days = daysUntil(expiresAt);
  if (days <= 1) return <span className="points-badge points-critical">Expires {days <= 0 ? 'today' : 'tomorrow'}</span>;
  if (days <= 7) return <span className="points-badge points-warn">Expires in {days} day{days === 1 ? '' : 's'}</span>;
  return <span className="points-badge points-ok">Valid until {expiresAt}</span>;
}

export default function Points() {
  const [rows, setRows] = useState<LoyaltyPointsRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showExpired, setShowExpired] = useState(false);

  useEffect(() => {
    setLoading(true);
    listPoints(showExpired)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [showExpired]);

  const byStore = useMemo(() => {
    const map = new Map<string, LoyaltyPointsRow[]>();
    for (const row of rows) {
      map.set(row.store_name, [...(map.get(row.store_name) ?? []), row]);
    }
    return [...map.entries()].sort((a, b) => {
      // Stores with soonest-expiring points first.
      const soonest = (rs: LoyaltyPointsRow[]) =>
        rs.reduce<string | null>(
          (min, r) => (r.expires_at && (!min || r.expires_at < min) ? r.expires_at : min),
          null,
        ) ?? '9999-12-31';
      return soonest(a[1]).localeCompare(soonest(b[1]));
    });
  }, [rows]);

  const urgent = rows.filter((r) => r.expires_at && daysUntil(r.expires_at) <= 7);
  const total = rows.reduce((sum, r) => sum + r.points, 0);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Points</h1>
          <p className="page-subtitle">Spendable points per store, soonest expiry first.</p>
        </div>
      </div>

      {urgent.length > 0 && (
        <motion.div
          className="points-alert"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
        >
          ⏰ {urgent.reduce((sum, r) => sum + r.points, 0)} points expire within 7 days — spend them soon.
        </motion.div>
      )}

      {loading ? (
        <p className="page-subtitle">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="empty-state">
          <p>No points yet. Scan a Pick n Pay or Clicks slip and the points show up here automatically.</p>
        </div>
      ) : (
        <>
          <p className="points-total">
            <strong>{total.toLocaleString()}</strong> points across {byStore.length} store{byStore.length === 1 ? '' : 's'}
          </p>
          {byStore.map(([storeName, storeRows]) => (
            <section key={storeName} className="points-store">
              <h2>{storeName}</h2>
              {storeRows.map((row) => (
                <div key={row.points_id} className="points-row">
                  <div className="points-amount">
                    {row.points.toLocaleString()}
                    <span className="points-unit">pts</span>
                  </div>
                  <div className="points-label">{row.label || 'Points'}</div>
                  <ExpiryBadge expiresAt={row.expires_at} />
                </div>
              ))}
            </section>
          ))}
        </>
      )}

      <label className="points-expired-toggle">
        <input type="checkbox" checked={showExpired} onChange={(e) => setShowExpired(e.target.checked)} />
        Show expired points
      </label>
    </div>
  );
}
