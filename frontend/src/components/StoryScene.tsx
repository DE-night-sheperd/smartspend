import { motion, useReducedMotion } from 'framer-motion';

/**
 * StoryScene — the SmartSpend story as a looping cartoon:
 * walk in → grab a basket → shop → pay → walk out → snap the slip
 * with the phone → bin the paper → keep the receipt digitally.
 *
 * One 14-second timeline; every element is keyframed against the same
 * duration so the whole cast stays in sync. All sizes use container-query
 * units (cqw) so the scene scales fluidly. Respects prefers-reduced-motion
 * with a static final-state frame.
 */

const D = 14; // seconds per loop
const at = (...secs: number[]) => secs.map((s) => s / D);

// Character stops along the stage (percent of stage width).
const X_DOOR_IN = 2;
const X_BASKET = 13;
const X_SHELF = 34;
const X_TILL = 54;
const X_OUTSIDE = 70;
const X_END = 88;

/** Beat timings (seconds) shared across elements. */
const B_PICK = 2.2; // basket picked up
const B_TILL = 5.5; // arrives at till
const B_PAYED = 6.0; // payment done, basket down
const B_OUT = 7.0; // outside the door
const B_SCANNED = 9.5; // scan finished
const B_TOSSED = 10.3; // paper binned
const B_END = 12.3; // final pose
const B_PHONE = 12.5; // digital receipt chip

const loop = {
  duration: D,
  repeat: Infinity,
  ease: 'linear' as const,
};

/** The shopper's 12-stop journey, shared by position and bounce. */
const PERSON_TIMES = at(0, 1.5, B_PICK, 4.0, 4.2, B_TILL, B_PAYED, B_OUT, B_SCANNED, B_TOSSED, B_END, D);
const PERSON_LEFT = [
  `${X_DOOR_IN}%`, `${X_BASKET}%`, `${X_BASKET}%`, `${X_SHELF}%`, `${X_SHELF}%`,
  `${X_TILL}%`, `${X_TILL}%`, `${X_OUTSIDE}%`, `${X_OUTSIDE}%`, `${X_OUTSIDE}%`,
  `${X_END}%`, `${X_END}%`,
];
const PERSON_BOUNCE = [0, -3, 0, -3, 0, -3, 0, -3, 0, 0, -3, 0];

const CAPTIONS = [
  { text: 'Shop like normal.', on: 0.001, off: 4.1 },
  { text: 'Pay and keep the slip.', on: 4.4, off: 6.7 },
  { text: 'Scan the slip with your phone.', on: 7.0, off: 10.0 },
  { text: 'Throw the paper away. The receipt stays in the app.', on: 10.3, off: 13.4 },
];

function Person({ children }: { children?: React.ReactNode }) {
  return (
    <motion.div
      className="cart-person"
      initial={{ left: `${X_DOOR_IN}%` }}
      animate={{ left: PERSON_LEFT, y: PERSON_BOUNCE }}
      transition={{
        ...loop,
        left: { ...loop, times: PERSON_TIMES },
        y: { ...loop, times: PERSON_TIMES },
      }}
    >
      <div className="person-shadow" />
      <div className="person-body">
        <div className="person-head">
          <div className="person-cap" />
        </div>
      </div>
      <div className="person-legs" />
      {children}
    </motion.div>
  );
}

function Scene() {
  return (
    <div className="story-scene" aria-label="Cartoon: a shopper pays at a till, scans the paper receipt with their phone, bins the paper, and keeps the receipt digitally">
      <div className="scene-stage">
        {/* --- backdrop: store interior + outside --- */}
        <div className="scene-wall" />
        <div className="scene-sky" />
        <div className="scene-sun" />
        <div className="scene-cloud" />
        <div className="scene-floor" />
        <div className="scene-sign num-tick">THE CORNER STORE</div>

        {/* sliding door between inside and outside */}
        <motion.div
          className="scene-door"
          initial={{ scaleX: 1 }}
          animate={{ scaleX: [1, 1, 0.12, 0.12, 1, 1] }}
          transition={{ ...loop, times: at(0, 6.2, 6.7, 7.4, 7.9, D) }}
        >
          <div className="door-handle" />
        </motion.div>

        {/* shelf + goods */}
        <div className="scene-shelf" />
        <div className="shelf-item bottle" />
        <div className="shelf-item can" />
        <div className="shelf-item box" />
        {/* items dropping into the basket while shopping */}
        {[
          { t: 2.8, cls: 'fly-0', top: '18.5%' },
          { t: 3.2, cls: 'fly-1', top: '21%' },
          { t: 3.6, cls: 'fly-2', top: '19.5%' },
        ].map((f) => (
          <motion.div
            key={f.cls}
            className={`shelf-fly ${f.cls}`}
            initial={{ opacity: 0, top: f.top }}
            animate={{
              opacity: [0, 0, 1, 1, 0, 0],
              top: [f.top, f.top, f.top, '33%', '35%', '35%'],
            }}
            transition={{
              ...loop,
              opacity: { ...loop, times: at(0, f.t - 0.1, f.t - 0.02, f.t + 0.18, f.t + 0.24, D) },
              top: { ...loop, times: at(0, f.t - 0.02, f.t, f.t + 0.24, f.t + 0.35, D) },
            }}
          />
        ))}

        {/* basket stand */}
        <div className="scene-stand" />
        <motion.div
          className="stand-basket basket-shape"
          initial={{ opacity: 1 }}
          animate={{ opacity: [1, 1, 0, 0] }}
          transition={{ ...loop, times: at(0, B_PICK - 0.1, B_PICK, D) }}
        />

        {/* till + counter */}
        <div className="scene-counter" />
        <div className="till-screen num-tick">R196.97</div>
        <motion.div
          className="till-paper"
          initial={{ scaleY: 0 }}
          animate={{ scaleY: [0, 0, 1, 1, 0] }}
          transition={{ ...loop, times: at(0, 4.6, 5.4, 13.4, D) }}
        >
          <span /><span /><span />
        </motion.div>
        <motion.div
          className="pay-beep num-tick"
          initial={{ opacity: 0, scale: 0.4 }}
          animate={{ opacity: [0, 0, 1, 1, 0, 0], scale: [0.4, 0.4, 1.15, 1, 0.6, 0.4] }}
          transition={{
            ...loop,
            opacity: { ...loop, times: at(0, 5.0, 5.3, 5.7, 5.95, D) },
            scale: { ...loop, times: at(0, 5.0, 5.3, 5.7, 5.95, D) },
          }}
        >
          ✓ paid
        </motion.div>
        <motion.div
          className="counter-basket basket-shape"
          initial={{ opacity: 0 }}
          animate={{ opacity: [0, 0, 1, 1, 0, 0] }}
          transition={{ ...loop, times: at(0, B_PAYED, B_PAYED + 0.15, 7.4, 7.7, D) }}
        />

        {/* dustbin outside */}
        <motion.div
          className="bin-lid"
          initial={{ rotate: 0 }}
          animate={{ rotate: [0, 0, -38, -10, 0, 0] }}
          transition={{ ...loop, times: at(0, 9.5, 9.75, 10.05, 10.3, D) }}
        />
        <div className="scene-bin" />
        <motion.div
          className="bin-ball"
          initial={{ opacity: 0, scale: 0.4 }}
          animate={{ opacity: [0, 0, 1, 1], scale: [0.4, 0.4, 1.1, 1] }}
          transition={{ ...loop, times: at(0, 10.1, 10.35, D) }}
        />

        {/* the shopper — carried props live inside so they move along */}
        <Person>
          {/* basket in hand */}
          <motion.div
            className="hand-basket basket-shape"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0, 1, 1, 0, 0] }}
            transition={{ ...loop, times: at(0, B_PICK - 0.1, B_PICK, B_TILL, B_PAYED, D) }}
          />
          {/* paper slip in hand, scanned, then tossed into the bin */}
          <motion.div
            className="hand-paper"
            initial={{ opacity: 0, x: 0, y: 0, rotate: 0 }}
            animate={{
              opacity: [0, 0, 1, 1, 1, 1, 0, 0],
              x: [0, 0, 0, 0, 26, 30, 30, 30],
              y: [0, 0, 0, 0, 20, 24, 24, 24],
              rotate: [0, 0, 0, 0, 110, 140, 140, 140],
            }}
            transition={{
              ...loop,
              opacity: { ...loop, times: at(0, B_PAYED - 0.2, B_PAYED - 0.05, 9.8, 10.05, 10.25, 10.4, D) },
              x: { ...loop, times: at(0, B_PAYED - 0.2, B_PAYED - 0.05, 9.8, 10.05, 10.25, 10.4, D) },
              y: { ...loop, times: at(0, B_PAYED - 0.2, B_PAYED - 0.05, 9.8, 10.05, 10.25, 10.4, D) },
              rotate: { ...loop, times: at(0, B_PAYED - 0.2, B_PAYED - 0.05, 9.8, 10.05, 10.25, 10.4, D) },
            }}
          >
            <motion.span
              className="hand-paper-sweep"
              initial={{ top: '0%' }}
              animate={{ top: ['0%', '0%', '100%', '100%'] }}
              transition={{ ...loop, times: at(0, 7.8, 9.3, D) }}
            />
            <span /><span /><span /><span />
          </motion.div>
          {/* scan confirmation chip */}
          <motion.div
            className="scan-chip"
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: [0, 0, 1, 1, 0, 0], scale: [0.5, 0.5, 1.15, 1, 0.7, 0.5] }}
            transition={{
              ...loop,
              opacity: { ...loop, times: at(0, 9.3, 9.6, 10.0, 10.25, D) },
              scale: { ...loop, times: at(0, 9.3, 9.6, 10.0, 10.25, D) },
            }}
          >
            ✓ AI read
          </motion.div>
          {/* phone */}
          <motion.div
            className="hand-phone"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: [0, 0, 1, 1], y: [30, 30, 0, 0] }}
            transition={{
              ...loop,
              opacity: { ...loop, times: at(0, B_OUT, B_OUT + 0.5, D) },
              y: { ...loop, times: at(0, B_OUT, B_OUT + 0.5, D) },
            }}
          >
            <motion.span
              className="phone-screen"
              initial={{ opacity: 0 }}
              animate={{ opacity: [0, 0, 1, 1] }}
              transition={{ ...loop, times: at(0, B_PHONE, B_PHONE + 0.4, D) }}
            >
              ✓
            </motion.span>
          </motion.div>
          {/* final chip */}
          <motion.div
            className="end-chip"
            initial={{ opacity: 0, scale: 0.5 }}
            animate={{ opacity: [0, 0, 1, 1, 0], scale: [0.5, 0.5, 1.15, 1, 0.6] }}
            transition={{
              ...loop,
              opacity: { ...loop, times: at(0, B_PHONE, B_PHONE + 0.4, 13.7, D) },
              scale: { ...loop, times: at(0, B_PHONE, B_PHONE + 0.4, 13.7, D) },
            }}
          >
            Kept in SmartSpend ✓
          </motion.div>
        </Person>
      </div>

      {/* narrated captions, synced to the same timeline */}
      <div className="story-captions" aria-hidden="true">
        {CAPTIONS.map((c) => (
          <motion.span
            key={c.text}
            className="story-caption"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0, 1, 1, 0, 0] }}
            transition={{ ...loop, times: at(0, c.on, c.on + 0.4, c.off - 0.3, c.off, D) }}
          >
            {c.text}
          </motion.span>
        ))}
      </div>
    </div>
  );
}

/** Static final-state frame for prefers-reduced-motion users. */
function StillScene() {
  return (
    <div className="story-scene" aria-label="Cartoon still: a shopper outside a store holds a phone with their digital receipt; the paper slip is in the bin">
      <div className="scene-stage">
        <div className="scene-wall" />
        <div className="scene-sky" />
        <div className="scene-sun" />
        <div className="scene-cloud" />
        <div className="scene-floor" />
        <div className="scene-sign num-tick">THE CORNER STORE</div>
        <div className="scene-door"><div className="door-handle" /></div>
        <div className="scene-shelf" />
        <div className="shelf-item bottle" />
        <div className="shelf-item can" />
        <div className="shelf-item box" />
        <div className="scene-stand" />
        <div className="scene-counter" />
        <div className="till-screen num-tick">R196.97</div>
        <div className="scene-bin" />
        <div className="bin-lid" />
        <div className="bin-ball" />
        <div className="cart-person" style={{ left: `${X_END}%` }}>
          <div className="person-shadow" />
          <div className="person-body">
            <div className="person-head"><div className="person-cap" /></div>
          </div>
          <div className="person-legs" />
          <div className="hand-phone"><span className="phone-screen">✓</span></div>
          <div className="end-chip">Kept in SmartSpend ✓</div>
        </div>
      </div>
      <div className="story-captions">
        <span className="story-caption" style={{ opacity: 1 }}>
          Throw the paper away. The receipt stays in the app.
        </span>
      </div>
    </div>
  );
}

export default function StoryScene() {
  const reduce = useReducedMotion();
  return reduce ? <StillScene /> : <Scene />;
}
