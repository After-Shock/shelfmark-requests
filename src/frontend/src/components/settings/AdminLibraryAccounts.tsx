import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AdminLibraryStatus, LibraryPasswordResults, LibraryService,
  getAdminLibraryAccounts, linkAdminLibraryAccount, unlinkAdminLibraryAccount, setAdminLibraryPassword,
} from '../../services/api';

const services: LibraryService[] = ['calibre_web', 'audiobookshelf'];
const labels = { calibre_web: 'Ebooks', audiobookshelf: 'Audiobooks', requests: 'Requests' };
const inputClasses = 'w-full px-3 py-2 rounded-lg border border-[var(--border-muted)] bg-[var(--bg-soft)] text-sm';
const buttonClasses = 'px-3 py-2 rounded-lg text-sm border border-[var(--border-muted)] hover:bg-[var(--hover-surface)] disabled:opacity-40 disabled:cursor-not-allowed';
type Review = { action: 'link' | 'unlink'; service: LibraryService; accountId: string; username: string } | { action: 'password' };
interface Props {
  user: { id: number; username: string; auth_source?: string; oidc_subject?: string | null };
}

export function AdminLibraryAccounts({ user }: Props) {
  const [data, setData] = useState<AdminLibraryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const operation = useRef(false);
  const [selected, setSelected] = useState<Partial<Record<LibraryService, string>>>({});
  const [review, setReview] = useState<Review | null>(null);
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [results, setResults] = useState<LibraryPasswordResults['results'] | null>(null);
  const canSetPassword = (user.auth_source || (user.oidc_subject ? 'oidc' : 'builtin')) === 'builtin';

  const refresh = useCallback(async (afterMutation = false) => {
    setLoading(true);
    try {
      setData(await getAdminLibraryAccounts(user.id));
      setSelected({});
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not load library accounts';
      if (afterMutation) setNotice('');
      setError(afterMutation ? `The account change was saved, but could not refresh its status. ${message}` : message);
    } finally { setLoading(false); }
  }, [user.id]);
  useEffect(() => { void refresh(); }, [refresh]);

  const preparePassword = () => {
    setError('');
    if (password.length < 4) { setError('Password must be at least 4 characters'); return; }
    if (password !== confirmation) { setError('Passwords do not match'); return; }
    setReview({ action: 'password' });
  };

  const apply = async () => {
    if (!review || operation.current) return;
    operation.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    const action = review.action;
    try {
      if (review.action === 'link') {
        await linkAdminLibraryAccount(user.id, review.service, review.accountId);
        setNotice('Account linked. Passwords were unchanged. Set a shared password below, or have the user complete a password reset.');
      } else if (review.action === 'unlink') {
        await unlinkAdminLibraryAccount(user.id, review.service);
        setNotice('Account unlinked. Its library data and password were unchanged.');
      } else {
        const response = await setAdminLibraryPassword(user.id, password, confirmation);
        setResults(response.results);
        setNotice('Check each result below. To retry a failed update, enter the shared password again.');
      }
      setReview(null);
      await refresh(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update library account');
      // Do not leave a password review active after clearing its secret inputs.
      if (action === 'password') setReview(null);
    } finally {
      if (action === 'password') { setPassword(''); setConfirmation(''); }
      operation.current = false;
      setBusy(false);
    }
  };

  return (
    <section className="border-t border-[var(--border-muted)] pt-5 space-y-4" aria-label="Library accounts">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-sm font-medium">Library accounts</h4>
        <button type="button" className={buttonClasses} disabled={busy || loading} onClick={() => { setError(''); setReview(null); void refresh(); }}>Refresh accounts</button>
      </div>
      <p className="text-xs opacity-70">Link the existing account that belongs to this user. Usernames can differ. Linking does not change passwords.</p>
      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {loading && <p className="text-sm opacity-60">Loading library accounts…</p>}
      {data && services.map(service => {
        const entry = data.services[service];
        const label = labels[service];
        if (!entry) return null;
        const account = entry.account;
        const unavailable = entry.state === 'unavailable' || !!entry.error;
        const chosen = entry.candidates.find(candidate => candidate.id === selected[service]);
        const claimed = chosen?.owner_user_id != null && chosen.owner_user_id !== user.id;
        return (
          <div key={service} className="rounded-lg border border-[var(--border-muted)] p-3 space-y-3">
            <div className="flex justify-between items-center gap-2">
              <h5 className="text-sm font-medium">{label}</h5>
              <span className="text-xs opacity-70">{unavailable ? 'Unavailable' : entry.state === 'missing' ? 'Account missing' : entry.linked ? 'Linked' : 'Not linked'}</span>
            </div>
            {account && <div className="text-sm break-words"><p className="font-medium">{account.username}</p>{account.email && <p className="text-xs opacity-70">{account.email}</p>}</div>}
            {entry.error && <p className="text-sm text-amber-500">{entry.error}</p>}
            {!entry.offered && !entry.error && <p className="text-xs opacity-60">This library is not available.</p>}
            {(entry.linked || account) && (
              <button type="button" disabled={busy || loading || !!review} className={buttonClasses}
                onClick={() => { setError(''); setReview({ action: 'unlink', service, accountId: account?.id || '', username: account?.username || user.username }); }}>
                Unlink {label}
              </button>
            )}
            {entry.offered && <>
              <label className="block text-xs font-medium" htmlFor={`library-${service}-${user.id}`}>{label} account</label>
              <select id={`library-${service}-${user.id}`} className={inputClasses} disabled={busy || loading || !!review || unavailable}
                value={selected[service] || ''} onChange={event => { setError(''); setSelected(prev => ({ ...prev, [service]: event.target.value })); }}>
                <option value="">Choose an existing account…</option>
                {entry.candidates.map(candidate => {
                  const owned = candidate.owner_user_id != null && candidate.owner_user_id !== user.id;
                  return <option key={candidate.id} value={candidate.id} disabled={owned}>
                    {candidate.username}{candidate.email ? ` · ${candidate.email}` : ''}{owned ? ` · Linked to ${candidate.owner_username || `user ${candidate.owner_user_id}`}` : ''}
                  </option>;
                })}
              </select>
              {!entry.candidates.length && !unavailable && <p className="text-xs opacity-60">No existing accounts found.</p>}
              <button type="button" disabled={busy || loading || !!review || unavailable || !chosen || claimed || account?.id === chosen?.id} className={buttonClasses}
                onClick={() => chosen && setReview({ action: 'link', service, accountId: chosen.id, username: chosen.username })}>
                Review {label} link
              </button>
            </>}
          </div>
        );
      })}
      {data && canSetPassword && <div className="space-y-3">
        <h5 className="text-sm font-medium">Set shared password</h5>
        <p className="text-xs opacity-70">Enter a known current password or a new password. This overwrites the requests password and each linked library password. The existing password cannot be retrieved.</p>
        <label className="block text-xs font-medium" htmlFor={`shared-password-${user.id}`}>Shared password</label>
        <input id={`shared-password-${user.id}`} type="password" autoComplete="new-password" className={inputClasses} value={password} disabled={busy || !!review}
          onChange={event => setPassword(event.target.value)} />
        <label className="block text-xs font-medium" htmlFor={`shared-confirm-${user.id}`}>Confirm shared password</label>
        <input id={`shared-confirm-${user.id}`} type="password" autoComplete="new-password" className={inputClasses} value={confirmation} disabled={busy || !!review}
          onChange={event => setConfirmation(event.target.value)} />
        <button type="button" disabled={busy || loading || !!review} className={buttonClasses} onClick={preparePassword}>Review password update</button>
      </div>}
      {review && <div className="rounded-lg border border-[var(--border-muted)] p-3 space-y-3" role="group" aria-label="Review account change">
        <p className="text-sm break-words">
          {review.action === 'link' ? `Link ${review.username} to ${user.username} for ${labels[review.service]}? This replaces any current ${labels[review.service]} link.` :
            review.action === 'unlink' ? `Unlink ${review.username} from ${user.username}? The library account will remain.` :
              `Set the supplied password for requests account ${user.username}${services.filter(s => data?.services[s]?.linked).map(s => ` and ${labels[s]} (${data?.services[s]?.account?.username || user.username})`).join('')}?`}
        </p>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={`${buttonClasses} font-medium`} disabled={busy} onClick={() => void apply()}>
            {review.action === 'link' ? 'Confirm link' : review.action === 'unlink' ? 'Confirm unlink' : 'Confirm password update'}
          </button>
          <button type="button" className={buttonClasses} disabled={busy} onClick={() => setReview(null)}>Cancel review</button>
        </div>
      </div>}
      {results && <div aria-live="polite" className="text-sm space-y-1">
        {(['requests', ...services] as const).map(service => {
          const result = results[service];
          return result && <p key={service} className={result.status === 'error' ? 'text-red-500' : ''}>
            {labels[service]}: {result.status === 'updated' ? 'Updated' : result.status === 'error' ? 'Failed' : 'Skipped'}{result.message ? ` — ${result.message}` : ''}
          </p>;
        })}
      </div>}
    </section>
  );
}
