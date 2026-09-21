import { useState } from 'react';
import { isSoundMuted, playSound, setSoundMuted } from '../lib/sounds';

/** 🔊/🔇 toggle in the navbar. Default is ON; the choice persists. */
export default function SoundToggle() {
  const [muted, setMuted] = useState(() => isSoundMuted());

  return (
    <button
      type="button"
      className="sound-toggle"
      onClick={() => {
        const next = !muted;
        setSoundMuted(next);
        setMuted(next);
        if (!next) playSound('pop');
      }}
      aria-pressed={!muted}
      aria-label={muted ? 'Turn sounds on' : 'Turn sounds off'}
      title={muted ? 'Sounds off' : 'Sounds on'}
    >
      {muted ? '🔇' : '🔊'}
    </button>
  );
}
