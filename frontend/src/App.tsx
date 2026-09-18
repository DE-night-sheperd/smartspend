import { AnimatePresence, motion } from 'framer-motion';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import NavBar from './components/NavBar';
import Login from './pages/Login';
import LoginPassword from './pages/LoginPassword';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import Receipts from './pages/Receipts';
import Settings from './pages/Settings';
import './App.css';

function AnimatedRoutes() {
  const location = useLocation();
  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/login" element={<PageFade><Login /></PageFade>} />
        <Route path="/login-password" element={<PageFade><LoginPassword /></PageFade>} />
        <Route path="/register" element={<PageFade><Register /></PageFade>} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <PageFade><Dashboard /></PageFade>
            </ProtectedRoute>
          }
        />
        <Route
          path="/receipts"
          element={
            <ProtectedRoute>
              <PageFade><Receipts /></PageFade>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings"
          element={
            <ProtectedRoute>
              <PageFade><Settings /></PageFade>
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AnimatePresence>
  );
}

function PageFade({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <NavBar />
        <AnimatedRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
