import confetti from 'canvas-confetti';

/** Fired when the user does something worth celebrating — saving a receipt
 * under budget, closing out a month with a positive variance. Skips
 * entirely if the user has requested reduced motion. */
export function celebrate() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

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
