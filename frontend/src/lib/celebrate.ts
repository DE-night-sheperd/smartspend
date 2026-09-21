import confetti from 'canvas-confetti';
import { playSound } from './sounds';

/** Fired when the user does something worth celebrating — saving a receipt
 * under budget, closing out a month with a positive variance. Confetti
 * skips under reduced motion; the cash-register sound respects its own
 * mute toggle (sound isn't motion). */
export function celebrate() {
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const colors = ['#2bd576', '#ffc94d', '#4a5cff'];
    confetti({
      particleCount: 70,
      spread: 65,
      origin: { y: 0.7 },
      colors,
      startVelocity: 38,
      scalar: 0.9,
      ticks: 180,
    });
  }
  playSound('chaChing');
}
