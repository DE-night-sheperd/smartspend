import { useEffect, useState, type FormEvent } from 'react';
import {
  createCategory,
  createReceipt,
  createStore,
  listCategories,
  listReceipts,
  listStores,
} from '../api/endpoints';
import type { Category, Receipt, Store } from '../types';

const emptyItem = { category: 0, item_name: '', unit_price: '', quantity: 1, is_impulse: false };

export default function Receipts() {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [stores, setStores] = useState<Store[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  async function loadAll() {
    const [r, s, c] = await Promise.all([listReceipts(), listStores(), listCategories()]);
    setReceipts(r);
    setStores(s);
    setCategories(c);
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
  }, []);

  return (
    <div className="page">
      <div className="page-header">
        <h1>Receipts</h1>
        <button onClick={() => setShowForm((v) => !v)}>{showForm ? 'Cancel' : '+ Add receipt'}</button>
      </div>

      {showForm && (
        <ReceiptForm
          stores={stores}
          categories={categories}
          onStoresChanged={setStores}
          onCategoriesChanged={setCategories}
          onCreated={(receipt) => {
            setReceipts((rs) => [receipt, ...rs]);
            setShowForm(false);
          }}
        />
      )}

      {loading && <p>Loading receipts…</p>}
      {!loading && receipts.length === 0 && <p className="empty-state">No receipts yet — capture your first one above.</p>}

      <ul className="receipt-list">
        {receipts.map((r) => (
          <li key={r.receipt_id} className="receipt-card">
            <div className="receipt-card-header">
              <strong>{r.store_name}</strong>
              <span>{r.purchase_date}</span>
              <span className="receipt-total">R{r.total_amount}</span>
            </div>
            <ul className="item-list">
              {r.items.map((it) => (
                <li key={it.item_id}>
                  {it.item_name} × {it.quantity} — R{it.line_total ?? (Number(it.unit_price) * it.quantity).toFixed(2)}
                  {' '}
                  <span className={`category-badge ${it.is_impulse ? 'impulse' : ''}`}>{it.category_name}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReceiptForm({
  stores,
  categories,
  onStoresChanged,
  onCategoriesChanged,
  onCreated,
}: {
  stores: Store[];
  categories: Category[];
  onStoresChanged: (s: Store[]) => void;
  onCategoriesChanged: (c: Category[]) => void;
  onCreated: (r: Receipt) => void;
}) {
  const [storeId, setStoreId] = useState<number | ''>('');
  const [newStoreName, setNewStoreName] = useState('');
  const [purchaseDate, setPurchaseDate] = useState(new Date().toISOString().slice(0, 10));
  const [items, setItems] = useState([{ ...emptyItem }]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function updateItem(idx: number, patch: Partial<typeof emptyItem>) {
    setItems((its) => its.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  }

  async function ensureCategory(name: string): Promise<number> {
    const existing = categories.find((c) => c.category_name.toLowerCase() === name.toLowerCase());
    if (existing) return existing.category_id;
    const created = await createCategory({ category_name: name, is_essential: true });
    onCategoriesChanged([...categories, created]);
    return created.category_id;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      let finalStoreId = storeId;
      if (!finalStoreId && newStoreName) {
        const created = await createStore({ store_name: newStoreName, channel_type: 'Physical_Store' });
        onStoresChanged([...stores, created]);
        finalStoreId = created.store_id;
      }
      if (!finalStoreId) throw new Error('Select or add a store');

      const totalAmount = items.reduce((sum, it) => sum + Number(it.unit_price || 0) * it.quantity, 0);

      const receipt = await createReceipt({
        store: finalStoreId,
        purchase_date: purchaseDate,
        total_amount: totalAmount.toFixed(2),
        source_type: 'upload',
        image_url: null,
        verified: true,
        items: items
          .filter((it) => it.item_name)
          .map((it) => ({
            category: it.category,
            item_name: it.item_name,
            unit_price: it.unit_price,
            quantity: it.quantity,
            is_impulse: it.is_impulse,
          })),
      });
      onCreated(receipt);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save this receipt.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="receipt-form" onSubmit={handleSubmit}>
      <h2>Verify &amp; save receipt</h2>
      <div className="form-row">
        <label>
          Store
          <select value={storeId} onChange={(e) => setStoreId(e.target.value ? Number(e.target.value) : '')}>
            <option value="">— new store —</option>
            {stores.map((s) => (
              <option key={s.store_id} value={s.store_id}>
                {s.store_name}
              </option>
            ))}
          </select>
        </label>
        {!storeId && (
          <label>
            New store name
            <input value={newStoreName} onChange={(e) => setNewStoreName(e.target.value)} placeholder="e.g. Checkers" />
          </label>
        )}
        <label>
          Purchase date
          <input type="date" value={purchaseDate} onChange={(e) => setPurchaseDate(e.target.value)} required />
        </label>
      </div>

      <h3>Line items</h3>
      {items.map((it, idx) => (
        <div className="form-row item-row" key={idx}>
          <input
            placeholder="Item name"
            value={it.item_name}
            onChange={(e) => updateItem(idx, { item_name: e.target.value })}
          />
          <input
            type="number"
            step="0.01"
            placeholder="Unit price"
            value={it.unit_price}
            onChange={(e) => updateItem(idx, { unit_price: e.target.value })}
          />
          <input
            type="number"
            min={1}
            value={it.quantity}
            onChange={(e) => updateItem(idx, { quantity: Number(e.target.value) })}
          />
          <input
            placeholder="Category (e.g. Groceries)"
            list="category-options"
            onBlur={async (e) => {
              if (e.target.value) {
                const catId = await ensureCategory(e.target.value);
                updateItem(idx, { category: catId });
              }
            }}
          />
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={it.is_impulse}
              onChange={(e) => updateItem(idx, { is_impulse: e.target.checked })}
            />
            Impulse buy
          </label>
        </div>
      ))}
      <datalist id="category-options">
        {categories.map((c) => (
          <option key={c.category_id} value={c.category_name} />
        ))}
      </datalist>

      <button type="button" onClick={() => setItems((its) => [...its, { ...emptyItem }])}>
        + Add line item
      </button>

      {error && <p className="form-error">{error}</p>}
      <button type="submit" disabled={submitting}>
        {submitting ? 'Saving…' : 'Save receipt'}
      </button>
    </form>
  );
}
