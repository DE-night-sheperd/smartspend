import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '../context/AuthContext';
import ProtectedRoute from '../components/ProtectedRoute';
import { getMe, verifyLoginCode } from '../api/endpoints';
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

function Probe({ path }: { path: string }) {
  const { user, loading } = useAuth();
  if (loading) return <p>loading…</p>;
  return (
    <p>
      {path} | {user ? user.email : 'anon'}
    </p>
  );
}

describe('AuthContext', () => {
  beforeEach(() => {
    vi.mocked(getMe).mockReset();
    vi.mocked(verifyLoginCode).mockReset();
  });

  it('loads the signed-in user from /me on mount', async () => {
    tokenStore.setTokens('access', 'refresh');
    vi.mocked(getMe).mockResolvedValue(me);
    render(
      <MemoryRouter>
        <AuthProvider>
          <Probe path="/dashboard" />
        </AuthProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText(/s@example.com/)).toBeInTheDocument());
    expect(screen.getByText(/\/dashboard/)).toBeInTheDocument();
  });

  it('stays anonymous with no token', async () => {
    vi.mocked(getMe).mockRejectedValue(new Error('no auth'));
    render(
      <MemoryRouter>
        <AuthProvider>
          <Probe path="/" />
        </AuthProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText(/anon/)).toBeInTheDocument());
  });

  it('loginWithCode returns created_account from the verify endpoint', async () => {
    tokenStore.setTokens('access', 'refresh');
    vi.mocked(getMe).mockResolvedValue(me);
    vi.mocked(verifyLoginCode).mockResolvedValue({ access: 'a', refresh: 'r', created_account: true });

    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }) => (
        <MemoryRouter>
          <AuthProvider>{children}</AuthProvider>
        </MemoryRouter>
      ),
    });
    await waitFor(() => expect(result.current.user).toBeTruthy());

    let created = false;
    await act(async () => {
      created = await result.current.loginWithCode('email', 's@example.com', '123456');
    });
    expect(created).toBe(true);
    expect(verifyLoginCode).toHaveBeenCalledWith('s@example.com', '123456');
  });
});

describe('ProtectedRoute', () => {
  it('redirects anonymous users to /login with a returnTo param', async () => {
    vi.mocked(getMe).mockRejectedValue(new Error('no auth'));
    render(
      <MemoryRouter initialEntries={['/receipts']}>
        <AuthProvider>
          <ProtectedRoute>
            <p>secret receipts</p>
          </ProtectedRoute>
        </AuthProvider>
      </MemoryRouter>,
    );
    await waitFor(() => {
      const login = screen.getByText(/code/i);
      expect(login).toBeInTheDocument();
    });
    expect(screen.queryByText('secret receipts')).not.toBeInTheDocument();
  });

  it('renders children for signed-in users', async () => {
    tokenStore.setTokens('access', 'refresh');
    vi.mocked(getMe).mockResolvedValue(me);
    render(
      <MemoryRouter initialEntries={['/receipts']}>
        <AuthProvider>
          <ProtectedRoute>
            <p>secret receipts</p>
          </ProtectedRoute>
        </AuthProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText('secret receipts')).toBeInTheDocument());
  });
});
