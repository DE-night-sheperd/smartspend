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

const STEPS = [
  {
    n: '01',
    title: 'Photograph the slip',
    body: 'Use your phone camera or upload an image.',
    chip: '📷',
  },
  {
    n: '02',
    title: 'Check the details',
    body: 'Store, date, items and total are filled in. Fix and save.',
    chip: '✅',
  },
  {
    n: '03',
    title: 'See your month',
    body: 'Spending by category and store, against your monthly budget.',
    chip: '📊',
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
      </motion.header>

      {/* ---------------- hero ---------------- */}
      <section className="hero">
        <motion.div className="hero-copy" variants={container} initial="hidden" animate="show">
          <motion.h1 variants={rise}>Scan slips, track spending, stay in budget.</motion.h1>
          <motion.div className="hero-actions" variants={rise}>
            <Link to="/register" className="landing-cta">Create account</Link>
            <Link to="/login" className="landing-cta ghost">Log in</Link>
          </motion.div>
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
        <motion.h2 variants={rise}>How it works</motion.h2>
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

      <footer className="landing-footer">
        <span>© 2026 SmartSpend</span>
        <Link to="/privacy" className="footer-link">
          Privacy
        </Link>
      </footer>
    </div>
  );
}
