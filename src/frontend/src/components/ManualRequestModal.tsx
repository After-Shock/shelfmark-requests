import { useState } from 'react';
import { ContentType } from '../types';
import { theme } from '../theme';

interface ManualRequestModalProps {
  contentType: ContentType;
  onSubmit: (data: {
    title: string;
    author: string;
    is_released: boolean;
    expected_release_date?: string;
    prefer_alternate_version: boolean;
  }) => void;
  onClose: () => void;
}

export const ManualRequestModal = ({ contentType, onSubmit, onClose }: ManualRequestModalProps) => {
  const [title, setTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [isReleased, setIsReleased] = useState<boolean | null>(null);
  const [expectedReleaseDate, setExpectedReleaseDate] = useState('');
  const [preferAlternate, setPreferAlternate] = useState(false);
  const minReleaseDate = new Date().toISOString().slice(0, 10);

  const requiresReleaseDate = isReleased === false;
  const canSubmit = (
    title.trim().length > 0 &&
    author.trim().length > 0 &&
    isReleased !== null &&
    (!requiresReleaseDate || expectedReleaseDate.trim().length > 0)
  );

  const handleSubmit = () => {
    if (!canSubmit) return;
    onSubmit({
      title: title.trim(),
      author: author.trim(),
      is_released: isReleased!,
      expected_release_date: requiresReleaseDate ? expectedReleaseDate : undefined,
      prefer_alternate_version: preferAlternate,
    });
  };

  return (
    <div
      className="modal-overlay active sm:px-6 sm:py-6"
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-md settings-modal-enter">
        <div className="flex flex-col rounded-none sm:rounded-2xl border-0 sm:border border-[var(--border-muted)] bg-[var(--bg)] text-[var(--text)] shadow-none sm:shadow-2xl overflow-hidden">

          {/* Header */}
          <header className="flex items-center justify-between border-b border-[var(--border-muted)] px-5 py-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                {contentType === 'audiobook' ? 'Audiobook' : 'Book'}
              </p>
              <h3 className="text-lg font-semibold">Request Manually</h3>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-full p-2 text-gray-500 transition-colors hover-action hover:text-gray-900 dark:hover:text-gray-100"
              aria-label="Close"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </header>

          {/* Body */}
          <div className="px-5 py-6 flex flex-col gap-4">

            {/* Title */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                Book Title <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="Enter book title"
                className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2"
                style={{
                  background: 'var(--bg-soft)',
                  borderColor: 'var(--border-muted)',
                  color: 'var(--text)',
                }}
                autoFocus
              />
            </div>

            {/* Author */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                Author <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={author}
                onChange={e => setAuthor(e.target.value)}
                placeholder="Enter author name"
                className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2"
                style={{
                  background: 'var(--bg-soft)',
                  borderColor: 'var(--border-muted)',
                  color: 'var(--text)',
                }}
              />
            </div>

            {/* Released toggle */}
            <div className="flex flex-col gap-2">
              <label className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                Has this been released? <span className="text-red-400">*</span>
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setIsReleased(true);
                    setExpectedReleaseDate('');
                  }}
                  className="flex-1 py-2 rounded-lg text-sm font-medium border transition-colors"
                  style={isReleased === true
                    ? { backgroundColor: theme.primary.turquoise, borderColor: theme.primary.turquoise, color: '#fff' }
                    : { background: 'var(--bg-soft)', borderColor: 'var(--border-muted)', color: 'var(--text)' }
                  }
                >
                  Yes
                </button>
                <button
                  type="button"
                  onClick={() => setIsReleased(false)}
                  className="flex-1 py-2 rounded-lg text-sm font-medium border transition-colors"
                  style={isReleased === false
                    ? { backgroundColor: theme.primary.turquoise, borderColor: theme.primary.turquoise, color: '#fff' }
                    : { background: 'var(--bg-soft)', borderColor: 'var(--border-muted)', color: 'var(--text)' }
                  }
                >
                  Not Yet
                </button>
              </div>
            </div>

            {requiresReleaseDate && (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Expected Release Date <span className="text-red-400">*</span>
                </label>
                <input
                  type="date"
                  value={expectedReleaseDate}
                  onChange={e => setExpectedReleaseDate(e.target.value)}
                  min={minReleaseDate}
                  className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2"
                  style={{
                    background: 'var(--bg-soft)',
                    borderColor: 'var(--border-muted)',
                    color: 'var(--text)',
                  }}
                />
              </div>
            )}

            {/* Audiobook-only: alternate version checkbox */}
            {contentType === 'audiobook' && (
              <label className="flex items-center gap-2 text-sm cursor-pointer select-none opacity-80 hover:opacity-100">
                <input
                  type="checkbox"
                  checked={preferAlternate}
                  onChange={e => setPreferAlternate(e.target.checked)}
                  className="w-4 h-4 rounded accent-[#00BCD4] cursor-pointer"
                />
                Request graphic or dramatized version if available
              </label>
            )}
          </div>

          {/* Footer */}
          <footer
            className="border-t border-[var(--border-muted)] px-5 py-4 flex justify-end gap-2"
            style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))' }}
          >
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-full text-sm font-medium transition-colors hover-action"
              style={{ color: 'var(--text)' }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              className="px-6 py-2 rounded-full text-sm font-medium text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ backgroundColor: theme.primary.turquoise }}
              onMouseEnter={e => { if (canSubmit) e.currentTarget.style.backgroundColor = '#00ACC1'; }}
              onMouseLeave={e => { e.currentTarget.style.backgroundColor = theme.primary.turquoise; }}
            >
              Submit Request
            </button>
          </footer>
        </div>
      </div>
    </div>
  );
};
