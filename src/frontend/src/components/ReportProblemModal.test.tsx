// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReportProblemModal } from './ReportProblemModal';
import type { LibraryMatch, RequestQuota } from '../types';

const api = vi.hoisted(() => ({ createReport: vi.fn(), getLibraryMatches: vi.fn() }));
vi.mock('../services/api', () => api);

const quota: RequestQuota = { limit: 6, used: 4, remaining: 2, is_default: true, resets_at: '2026-11-23T05:00:00Z' };
const match = (id: string, title = 'Dune'): LibraryMatch =>
  ({ library: 'abs', library_item_id: id, title, author: 'Frank Herbert', cover: null });
const target = (matches: LibraryMatch[]) => ({ title: 'Dune', author: 'Frank Herbert', contentType: 'audiobook' as const, matches });
const open = (matches: LibraryMatch[], q: RequestQuota | null = quota) =>
  render(<ReportProblemModal target={target(matches)} quota={q} onClose={() => {}} onDone={() => {}} />);
const submit = () => screen.getByRole('button', { name: 'Send report' }) as HTMLButtonElement;

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('ReportProblemModal', () => {
  it('shows the quota left', () => {
    open([match('a')]);
    expect(screen.getByText('2 of 6 reports left this week')).toBeTruthy();
  });

  it('requires a note for Something else', () => {
    open([match('a')]);
    fireEvent.click(screen.getByLabelText('Wrong cover'));
    expect(submit().disabled).toBe(false);
    fireEvent.click(screen.getByLabelText('Something else'));
    expect(submit().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'Chapters are out of order' } });
    expect(submit().disabled).toBe(false);
  });

  it('makes the reporter pick between several matches', () => {
    open([match('a', 'Dune'), match('b', 'Dune Messiah')]);
    fireEvent.click(screen.getByLabelText('Wrong cover'));
    expect(screen.getByLabelText(/Dune Messiah/)).toBeTruthy();
    expect(submit().disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/Dune Messiah/));
    expect(submit().disabled).toBe(false);
  });

  it('sends the report to the admin when nothing matches', async () => {
    api.createReport.mockResolvedValue({ report: {}, joined: false, quota });
    open([]);
    expect(screen.getByText(/We couldn't find this in the library yet/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Wrong cover'));
    fireEvent.click(submit());
    await waitFor(() => expect(api.createReport).toHaveBeenCalled());
    expect(api.createReport.mock.calls[0][0]).not.toHaveProperty('library_item_id');
  });

  it('explains a used-up weekly limit on 429', async () => {
    api.createReport.mockRejectedValue(Object.assign(new Error('raw server text'), { status: 429 }));
    open([match('a')]);
    fireEvent.click(screen.getByLabelText('Wrong cover'));
    fireEvent.click(submit());
    expect(await screen.findByText("You've used all your reports this week. They reset Monday.")).toBeTruthy();
    expect(api.createReport.mock.calls[0][0]).toMatchObject({ library_item_id: 'a', problem_type: 'wrong_cover' });
  });
});
