import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';

export default function Privacy() {
  return (
    <div className="page privacy-page">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="privacy-card"
      >
        <h1>Privacy</h1>
        <p className="privacy-updated">Last updated: September 2026</p>

        <h2>What we store</h2>
        <p>
          Your account details (name, email, phone number), your monthly budget, and the receipts you add:
          the photos, the store, the date, and the items on them.
        </p>

        <h2>What we do with it</h2>
        <p>
          Nothing except run the app for you. When you scan a slip, the photo is sent to an AI service that
          reads the text and fills in the fields. Your data is never sold, shared, or used for advertising.
        </p>

        <h2>Logging in</h2>
        <p>
          Sign-in works with a 6-digit code sent to your email or phone. The codes expire after 10 minutes and
          can only be used once.
        </p>

        <h2>Deleting your data</h2>
        <p>Any receipt can be deleted from the Receipts page and is removed permanently.</p>

        <h2>Exporting</h2>
        <p>Use Settings → Export receipts to download everything as a CSV file at any time.</p>

        <h2>Contact</h2>
        <p>Questions about your data? Email privacy@smartspend.app.</p>

        <Link to="/" className="button-secondary privacy-back">
          ← Back
        </Link>
      </motion.div>
    </div>
  );
}
