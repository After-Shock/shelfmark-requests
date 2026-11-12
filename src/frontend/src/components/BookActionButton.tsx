import { CSSProperties } from 'react';
import { Book, ButtonStateInfo } from '../types';
import { useSearchMode } from '../contexts/SearchModeContext';
import { BookDownloadButton } from './BookDownloadButton';
import { BookGetButton } from './BookGetButton';

type ButtonSize = 'sm' | 'md';
type ButtonVariant = 'default' | 'icon';

interface BookActionButtonProps {
  book: Book;
  buttonState: ButtonStateInfo;
  onDownload: (book: Book) => Promise<void>;
  onGetReleases: (book: Book) => void;
  isLoadingReleases?: boolean;
  size?: ButtonSize;
  variant?: ButtonVariant;
  fullWidth?: boolean;
  className?: string;
  style?: CSSProperties;
  isAdmin?: boolean;
  showRequestButton?: boolean;
  onRequest?: (book: Book) => void;
}

export function BookActionButton({
  book,
  buttonState,
  onDownload,
  onGetReleases,
  isLoadingReleases,
  size,
  variant = 'default',
  fullWidth,
  className,
  style,
  showRequestButton,
  onRequest,
}: BookActionButtonProps) {
  const { searchMode } = useSearchMode();

  // All users with requests enabled see Request button / In Library badge
  if (showRequestButton && onRequest) {
    const sizeClasses = size === 'sm' ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm';

    if (book.abs_owned) {
      return (
        <span
          className={`${sizeClasses} rounded font-medium text-white inline-block`}
          style={{ backgroundColor: '#6B7280' }}
          title="Already in your Audiobookshelf library"
        >
          In Library
        </span>
      );
    }

    return (
      <button
        onClick={() => onRequest(book)}
        className={`${sizeClasses} rounded font-medium text-white transition-colors bg-accent hover:bg-accent-hover ${fullWidth ? 'w-full' : ''} ${className || ''}`}
        style={{
          boxShadow: '0 2px 8px var(--accent-muted-strong)',
          ...style
        }}
      >
        Request
      </button>
    );
  }

  // Admin users see download buttons
  if (searchMode === 'universal') {
    return (
      <BookGetButton
        book={book}
        onGetReleases={onGetReleases}
        buttonState={buttonState}
        isLoading={isLoadingReleases}
        size={size}
        variant={variant}
        fullWidth={fullWidth}
        className={className}
        style={style}
      />
    );
  }

  return (
    <BookDownloadButton
      buttonState={buttonState}
      onDownload={() => onDownload(book)}
      size={size}
      variant={variant === 'default' ? 'primary' : 'icon'}
      fullWidth={fullWidth}
      className={className}
      style={style}
      ariaLabel={buttonState.text}
    />
  );
}
