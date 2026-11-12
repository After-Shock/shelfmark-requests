import { useEffect, useState } from 'react';
import { Command, defaultFilter } from 'cmdk';
import { BookRequest } from '../types';
import { STATUS_STYLES } from './RequestsSidebar';

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  requests: BookRequest[];
  theme: 'light' | 'dark';
  onSearch: (text: string) => void;
  onToggleTheme: () => void;
  onOpenRequests?: () => void;
  onOpenDownloads?: () => void;
  onOpenSettings?: () => void;
  onOpenAccount?: () => void;
  onManualRequest?: () => void;
  onLogout?: () => void;
  libraryUrl?: string;
  audiobookLibraryUrl?: string;
}

// Search row always matches (cmdk would otherwise fuzzy-score its value against the query).
const SEARCH_PREFIX = '__search ';
const filter = (value: string, search: string, keywords?: string[]) =>
  value.startsWith(SEARCH_PREFIX) ? 1 : defaultFilter(value, search, keywords);

const groupClass =
  '[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:opacity-60';

const itemClass =
  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm cursor-pointer select-none data-[selected=true]:bg-accent-muted';

/** Ctrl/⌘+K: search books, jump to your requests, or run app actions from the keyboard. */
export const CommandPalette = ({
  open,
  onOpenChange: setOpen,
  requests,
  theme,
  onSearch,
  onToggleTheme,
  onOpenRequests,
  onOpenDownloads,
  onOpenSettings,
  onOpenAccount,
  onManualRequest,
  onLogout,
  libraryUrl,
  audiobookLibraryUrl,
}: CommandPaletteProps) => {
  const [text, setText] = useState('');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(!open);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, setOpen]);

  useEffect(() => {
    if (!open) setText('');
  }, [open]);

  // Close first, then act, so the action's own modal/sidebar isn't fighting the palette for focus
  const run = (fn: () => void) => () => {
    setOpen(false);
    fn();
  };

  const actions = ([
    ['Open requests', onOpenRequests],
    ['Request a book manually', onManualRequest],
    ['Open downloads', onOpenDownloads],
    ['Open settings', onOpenSettings],
    ['Account settings', onOpenAccount],
    [`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`, onToggleTheme],
    ['Go to ebook library', libraryUrl ? () => void window.open(libraryUrl, '_blank', 'noopener') : undefined],
    ['Go to audiobook library', audiobookLibraryUrl ? () => void window.open(audiobookLibraryUrl, '_blank', 'noopener') : undefined],
    ['Log out', onLogout],
  ] as [string, (() => void) | undefined][]).filter((a): a is [string, () => void] => !!a[1]);

  const query = text.trim();

  // cmdk 1.1 sorts items within a group but never re-orders groups, so order them here:
  // a matching action ("settings", "dark mode") comes first; otherwise "Search books for …" is on
  // top so Enter searches, with your requests below it (titles overlap with what people search for).
  const actionMatches = !!query && actions.some(([label]) => defaultFilter(label, query) > 0);

  const searchGroup = query && (
    <Command.Group value="search">
      <Command.Item value={SEARCH_PREFIX + query} onSelect={run(() => onSearch(query))} className={itemClass}>
        <span className="flex-1 truncate">
          Search books for <strong>“{query}”</strong>
        </span>
      </Command.Item>
    </Command.Group>
  );

  const requestsGroup = onOpenRequests && requests.length > 0 && (
    <Command.Group heading="Requests" className={groupClass}>
      {requests.map(req => (
        <Command.Item
          key={req.id}
          value={`request ${req.id}`}
          keywords={[req.title, req.author ?? '', STATUS_STYLES[req.status]?.label ?? req.status]}
          onSelect={run(onOpenRequests)}
          className={itemClass}
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate">{req.title}</span>
            {req.author && <span className="block truncate text-xs opacity-60">{req.author}</span>}
          </span>
          <span className="shrink-0 rounded-full bg-[var(--bg-soft)] px-2 py-0.5 text-xs">
            {STATUS_STYLES[req.status]?.label ?? req.status}
          </span>
        </Command.Item>
      ))}
    </Command.Group>
  );

  const actionsGroup = (
    <Command.Group heading="Actions" className={groupClass}>
      {actions.map(([label, fn]) => (
        <Command.Item key={label} value={label} onSelect={run(fn)} className={itemClass}>
          {label}
        </Command.Item>
      ))}
    </Command.Group>
  );

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      filter={filter}
      loop
      overlayClassName="fixed inset-0 z-[1000] bg-black/50 backdrop-blur-[2px] animate-fade-in"
      contentClassName="fixed left-1/2 top-[15vh] z-[1001] w-[calc(100%-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-[var(--border-muted)] bg-[var(--bg)] text-[var(--text)] shadow-2xl"
    >
      <Command.Input
        value={text}
        onValueChange={setText}
        placeholder="Search books, your requests, or actions…"
        className="w-full border-b border-[var(--border-muted)] bg-transparent px-4 py-3 text-base outline-none placeholder:opacity-50"
      />
      <Command.List className="max-h-[50vh] overflow-y-auto p-2">
        {actionMatches && actionsGroup}
        {searchGroup}
        {requestsGroup}
        {!actionMatches && actionsGroup}
      </Command.List>
    </Command.Dialog>
  );
};
