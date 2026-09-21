import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { getMe } from '../api/endpoints';
import Dashboard from '../pages/Dashboard';
import GuestRoute from '../components/GuestRoute';
import Landing from '../pages/Landing';
import MascotTour, { isTourDone, markTourDone } from '../components/MascotTour';
import Login from '../pages/Login';
import Privacy from '../pages/Privacy';
import Points from '../pages/Points';
import Receipts from '../pages/Receipts';
import Settings from '../pages/Settings';
import { AuthProvider, useAuth } from '../context/AuthContext';
import { tokenStore } from '../api/client';
import type { BudgetAdvice, MonthBreakdown, User } from '../types';

vi.mock('../api/endpoints');
vi.mock('../lib/celebrate', () => ({ celebrate: vi.fn() }));

const me: User = {
  user_id: 'u1',
  email: 's@example.com',
  first_name: 'Sipho',
  last_name: 'N',
  phone: '',
  monthly_budget_limit: '2500.00',
  created_at: '2026-09-01T00:00:00Z',
};

/** Date string ~5 days from now so the 7-day warning window holds on any run date. */
function daysFromNow(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

describe('Landing', () => {
  it('shows the app entrance with create-account and login CTAs for signed-out visitors', async () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <Landing />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('link', { name: 'Create account' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Log in' })).toBeInTheDocument();
    expect(screen.getByText('Scan slips, track spending, stay in budget.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Privacy' })).toBeInTheDocument();
  });

  it('never pitches signup to a signed-in user — it hands them the dashboard instead', async () => {
    vi.mocked(getMe).mockResolvedValue(me);
    tokenStore.setTokens('access', 'refresh');
    render(
      <MemoryRouter>
        <AuthProvider>
          <Landing />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('link', { name: 'Go to dashboard →' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument();
    expect(screen.getByText(/Welcome back, Sipho/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Create account' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Log in' })).not.toBeInTheDocument();
    tokenStore.clear();
  });
});

describe('Privacy', () => {
  it('explains what is stored in plain language', () => {
    render(
      <MemoryRouter>
        <Privacy />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'What we store' })).toBeInTheDocument();
    expect(screen.getByText(/never sold, shared, or used for advertising/)).toBeInTheDocument();
  });
});

describe('Receipts page', () => {
  it('renders the scanner, upload, manual entry and filter toolbar', async () => {
    const { listReceipts, listStores, listCategories } = await import('../api/endpoints');
    vi.mocked(listReceipts).mockResolvedValue({ results: [], count: 0 });
    vi.mocked(listStores).mockResolvedValue([]);
    vi.mocked(listCategories).mockResolvedValue([]);

    render(
      <MemoryRouter>
        <Receipts />
      </MemoryRouter>,
    );
    expect(await screen.findByText('No receipts yet — scan or add your first one above.')).toBeInTheDocument();
    expect(screen.getByText('📷 Scan slip')).toBeInTheDocument();
    expect(screen.getByText('Upload image')).toBeInTheDocument();
    expect(screen.getByText('+ Add manually')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search store or item…')).toBeInTheDocument();
    expect(screen.getByLabelText('Sort')).toBeInTheDocument();
    expect(screen.getByText('⤓ CSV')).toBeInTheDocument();
  });
});

describe('Points page', () => {
  it('groups spendable points per store and warns about the 7-day window', async () => {
    const { listPoints } = await import('../api/endpoints');
    vi.mocked(listPoints).mockResolvedValue([
      {
        points_id: 1, store_id: 1, store_name: 'Pick n Pay', label: 'Smart Shopper points',
        points: 250, expires_at: daysFromNow(5), created_at: '',
      },
      {
        points_id: 2, store_id: 2, store_name: 'Clicks', label: 'ClubCard points',
        points: 500, expires_at: null, created_at: '',
      },
    ]);

    render(
      <MemoryRouter>
        <Points />
      </MemoryRouter>,
    );
    expect(await screen.findByText('Pick n Pay')).toBeInTheDocument();
    expect(screen.getByText('Clicks')).toBeInTheDocument();
    expect(screen.getByText(/points expire within 7 days/)).toBeInTheDocument();
    expect(screen.getByText('750')).toBeInTheDocument(); // total across stores
    expect(screen.getByText(/points across 2 stores/)).toBeInTheDocument();
    expect(screen.getByText('Show expired points')).toBeInTheDocument();
  });

  it('shows the empty state when no points have been scanned', async () => {
    const { listPoints } = await import('../api/endpoints');
    vi.mocked(listPoints).mockResolvedValue([]);

    render(
      <MemoryRouter>
        <Points />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText(/Scan a Pick n Pay or Clicks slip/),
    ).toBeInTheDocument();
    expect(screen.getByText('+ Add points')).toBeInTheDocument();
  });
});

describe('Dashboard', () => {
  const breakdown: MonthBreakdown = {
    year: 2026,
    month: 9,
    total_spent: '260.00',
    impulse_spend: '120.00',
    essential_spend: '140.00',
    budget_limit: '1000.00',
    budget_variance: '740.00',
    daily_totals: { '2026-09-02': '120.00', '2026-09-09': '70.00' },
    categories: [{ category_name: 'Snacks & Drinks', is_essential: false, total: '165.00', item_count: 3 }],
    stores: [{ store_name: 'Checkers', channel_type: 'Physical_Store', total: '260.00', receipt_count: 4 }],
    channels: { Physical_Store: '260.00' },
    biggest_purchase: { item_name: 'Coke 2L', line_total: '120.00', store_name: 'Checkers', purchase_date: '2026-09-02' },
  };
  const advice: BudgetAdvice = {
    year: 2026,
    month: 9,
    budget_limit: '1000.00',
    total_spent: '260.00',
    has_budget: true,
    suggestions: [
      {
        kind: 'impulse',
        title: 'Skip the impulse buys',
        detail: '2 impulse purchase(s) cost R120.00 this month.',
        potential_saving: '120.00',
      },
      {
        kind: 'store_frequency',
        title: 'Batch your Checkers trips',
        detail: '4 separate trips to Checkers this month averaged R65.00 each.',
        potential_saving: '65.00',
      },
    ],
    potential_total_saving: '185.00',
  };

  function renderDashboard() {
    tokenStore.setTokens('access', 'refresh');
    return render(
      <MemoryRouter>
        <AuthProvider>
          <Dashboard />
        </AuthProvider>
      </MemoryRouter>,
    );
  }

  it('shows the Ways to save card with every suggestion and the total', async () => {
    const { getMonthBreakdown, getBudgetAdvice, getMonthlyAnalytics, listPoints, getGeminiKeyStatus } =
      await import('../api/endpoints');
    vi.mocked(getMonthBreakdown).mockResolvedValue(breakdown);
    vi.mocked(getBudgetAdvice).mockResolvedValue(advice);
    vi.mocked(getMonthlyAnalytics).mockResolvedValue([]);
    vi.mocked(listPoints).mockResolvedValue([]);
    vi.mocked(getGeminiKeyStatus).mockResolvedValue({ connected: true, key_hint: '' });

    renderDashboard();

    expect(await screen.findByText(/Ways to save this month/)).toBeInTheDocument();
    expect(screen.getByText('Skip the impulse buys')).toBeInTheDocument();
    expect(screen.getByText('Batch your Checkers trips')).toBeInTheDocument();
    expect(screen.getByText('+R120.00')).toBeInTheDocument();
    expect(screen.getByText('+R65.00')).toBeInTheDocument();
    expect(screen.getByText(/Sticking to every suggestion could free up about/)).toBeInTheDocument();
    expect(screen.getByText('R185.00')).toBeInTheDocument();
  });

  it('renders no advice card when the month has nothing to suggest', async () => {
    const { getMonthBreakdown, getBudgetAdvice, getMonthlyAnalytics, listPoints, getGeminiKeyStatus } =
      await import('../api/endpoints');
    vi.mocked(getMonthBreakdown).mockResolvedValue(breakdown);
    vi.mocked(getBudgetAdvice).mockResolvedValue({ ...advice, suggestions: [], potential_total_saving: '0.00' });
    vi.mocked(getMonthlyAnalytics).mockResolvedValue([]);
    vi.mocked(listPoints).mockResolvedValue([]);
    vi.mocked(getGeminiKeyStatus).mockResolvedValue({ connected: true, key_hint: '' });

    renderDashboard();

    // The card is absent entirely, and the month itself still renders.
    await screen.findByText('Where it went');
    expect(screen.queryByText(/Ways to save this month/)).not.toBeInTheDocument();
  });

  it('collapses and expands the suggestions card on toggle', async () => {
    const { getMonthBreakdown, getBudgetAdvice, getMonthlyAnalytics, listPoints, getGeminiKeyStatus } =
      await import('../api/endpoints');
    vi.mocked(getMonthBreakdown).mockResolvedValue(breakdown);
    vi.mocked(getBudgetAdvice).mockResolvedValue(advice);
    vi.mocked(getMonthlyAnalytics).mockResolvedValue([]);
    vi.mocked(listPoints).mockResolvedValue([]);
    vi.mocked(getGeminiKeyStatus).mockResolvedValue({ connected: true, key_hint: '' });

    const user = userEvent.setup();
    renderDashboard();

    const toggle = await screen.findByRole('button', { name: /Ways to save this month/ });
    expect(screen.getByText('Skip the impulse buys')).toBeInTheDocument();
    await user.click(toggle);
    expect(screen.queryByText('Skip the impulse buys')).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByText('Skip the impulse buys')).toBeInTheDocument();
  });
});

describe('Login OTP flow', () => {
  function renderLogin(search = '') {
    return render(
      <MemoryRouter initialEntries={[`/login${search}`]}>
        <AuthProvider>
          <Login />
        </AuthProvider>
      </MemoryRouter>,
    );
  }

  it('opens the OTP holder immediately on Enter and shows the delivering state while the request is in flight', async () => {
    const user = userEvent.setup();
    const { requestLoginCode, getAuthConfig, getGeminiKeyStatus } = await import('../api/endpoints');
    vi.mocked(getAuthConfig).mockResolvedValue({ apple_enabled: false, sms_enabled: false, whatsapp_enabled: false });
    vi.mocked(getGeminiKeyStatus).mockResolvedValue({ connected: true, key_hint: '' });
    // A slow request — the OTP screen must already be up while it resolves.
    vi.mocked(requestLoginCode).mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({ detail: 'ok', transport: 'console', dev_code: '424242' }), 150)),
    );

    renderLogin();
    await screen.findByRole('heading', { name: 'Log in to SmartSpend' });

    const emailInput = screen.getByLabelText('Email');
    await user.type(emailInput, 'sipho@example.com{Enter}');

    // Optimistic switch: OTP holder visible BEFORE the request resolves.
    expect(screen.getByRole('heading', { name: 'Check your inbox' })).toBeInTheDocument();
    expect(screen.getByLabelText('Login code')).toBeInTheDocument();
    expect(screen.getByText(/Delivering your code to/)).toBeInTheDocument();

    // Once the request resolves, the delivering note is replaced by the countdown.
    await waitFor(() => expect(screen.getByText(/Resend code in/)).toBeInTheDocument());
    expect(screen.getByText(/We sent a 6-digit code to/)).toBeInTheDocument();
    expect(requestLoginCode).toHaveBeenCalledWith('sipho@example.com');
  });

  it('keeps the OTP screen open with an inline retry when sending fails', async () => {
    const user = userEvent.setup();
    const { requestLoginCode, getAuthConfig } = await import('../api/endpoints');
    vi.mocked(getAuthConfig).mockResolvedValue({ apple_enabled: false, sms_enabled: false, whatsapp_enabled: false });
    vi.mocked(requestLoginCode).mockRejectedValue({ response: { status: 502, data: { detail: 'Could not send the email right now. Please try again.' } } });

    renderLogin();
    await screen.findByRole('heading', { name: 'Log in to SmartSpend' });

    await user.type(screen.getByLabelText('Email'), 'sipho@example.com{Enter}');

    await waitFor(() => expect(screen.getByText(/Could not send the email right now/)).toBeInTheDocument());
    // Still on the OTP screen (no bounce back to the email form)…
    expect(screen.getByLabelText('Login code')).toBeInTheDocument();
    // …with an instant retry available (no countdown blocking it).
    expect(screen.getByRole('button', { name: 'Resend code' })).toBeInTheDocument();
  });

  it('pre-fills the email handed over from signup', async () => {
    const { getAuthConfig } = await import('../api/endpoints');
    vi.mocked(getAuthConfig).mockResolvedValue({ apple_enabled: false, sms_enabled: false, whatsapp_enabled: false });

    renderLogin('?email=new%40example.com');
    const emailInput = await screen.findByLabelText('Email');
    expect(emailInput).toHaveValue('new@example.com');
  });
});

describe('MascotTour', () => {
  const TOUR_KEY = 'smartspend_tour_done_u1';

  function renderTour() {
    return render(
      <MemoryRouter>
        <AuthProvider>
          <MascotTour />
        </AuthProvider>
      </MemoryRouter>,
    );
  }

  beforeEach(() => {
    localStorage.clear();
  });

  it('greets a first-time user as R: and walks all four steps, then flags itself done', async () => {
    vi.mocked(getMe).mockResolvedValue(me);
    tokenStore.setTokens('access', 'refresh');
    const user = userEvent.setup();
    renderTour();

    const dialog = await screen.findByRole('dialog', {}, { timeout: 2500 });
    expect(dialog).toHaveTextContent("Hi, I'm R:");
    expect(screen.getByText('1 / 4')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText('2 / 4')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText('3 / 4')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText('4 / 4')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Let's go/ }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(localStorage.getItem(TOUR_KEY)).toBe('1');
    tokenStore.clear();
  });

  it('never nags a user who already saw it', async () => {
    vi.mocked(getMe).mockResolvedValue(me);
    tokenStore.setTokens('access', 'refresh');
    markTourDone('u1');
    expect(isTourDone('u1')).toBe(true);
    renderTour();

    // Wait past the 900ms auto-open window — nothing may appear.
    await new Promise((resolve) => setTimeout(resolve, 1100));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    tokenStore.clear();
  });

  it('supports skipping, which also marks the tour done', async () => {
    vi.mocked(getMe).mockResolvedValue(me);
    tokenStore.setTokens('access', 'refresh');
    const user = userEvent.setup();
    renderTour();

    await screen.findByRole('dialog', {}, { timeout: 2500 });
    await user.click(screen.getByRole('button', { name: 'Skip tour' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(localStorage.getItem(TOUR_KEY)).toBe('1');
    tokenStore.clear();
  });
});

describe('GuestRoute', () => {
  function renderGuestPage(initialPath: string) {
    return render(
      <MemoryRouter initialEntries={[initialPath]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<GuestRoute><div>auth form</div></GuestRoute>} />
            <Route path="/dashboard" element={<div>the dashboard</div>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
  }

  it('bounces a signed-in user from a public auth page straight to the dashboard', async () => {
    vi.mocked(getMe).mockResolvedValue(me);
    tokenStore.setTokens('access', 'refresh');
    renderGuestPage('/login');

    expect(await screen.findByText('the dashboard')).toBeInTheDocument();
    expect(screen.queryByText('auth form')).not.toBeInTheDocument();
    tokenStore.clear();
  });

  it('renders the auth page for signed-out visitors', async () => {
    renderGuestPage('/login');

    expect(await screen.findByText('auth form')).toBeInTheDocument();
    expect(screen.queryByText('the dashboard')).not.toBeInTheDocument();
  });
});

describe('Settings page', () => {
  it('keeps the budget limit inside profile settings, after the profile fields', async () => {
    const { getMe, getGeminiKeyStatus } = await import('../api/endpoints');
    vi.mocked(getMe).mockResolvedValue(me);
    vi.mocked(getGeminiKeyStatus).mockResolvedValue({ connected: false, key_hint: '' });
    tokenStore.setTokens('access', 'refresh');

    // Mirror ProtectedRoute: Settings only mounts once auth has resolved.
    function SettingsGate() {
      const { user, loading } = useAuth();
      if (loading || !user) return <p>loading…</p>;
      return <Settings />;
    }

    render(
      <MemoryRouter>
        <AuthProvider>
          <SettingsGate />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('heading', { name: 'Profile' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Budget' })).toBeInTheDocument();
    expect(await screen.findByLabelText(/Monthly budget limit/)).toHaveValue(2500);

    // Order: the Profile section comes before the Budget section.
    const profile = screen.getByRole('heading', { name: 'Profile' });
    const budget = screen.getByRole('heading', { name: 'Budget' });
    expect(profile.compareDocumentPosition(budget) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('offers the BYOK Gemini connect flow when not connected', async () => {
    const { getMe, getGeminiKeyStatus } = await import('../api/endpoints');
    vi.mocked(getMe).mockResolvedValue(me);
    vi.mocked(getGeminiKeyStatus).mockResolvedValue({ connected: false, key_hint: '' });
    tokenStore.setTokens('access', 'refresh');

    render(
      <MemoryRouter>
        <AuthProvider>
          <Settings />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('heading', { name: 'AI scanning (Gemini)' })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /Get your free key at Google AI Studio/ }),
    ).toHaveAttribute('href', 'https://aistudio.google.com/app/apikey');
    expect(screen.getByLabelText(/Paste your Gemini API key/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect Gemini' })).toBeInTheDocument();
  });

  it('shows the connected state with a masked key hint and disconnect action', async () => {
    const { getMe, getGeminiKeyStatus } = await import('../api/endpoints');
    vi.mocked(getMe).mockResolvedValue(me);
    vi.mocked(getGeminiKeyStatus).mockResolvedValue({ connected: true, key_hint: 'AIzaS…9f2c' });
    tokenStore.setTokens('access', 'refresh');

    render(
      <MemoryRouter>
        <AuthProvider>
          <Settings />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/Connected · AIzaS…9f2c/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Connect Gemini' })).not.toBeInTheDocument();
  });
});
