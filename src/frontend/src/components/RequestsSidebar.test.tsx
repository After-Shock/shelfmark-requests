import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { RequestsSidebar } from './RequestsSidebar';
import { BookRequest, RequestStatus } from '../types';

const tab = vi.hoisted(() => ({ value: 'all' as string }));
vi.mock('react', async (importOriginal) => {
  const original = await importOriginal<typeof import('react')>();
  return {
    ...original,
    useState: (initial: unknown) => original.useState(initial === 'default' ? tab.value : initial),
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
    for (const status of ['fulfilled', 'denied', 'cancelled'] as const) {
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

  it.each([true, false])('keeps pending requests out of Active (admin=%s)', (isAdmin) => {
    tab.value = 'all';
    expect(render('pending', isAdmin)).not.toContain('Future book');
    tab.value = 'pending';
    expect(render('pending', isAdmin)).toContain('Future book');
  });
});

describe('pre-release permissions', () => {
  it('gives regular users a view-only pre-release tab', () => {
    tab.value = 'prerelease';
    const html = render('prerelease_requested', false);
    expect(html).toContain('Future book');
    expect(html).not.toMatch(/<(?:input|select|textarea)\b/);
    for (const action of ['Activate Now', 'Deny', 'Apply', 'Clear Completed', 'Remove from history']) {
      expect(html).not.toContain(action);
    }
  });

  it('preserves admin pre-release controls', () => {
    tab.value = 'prerelease';
    const html = render('prerelease_requested', true);
    expect(html).toContain('Activate Now');
    expect(html).toContain('Deny');
    expect(html).toContain('Status for Future book');
    expect(html).toContain('Release date for Future book');
    expect(html).toContain('Apply');
  });
});

describe('needs action', () => {
  it('lists failed requests in the admin Needs action tab, where they can be dismissed', () => {
    tab.value = 'needs_action';
    const html = render('failed', true);
    expect(html).toContain('Future book');
    expect(html).toContain('Needs action (1)');
    expect(html).toContain('aria-label="Dismiss from Needs action"');
    expect(html).toContain('>Failed<');
    tab.value = 'history';
    expect(render('failed', true)).not.toContain('Future book');
  });

  it('opens on Needs action for admins and Active for users', () => {
    tab.value = 'default';
    expect(render('failed', true)).toContain('Future book');
    expect(render('approved', true)).not.toContain('Future book');
    expect(render('approved', false)).toContain('Future book');
  });

  it('shows users a failed request as Needs review in Active, without a Needs action tab', () => {
    tab.value = 'all';
    const html = render('failed', false);
    expect(html).toContain('Future book');
    expect(html).toContain('Needs review');
    expect(html).toContain('The admin has been notified');
    expect(html).not.toContain('Needs action');
    expect(html).not.toContain('aria-label="Remove from history"');
  });

  it('only shows the Pending tab while pending requests exist', () => {
    tab.value = 'all';
    const pendingTab = /rounded-full[^"]*"[^>]*>Pending</;
    expect(render('approved', true)).not.toMatch(pendingTab);
    expect(render('pending', true)).toMatch(pendingTab);
  });
});
