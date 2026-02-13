import { BookRequest, RequestCounts, RequestStatus } from '../types';
import { theme } from '../theme';

interface UserDashboardProps {
  requests: BookRequest[];
  counts: RequestCounts;
  logoUrl: string;
  searchInput: string;
  onSearchInputChange: (value: string) => void;
  onSearch: (query: string) => void;
  contentType: 'ebook' | 'audiobook';
  onContentTypeChange: (type: 'ebook' | 'audiobook') => void;
}

const STATUS_STYLES: Record<RequestStatus, { bg: string; text: string; label: string }> = {
  pending: { bg: 'bg-amber-500/20', text: 'text-amber-700 dark:text-amber-300', label: 'Pending' },
  approved: { bg: 'bg-sky-500/20', text: 'text-sky-700 dark:text-sky-300', label: 'Approved' },
  denied: { bg: 'bg-red-500/20', text: 'text-red-700 dark:text-red-300', label: 'Denied' },
  downloading: { bg: 'bg-indigo-500/20', text: 'text-indigo-700 dark:text-indigo-300', label: 'Downloading' },
  fulfilled: { bg: 'bg-green-500/20', text: 'text-green-700 dark:text-green-300', label: 'Fulfilled' },
  failed: { bg: 'bg-red-500/20', text: 'text-red-700 dark:text-red-300', label: 'Failed' },
};

const formatRelativeTime = (dateString: string): string => {
  const date = new Date(dateString + (dateString.endsWith('Z') ? '' : 'Z'));
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 30) return `${diffDay}d ago`;
  return date.toLocaleDateString();
};

export const UserDashboard = ({
  requests,
  counts,
  logoUrl,
  searchInput,
  onSearchInputChange,
  onSearch,
  contentType,
  onContentTypeChange,
}: UserDashboardProps) => {
  const pendingCount = counts.pending || 0;
  const inProgressCount = (counts.approved || 0) + (counts.downloading || 0);
  const fulfilledCount = counts.fulfilled || 0;

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchInput.trim()) {
      onSearch(searchInput.trim());
    }
  };

  return (
    <div className="flex flex-col items-center w-full">
      {/* Logo and search */}
      <div className="flex flex-col items-center w-full max-w-2xl pt-8 sm:pt-16 pb-6 px-4">
        <img src={logoUrl} alt="Shelfmark" className="w-60 h-60 sm:w-72 sm:h-72 mb-6" />

        <form onSubmit={handleSearchSubmit} className="w-full flex gap-2">
          <div className="flex-1 relative">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => onSearchInputChange(e.target.value)}
              placeholder="Search for books to request..."
              className="w-full px-4 py-3 rounded-lg border focus:outline-none focus:ring-2 transition-colors"
              style={{
                backgroundColor: 'var(--input-background, var(--bg-soft))',
                borderColor: 'var(--border-muted)',
                color: 'var(--text-color)',
                '--tw-ring-color': theme.primary.turquoise,
              } as React.CSSProperties}
            />
          </div>
          <button
            type="submit"
            className="px-5 py-3 rounded-lg font-medium text-white transition-colors"
            style={{ backgroundColor: theme.button.secondary }}
            onMouseEnter={(e) => e.currentTarget.style.backgroundColor = theme.button.secondaryHover}
            onMouseLeave={(e) => e.currentTarget.style.backgroundColor = theme.button.secondary}
          >
            Search
          </button>
        </form>

        {/* Content type toggle */}
        <div className="flex gap-1 mt-3">
          {(['ebook', 'audiobook'] as const).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => onContentTypeChange(type)}
              className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                contentType === type
                  ? 'text-white'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
              }`}
              style={contentType === type ? { backgroundColor: theme.primary.turquoise } : undefined}
            >
              {type === 'ebook' ? 'Ebooks' : 'Audiobooks'}
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3 w-full max-w-2xl px-4 mb-6">
        <div
          className="rounded-lg p-4 text-center border"
          style={{ background: 'var(--bg-soft)', borderColor: 'var(--border-muted)' }}
        >
          <div className="text-2xl font-bold text-amber-600 dark:text-amber-400">{pendingCount}</div>
          <div className="text-xs opacity-70 mt-1">Pending</div>
        </div>
        <div
          className="rounded-lg p-4 text-center border"
          style={{ background: 'var(--bg-soft)', borderColor: 'var(--border-muted)' }}
        >
          <div className="text-2xl font-bold" style={{ color: theme.primary.turquoise }}>{inProgressCount}</div>
          <div className="text-xs opacity-70 mt-1">In Progress</div>
        </div>
        <div
          className="rounded-lg p-4 text-center border"
          style={{ background: 'var(--bg-soft)', borderColor: 'var(--border-muted)' }}
        >
          <div className="text-2xl font-bold text-green-600 dark:text-green-400">{fulfilledCount}</div>
          <div className="text-xs opacity-70 mt-1">Fulfilled</div>
        </div>
      </div>

      {/* Recent requests */}
      <div className="w-full max-w-2xl px-4 pb-8">
        {requests.length > 0 ? (
          <>
            <h3 className="text-sm font-medium opacity-70 mb-3">Your Requests</h3>
            <div className="space-y-2">
              {requests.slice(0, 10).map((req) => {
                const statusStyle = STATUS_STYLES[req.status];
                return (
                  <div
                    key={req.id}
                    className="flex items-center gap-3 rounded-lg border p-3 transition-colors"
                    style={{ background: 'var(--bg-soft)', borderColor: 'var(--border-muted)' }}
                  >
                    {/* Thumbnail */}
                    {req.cover_url ? (
                      <img
                        src={req.cover_url}
                        alt=""
                        className="w-10 h-14 object-cover rounded flex-shrink-0"
                        style={{ aspectRatio: '2/3' }}
                      />
                    ) : (
                      <div
                        className="w-10 h-14 rounded bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-[7px] text-gray-400 flex-shrink-0"
                        style={{ aspectRatio: '2/3' }}
                      >
                        No Cover
                      </div>
                    )}

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{req.title}</p>
                      <p className="text-xs opacity-60 truncate">
                        {req.author || 'Unknown Author'}
                        <span className="mx-1">&middot;</span>
                        {formatRelativeTime(req.created_at)}
                      </p>
                      {req.admin_note && (
                        <p className="text-xs opacity-50 italic truncate mt-0.5">{req.admin_note}</p>
                      )}
                    </div>

                    {/* Status badge */}
                    <span
                      className={`flex-shrink-0 px-2 py-0.5 rounded-lg text-xs font-medium ${statusStyle.bg} ${statusStyle.text}`}
                    >
                      {statusStyle.label}
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <div className="text-center py-8 opacity-50">
            <p className="text-sm">No requests yet</p>
            <p className="text-xs mt-1">Search for a book above to make your first request</p>
          </div>
        )}
      </div>
    </div>
  );
};
