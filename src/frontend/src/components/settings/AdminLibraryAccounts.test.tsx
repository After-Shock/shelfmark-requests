// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminLibraryAccounts } from './AdminLibraryAccounts';
import * as api from '../../services/api';
vi.mock('../../services/api', () => ({ getAdminLibraryAccounts: vi.fn(), linkAdminLibraryAccount: vi.fn(), unlinkAdminLibraryAccount: vi.fn(), setAdminLibraryPassword: vi.fn() }));
const account = { id: '27', username: 'OtherName', email: 'reader@example.com' };
const user = { id: 2, username: 'reader@example.com', auth_source: 'builtin' };
const status = () => ({ services: {
  calibre_web: { offered: true, linked: true, account, candidates: [account] },
  audiobookshelf: { offered: true, linked: false, account: null, candidates: [
    { id: 'abs1', username: 'AudioReader', email: null },
    { id: 'abs2', username: 'Claimed', email: null, owner_user_id: 9, owner_username: 'SomeoneElse' },
  ] },
} });
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getAdminLibraryAccounts).mockResolvedValue(status());
  vi.mocked(api.linkAdminLibraryAccount).mockResolvedValue({ success: true });
  vi.mocked(api.unlinkAdminLibraryAccount).mockResolvedValue({ success: true });
});
describe('AdminLibraryAccounts', () => {
  it('shows linked external identity even when username differs', async () => {
    render(<AdminLibraryAccounts user={user} />);
    expect(await screen.findByText('OtherName')).toBeTruthy();
    expect(screen.getByText('reader@example.com')).toBeTruthy();
    expect(screen.getByText('Linked')).toBeTruthy();
  });
  it('requires selection and identity review before linking', async () => {
    render(<AdminLibraryAccounts user={user} />);
    fireEvent.change(await screen.findByLabelText('Audiobooks account'), { target: { value: 'abs1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review Audiobooks link' }));
    expect(api.linkAdminLibraryAccount).not.toHaveBeenCalled();
    expect(screen.getByText(/Link AudioReader to reader@example.com/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm link' }));
    await waitFor(() => expect(api.linkAdminLibraryAccount).toHaveBeenCalledWith(2, 'audiobookshelf', 'abs1'));
  });
  it('disables accounts owned by someone else', async () => {
    render(<AdminLibraryAccounts user={user} />);
    const option = await screen.findByRole('option', { name: /Claimed.*SomeoneElse/ });
    expect((option as HTMLOptionElement).disabled).toBe(true);
  });
  it('unlinks only after review and refreshes status', async () => {
    render(<AdminLibraryAccounts user={user} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Unlink Ebooks' }));
    expect(api.unlinkAdminLibraryAccount).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm unlink' }));
    await waitFor(() => expect(api.unlinkAdminLibraryAccount).toHaveBeenCalledWith(2, 'calibre_web'));
    await waitFor(() => expect(api.getAdminLibraryAccounts).toHaveBeenCalledTimes(2));
  });
  it('rejects mismatched passwords before submission', async () => {
    render(<AdminLibraryAccounts user={user} />);
    await screen.findByText('OtherName');
    fireEvent.change(screen.getByLabelText('Shared password'), { target: { value: 'secret123' } });
    fireEvent.change(screen.getByLabelText('Confirm shared password'), { target: { value: 'different' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review password update' }));
    expect(screen.getByText('Passwords do not match')).toBeTruthy();
    expect(api.setAdminLibraryPassword).not.toHaveBeenCalled();
  });
  it('shows partial password results and clears passwords', async () => {
    vi.mocked(api.setAdminLibraryPassword).mockResolvedValue({ results: {
      requests: { status: 'updated' }, calibre_web: { status: 'error', message: 'Library offline' },
    } });
    render(<AdminLibraryAccounts user={user} />);
    await screen.findByText('OtherName');
    fireEvent.change(screen.getByLabelText('Shared password'), { target: { value: 'secret123' } });
    fireEvent.change(screen.getByLabelText('Confirm shared password'), { target: { value: 'secret123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review password update' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm password update' }));
    expect(await screen.findByText(/Library offline/)).toBeTruthy();
    expect(api.setAdminLibraryPassword).toHaveBeenCalledWith(2, 'secret123', 'secret123');
    expect((screen.getByLabelText('Shared password') as HTMLInputElement).value).toBe('');
    expect(screen.getByText(/Requests: Updated/)).toBeTruthy();
  });
  it('allows unlinking unavailable mapped accounts', async () => {
    const data = status();
    Object.assign(data.services.calibre_web, { offered: false, error: 'Library unavailable', state: 'unavailable' });
    vi.mocked(api.getAdminLibraryAccounts).mockResolvedValue(data);
    render(<AdminLibraryAccounts user={user} />);
    expect(await screen.findByText('Library unavailable')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Unlink Ebooks' }) as HTMLButtonElement).disabled).toBe(false);
  });
  it('hides password writes for non-local users', async () => {
    render(<AdminLibraryAccounts user={{ ...user, auth_source: 'oidc' }} />);
    await screen.findByText('OtherName');
    expect(screen.queryByLabelText('Shared password')).toBeNull();
  });
  it('disables repeated mutations while pending', async () => {
    let resolve!: (value: { success: boolean }) => void;
    vi.mocked(api.unlinkAdminLibraryAccount).mockReturnValue(new Promise(r => { resolve = r; }));
    render(<AdminLibraryAccounts user={user} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Unlink Ebooks' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm unlink' }));
    expect((screen.getByRole('button', { name: 'Confirm unlink' }) as HTMLButtonElement).disabled).toBe(true);
    resolve({ success: true });
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Confirm unlink' })).toBeNull());
  });
});

it('disables an unavailable service picker without claiming there are no accounts', async () => {
  const data = status();
  Object.assign(data.services.audiobookshelf, { state: 'unavailable', error: 'Library unavailable', candidates: [] });
  vi.mocked(api.getAdminLibraryAccounts).mockResolvedValue(data);
  render(<AdminLibraryAccounts user={user} />);
  expect(await screen.findByText('Library unavailable')).toBeTruthy();
  expect((screen.getByLabelText('Audiobooks account') as HTMLSelectElement).disabled).toBe(true);
  expect(screen.queryByText('No existing accounts found.')).toBeNull();
});

it('distinguishes a saved change from a failed status refresh', async () => {
  vi.mocked(api.getAdminLibraryAccounts).mockResolvedValueOnce(status()).mockRejectedValueOnce(new Error('Offline'));
  render(<AdminLibraryAccounts user={user} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Unlink Ebooks' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm unlink' }));
  expect(await screen.findByText(/change was saved.*could not refresh/i)).toBeTruthy();
  expect(screen.queryByText(/Account unlinked. Its library/)).toBeNull();
});
