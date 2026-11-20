import { useEffect, useState } from 'react';
import { ContentType, LibraryMatch } from '../types';
import { getLibraryMatches } from '../services/api';

// One lookup per title|author|type for the whole session, shared by every result that asks.
const cache = new Map<string, Promise<LibraryMatch[]>>();

/** Library matches for a result; null while the check is pending (callers keep showing Request). */
export const useLibraryMatches = (
  title: string, author: string, contentType: ContentType | undefined, enabled: boolean,
): LibraryMatch[] | null => {
  const [matches, setMatches] = useState<LibraryMatch[] | null>(null);
  const key = `${title}|${author}|${contentType}`;

  useEffect(() => {
    setMatches(null);
    if (!enabled || !contentType || !title) return;
    let live = true;
    let lookup = cache.get(key);
    if (!lookup) {
      lookup = getLibraryMatches(title, author, contentType).catch(() => {
        cache.delete(key);  // a failed check is retried next time; the Request button still works
        return [];
      });
      cache.set(key, lookup);
    }
    lookup.then((m) => live && setMatches(m));
    return () => { live = false; };
  }, [key, enabled]);  // eslint-disable-line react-hooks/exhaustive-deps

  return matches;
};
