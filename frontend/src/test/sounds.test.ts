import { beforeEach, describe, expect, it } from 'vitest';
import { isSoundMuted, playSound, setSoundMuted } from '../lib/sounds';

describe('sounds', () => {
  beforeEach(() => {
    localStorage.clear();
    // jsdom has no AudioContext — playSound must degrade to a no-op there.
    (window as unknown as { AudioContext?: unknown }).AudioContext = undefined;
  });

  it('starts unmuted and persists the mute choice', () => {
    expect(isSoundMuted()).toBe(false);
    setSoundMuted(true);
    expect(isSoundMuted()).toBe(true);
    setSoundMuted(false);
    expect(isSoundMuted()).toBe(false);
  });

  it('plays nothing (silently) when every sound is invoked without AudioContext', () => {
    // The contract: every name is safe to fire anywhere, including jsdom.
    for (const name of ['chaChing', 'beep', 'success', 'error', 'pop', 'swipe'] as const) {
      expect(() => playSound(name)).not.toThrow();
    }
  });

  it('stays a no-op when muted even with an AudioContext available', () => {
    setSoundMuted(true);
    // Even if a real context existed, muted playback must never throw.
    expect(() => playSound('chaChing')).not.toThrow();
  });
});
