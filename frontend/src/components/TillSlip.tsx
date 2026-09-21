import { useMemo, useState } from 'react';
import type { Receipt } from '../types';

/**
 * TillSlip — renders a saved receipt as a realistic till slip: torn zigzag
 * top/bottom edges, dot-matrix monospace rows with dotted leaders, a
 * barcode-style footer and slip identity (cashier/branch/slip no./payment).
 *
 * Two jobs:
 * 1. In the receipts list — the receipt card IS the slip.
 * 2. Print (window.print with a print-only stylesheet) — the user can show
 *    or hand over the digital slip for returns/disputes at the store. The
 *    tapped slip gets a temporary .print-target class so exactly one slip
 *    prints, even with a full list on the page.
 */

// Deterministic pseudo-barcode from the receipt id: bar widths vary but are
// stable for a given receipt, so the same slip always looks the same.
function barcodeBars(seed: number, count = 42): { w: number; gap: boolean }[] {
  let x = seed * 2654435761;
  return Array.from({ length: count }, (_, i) => {
    x = (x * 1103515245 + 12345) & 0x7fffffff;
    const w = 1 + (x % 3);
    void i;
    return { w, gap: (x >> 5) % 2 === 0 };
  });
}

function dots(name: string, price: string): { name: string; dots: string; price: string } {
  const target = 34;
  const used = name.length + price.length;
  const n = Math.max(3, target - used);
  return { name, dots: '.'.repeat(n), price };
}

/** Print exactly this slip: mark it, run the browser's print dialog, then
 * unmark whatever the dialog left marked. */
function printOnlySlip(slip: Element) {
  slip.classList.add('print-target');
  const cleanup = () => {
    document.querySelectorAll('.print-target').forEach((el) => el.classList.remove('print-target'));
    window.removeEventListener('afterprint', cleanup);
  };
  window.addEventListener('afterprint', cleanup);
  window.print();
  // afterprint is unreliable in some browsers — also clean up on the next tick
  // (the print dialog blocks JS, so this runs only after it closes).
  setTimeout(cleanup, 500);
}

export default function TillSlip({ receipt, expanded = false }: { receipt: Receipt; expanded?: boolean }) {
  const bars = useMemo(() => barcodeBars(receipt.receipt_id), [receipt.receipt_id]);
  const [showOriginal, setShowOriginal] = useState(false);
  const slipNo = receipt.slip_number || `SS-${String(receipt.receipt_id).padStart(6, '0')}`;
  const originalLines = (receipt.original_text ?? '').split('\n').filter((ln) => ln.trim().length > 0);

  const lines = receipt.items.map((it) => ({
    key: it.item_id,
    ...dots(
      `${it.item_name}${it.quantity > 1 ? ` x${it.quantity}` : ''}`,
      `R${Number(it.line_total ?? Number(it.unit_price) * it.quantity).toFixed(2)}`,
    ),
    isImpulse: it.is_impulse,
    category: it.category_name,
  }));

  const date = new Date(receipt.purchase_date);
  const dateStr = `${String(date.getDate()).padStart(2, '0')}/${String(date.getMonth() + 1).padStart(2, '0')}/${date.getFullYear()}`;

  return (
    <div className={`till-slip ${expanded ? 'till-slip-expanded' : ''}`} data-receipt={receipt.receipt_id}>
      <div className="till-zigzag till-zigzag-top" aria-hidden="true" />
      <div className="till-body">
        <div className="till-head">
          <div className="till-store">{receipt.store_name ?? 'RECEIPT'}</div>
          {receipt.branch_name && <div className="till-sub">{receipt.branch_name}</div>}
          <div className="till-sub">{dateStr}</div>
        </div>

        <div className="till-meta">
          {receipt.cashier_name && (
            <div className="till-meta-row">
              <span>Cashier</span>
              <span className="till-meta-val">{receipt.cashier_name}</span>
            </div>
          )}
          <div className="till-meta-row">
            <span>Slip no.</span>
            <span className="till-meta-val">{slipNo}</span>
          </div>
          {receipt.payment_method && (
            <div className="till-meta-row">
              <span>Paid</span>
              <span className="till-meta-val">{receipt.payment_method}</span>
            </div>
          )}
        </div>

        {(originalLines.length > 0 || receipt.items.length > 0) && (
          <div className="till-view-toggle no-print" role="tablist" aria-label="Slip view">
            <button
              type="button"
              role="tab"
              aria-selected={!showOriginal}
              className={!showOriginal ? 'active' : ''}
              onClick={() => setShowOriginal(false)}
            >
              Clean
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={showOriginal}
              className={showOriginal ? 'active' : ''}
              onClick={() => setShowOriginal(true)}
              disabled={originalLines.length === 0}
              title={originalLines.length === 0 ? 'No original transcription captured' : 'The slip exactly as printed'}
            >
              Original
            </button>
          </div>
        )}

        {showOriginal ? (
          <div className="till-original">
            {originalLines.map((ln, i) => (
              <div key={i} className="till-original-line">{ln}</div>
            ))}
          </div>
        ) : (
          <>
            <div className="till-divider" aria-hidden="true">
              ···· ITEMS ····
            </div>

            <ul className="till-items">
              {lines.map((l) => (
                <li key={l.key} className="till-item" title={l.isImpulse ? 'Flagged impulse buy' : l.category}>
                  <span className="till-item-name">
                    {l.isImpulse && <em className="till-impulse">*</em>}
                    {l.name}
                  </span>
                  <span className="till-item-dots">{l.dots}</span>
                  <span className="till-item-price">{l.price}</span>
                </li>
              ))}
            </ul>

            <div className="till-total-row">
              <span>TOTAL</span>
              <span className="till-total-num">R{Number(receipt.total_amount).toFixed(2)}</span>
            </div>
          </>
        )}

        <div className="till-barcode" aria-hidden="true">
          {bars.map((b, i) => (
            <span key={i} className={b.gap ? 'bar gap' : 'bar'} style={{ width: `${b.w}px` }} />
          ))}
        </div>
        <div className="till-foot">{slipNo.replace(/\s+/g, '')}</div>
        <div className="till-thanks">* impulse buy — keep this slip for returns *</div>

        <div className="till-print-row no-print">
          <button
            type="button"
            className="button-secondary till-print-btn"
            onClick={(e) => {
              const slip = e.currentTarget.closest('.till-slip');
              if (slip) printOnlySlip(slip);
            }}
          >
            🖨️ Print return slip
          </button>
        </div>
      </div>
      <div className="till-zigzag till-zigzag-bottom" aria-hidden="true" />
    </div>
  );
}
