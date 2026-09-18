import { Link } from 'react-router-dom';
import { motion, type Variants } from 'framer-motion';
import StoryScene from '../components/StoryScene';

const container: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.12, delayChildren: 0.15 } },
};

const rise: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: 'easeOut' } },
};

const pop: Variants = {
  hidden: { opacity: 0, scale: 0.85 },
  show: { opacity: 1, scale: 1, transition: { type: 'spring', stiffness: 320, damping: 22 } },
};

const STEPS = [
  {
    n: '01',
    title: 'Snap the slip',
    body: 'Photograph any till slip or upload the PDF. No typing, no spreadsheets — the camera does the data entry.',
    chip: '📷',
  },
  {
    n: '02',
    title: 'AI reads it',
    body: 'Gemini vision pulls the store, date, every line item, and the total straight off the paper — then suggests categories and flags impulse buys.',
    chip: '🤖',
  },
  {
    n: '03',
    title: 'Close the month in the green',
    body: 'A live budget thermometer, category donut, and one-click Monthly Audit PDF show exactly where the money leaked.',
    chip: '🧾',
  },
];

const FEATURES = [
  {
    title: 'Real receipt AI',
    body: 'Crumpled photo? Fine print? Multi-column layout? The vision model reads it and drafts the whole receipt for you to check — you stay the verifier.',
    accent: 'var(--indigo)',
    chip: 'AI read · 98%',
  },
  {
    title: 'Budget thermometer',
    body: 'A live gauge fills as you spend. The second you cross the line, it flips red — no more end-of-month surprises.',
    accent: 'var(--grow-bright)',
    chip: 'R1 240 of R3 000',
  },
  {
    title: 'Impulse-spend audit',
    body: 'Snacks, energy drinks, gadgets — every non-essential line is flagged and tallied, so you see what “just one treat” costs per month.',
    accent: 'var(--spend-bright)',
    chip: 'Impulse: R212',
  },
  {
    title: 'Monthly audit PDF',
    body: 'Budget variance, daily spikes, impulse audit, and store comparison — the full report your budgeter asked for, in one click.',
    accent: 'var(--gold-bright)',
    chip: 'Audit · Aug 2026',
  },
];

export default function Landing() {
  return (
    <div className="landing">
      <motion.header
        className="landing-nav"
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <span className="brand">
          <span className="brand-mark">R:</span>
          SmartSpend
        </span>
        <div className="landing-nav-actions">
          <Link to="/login" className="landing-link">Log in</Link>
          <Link to="/register" className="landing-cta-sm">Get started</Link>
        </div>
      </motion.header>

      {/* ---------------- hero ---------------- */}
      <section className="hero">
        <motion.div className="hero-copy" variants={container} initial="hidden" animate="show">
          <motion.span className="hero-eyebrow" variants={pop}>Student budgeting, minus the admin</motion.span>
          <motion.h1 variants={rise}>
            Snap the slip.<br />
            <em>We do the sums.</em>
          </motion.h1>
          <motion.p variants={rise}>
            SmartSpend turns any receipt photo into a categorized, impulse-flagged
            expense — then holds it against your monthly budget so every rand is
            accounted for before it's gone.
          </motion.p>
          <motion.div className="hero-actions" variants={rise}>
            <Link to="/register" className="landing-cta">Create your free account</Link>
            <Link to="/login" className="landing-cta ghost">I have an account</Link>
          </motion.div>
          <motion.ul className="hero-ticks" variants={rise}>
            <li>✓ AI receipt extraction</li>
            <li>✓ Email or SMS code login</li>
            <li>✓ Monthly audit PDF</li>
          </motion.ul>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 24, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.6, ease: 'easeOut', delay: 0.25 }}
          style={{ width: '100%', display: 'flex', justifyContent: 'center' }}
        >
          <StoryScene />
        </motion.div>
      </section>

      {/* ---------------- how it works ---------------- */}
      <motion.section
        className="landing-steps"
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: '-80px' }}
      >
        <motion.h2 variants={rise}>From paper to plan in three moves</motion.h2>
        <div className="steps-grid">
          {STEPS.map((s) => (
            <motion.article className="step-card" key={s.n} variants={rise}>
              <div className="step-top">
                <span className="step-n num-tick">{s.n}</span>
                <span className="step-chip">{s.chip}</span>
              </div>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </motion.article>
          ))}
        </div>
      </motion.section>

      {/* ---------------- features ---------------- */}
      <motion.section
        className="landing-features"
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: '-80px' }}
      >
        <motion.h2 variants={rise}>Built like a till slip, wired like a CFO</motion.h2>
        <div className="features-grid">
          {FEATURES.map((f) => (
            <motion.article className="feature-card" key={f.title} variants={rise} style={{ ['--accent' as string]: f.accent }}>
              <span className="feature-chip num-tick">{f.chip}</span>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </motion.article>
          ))}
        </div>
      </motion.section>

      {/* ---------------- closing CTA ---------------- */}
      <motion.section
        className="landing-close"
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: '-60px' }}
      >
        <motion.h2 variants={rise}>Your budget has been guessing long enough.</motion.h2>
        <motion.p variants={rise}>Free account · sign in with just your email or phone · receipts stay yours.</motion.p>
        <motion.div variants={pop}>
          <Link to="/register" className="landing-cta big">Start with your next receipt</Link>
        </motion.div>
      </motion.section>

      <footer className="landing-footer">
        <span>© 2026 SmartSpend — every rand accounted for.</span>
      </footer>
    </div>
  );
}
