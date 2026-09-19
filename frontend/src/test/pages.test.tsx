import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import Landing from '../pages/Landing';
import Privacy from '../pages/Privacy';
import Receipts from '../pages/Receipts';

vi.mock('../api/endpoints');

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
    vi.mocked(listReceipts).mockResolvedValue([]);
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
