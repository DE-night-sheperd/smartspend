import { describe, expect, it } from 'vitest';
import { playSound } from '../lib/sounds';

describe('sounds', () => {
  // jsdom has no AudioContext — playSound must degrade to a no-op there.

  it('plays nothing (silently) when every sound is invoked without AudioContext', () => {
    // The contract: every name is safe to fire anywhere, including jsdom.
    for (const name of ['chaChing', 'beep', 'success', 'error', 'pop', 'swipe'] as const) {
      expect(() => playSound(name)).not.toThrow();
    }
  });
});
