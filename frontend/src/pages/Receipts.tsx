import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  attachReceiptImage,
  createReceipt,
  deleteReceipt,
  exportReceiptsCsv,
  listCategories,
  listReceipts,
  listStores,
  ocrExtract,
  updateReceipt,
} from '../api/endpoints';
import type { Category, OcrDraft, Receipt, Store } from '../types';
import { celebrate } from '../lib/celebrate';
import SlipScanner from '../components/SlipScanner';

interface ReceiptFilters {
  search: string;
  store: string;
  category: string;
  date_from: string;
  date_to: string;
  ordering: string;
}

const emptyFilters: ReceiptFilters = {
  search: '',
  store: '',
  category: '',
  date_from: '',
  date_to: '',
  ordering: '-purchase_date',
};

interface ItemDraft {
  item_name: string;
  unit_price: string;
  quantity: number;
  category: string;
  is_impulse: boolean;
}

const emptyItem: ItemDraft = { item_name: '', unit_price: '', quantity: 1, category: '', is_impulse: false };

function sumItems(items: ItemDraft[]): number {
  return items.reduce((sum, it) => sum + Number(it.unit_price || 0) * (Number(it.quantity) || 0), 0);
}

export default function Receipts() {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [stores, setStores] = useState<Store[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Receipt | null>(null); // receipt being edited
  const [showForm, setShowForm] = useState(false);
  const [ocrDraft, setOcrDraft] = useState<OcrDraft | null>(null);
  const [pendingImage, setPendingImage] = useState<File | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [filters, setFilters] = useState<ReceiptFilters>(emptyFilters);

  async function loadReceipts() {
    const params = Object.fromEntries(
      Object.entries(filters).filter(([, v]) => v !== ''),
    );
    const r = await listReceipts(params);
    setReceipts(r);
  }

  async function loadAll() {
    const [r, s, c] = await Promise.all([listReceipts(), listStores(), listCategories()]);
    setReceipts(r);
    setStores(s);
    setCategories(c);
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounced reload whenever filters change.
  useEffect(() => {
    const t = setTimeout(() => {
      loadReceipts().catch(() => undefined);
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  function setFilter<K extends keyof ReceiptFilters>(key: K, value: string) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

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
      setEditing(null);
      setShowForm(true);
    } catch {
      setScanError('Could not read that image. You can still add the receipt manually below.');
      setShowForm(true);
    } finally {
      setScanning(false);
    }
  }

  function openCreate() {
    setEditing(null);
    setOcrDraft(null);
    setPendingImage(null);
    setShowForm((v) => !v || editing !== null);
  }

  function openEdit(receipt: Receipt) {
    setEditing(receipt);
    setOcrDraft(null);
    setPendingImage(null);
    setShowForm(true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function handleDelete(receipt: Receipt) {
    if (!window.confirm(`Delete the ${receipt.store_name} receipt from ${receipt.purchase_date}? This can't be undone.`)) {
      return;
    }
    setDeletingId(receipt.receipt_id);
    try {
      await deleteReceipt(receipt.receipt_id);
      setReceipts((rs) => rs.filter((r) => r.receipt_id !== receipt.receipt_id));
      setToast('Receipt deleted');
    } catch {
      setToast('Could not delete that receipt.');
    } finally {
      setDeletingId(null);
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
          <button type="button" className="scan-dropzone" onClick={() => setScannerOpen(true)} disabled={scanning}>
            {scanning ? (
              <>
                Reading receipt…
                <motion.span
                  className="scan-sweep"
                  initial={{ y: '-100%' }}
                  animate={{ y: '100%' }}
                  transition={{ duration: 1.1, repeat: Infinity, ease: 'linear' }}
                />
              </>
            ) : (
              '📷 Scan slip'
            )}
          </button>
          <label className="button-secondary scan-dropzone">
            Upload image
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
          <button onClick={openCreate}>{showForm && !editing ? 'Cancel' : '+ Add manually'}</button>
        </div>
      </div>

      {scanError && <p className="form-error">{scanError}</p>}

      <div className="receipt-toolbar">
        <input
          className="toolbar-search"
          type="search"
          placeholder="Search store or item…"
          value={filters.search}
          onChange={(e) => setFilter('search', e.target.value)}
        />
        <select value={filters.store} onChange={(e) => setFilter('store', e.target.value)} aria-label="Filter by store">
          <option value="">All stores</option>
          {stores.map((s) => (
            <option key={s.store_id} value={s.store_id}>
              {s.store_name}
            </option>
          ))}
        </select>
        <select
          value={filters.category}
          onChange={(e) => setFilter('category', e.target.value)}
          aria-label="Filter by category"
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c.category_id} value={c.category_id}>
              {c.category_name}
            </option>
          ))}
        </select>
        <input
          type="date"
          value={filters.date_from}
          onChange={(e) => setFilter('date_from', e.target.value)}
          aria-label="From date"
        />
        <input
          type="date"
          value={filters.date_to}
          onChange={(e) => setFilter('date_to', e.target.value)}
          aria-label="To date"
        />
        <select value={filters.ordering} onChange={(e) => setFilter('ordering', e.target.value)} aria-label="Sort">
          <option value="-purchase_date">Newest first</option>
          <option value="purchase_date">Oldest first</option>
          <option value="-total_amount">Biggest first</option>
          <option value="total_amount">Smallest first</option>
        </select>
        {(filters.search || filters.store || filters.category || filters.date_from || filters.date_to) && (
          <button type="button" className="button-ghost" onClick={() => setFilters(emptyFilters)}>
            Clear
          </button>
        )}
        <button type="button" className="button-secondary toolbar-export" onClick={() => void exportReceiptsCsv()}>
          ⤓ CSV
        </button>
      </div>

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
              key={editing ? `edit-${editing.receipt_id}` : 'create'}
              stores={stores}
              categories={categories}
              editing={editing}
              ocrDraft={ocrDraft}
              pendingImage={pendingImage}
              onCancel={() => {
                setShowForm(false);
                setEditing(null);
                setOcrDraft(null);
                setPendingImage(null);
              }}
              onSaved={(receipt, mode) => {
                setReceipts((rs) => {
                  const exists = rs.some((r) => r.receipt_id === receipt.receipt_id);
                  return exists ? rs.map((r) => (r.receipt_id === receipt.receipt_id ? receipt : r)) : [receipt, ...rs];
                });
                setShowForm(false);
                setEditing(null);
                setOcrDraft(null);
                setPendingImage(null);
                setToast(mode === 'edit' ? 'Receipt updated ✓' : 'Receipt saved ✓');
                if (mode === 'create') celebrate();
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
                <span className={`source-chip ${r.source_type}`}>{r.source_type === 'camera' ? 'scanned' : 'manual'}</span>
                <span className="receipt-total">R{r.total_amount}</span>
                <div className="receipt-actions">
                  <button className="icon-button" title="Edit receipt" onClick={() => openEdit(r)}>
                    ✏️
                  </button>
                  <button
                    className="icon-button danger"
                    title="Delete receipt"
                    disabled={deletingId === r.receipt_id}
                    onClick={() => handleDelete(r)}
                  >
                    {deletingId === r.receipt_id ? '…' : '🗑️'}
                  </button>
                </div>
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
        {scannerOpen && (
          <SlipScanner
            onClose={() => setScannerOpen(false)}
            onScanned={(file) => {
              setScannerOpen(false);
              void handleScan(file);
            }}
          />
        )}
      </AnimatePresence>

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
  editing,
  ocrDraft,
  pendingImage,
  onSaved,
  onCancel,
}: {
  stores: Store[];
  categories: Category[];
  editing: Receipt | null;
  ocrDraft: OcrDraft | null;
  pendingImage: File | null;
  onSaved: (receipt: Receipt, mode: 'create' | 'edit') => void;
  onCancel: () => void;
}) {
  const initialItems: ItemDraft[] = useMemo(() => {
    if (editing) {
      return editing.items.map((it) => ({
        item_name: it.item_name,
        unit_price: String(it.unit_price),
        quantity: it.quantity,
        category: it.category_name ?? String(it.category),
        is_impulse: it.is_impulse,
      }));
    }
    if (ocrDraft && ocrDraft.items.length > 0) {
      return ocrDraft.items.map((it) => ({
        ...emptyItem,
        item_name: it.name,
        unit_price: String(it.price),
        category: it.category ?? '',
        is_impulse: it.is_impulse ?? false,
      }));
    }
    return [{ ...emptyItem }];
  }, [editing, ocrDraft]);

  const [storeId, setStoreId] = useState<number | ''>(editing?.store ?? '');
  const [newStoreName, setNewStoreName] = useState(
    editing?.store_name ?? (storeId ? '' : ocrDraft?.merchant_name ?? ''),
  );
  const [channelType, setChannelType] = useState<Store['channel_type']>(
    ocrDraft?.channel_type === 'Online_Ecommerce' ? 'Online_Ecommerce' : 'Physical_Store',
  );
  const [purchaseDate, setPurchaseDate] = useState(
    editing?.purchase_date ?? ocrDraft?.purchase_date ?? new Date().toISOString().slice(0, 10),
  );
  const [items, setItems] = useState<ItemDraft[]>(initialItems);
  const [totalAmount, setTotalAmount] = useState<string>(
    editing?.total_amount ?? (ocrDraft?.total_amount != null ? String(ocrDraft.total_amount) : ''),
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const itemsTotal = useMemo(() => sumItems(items), [items]);

  function updateItem(idx: number, patch: Partial<ItemDraft>) {
    setItems((its) => its.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      let finalStoreId = storeId;
      let finalStoreName: string | undefined;
      if (!finalStoreId && newStoreName.trim()) {
        finalStoreName = newStoreName.trim();
      }
      if (!finalStoreId && !finalStoreName) throw new Error('Select or add a store');

      const filled = items.filter((it) => it.item_name.trim());
      if (filled.length === 0) throw new Error('Add at least one line item with a name');

      const payload = {
        store: finalStoreId || undefined,
        store_name: finalStoreName,
        channel_type: channelType,
        purchase_date: purchaseDate,
        total_amount: (totalAmount !== '' ? Number(totalAmount) : itemsTotal).toFixed(2),
        source_type: pendingImage ? ('camera' as const) : ('upload' as const),
        verified: true,
        items: filled.map((it) => ({
          item_name: it.item_name.trim(),
          unit_price: it.unit_price === '' ? '0.00' : it.unit_price,
          quantity: Math.max(1, Number(it.quantity) || 1),
          category: it.category.trim() || 'Other',
          is_impulse: it.is_impulse,
        })),
      };

      const receipt = editing
        ? await updateReceipt(editing.receipt_id, payload)
        : await createReceipt(payload);

      if (pendingImage && !editing) {
        await attachReceiptImage(receipt.receipt_id, pendingImage);
      }

      onSaved(receipt, editing ? 'edit' : 'create');
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || (err instanceof Error ? err.message : 'Could not save this receipt.'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="receipt-form" onSubmit={handleSubmit}>
      <div className="form-title-row">
        <h2>{editing ? 'Edit receipt' : 'Verify & save receipt'}</h2>
        {ocrDraft && (
          <span className={`engine-chip ${ocrDraft.engine}`}>
            {ocrDraft.engine === 'gemini' ? '🤖 AI read' : '⚙️ OCR read'}
            {ocrDraft.confidence ? ` · ${Math.round(ocrDraft.confidence * 100)}%` : ''}
          </span>
        )}
      </div>
      {ocrDraft && (
        <p className="ocr-hint">
          Auto-filled{ocrDraft.engine === 'gemini' ? ' by AI' : ''} from your photo — check the store, date, prices and
          categories below before saving.
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
          <>
            <label>
              New store name
              <input
                value={newStoreName}
                onChange={(e) => setNewStoreName(e.target.value)}
                placeholder="e.g. Checkers"
                required
              />
            </label>
            <label>
              Channel
              <select value={channelType} onChange={(e) => setChannelType(e.target.value as Store['channel_type'])}>
                <option value="Physical_Store">Physical store</option>
                <option value="Online_Ecommerce">Online / ecommerce</option>
              </select>
            </label>
          </>
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
            min="0"
            placeholder="Unit price"
            value={it.unit_price}
            onChange={(e) => updateItem(idx, { unit_price: e.target.value })}
          />
          <input
            type="number"
            min={1}
            title="Quantity"
            value={it.quantity}
            onChange={(e) => updateItem(idx, { quantity: Number(e.target.value) })}
          />
          <input
            placeholder={`Category (e.g. ${categories[0]?.category_name ?? 'Groceries'})`}
            list="category-options"
            value={it.category}
            onChange={(e) => updateItem(idx, { category: e.target.value })}
          />
          <label className="checkbox-label" title="Non-essential impulse buy">
            <input
              type="checkbox"
              checked={it.is_impulse}
              onChange={(e) => updateItem(idx, { is_impulse: e.target.checked })}
            />
            Impulse
          </label>
          <button
            type="button"
            className="icon-button danger"
            title="Remove line item"
            onClick={() => setItems((its) => its.filter((_, i) => i !== idx))}
            disabled={items.length === 1}
          >
            ✕
          </button>
        </div>
      ))}
      <datalist id="category-options">
        {categories.map((c) => (
          <option key={c.category_id} value={c.category_name} />
        ))}
      </datalist>

      <div className="form-row total-row">
        <button type="button" className="button-secondary" onClick={() => setItems((its) => [...its, { ...emptyItem }])}>
          + Add line item
        </button>
        <label>
          Total (R)
          <input
            type="number"
            step="0.01"
            min="0"
            value={totalAmount}
            placeholder={itemsTotal.toFixed(2)}
            onChange={(e) => setTotalAmount(e.target.value)}
          />
        </label>
        <span className="items-sum">
          items sum: <strong className="num-tick">R{itemsTotal.toFixed(2)}</strong>
        </span>
      </div>

      {error && <p className="form-error">{error}</p>}
      <div className="form-actions">
        <button type="submit" disabled={submitting}>
          {submitting ? 'Saving…' : editing ? 'Save changes' : 'Save receipt'}
        </button>
        <button type="button" className="button-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
