import { useState, useEffect } from 'react';
import { BookRequest, RequestStatus } from '../types';
import { theme } from '../theme';

interface RequestsSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  requests: BookRequest[];
  isAdmin: boolean;
  onApprove: (requestId: number) => Promise<void>;
  onDeny: (requestId: number, adminNote?: string) => Promise<void>;
  onRetry: (requestId: number) => Promise<void>;
  onDelete: (requestId: number) => Promise<void>;
  onMarkCompleted: (requestId: number) => Promise<void>;
}

type FilterTab = 'all' | 'pending' | 'fulfilled';

const STATUS_STYLES: Record<RequestStatus, { bg: string; text: string; label: string; customStyle?: React.CSSProperties }> = {
  pending: { bg: 'bg-amber-500/20', text: 'text-amber-700 dark:text-amber-300', label: 'Pending' },
  approved: {
    bg: '',
    text: '',
    label: 'Approved',
    customStyle: {
      backgroundColor: 'rgba(0, 188, 212, 0.2)',
      color: theme.primary.turquoise
    }
  },
  denied: { bg: 'bg-red-500/20', text: 'text-red-700 dark:text-red-300', label: 'Denied' },
  downloading: { bg: 'bg-indigo-500/20', text: 'text-indigo-700 dark:text-indigo-300', label: 'Downloading' },
  fulfilled: { bg: 'bg-green-500/20', text: 'text-green-700 dark:text-green-300', label: 'Fulfilled' },
  failed: { bg: 'bg-red-500/20', text: 'text-red-700 dark:text-red-300', label: 'Failed' },
  cancelled: { bg: 'bg-gray-500/20', text: 'text-gray-700 dark:text-gray-300', label: 'Cancelled' },
};

const BookThumbnail = ({ coverUrl, title }: { coverUrl?: string; title?: string }) => {
  if (!coverUrl) {
    return (
      <div
        className="w-16 h-24 rounded-tl bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-[8px] font-medium text-gray-500 dark:text-gray-400"
        style={{ aspectRatio: '2/3' }}
      >
        No Cover
      </div>
    );
  }

  return (
    <img
      src={coverUrl}
      alt={title || 'Book cover'}
      className="w-16 h-24 object-cover rounded-tl shadow-sm"
      style={{ aspectRatio: '2/3' }}
      onError={(e) => {
        const target = e.target as HTMLImageElement;
        const placeholder = document.createElement('div');
        placeholder.className = 'w-16 h-24 rounded-tl bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-[8px] font-medium text-gray-500 dark:text-gray-400';
        placeholder.style.aspectRatio = '2/3';
        placeholder.textContent = 'No Cover';
        target.replaceWith(placeholder);
      }}
    />
  );
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

export const RequestsSidebar = ({
  isOpen,
  onClose,
  requests,
  isAdmin,
  onApprove,
  onDeny,
  onRetry,
  onDelete,
  onMarkCompleted,
}: RequestsSidebarProps) => {
  const [filter, setFilter] = useState<FilterTab>('all');
  const [denyNoteId, setDenyNoteId] = useState<number | null>(null);
  const [denyNote, setDenyNote] = useState('');
  const [processingId, setProcessingId] = useState<number | null>(null);

  // Handle ESC key to close sidebar
  useEffect(() => {
    if (!isOpen) return;

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  // Filter requests based on active tab
  const filteredRequests = requests.filter((req) => {
    if (filter === 'pending') return req.status === 'pending';
    if (filter === 'fulfilled') return req.status === 'fulfilled' || req.status === 'denied' || req.status === 'failed';
    return true;
  });

  const handleApproveClick = async (requestId: number) => {
    setProcessingId(requestId);
    try {
      await onApprove(requestId);
    } catch (error) {
      console.error('Failed to approve request:', error);
    } finally {
      setProcessingId(null);
    }
  };

  const handleDenyClick = async (requestId: number) => {
    if (denyNoteId === requestId) {
      // Submit deny with note
      setProcessingId(requestId);
      try {
        await onDeny(requestId, denyNote || undefined);
        setDenyNoteId(null);
        setDenyNote('');
      } catch (error) {
        console.error('Failed to deny request:', error);
      } finally {
        setProcessingId(null);
      }
    } else {
      // Show note input
      setDenyNoteId(requestId);
      setDenyNote('');
    }
  };

  const handleRetryClick = async (requestId: number) => {
    setProcessingId(requestId);
    try {
      await onRetry(requestId);
    } catch (error) {
      console.error('Failed to retry request:', error);
    } finally {
      setProcessingId(null);
    }
  };

  const handleMarkCompletedClick = async (requestId: number) => {
    setProcessingId(requestId);
    try {
      await onMarkCompleted(requestId);
    } catch (error) {
      console.error('Failed to mark request as completed:', error);
      // Re-throw so App.tsx can show error toast
      throw error;
    } finally {
      setProcessingId(null);
    }
  };

  const handleClearFulfilled = async () => {
    // Clear all completed requests (fulfilled, denied, failed, cancelled)
    const clearableRequests = requests.filter(
      (r) => r.status === 'fulfilled' || r.status === 'denied' || r.status === 'failed' || r.status === 'cancelled'
    );

    // Delete all clearable requests in parallel
    try {
      await Promise.all(clearableRequests.map((r) => onDelete(r.id)));
    } catch (error) {
      console.error('Failed to clear completed requests:', error);
      // Errors are already handled by individual onDelete calls
    }
  };

  // Show clear button if there are any completed requests
  const hasClearable = requests.some(
    (r) => r.status === 'fulfilled' || r.status === 'denied' || r.status === 'failed' || r.status === 'cancelled'
  );

  const renderRequestItem = (req: BookRequest) => {
    const statusStyle = STATUS_STYLES[req.status];
    const isPending = req.status === 'pending';
    // Show retry for: failed, cancelled, denied, stuck downloading, or approved (audiobooks)
    const isRetryable = req.status === 'failed' || req.status === 'cancelled' || req.status === 'denied' || req.status === 'downloading' || req.status === 'approved';
    const isDeniable = req.status === 'pending' || req.status === 'approved' || req.status === 'downloading' || req.status === 'failed';
    // Show "Mark Completed" for any non-fulfilled/non-cancelled request
    const canMarkCompleted = req.status !== 'fulfilled' && req.status !== 'cancelled';
    // Users can now delete their own requests (any status), admins can delete any request
    const canDelete = true;

    return (
      <div
        key={req.id}
        className="relative rounded-lg border hover:shadow-md transition-shadow overflow-hidden"
        style={{ borderColor: 'var(--border-muted)', background: 'var(--bg-soft)' }}
      >
        {/* Delete button - top right (only show if allowed) */}
        {canDelete && (
          <button
            type="button"
            onClick={() => onDelete(req.id)}
            className="absolute top-1 right-1 z-10 flex h-8 w-8 items-center justify-center rounded-full transition-colors text-gray-500 hover:text-red-600 hover:bg-red-100 dark:hover:bg-red-900/30"
            title="Cancel request"
            aria-label="Cancel request"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}

        <div className="flex gap-2">
          {/* Book Thumbnail */}
          <div className="flex-shrink-0">
            <BookThumbnail coverUrl={req.cover_url} title={req.title} />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0 flex flex-col pl-1.5 pr-3 pt-2 pb-2">
            <div className="pr-6">
              <h3 className="font-semibold text-sm truncate" title={req.title}>
                {req.title}
              </h3>
              <p className="text-xs opacity-70 truncate" title={req.author}>
                {req.author || 'Unknown Author'}
              </p>
            </div>

            {/* Content type + requester (admin view) + time */}
            <div className="text-xs opacity-70 mt-1">
              <span className="uppercase">{req.content_type}</span>
              {isAdmin && (
                <>
                  <span> &middot; </span>
                  <span>{req.requester_display_name || req.requester_username}</span>
                </>
              )}
              <span> &middot; </span>
              <span>{formatRelativeTime(req.created_at)}</span>
            </div>

            {/* Admin note */}
            {req.admin_note && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 italic truncate" title={req.admin_note}>
                {req.admin_note}
              </p>
            )}

            {/* Status badge + admin actions */}
            <div className="flex items-center justify-between mt-auto pt-1 gap-2">
              {/* Admin approve/deny/complete buttons for pending items */}
              {isAdmin && isPending && (
                <div className="flex items-center gap-1 flex-wrap">
                  <button
                    type="button"
                    onClick={() => handleApproveClick(req.id)}
                    disabled={processingId === req.id}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {processingId === req.id ? 'Processing...' : 'Approve'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleMarkCompletedClick(req.id)}
                    disabled={processingId === req.id}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {processingId === req.id ? 'Marking...' : 'Mark Completed'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDenyClick(req.id)}
                    disabled={processingId === req.id}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {processingId === req.id && denyNoteId === req.id ? 'Processing...' : 'Deny'}
                  </button>
                </div>
              )}

              {/* Admin retry/deny/complete buttons for retryable items */}
              {isAdmin && isRetryable && (
                <div className="flex items-center gap-1 flex-wrap">
                  <button
                    type="button"
                    onClick={() => handleRetryClick(req.id)}
                    disabled={processingId === req.id}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{
                      backgroundColor: 'rgba(0, 188, 212, 0.2)',
                      color: theme.primary.turquoise
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = 'rgba(0, 188, 212, 0.3)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = 'rgba(0, 188, 212, 0.2)';
                    }}
                  >
                    {processingId === req.id ? 'Retrying...' : 'Retry'}
                  </button>
                  {canMarkCompleted && (
                    <button
                      type="button"
                      onClick={() => handleMarkCompletedClick(req.id)}
                      disabled={processingId === req.id}
                      className="px-2 py-0.5 text-xs font-medium rounded-lg bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {processingId === req.id ? 'Marking...' : 'Mark Completed'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDenyClick(req.id)}
                    disabled={processingId === req.id}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {processingId === req.id && denyNoteId === req.id ? 'Processing...' : 'Deny'}
                  </button>
                </div>
              )}

              {/* Admin deny/complete buttons for other deniable statuses (non-pending, non-retryable) */}
              {isAdmin && !isPending && !isRetryable && isDeniable && (
                <div className="flex items-center gap-1 flex-wrap">
                  {canMarkCompleted && (
                    <button
                      type="button"
                      onClick={() => handleMarkCompletedClick(req.id)}
                      disabled={processingId === req.id}
                      className="px-2 py-0.5 text-xs font-medium rounded-lg bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {processingId === req.id ? 'Marking...' : 'Mark Completed'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDenyClick(req.id)}
                    disabled={processingId === req.id}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {processingId === req.id && denyNoteId === req.id ? 'Processing...' : 'Deny'}
                  </button>
                </div>
              )}

              <span
                className={`ml-auto px-2 py-0.5 rounded-lg text-xs font-medium ${statusStyle.bg} ${statusStyle.text}`}
                style={statusStyle.customStyle}
              >
                {statusStyle.label}
              </span>
            </div>

            {/* Deny note input */}
            {denyNoteId === req.id && (
              <div className="flex gap-1 mt-1.5">
                <input
                  type="text"
                  value={denyNote}
                  onChange={(e) => setDenyNote(e.target.value)}
                  placeholder="Reason (optional)"
                  className="flex-1 px-2 py-1 text-xs rounded border border-[var(--border-muted)] bg-[var(--bg)]"
                  autoFocus
                  disabled={processingId === req.id}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      handleDenyClick(req.id);
                    }
                    if (e.key === 'Escape') {
                      setDenyNoteId(null);
                      setDenyNote('');
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={() => handleDenyClick(req.id)}
                  disabled={processingId === req.id}
                  className="px-2 py-1 text-xs font-medium rounded bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {processingId === req.id ? 'Sending...' : 'Send'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 bg-black/50 z-40 transition-opacity duration-300 ${
          isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onClick={onClose}
      />

      {/* Sidebar */}
      <div
        className={`fixed top-0 right-0 h-full w-full sm:w-96 z-50 flex flex-col shadow-2xl transition-transform duration-300 ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
        style={{ background: 'var(--bg)' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between p-4 border-b"
          style={{ paddingTop: 'calc(1rem + env(safe-area-inset-top))', borderColor: 'var(--border-muted)' }}
        >
          <h2 className="text-lg font-semibold">
            {isAdmin ? 'User Requests' : 'My Requests'}{requests.length > 0 && ` (${requests.length})`}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 items-center justify-center rounded-full hover-action transition-colors"
            aria-label="Close sidebar"
          >
            <svg
              className="w-5 h-5"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth="2"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Filter Tabs */}
        <div className="flex gap-1 px-4 pt-3 pb-1">
          {(['all', 'pending', 'fulfilled'] as FilterTab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setFilter(tab)}
              className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                filter === tab
                  ? 'text-white'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
              }`}
              style={filter === tab ? { backgroundColor: theme.button.primary } : {}}
            >
              {tab === 'all' ? 'All' : tab === 'pending' ? 'Pending' : 'Completed'}
            </button>
          ))}
        </div>

        {/* Request Items */}
        <div
          className="flex-1 overflow-y-auto p-4 space-y-3"
          style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))' }}
        >
          {filteredRequests.length > 0 ? (
            filteredRequests.map((req) => renderRequestItem(req))
          ) : (
            <div className="text-center text-sm opacity-70 mt-8">
              No requests{filter !== 'all' ? ` (${filter})` : ''}
            </div>
          )}
        </div>

        {/* Footer - always show */}
        <div
          className="p-3 border-t flex items-center justify-center"
          style={{
            borderColor: 'var(--border-muted)',
            paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom))',
          }}
        >
          {/* Clear Completed button - disabled if no completed requests */}
          <button
            type="button"
            onClick={handleClearFulfilled}
            disabled={!hasClearable}
            className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            title={isAdmin ? "Hide completed requests from admin view" : "Delete completed requests"}
          >
            Clear Completed
          </button>
        </div>
      </div>
    </>
  );
};
