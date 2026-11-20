import { useEffect, useState } from 'react';
import { ContentType, CreateReportResponse, LibraryMatch, ProblemType, RequestQuota } from '../types';
import { createReport, getLibraryMatches } from '../services/api';
import {
  formatReportQuotaLeft, NOT_IN_LIBRARY_MESSAGE, PROBLEM_LABELS, REPORT_LIMIT_MESSAGE,
} from '../utils/reportOutcome';
import { Dialog, ModalRoot, ignoreToastClicks, focusDialog } from './shared/ModalRoot';

export interface ReportTarget {
  title: string;
  author: string;
  contentType: ContentType;
  /** Already-known library matches (search results); omit to look them up (History). */
  matches?: LibraryMatch[];
  requestId?: number;
  provider?: string;
  providerId?: string;
  preset?: ProblemType;
}

interface ReportProblemModalProps {
  target: ReportTarget;
  /** Weekly report limit; null/undefined = unlimited. */
  quota?: RequestQuota | null;
  onClose: () => void;
  onDone: (result: CreateReportResponse) => void;
}

const PROBLEMS = Object.keys(PROBLEM_LABELS) as ProblemType[];

const MatchRow = ({ match }: { match: LibraryMatch }) => (
  <span className="flex items-center gap-3 min-w-0">
    {match.cover ? (
      <img src={match.cover} alt="" className="w-10 h-14 object-cover rounded shrink-0" />
    ) : (
      <span className="w-10 h-14 rounded bg-gray-200 dark:bg-gray-700 shrink-0" aria-hidden="true" />
    )}
    <span className="min-w-0">
      <span className="block text-sm font-medium truncate">{match.title}</span>
      <span className="block text-xs opacity-70 truncate">{match.author}</span>
    </span>
  </span>
);

export const ReportProblemModal = ({ target, quota, onClose, onDone }: ReportProblemModalProps) => {
  const [matches, setMatches] = useState<LibraryMatch[] | null>(target.matches ?? null);
  const [problem, setProblem] = useState<ProblemType | null>(target.preset ?? null);
  const [note, setNote] = useState('');
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (target.matches) return;
    getLibraryMatches(target.title, target.author, target.contentType)
      .then(setMatches)
      .catch(() => setMatches([]));
  }, [target]);

  const chosen = matches?.length === 1 ? matches[0] : matches?.find((m) => m.library_item_id === pickedId);
  const outOfReports = !!quota && quota.remaining === 0;
  const canSubmit = !busy && !outOfReports && !!problem && matches !== null
    && (problem !== 'other' || note.trim().length > 0)
    && (matches.length < 2 || !!chosen);

  const handleSubmit = async () => {
    if (!canSubmit || !problem) return;
    setBusy(true);
    setError(null);
    try {
      onDone(await createReport({
        problem_type: problem,
        title: chosen?.title ?? target.title,
        author: chosen?.author ?? target.author,
        content_type: target.contentType,
        ...(note.trim() && { note: note.trim() }),
        ...(chosen?.library_item_id && { library_item_id: chosen.library_item_id }),
        ...(target.requestId !== undefined && { request_id: target.requestId }),
        ...(target.provider && { provider: target.provider }),
        ...(target.providerId && { provider_id: target.providerId }),
      }));
    } catch (err) {
      setError((err as { status?: number }).status === 429
        ? REPORT_LIMIT_MESSAGE
        : err instanceof Error ? err.message : 'Failed to send report');
      setBusy(false);
    }
  };

  const problems = PROBLEMS.filter((p) => p !== 'audio_problem' || target.contentType === 'audiobook');

  return (
    <ModalRoot onClose={onClose}>
    <Dialog.Overlay className="modal-overlay active sm:px-6 sm:py-6">
      <Dialog.Content aria-describedby={undefined} onOpenAutoFocus={focusDialog} onPointerDownOutside={ignoreToastClicks} className="w-full max-w-md settings-modal-enter">
        <div className="flex flex-col max-h-[100dvh] rounded-none sm:rounded-2xl border-0 sm:border border-[var(--border-muted)] bg-[var(--bg)] text-[var(--text)] shadow-none sm:shadow-2xl overflow-hidden">
          <header className="flex items-center justify-between border-b border-[var(--border-muted)] px-5 py-4">
            <Dialog.Title className="text-lg font-semibold">Report a problem</Dialog.Title>
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

          <div className="px-5 py-5 flex flex-col gap-4 overflow-y-auto">
            {matches === null && <p className="text-sm opacity-70">Looking in the library...</p>}
            {matches?.length === 0 && (
              <p className="text-sm">
                <span className="font-medium">{target.title}</span>
                <span className="block text-xs opacity-70 mt-1">{NOT_IN_LIBRARY_MESSAGE}</span>
              </p>
            )}
            {matches?.length === 1 && <MatchRow match={matches[0]} />}
            {matches && matches.length > 1 && (
              <fieldset className="flex flex-col gap-2">
                <legend className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">Which one?</legend>
                {matches.map((m) => (
                  <label key={m.library_item_id ?? m.title} className="flex items-center gap-3 cursor-pointer rounded-lg border border-[var(--border-muted)] bg-[var(--bg-soft)] p-2">
                    <input
                      type="radio"
                      name="report-match"
                      checked={m.library_item_id === pickedId}
                      onChange={() => setPickedId(m.library_item_id)}
                    />
                    <MatchRow match={m} />
                  </label>
                ))}
              </fieldset>
            )}

            <fieldset className="flex flex-col gap-1.5">
              <legend className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">What's wrong?</legend>
              {problems.map((p) => (
                <label key={p} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="radio" name="report-problem" checked={problem === p} onChange={() => setProblem(p)} className="accent-accent" />
                  {PROBLEM_LABELS[p]}
                </label>
              ))}
            </fieldset>

            <textarea
              aria-label="Note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder={problem === 'other' ? 'Describe the problem (required)' : 'Add a note (optional)'}
              className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2"
              style={{ background: 'var(--bg-soft)', borderColor: 'var(--border-muted)', color: 'var(--text)' }}
            />

            {(error || outOfReports) && (
              <p className="text-sm text-red-600 dark:text-red-400" role="alert">{error ?? REPORT_LIMIT_MESSAGE}</p>
            )}
          </div>

          <footer
            className="border-t border-[var(--border-muted)] px-5 py-4 flex items-center justify-between gap-2"
            style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))' }}
          >
            <span className={`text-xs ${outOfReports ? 'text-red-600 dark:text-red-400 font-medium' : 'opacity-70'}`}>
              {quota ? formatReportQuotaLeft(quota) : ''}
            </span>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              className="px-6 py-2 rounded-full text-sm font-medium text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-accent enabled:hover:bg-accent-hover"
            >
              {busy ? 'Sending...' : 'Send report'}
            </button>
          </footer>
        </div>
      </Dialog.Content>
    </Dialog.Overlay>
    </ModalRoot>
  );
};
