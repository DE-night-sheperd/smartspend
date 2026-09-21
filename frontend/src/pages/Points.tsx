import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { motion } from 'framer-motion';
import { createPoints, deletePoints, listPoints, updatePoints } from '../api/endpoints';
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

interface EditorState {
  id: number | null; // null = creating
  store_name: string;
  label: string;
  points: string;
  expires_at: string;
}

const emptyEditor: EditorState = { id: null, store_name: '', label: 'Points', points: '', expires_at: '' };

export default function Points() {
  const [rows, setRows] = useState<LoyaltyPointsRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showExpired, setShowExpired] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

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

  async function reload() {
    try {
      setRows(await listPoints(showExpired));
    } catch {
      /* keep the current list on a transient failure */
    }
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!editor) return;
    setError(null);
    const points = parseInt(editor.points, 10);
    if (!editor.store_name.trim() || !Number.isFinite(points) || points <= 0) {
      setError('Enter the store and a points amount above zero.');
      return;
    }
    setBusy(true);
    const payload = {
      store_name: editor.store_name.trim(),
      label: editor.label.trim() || 'Points',
      points,
      expires_at: editor.expires_at || null,
    };
    try {
      if (editor.id === null) {
        await createPoints(payload);
      } else {
        await updatePoints(editor.id, payload);
      }
      setEditor(null);
      await reload();
    } catch {
      setError('Could not save that points block. Try again.');
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(id: number) {
    setBusy(true);
    setError(null);
    try {
      await deletePoints(id);
      setConfirmDeleteId(null);
      await reload();
    } catch {
      setError('Could not delete that block. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Points</h1>
          <p className="page-subtitle">Spendable points per store, soonest expiry first.</p>
        </div>
        <button
          onClick={() => {
            setEditor(editor === null ? emptyEditor : null);
            setError(null);
          }}
        >
          {editor && editor.id === null ? 'Cancel' : '+ Add points'}
        </button>
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

      {editor && (
        <motion.form
          className="points-editor"
          onSubmit={handleSave}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <h2>{editor.id === null ? 'Add a points block' : 'Edit points block'}</h2>
          <p className="field-hint">
            E.g. the Smart Shopper balance printed on last month's slip — scans add new blocks automatically.
          </p>
          <div className="form-row">
            <label>
              Store
              <input
                value={editor.store_name}
                onChange={(e) => setEditor({ ...editor, store_name: e.target.value })}
                placeholder="Pick n Pay"
                required
              />
            </label>
            <label>
              Points
              <input
                type="number"
                min="1"
                value={editor.points}
                onChange={(e) => setEditor({ ...editor, points: e.target.value })}
                placeholder="1200"
                required
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              Label
              <input
                value={editor.label}
                onChange={(e) => setEditor({ ...editor, label: e.target.value })}
                placeholder="Smart Shopper points"
              />
            </label>
            <label>
              Expires on
              <input
                type="date"
                value={editor.expires_at}
                onChange={(e) => setEditor({ ...editor, expires_at: e.target.value })}
              />
            </label>
          </div>
          {error && <p className="form-error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Saving…' : editor.id === null ? 'Add points' : 'Save changes'}
          </button>
        </motion.form>
      )}

      {loading ? (
        <p className="page-subtitle">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="empty-state">
          <p>No points yet. Scan a Pick n Pay or Clicks slip and the points show up here automatically — or add them by hand with “+ Add points”.</p>
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
                  <div className="points-actions">
                    <button
                      type="button"
                      className="points-action"
                      aria-label={`Edit ${row.points} points at ${row.store_name}`}
                      onClick={() => {
                        setEditor({
                          id: row.points_id,
                          store_name: row.store_name,
                          label: row.label || 'Points',
                          points: String(row.points),
                          expires_at: row.expires_at ?? '',
                        });
                        setError(null);
                      }}
                    >
                      ✎
                    </button>
                    {confirmDeleteId === row.points_id ? (
                      <>
                        <button
                          type="button"
                          className="points-action points-action-danger"
                          disabled={busy}
                          onClick={() => void handleDelete(row.points_id)}
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          className="points-action"
                          onClick={() => setConfirmDeleteId(null)}
                        >
                          Keep
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="points-action"
                        aria-label={`Delete ${row.points} points at ${row.store_name}`}
                        onClick={() => setConfirmDeleteId(row.points_id)}
                      >
                        🗑
                      </button>
                    )}
                  </div>
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
