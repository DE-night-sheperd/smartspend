import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useState, type FormEvent } from 'react';
import {
  attachReceiptImage,
  createCategory,
  createReceipt,
  createStore,
  listCategories,
  listReceipts,
  listStores,
  ocrExtract,
} from '../api/endpoints';
import type { Category, Receipt, Store } from '../types';
import { celebrate } from '../lib/celebrate';

const emptyItem = { category: 0, item_name: '', unit_price: '', quantity: 1, is_impulse: false };

export default function Receipts() {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [stores, setStores] = useState<Store[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [ocrDraft, setOcrDraft] = useState<{
    merchant_name: string | null;
    purchase_date: string | null;
    total_amount: number | null;
    items: { name: string; price: number }[];
  } | null>(null);
  const [pendingImage, setPendingImage] = useState<File | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

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

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  async function handleScan(file: File) {
    setScanning(true);
    setScanError(null);
    try {
      const result = await ocrExtract(file);
      setOcrDraft(result);
      setPendingImage(file);
      setShowForm(true);
    } catch {
      setScanError('Could not read that image. You can still add the receipt manually below.');
      setShowForm(true);
    } finally {
      setScanning(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Receipts</h1>
          <p className="page-subtitle">Snap it, check it, done — SmartSpend does the typing.</p>
        </div>
        <div className="header-actions">
          <label className={`button-secondary scan-dropzone`}>
            {scanning ? (
              <>
                Scanning…
                <motion.span
                  className="scan-sweep"
                  initial={{ y: '-100%' }}
                  animate={{ y: '100%' }}
                  transition={{ duration: 1.1, repeat: Infinity, ease: 'linear' }}
                />
              </>
            ) : (
              '📷 Scan receipt'
            )}
            <input
              type="file"
              accept="image/*"
              hidden
              disabled={scanning}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleScan(file);
                e.target.value = '';
              }}
            />
          </label>
          <button
            onClick={() => {
              setOcrDraft(null);
              setPendingImage(null);
              setShowForm((v) => !v);
            }}
          >
            {showForm ? 'Cancel' : '+ Add manually'}
          </button>
        </div>
      </div>

      {scanError && <p className="form-error">{scanError}</p>}

      <AnimatePresence>
        {showForm && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25 }}
            style={{ overflow: 'hidden' }}
          >
            <ReceiptForm
              stores={stores}
              categories={categories}
              onStoresChanged={setStores}
              onCategoriesChanged={setCategories}
              ocrDraft={ocrDraft}
              pendingImage={pendingImage}
              onCreated={(receipt) => {
                setReceipts((rs) => [receipt, ...rs]);
                setShowForm(false);
                setOcrDraft(null);
                setPendingImage(null);
                setToast('Receipt saved ✓');
                celebrate();
              }}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {loading && <p>Loading receipts…</p>}
      {!loading && receipts.length === 0 && !showForm && (
        <p className="empty-state">No receipts yet — scan or add your first one above.</p>
      )}

      <motion.ul
        className="receipt-list"
        initial="hidden"
        animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }}
      >
        <AnimatePresence>
          {receipts.map((r) => (
            <motion.li
              key={r.receipt_id}
              className="receipt-card"
              layout
              variants={{ hidden: { opacity: 0, y: 14, rotate: -1 }, show: { opacity: 1, y: 0, rotate: 0 } }}
              exit={{ opacity: 0, scale: 0.96 }}
            >
              <div className="receipt-card-header">
                {r.receipt_image && <img className="receipt-thumb" src={r.receipt_image} alt="" />}
                <strong>{r.store_name}</strong>
                <span>{r.purchase_date}</span>
                <span className="receipt-total">R{r.total_amount}</span>
              </div>
              <ul className="item-list">
                {r.items.map((it) => (
                  <li key={it.item_id}>
                    {it.item_name} × {it.quantity} — R{it.line_total ?? (Number(it.unit_price) * it.quantity).toFixed(2)}
                    <span className={`category-badge ${it.is_impulse ? 'impulse' : ''}`}>{it.category_name}</span>
                  </li>
                ))}
              </ul>
            </motion.li>
          ))}
        </AnimatePresence>
      </motion.ul>

      <AnimatePresence>
        {toast && (
          <motion.div
            className="toast"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ReceiptForm({
  stores,
  categories,
  onStoresChanged,
  onCategoriesChanged,
  onCreated,
  ocrDraft,
  pendingImage,
}: {
  stores: Store[];
  categories: Category[];
  onStoresChanged: (s: Store[]) => void;
  onCategoriesChanged: (c: Category[]) => void;
  onCreated: (r: Receipt) => void;
  ocrDraft?: {
    merchant_name: string | null;
    purchase_date: string | null;
    total_amount: number | null;
    items: { name: string; price: number }[];
  } | null;
  pendingImage?: File | null;
}) {
  const [storeId, setStoreId] = useState<number | ''>('');
  const [newStoreName, setNewStoreName] = useState(ocrDraft?.merchant_name ?? '');
  const [purchaseDate, setPurchaseDate] = useState(
    ocrDraft?.purchase_date ?? new Date().toISOString().slice(0, 10),
  );
  const [items, setItems] = useState(
    ocrDraft && ocrDraft.items.length > 0
      ? ocrDraft.items.map((it) => ({
          ...emptyItem,
          item_name: it.name,
          unit_price: String(it.price),
        }))
      : [{ ...emptyItem }],
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (ocrDraft) {
      const matched = stores.find(
        (s) => s.store_name.toLowerCase() === (ocrDraft.merchant_name ?? '').toLowerCase(),
      );
      if (matched) setStoreId(matched.store_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

      const totalAmount =
        ocrDraft?.total_amount ?? items.reduce((sum, it) => sum + Number(it.unit_price || 0) * it.quantity, 0);

      const receipt = await createReceipt({
        store: finalStoreId,
        purchase_date: purchaseDate,
        total_amount: totalAmount.toFixed(2),
        source_type: pendingImage ? 'camera' : 'upload',
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

      if (pendingImage) {
        await attachReceiptImage(receipt.receipt_id, pendingImage);
      }

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
      {ocrDraft && (
        <p className="ocr-hint">
          Auto-filled from your photo — double check the store, date, and prices below before saving.
        </p>
      )}
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
