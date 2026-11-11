import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { RequestsSidebar } from './RequestsSidebar';
import { BookRequest, RequestStatus } from '../types';

const tab = vi.hoisted(() => ({ value: 'all' }));
vi.mock('react', async (importOriginal) => {
  const original = await importOriginal<typeof import('react')>();
  return {
    ...original,
    useState: (initial: unknown) => original.useState(initial === 'all' ? tab.value : initial),
  };
});

const noop = async () => {};
function render(status: RequestStatus, isAdmin: boolean) {
  return renderToStaticMarkup(<RequestsSidebar
    isOpen onClose={() => {}} isAdmin={isAdmin}
    requests={[{ id: 1, title: 'Future book', status, content_type: 'ebook',
      created_at: '2026-11-01', updated_at: '2026-11-01' } as BookRequest]}
    onApprove={noop} onDeny={noop} onRetry={noop} onActivatePrerelease={noop}
    onMoveToPrerelease={noop} onSetStatus={noop} onDelete={noop}
    onMarkCompleted={noop} onRefresh={noop}
  />);
}

describe('request removal', () => {
  it.each([true, false])('omits removal outside History (admin=%s)', (isAdmin) => {
    for (const [filter, status] of [
      ['all', 'approved'], ['all', 'no_sources_requested'],
      ['all', 'downloading'],
      ['prerelease', 'prerelease_requested'], ['pending', 'pending'],
    ] as const) {
      tab.value = filter;
      const html = render(status, isAdmin);
      expect(html).toContain('Future book');
      expect(html).not.toContain('aria-label="Remove from history"');
      expect(html).not.toContain('aria-label="Cancel request"');
    }
  });

  it.each([true, false])('allows removal in History (admin=%s)', (isAdmin) => {
    tab.value = 'history';
    for (const status of ['fulfilled', 'denied', 'failed', 'cancelled'] as const) {
      expect(render(status, isAdmin)).toContain('aria-label="Remove from history"');
    }
  });
});

describe('pre-release lifecycle', () => {
  it.each([true, false])('shows pre-releases only in their own tab (admin=%s)', (isAdmin) => {
    tab.value = 'all';
    expect(render('prerelease_requested', isAdmin)).not.toContain('Future book');
    tab.value = 'prerelease';
    expect(render('prerelease_requested', isAdmin)).toContain('Future book');
    tab.value = 'all';
    expect(render('approved', isAdmin)).toContain('Future book');
  });
});
