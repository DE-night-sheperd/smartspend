import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import Landing from '../pages/Landing';
import Privacy from '../pages/Privacy';
import Points from '../pages/Points';
import Receipts from '../pages/Receipts';
import Settings from '../pages/Settings';
import { AuthProvider, useAuth } from '../context/AuthContext';
import { tokenStore } from '../api/client';
import type { User } from '../types';

vi.mock('../api/endpoints');

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
  it('shows the app entrance with create-account and login CTAs', () => {
    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Create account' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Log in' })).toBeInTheDocument();
    expect(screen.getByText('Scan slips, track spending, stay in budget.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Privacy' })).toBeInTheDocument();
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
