/**
 * Tiny synthesized sound engine for the till-receipt theme — no audio
 * files, just the WebAudio API. Every sound is a few short tones (plus a
 * filtered-noise burst where it earns its keep), so the bundle stays
 * text-only and nothing blocks the first paint.
 *
 * Sounds are opt-out: a 🔊/🔇 toggle in the navbar persists to
 * localStorage, and every entry point checks it first. Playback failures
 * (no AudioContext, autoplay policy, jsdom tests) are swallowed — audio
 * is garnish, never worth an error.
 */

export type SoundName =
  | 'chaChing' // cash register — receipt saved / under budget
  | 'beep'     // scanner read complete
  | 'success'  // two ascending tones — profile saved, code verified
  | 'error'    // two descending tones — something failed
  | 'pop'      // soft blip — downloads, small confirmations
  | 'swipe';   // paper torn off — deletes

const MUTE_KEY = 'smartspend:sound-muted';

let ctx: AudioContext | null = null;

function getCtx(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const Ctor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  try {
    if (!ctx) ctx = new Ctor();
    if (ctx.state === 'suspended') void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

export function isSoundMuted(): boolean {
  try {
    return localStorage.getItem(MUTE_KEY) === '1';
  } catch {
    return false;
  }
}

export function setSoundMuted(muted: boolean): void {
  try {
    if (muted) localStorage.setItem(MUTE_KEY, '1');
    else localStorage.removeItem(MUTE_KEY);
  } catch {
    /* private mode etc. — the toggle still works for this session */
  }
}

interface ToneSpec {
  freq: number;
  /** Seconds from sound start. */
  at?: number;
  dur: number;
  type?: OscillatorType;
  gain?: number;
  /** Glide target (Hz) for slidey effects. */
  slideTo?: number;
}

function playTones(ac: AudioContext, tones: ToneSpec[]): void {
  const t0 = ac.currentTime + 0.01;
  for (const t of tones) {
    const osc = ac.createOscillator();
    const amp = ac.createGain();
    const start = t0 + (t.at ?? 0);
    const end = start + t.dur;
    const peak = t.gain ?? 0.08;

    osc.type = t.type ?? 'sine';
    osc.frequency.setValueAtTime(t.freq, start);
    if (t.slideTo) osc.frequency.exponentialRampToValueAtTime(t.slideTo, end);

    amp.gain.setValueAtTime(0.0001, start);
    amp.gain.exponentialRampToValueAtTime(peak, start + 0.012);
    amp.gain.exponentialRampToValueAtTime(0.0001, end);

    osc.connect(amp).connect(ac.destination);
    osc.start(start);
    osc.stop(end + 0.02);
  }
}

/** Short bandpassed noise burst — the till's paper/coin textures. */
function playNoise(ac: AudioContext, { at = 0, dur, freq, gain = 0.05 }: { at?: number; dur: number; freq: number; gain?: number }): void {
  const t0 = ac.currentTime + 0.01 + at;
  const frames = Math.max(1, Math.floor(ac.sampleRate * dur));
  const buffer = ac.createBuffer(1, frames, ac.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < frames; i++) data[i] = Math.random() * 2 - 1;

  const src = ac.createBufferSource();
  src.buffer = buffer;

  const band = ac.createBiquadFilter();
  band.type = 'bandpass';
  band.frequency.setValueAtTime(freq, t0);
  band.Q.value = 1.4;

  const amp = ac.createGain();
  amp.gain.setValueAtTime(0.0001, t0);
  amp.gain.exponentialRampToValueAtTime(gain, t0 + 0.015);
  amp.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);

  src.connect(band).connect(amp).connect(ac.destination);
  src.start(t0);
  src.stop(t0 + dur + 0.02);
}

/** Fire a named sound. Safe to call anywhere: muted → no-op, failures → silent. */
export function playSound(name: SoundName): void {
  if (isSoundMuted()) return;
  const ac = getCtx();
  if (!ac) return;

  try {
    switch (name) {
      case 'chaChing':
        // Drawer bang + the classic double bell + coin shimmer.
        playNoise(ac, { dur: 0.06, freq: 900, gain: 0.06 });
        playTones(ac, [
          { freq: 1318.5, dur: 0.16, type: 'triangle', gain: 0.09 }, // E6
          { freq: 1046.5, at: 0.11, dur: 0.4, type: 'triangle', gain: 0.09 }, // C6
        ]);
        playNoise(ac, { at: 0.22, dur: 0.3, freq: 5200, gain: 0.028 });
        break;
      case 'beep':
        playTones(ac, [{ freq: 1245, dur: 0.09, type: 'square', gain: 0.05 }]);
        break;
      case 'success':
        playTones(ac, [
          { freq: 523.25, dur: 0.12, type: 'sine', gain: 0.07 }, // C5
          { freq: 783.99, at: 0.1, dur: 0.22, type: 'sine', gain: 0.07 }, // G5
        ]);
        break;
      case 'error':
        playTones(ac, [
          { freq: 196, dur: 0.14, type: 'sawtooth', gain: 0.045 }, // G3
          { freq: 147, at: 0.12, dur: 0.24, type: 'sawtooth', gain: 0.045 }, // D3
        ]);
        break;
      case 'pop':
        playTones(ac, [{ freq: 320, dur: 0.07, type: 'sine', gain: 0.06, slideTo: 520 }]);
        break;
      case 'swipe':
        playNoise(ac, { dur: 0.16, freq: 2400, gain: 0.045 });
        break;
    }
  } catch {
    /* never let a sound break an interaction */
  }
}
