import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useAuth } from '../context/AuthContext';
import { playSound } from '../lib/sounds';

/**
 * R: — the SmartSpend receipt-ranger mascot. After login it walks new users
 * through the four surfaces of the app, one card at a time. Runs once per
 * user (flagged in localStorage); "Skip" or finishing marks it done so it
 * never nags again.
 */

interface TourStep {
  /** Route the tour navigates to so the user sees the real surface. */
  to: string;
  /** What R: says. */
  line: string;
}

const STEPS: TourStep[] = [
  {
    to: '/dashboard',
    line: 'Hi, I\'m R: — your receipt ranger! This is your Monthly Financial Audit. Every slip you scan lands here as a live tally against your budget.',
  },
  {
    to: '/receipts',
    line: 'This is the till. Snap or upload a receipt, check the details R: pulled off it, and save. Impulse buys get flagged automatically.',
  },
  {
    to: '/points',
    line: 'Your loyalty points ledger. R: keeps the balances per store and warns you 7 days before points expire.',
  },
  {
    to: '/settings',
    line: 'Last stop — set your monthly budget here, and connect your own free Gemini key so scans use your AI quota. That\'s it, you\'re set!',
  },
];

function doneKey(userId: string): string {
  return `smartspend_tour_done_${userId}`;
}

export function isTourDone(userId: string): boolean {
  try {
    return localStorage.getItem(doneKey(userId)) === '1';
  } catch {
    return true; // storage unavailable — never nag
  }
}

export function markTourDone(userId: string): void {
  try {
    localStorage.setItem(doneKey(userId), '1');
  } catch {
    // storage unavailable — the tour simply shows again next visit
  }
}

export default function MascotTour() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [stepIndex, setStepIndex] = useState(0);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (user && !isTourDone(user.user_id)) {
      // Small delay so the dashboard's own entrance animation settles first.
      const t = setTimeout(() => setOpen(true), 900);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [user]);

  const finish = useCallback(() => {
    if (user) markTourDone(user.user_id);
    setOpen(false);
    playSound('pop');
  }, [user]);

  // Escape closes the tour — same contract as the rest of the app's overlays.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') finish();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, finish]);

  if (!user || !open) return null;

  const step = STEPS[stepIndex];
  const isLast = stepIndex === STEPS.length - 1;

  function next() {
    playSound('beep');
    if (isLast) {
      finish();
      return;
    }
    const nextIndex = stepIndex + 1;
    setStepIndex(nextIndex);
    navigate(STEPS[nextIndex].to);
  }

  function skip() {
    finish();
  }

  return (
    <AnimatePresence>
      <motion.aside
        className="mascot-tour"
        role="dialog"
        aria-label="Guided walkthrough from R:, the SmartSpend mascot"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 24 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
      >
        <div className="mascot-avatar" aria-hidden="true">
          <span className="mascot-face">R:</span>
          <span className="mascot-eye" />
        </div>
        <div className="mascot-bubble">
          <p className="mascot-msg" aria-live="polite">{step.line}</p>
          <div className="mascot-progress" aria-hidden="true">
            {STEPS.map((s, i) => (
              <span key={s.to} className={`mascot-dot${i <= stepIndex ? ' on' : ''}`} />
            ))}
          </div>
          <div className="mascot-actions">
            <button type="button" className="link-button" onClick={skip}>
              Skip tour
            </button>
            <span className="mascot-stepcount">
              {stepIndex + 1} / {STEPS.length}
            </span>
            <button type="button" className="mascot-next" onClick={next} autoFocus>
              {isLast ? "Let's go 🎉" : 'Next'}
            </button>
          </div>
        </div>
      </motion.aside>
    </AnimatePresence>
  );
}
