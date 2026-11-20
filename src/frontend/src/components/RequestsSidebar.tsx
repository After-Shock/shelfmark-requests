import { useState, useEffect } from 'react';
import { BookRequest, MediaReport, RequestQuota, RequestStatus } from '../types';
import { deleteBookRequest, ReportAction } from '../services/api';
import { theme } from '../theme';
import { formatQuotaLeft } from '../utils/requestOutcome';
import { PROBLEM_LABELS, reportStatusText } from '../utils/reportOutcome';

interface RequestsSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  requests: BookRequest[];
  isAdmin: boolean;
  onApprove: (requestId: number) => Promise<void>;
  onDeny: (requestId: number, adminNote?: string) => Promise<void>;
  onRetry: (requestId: number) => Promise<void>;
  onSeriesPack?: (requestId: number, accept: boolean) => Promise<void>;
  onActivatePrerelease: (requestId: number) => Promise<void>;
  onMoveToPrerelease: (requestId: number, expectedReleaseDate: string) => Promise<void>;
  onSetStatus: (requestId: number, status: RequestStatus) => Promise<void>;
  onDelete: (requestId: number) => Promise<void>;
  onMarkCompleted: (requestId: number) => Promise<void>;
  onRefresh: () => Promise<void>;
  /** Weekly request limit for non-admins; null/undefined = unlimited. */
  quota?: RequestQuota | null;
  /** The viewer's own reports (non-admins). */
  reports?: MediaReport[];
  /** Admin queue: needs_action, awaiting_approval and fixed reports. */
  adminReports?: MediaReport[];
  /** Server count of reports waiting on the admin; shown even before the report list loads. */
  reportsNeedingAction?: number;
  onReportProblem?: (request: BookRequest) => void;
  /** "Still wrong?" on a fixed cover report. */
  onReportAgain?: (report: MediaReport) => void;
  onReportAction?: (reportId: number, action: ReportAction) => Promise<void>;
}

type FilterTab = 'needs_action' | 'all' | 'prerelease' | 'pending' | 'history';
// Failed requests wait for the admin: the admin's Needs action tab, the user's Active tab.
const HISTORY_STATUSES: RequestStatus[] = ['fulfilled', 'denied', 'cancelled'];
// Active = approved and in progress; pending/pre-release/history each have their own tab
const ACTIVE_STATUSES: RequestStatus[] = ['approved', 'downloading', 'no_sources_requested'];
const FAILED_ADMIN_STYLE: { bg: string; text: string; label: string; customStyle?: React.CSSProperties } = { bg: 'bg-red-500/20', text: 'text-red-700 dark:text-red-300', label: 'Failed' };
const REPORT_WAITING: MediaReport['status'][] = ['needs_action', 'awaiting_approval'];
const FILE_PROBLEMS: MediaReport['problem_type'][] = ['wrong_language', 'wrong_edition', 'broken_file', 'audio_problem'];
const UNDO_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
const ADMIN_REPORT_LABELS: Record<string, string> = {
  awaiting_approval: 'Awaiting approval', needs_action: 'Needs action', fixing: 'Fixing…', fixed: 'Fixed',
};
const TAB_LABELS: Record<FilterTab, string> = {
  needs_action: 'Needs action', all: 'Active', prerelease: 'Pre-release', pending: 'Pending', history: 'History',
};

const formatResetDay = (iso: string): string => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? 'Monday'
    : date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
};

export const STATUS_STYLES: Record<RequestStatus, { bg: string; text: string; label: string; customStyle?: React.CSSProperties }> = {
  pending: { bg: 'bg-amber-500/20', text: 'text-amber-700 dark:text-amber-300', label: 'Pending' },
  prerelease_requested: {
    bg: '',
    text: '',
    label: 'Pre-release',
    customStyle: {
      backgroundColor: 'rgba(245, 158, 11, 0.2)',
      color: '#d97706'
    }
  },
  approved: {
    bg: '',
    text: '',
    label: 'Approved',
    customStyle: {
      backgroundColor: 'var(--accent-muted)',
      color: theme.primary.turquoise
    }
  },
  denied: { bg: 'bg-red-500/20', text: 'text-red-700 dark:text-red-300', label: 'Denied' },
  downloading: { bg: 'bg-indigo-500/20', text: 'text-indigo-700 dark:text-indigo-300', label: 'Downloading' },
  no_sources_requested: {
    bg: '',
    text: '',
    label: 'Requested',
    customStyle: {
      backgroundColor: 'rgba(249, 115, 22, 0.2)',
      color: '#ea580c'
    }
  },
  fulfilled: { bg: 'bg-green-500/20', text: 'text-green-700 dark:text-green-300', label: 'Fulfilled' },
  // What users see; admins get FAILED_ADMIN_STYLE.
  failed: { bg: 'bg-amber-500/20', text: 'text-amber-700 dark:text-amber-300', label: 'Needs review' },
  cancelled: { bg: 'bg-gray-500/20', text: 'text-gray-700 dark:text-gray-300', label: 'Cancelled' },
};

const isValidCoverUrl = (url?: string): boolean =>
  !!url && (url.startsWith('http://') || url.startsWith('https://'));

const BookThumbnail = ({ coverUrl, title }: { coverUrl?: string; title?: string }) => {
  if (!isValidCoverUrl(coverUrl)) {
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

const formatHistoryDate = (dateString: string): string => {
  const date = new Date(normalizeTimestamp(dateString));
  if (Number.isNaN(date.getTime())) return dateString;
  return date.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
};

const normalizeTimestamp = (dateString: string): string =>
  dateString.includes('T') || dateString.endsWith('Z') ? dateString : `${dateString.replace(' ', 'T')}Z`;

export const RequestsSidebar = ({
  isOpen,
  onClose,
  requests,
  isAdmin,
  onApprove,
  onDeny,
  onRetry,
  onSeriesPack,
  onActivatePrerelease,
  onMoveToPrerelease,
  onSetStatus,
  onDelete,
  onMarkCompleted,
  onRefresh,
  quota,
  reports = [],
  adminReports = [],
  reportsNeedingAction,
  onReportProblem,
  onReportAgain,
  onReportAction,
}: RequestsSidebarProps) => {
  // 'default' until the viewer picks a tab, so the default follows isAdmin once it loads.
  const [chosenFilter, setFilter] = useState<FilterTab | 'default'>('default');
  const filter: FilterTab = chosenFilter === 'default' ? (isAdmin ? 'needs_action' : 'all') : chosenFilter;
  const hasPending = requests.some((r) => r.status === 'pending');
  const tabs: FilterTab[] = [
    ...(isAdmin ? ['needs_action' as const] : []),
    'all',
    'prerelease',
    'history',
    // Requests are approved automatically; the tab only remains for older pending ones.
    ...(hasPending || filter === 'pending' ? ['pending' as const] : []),
  ];
  const waitingReports = adminReports.filter((r) => REPORT_WAITING.includes(r.status));
  const needsActionCount = requests.filter((r) => r.status === 'failed').length + (reportsNeedingAction ?? waitingReports.length);
  const [busyReportIds, setBusyReportIds] = useState<Set<number>>(new Set());
  const [denyNoteId, setDenyNoteId] = useState<number | null>(null);
  const [denyNote, setDenyNote] = useState('');
  const [processingIds, setProcessingIds] = useState<Set<number>>(new Set());
  const [prereleaseDateById, setPrereleaseDateById] = useState<Record<number, string>>({});
  const [selectedStatusById, setSelectedStatusById] = useState<Record<number, RequestStatus>>({});
  const addProcessing = (id: number) => setProcessingIds(prev => new Set(prev).add(id));
  const removeProcessing = (id: number) => setProcessingIds(prev => { const next = new Set(prev); next.delete(id); return next; });
  const isProcessing = (id: number) => processingIds.has(id);

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
    if (filter === 'needs_action') return req.status === 'failed';
    if (filter === 'prerelease') return req.status === 'prerelease_requested';
    if (filter === 'pending') return req.status === 'pending';
    if (filter === 'history') return HISTORY_STATUSES.includes(req.status);
    return ACTIVE_STATUSES.includes(req.status) || (!isAdmin && req.status === 'failed');
  }).sort((a, b) => {
    if (filter !== 'history') return 0;
    const aTime = new Date(normalizeTimestamp(a.completed_at || a.updated_at)).getTime();
    const bTime = new Date(normalizeTimestamp(b.completed_at || b.updated_at)).getTime();
    return bTime - aTime;
  });

  // Admin report lists: waiting ones under Needs action, recently fixed (undoable) under History.
  const tabReports: MediaReport[] = !isAdmin ? [] : filter === 'needs_action' ? waitingReports
    : filter === 'history'
      ? adminReports.filter((r) => r.status === 'fixed'
        && Date.now() - new Date(normalizeTimestamp(r.updated_at)).getTime() < UNDO_WINDOW_MS)
      : [];
  const myReports = !isAdmin && filter === 'all' ? reports : [];

  const handleReportActionClick = async (reportId: number, action: ReportAction) => {
    if (!onReportAction) return;
    setBusyReportIds((prev) => new Set(prev).add(reportId));
    try {
      await onReportAction(reportId, action);
    } finally {
      setBusyReportIds((prev) => { const next = new Set(prev); next.delete(reportId); return next; });
    }
  };

  const handleApproveClick = async (requestId: number) => {
    addProcessing(requestId);
    try {
      await onApprove(requestId);
    } catch (error) {
      console.error('Failed to approve request:', error);
    } finally {
      removeProcessing(requestId);
    }
  };

  const handleDenyClick = async (requestId: number) => {
    if (denyNoteId === requestId) {
      // Submit deny with note
      addProcessing(requestId);
      try {
        await onDeny(requestId, denyNote || undefined);
        setDenyNoteId(null);
        setDenyNote('');
      } catch (error) {
        console.error('Failed to deny request:', error);
      } finally {
        removeProcessing(requestId);
      }
    } else {
      // Show note input
      setDenyNoteId(requestId);
      setDenyNote('');
    }
  };

  const handleRetryClick = async (requestId: number) => {
    addProcessing(requestId);
    try {
      await onRetry(requestId);
    } catch (error) {
      console.error('Failed to retry request:', error);
    } finally {
      removeProcessing(requestId);
    }
  };

  const handleSeriesPackClick = async (requestId: number, accept: boolean) => {
    if (!onSeriesPack) return;
    addProcessing(requestId);
    try {
      await onSeriesPack(requestId, accept);
    } catch (error) {
      console.error('Failed to answer series pack offer:', error);
    } finally {
      removeProcessing(requestId);
    }
  };

  const handleMarkCompletedClick = async (requestId: number) => {
    addProcessing(requestId);
    try {
      await onMarkCompleted(requestId);
    } catch (error) {
      console.error('Failed to mark request as completed:', error);
      // Re-throw so App.tsx can show error toast
      throw error;
    } finally {
      removeProcessing(requestId);
    }
  };

  const handleActivatePrereleaseClick = async (requestId: number) => {
    addProcessing(requestId);
    try {
      await onActivatePrerelease(requestId);
    } catch (error) {
      console.error('Failed to activate prerelease request:', error);
    } finally {
      removeProcessing(requestId);
    }
  };

  const handleClearFulfilled = async () => {
    // Clear all completed requests (fulfilled, denied, cancelled); failed ones still need the admin
    const clearableRequests = requests.filter((r) => HISTORY_STATUSES.includes(r.status));

    // Delete all clearable requests in parallel using the API directly,
    // then refresh once at the end to avoid stale optimistic rollback snapshots
    try {
      await Promise.allSettled(
        clearableRequests.map((r) => deleteBookRequest(r.id))
      );
    } catch (error) {
      console.error('Failed to clear completed requests:', error);
    }
    // Single refresh to sync UI with server state
    await onRefresh();
  };

  // Show clear button if there are any completed requests
  const hasClearable = requests.some(
    (r) => HISTORY_STATUSES.includes(r.status)
  );

  const getPrereleaseDateValue = (req: BookRequest): string =>
    prereleaseDateById[req.id] ?? req.expected_release_date ?? '';

  const getSelectedStatus = (req: BookRequest): RequestStatus =>
    selectedStatusById[req.id] ?? req.status;

  const handleAdminStatusApply = async (req: BookRequest) => {
    const nextStatus = getSelectedStatus(req);
    if (nextStatus === req.status) return;

    addProcessing(req.id);
    try {
      if (nextStatus === 'prerelease_requested') {
        const expectedReleaseDate = getPrereleaseDateValue(req);
        if (!expectedReleaseDate) {
          return;
        }
        await onMoveToPrerelease(req.id, expectedReleaseDate);
      } else {
        await onSetStatus(req.id, nextStatus);
      }
      setSelectedStatusById((prev) => {
        const next = { ...prev };
        delete next[req.id];
        return next;
      });
      if (nextStatus === 'prerelease_requested') {
        setPrereleaseDateById((prev) => {
          const next = { ...prev };
          delete next[req.id];
          return next;
        });
      }
    } catch (error) {
      console.error('Failed to apply request status change:', error);
    } finally {
      removeProcessing(req.id);
    }
  };

  const renderReportItem = (report: MediaReport) => {
    const busy = busyReportIds.has(report.id);
    const actionClass = 'px-2 py-0.5 text-xs font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed';
    const canRetry = report.status === 'needs_action' && FILE_PROBLEMS.includes(report.problem_type)
      && report.library === 'abs' && !!report.library_item_id;
    const canDismiss = report.status === 'needs_action' || report.status === 'awaiting_approval' || report.status === 'fixing';
    const action = (label: string, kind: ReportAction, className: string) => (
      <button
        type="button"
        onClick={() => handleReportActionClick(report.id, kind)}
        disabled={busy}
        className={`${actionClass} ${className}`}
      >
        {label}
      </button>
    );
    return (
      <div
        key={`report-${report.id}`}
        className="rounded-lg border p-3 flex flex-col gap-1"
        style={{ borderColor: 'var(--border-muted)', background: 'var(--bg-soft)' }}
      >
        <h3 className="font-semibold text-sm truncate" title={report.title}>{report.title}</h3>
        <p className="text-xs opacity-70 truncate">{report.author || 'Unknown Author'}</p>
        <div className="text-xs opacity-70">
          <span className="uppercase">{report.content_type}</span>
          <span> &middot; </span>
          <span>{PROBLEM_LABELS[report.problem_type]}</span>
          {isAdmin && !!report.reporter && <span> &middot; {report.reporter}</span>}
          {isAdmin && !!report.joined_count && <span> (+{report.joined_count} more)</span>}
          <span> &middot; </span>
          <span>{formatRelativeTime(report.created_at)}</span>
        </div>
        {!!report.note && <p className="text-xs italic text-gray-500 dark:text-gray-400">{report.note}</p>}
        {!!report.resolution_note && (
          <p className={`text-xs ${isAdmin && report.status === 'needs_action' ? 'text-red-600 dark:text-red-400 font-medium' : 'text-gray-500 dark:text-gray-400'}`}>
            {report.resolution_note}
          </p>
        )}
        <div className="flex items-center justify-between gap-2 pt-1">
          <div className="flex items-center gap-1 flex-wrap">
            {isAdmin && report.status === 'awaiting_approval' && action('Approve', 'approve', 'bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30')}
            {isAdmin && canRetry && action('Retry', 'retry', 'bg-accent-muted text-accent enabled:hover:bg-accent-muted-strong')}
            {isAdmin && canDismiss && action('Dismiss', 'dismiss', 'bg-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-500/30')}
            {isAdmin && report.status === 'fixed' && action('Undo', 'undo', 'bg-amber-500/20 text-amber-700 dark:text-amber-300 hover:bg-amber-500/30')}
            {!isAdmin && report.status === 'fixed' && report.problem_type === 'wrong_cover' && onReportAgain && (
              <button
                type="button"
                onClick={() => onReportAgain(report)}
                className={`${actionClass} bg-accent-muted text-accent enabled:hover:bg-accent-muted-strong`}
              >
                Still wrong?
              </button>
            )}
          </div>
          <span className="ml-auto px-2 py-0.5 rounded-lg text-xs font-medium bg-gray-500/20 text-gray-700 dark:text-gray-300">
            {isAdmin ? ADMIN_REPORT_LABELS[report.status] ?? report.status : reportStatusText(report.status)}
          </span>
        </div>
      </div>
    );
  };

  const renderRequestItem = (req: BookRequest) => {
    const statusStyle = isAdmin && req.status === 'failed' ? FAILED_ADMIN_STYLE : STATUS_STYLES[req.status];
    const isPending = req.status === 'pending';
    const isPrerelease = req.status === 'prerelease_requested';
    const selectedStatus = getSelectedStatus(req);
    const isHistoryItem = HISTORY_STATUSES.includes(req.status);
    // Show retry for: failed, cancelled, denied, stuck downloading, or approved (audiobooks)
    const isRetryable = req.status === 'failed' || req.status === 'cancelled' || req.status === 'denied' || req.status === 'downloading' || req.status === 'approved';
    const isDeniable = req.status === 'pending' || req.status === 'approved' || req.status === 'downloading' || req.status === 'failed';
    // Show "Mark Completed" for any non-fulfilled/non-cancelled request
    const canMarkCompleted = req.status !== 'fulfilled' && req.status !== 'cancelled';
    // Admins can also dismiss (hide) a failed request from Needs action.
    const canDismiss = isAdmin && filter === 'needs_action' && req.status === 'failed';
    const canDelete = (filter === 'history' && isHistoryItem) || canDismiss;

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
            title={canDismiss ? 'Dismiss from Needs action' : 'Remove from history'}
            aria-label={canDismiss ? 'Dismiss from Needs action' : 'Remove from history'}
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

            {isHistoryItem && (
              <p className="text-xs mt-1 text-gray-500 dark:text-gray-400">
                History date: {formatHistoryDate(req.completed_at || req.updated_at)}
              </p>
            )}

            {/* Admin note */}
            {!!req.admin_note && (
              <p
                className={`text-xs mt-1 ${req.status === 'failed' && isAdmin ? 'text-red-600 dark:text-red-400 font-medium' : 'text-gray-500 dark:text-gray-400 italic'}`}
                title={req.admin_note}
              >
                {req.admin_note}
              </p>
            )}
            {!isAdmin && req.status === 'failed' && (
              <p className="text-xs mt-1 text-amber-700 dark:text-amber-300">
                We couldn&apos;t get this one automatically. The admin has been notified and will look into it.
              </p>
            )}

            {/* Alternate version preference */}
            {!!req.prefer_alternate_version && (
              <p className="text-xs mt-1 italic" style={{ color: 'var(--accent)' }}>
                Prefers graphic/dramatized version
              </p>
            )}
            {!!req.is_manual_request && (
              <p className="text-xs mt-1 font-medium" style={{ color: 'var(--accent)' }}>
                Manual request
              </p>
            )}
            {req.is_released != null && !req.is_released && (
              <p className="text-xs mt-0.5 font-medium text-amber-600 dark:text-amber-400">
                Not yet released{req.expected_release_date ? ` — expected ${req.expected_release_date}` : ''}
              </p>
            )}
            {isPrerelease && req.expected_release_date && (
              <p className="text-xs mt-0.5 text-amber-700 dark:text-amber-300">
                Automatically approved at 9:00 AM ET on release day
              </p>
            )}
            {req.is_released != null && !!req.is_released && (
              <p className="text-xs mt-0.5 text-green-600 dark:text-green-400">
                Released
              </p>
            )}

            {/* Handled by (non-pending requests) */}
            {req.status !== 'pending' && req.status !== 'prerelease_requested' && !!(req.handled_by_display_name || req.handled_by_username) && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Handled by: {req.handled_by_display_name || req.handled_by_username}
              </p>
            )}

            {/* Status badge + admin actions */}
            <div className="flex items-center justify-between mt-auto pt-1 gap-2">
              {isAdmin && isPrerelease && (
                <div className="flex items-center gap-1 flex-wrap">
                  <button
                    type="button"
                    onClick={() => handleActivatePrereleaseClick(req.id)}
                    disabled={isProcessing(req.id)}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-amber-500/20 text-amber-700 dark:text-amber-300 hover:bg-amber-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isProcessing(req.id) ? 'Activating...' : 'Activate Now'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDenyClick(req.id)}
                    disabled={isProcessing(req.id)}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isProcessing(req.id) && denyNoteId === req.id ? 'Processing...' : 'Deny'}
                  </button>
                </div>
              )}

              {/* Admin approve/deny/complete buttons for pending items */}
              {isAdmin && isPending && (
                <div className="flex items-center gap-1 flex-wrap">
                  <button
                    type="button"
                    onClick={() => handleApproveClick(req.id)}
                    disabled={isProcessing(req.id)}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isProcessing(req.id) ? 'Processing...' : 'Approve'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleMarkCompletedClick(req.id)}
                    disabled={isProcessing(req.id)}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isProcessing(req.id) ? 'Marking...' : 'Mark Completed'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDenyClick(req.id)}
                    disabled={isProcessing(req.id)}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isProcessing(req.id) && denyNoteId === req.id ? 'Processing...' : 'Deny'}
                  </button>
                </div>
              )}

              {/* Series pack offer: the book has no release of its own */}
              {isAdmin && req.series_pack_offer && onSeriesPack && (
                <div className="flex flex-col gap-1 rounded-lg bg-amber-500/10 px-2 py-1.5">
                  <p className="text-xs text-amber-800 dark:text-amber-200">
                    Not available on its own. Grab the whole series pack <span className="font-medium">{req.series_pack_offer}</span>?
                  </p>
                  <div className="flex items-center gap-1 flex-wrap">
                    <button
                      type="button"
                      onClick={() => handleSeriesPackClick(req.id, true)}
                      disabled={isProcessing(req.id)}
                      className="px-2 py-0.5 text-xs font-medium rounded-lg bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isProcessing(req.id) ? 'Processing...' : 'Grab Series'}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSeriesPackClick(req.id, false)}
                      disabled={isProcessing(req.id)}
                      className="px-2 py-0.5 text-xs font-medium rounded-lg bg-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Decline
                    </button>
                  </div>
                </div>
              )}

              {/* Admin retry/deny/complete buttons for retryable items */}
              {isAdmin && isRetryable && (
                <div className="flex items-center gap-1 flex-wrap">
                  <button
                    type="button"
                    onClick={() => handleRetryClick(req.id)}
                    disabled={isProcessing(req.id)}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-accent-muted text-accent enabled:hover:bg-accent-muted-strong"
                  >
                    {isProcessing(req.id) ? 'Retrying...' : 'Retry'}
                  </button>
                  {canMarkCompleted && (
                    <button
                      type="button"
                      onClick={() => handleMarkCompletedClick(req.id)}
                      disabled={isProcessing(req.id)}
                      className="px-2 py-0.5 text-xs font-medium rounded-lg bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isProcessing(req.id) ? 'Marking...' : 'Mark Completed'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDenyClick(req.id)}
                    disabled={isProcessing(req.id)}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isProcessing(req.id) && denyNoteId === req.id ? 'Processing...' : 'Deny'}
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
                      disabled={isProcessing(req.id)}
                      className="px-2 py-0.5 text-xs font-medium rounded-lg bg-green-500/20 text-green-700 dark:text-green-300 hover:bg-green-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isProcessing(req.id) ? 'Marking...' : 'Mark Completed'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDenyClick(req.id)}
                    disabled={isProcessing(req.id)}
                    className="px-2 py-0.5 text-xs font-medium rounded-lg bg-red-500/20 text-red-700 dark:text-red-300 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isProcessing(req.id) && denyNoteId === req.id ? 'Processing...' : 'Deny'}
                  </button>
                </div>
              )}

              {req.status === 'fulfilled' && onReportProblem && (
                <button
                  type="button"
                  onClick={() => onReportProblem(req)}
                  className="px-2 py-0.5 text-xs font-medium rounded-lg transition-colors bg-accent-muted text-accent hover:bg-accent-muted-strong"
                >
                  Report a problem
                </button>
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
                  disabled={isProcessing(req.id)}
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
                  disabled={isProcessing(req.id)}
                  className="px-2 py-1 text-xs font-medium rounded bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isProcessing(req.id) ? 'Sending...' : 'Send'}
                </button>
              </div>
            )}

            {isAdmin && (
              <div className="flex flex-col gap-1 mt-1.5">
                <select
                  value={selectedStatus}
                  onChange={(e) => setSelectedStatusById(prev => ({ ...prev, [req.id]: e.target.value as RequestStatus }))}
                  className="w-full min-w-0 px-2 py-2 text-base rounded border border-[var(--border-muted)] bg-[var(--bg)]"
                  disabled={isProcessing(req.id)}
                  aria-label={`Status for ${req.title}`}
                >
                  <option value="pending">Pending</option>
                  <option value="prerelease_requested">Pre-release</option>
                  <option value="approved">Approved</option>
                  <option value="denied">Denied</option>
                  <option value="downloading">Downloading</option>
                  <option value="no_sources_requested">No Sources / Requested</option>
                  <option value="fulfilled">Fulfilled</option>
                  <option value="failed">Failed</option>
                  <option value="cancelled">Cancelled</option>
                </select>
                {selectedStatus === 'prerelease_requested' && (
                  <input
                    type="date"
                    value={getPrereleaseDateValue(req)}
                    onChange={(e) => setPrereleaseDateById(prev => ({ ...prev, [req.id]: e.target.value }))}
                    className="w-full min-w-0 max-w-full px-2 py-2 text-base rounded border border-[var(--border-muted)] bg-[var(--bg)]"
                    disabled={isProcessing(req.id)}
                    aria-label={`Release date for ${req.title}`}
                  />
                )}
                <button
                  type="button"
                  onClick={() => handleAdminStatusApply(req)}
                  disabled={
                    isProcessing(req.id) ||
                    selectedStatus === req.status ||
                    (selectedStatus === 'prerelease_requested' && !getPrereleaseDateValue(req))
                  }
                  className="w-full min-h-10 shrink-0 px-2 py-2 text-sm font-medium rounded-lg bg-amber-500/20 text-amber-700 dark:text-amber-300 hover:bg-amber-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isProcessing(req.id) ? 'Applying...' : 'Apply'}
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
        className={`fixed top-0 right-0 h-[100dvh] w-full sm:w-96 z-50 flex flex-col shadow-2xl transition-transform duration-300 ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
        style={{ background: 'var(--bg)' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between p-4 border-b"
          style={{ paddingTop: 'calc(1rem + env(safe-area-inset-top))', borderColor: 'var(--border-muted)' }}
        >
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">
              {isAdmin ? 'User Requests' : 'My Requests'}{requests.length > 0 && ` (${requests.length})`}
            </h2>
            {!isAdmin && quota && (
              <p className={`text-xs ${quota.remaining === 0 ? 'text-red-600 dark:text-red-400 font-medium' : 'opacity-70'}`}>
                {formatQuotaLeft(quota)} &middot; resets {formatResetDay(quota.resets_at)}
              </p>
            )}
          </div>
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
          {tabs.map((tab) => (
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
              {TAB_LABELS[tab]}{tab === 'needs_action' && needsActionCount > 0 ? ` (${needsActionCount})` : ''}
            </button>
          ))}
        </div>

        {/* Request Items */}
        <div
          className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3"
          style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))' }}
        >
          {filteredRequests.length > 0 && filteredRequests.map((req) => renderRequestItem(req))}
          {tabReports.map(renderReportItem)}
          {myReports.length > 0 && (
            <>
              <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide opacity-70">Reports</h3>
              {myReports.map(renderReportItem)}
            </>
          )}
          {filteredRequests.length === 0 && tabReports.length === 0 && myReports.length === 0 && (
            <div className="text-center text-sm opacity-70 mt-8">
              {filter === 'needs_action' ? 'Nothing needs your attention' : `No requests${filter !== 'all' ? ` (${TAB_LABELS[filter].toLowerCase()})` : ''}`}
            </div>
          )}
        </div>

        {/* Keep the regular-user Pre-release tab view-only. */}
        {(isAdmin || filter !== 'prerelease') && (
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
        )}
      </div>
    </>
  );
};
