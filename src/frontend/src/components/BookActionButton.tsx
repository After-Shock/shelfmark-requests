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
  isAdmin,
  showRequestButton,
  onRequest,
}: BookActionButtonProps) {
  const { searchMode } = useSearchMode();

  // Non-admin users with requests enabled see Request button only
  if (showRequestButton && !isAdmin && onRequest) {
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

    const sulleyBlue = '#00BCD4'; // Sulley from Monsters Inc - teal/turquoise
    const sulleyBlueHover = '#00ACC1';
    return (
      <button
        onClick={() => onRequest(book)}
        className={`${sizeClasses} rounded font-medium text-white transition-colors ${fullWidth ? 'w-full' : ''} ${className || ''}`}
        style={{
          backgroundColor: sulleyBlue,
          boxShadow: '0 2px 8px rgba(0, 188, 212, 0.3)',
          ...style
        }}
        onMouseEnter={(e) => e.currentTarget.style.backgroundColor = sulleyBlueHover}
        onMouseLeave={(e) => e.currentTarget.style.backgroundColor = sulleyBlue}
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
