import { ReactNode, useRef, useState } from 'react';
import * as Popover from '@radix-ui/react-popover';

interface DropdownProps {
  label?: string;
  summary?: ReactNode;
  children: (helpers: { close: () => void }) => ReactNode;
  align?: 'left' | 'right';
  widthClassName?: string;
  buttonClassName?: string;
  panelClassName?: string;
  disabled?: boolean;
  renderTrigger?: (props: { isOpen: boolean; toggle: () => void }) => ReactNode;
  /** Disable max-height and overflow scrolling (for panels with nested dropdowns) */
  noScrollLimit?: boolean;
}

export const Dropdown = ({
  label,
  summary,
  children,
  align = 'left',
  widthClassName = 'w-full',
  buttonClassName = '',
  panelClassName = '',
  disabled = false,
  renderTrigger,
  noScrollLimit = false,
}: DropdownProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  const toggleOpen = () => {
    if (disabled) return;
    setIsOpen(prev => !prev);
  };

  const close = () => setIsOpen(false);

  return (
    <Popover.Root open={isOpen} onOpenChange={setIsOpen}>
      <div className={widthClassName}>
        {label && (
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5" onClick={toggleOpen}>
            {label}
          </label>
        )}
        <Popover.Anchor asChild>
          <div ref={anchorRef}>
            {renderTrigger ? (
              renderTrigger({ isOpen, toggle: toggleOpen })
            ) : (
              <button
                type="button"
                onClick={toggleOpen}
                disabled={disabled}
                aria-expanded={isOpen}
                className={`w-full px-3 py-2 text-sm border rounded-lg flex items-center justify-between text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary-color)] ${buttonClassName}`}
                style={{
                  background: 'var(--bg-soft)',
                  color: 'var(--text)',
                  borderColor: isOpen ? 'var(--primary-color)' : 'var(--border-muted)',
                }}
              >
                <span className="truncate">
                  {summary ?? <span className="opacity-60">Select an option</span>}
                </span>
                <svg
                  className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  strokeWidth="1.5"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
                </svg>
              </button>
            )}
          </div>
        </Popover.Anchor>
      </div>
      <Popover.Portal>
        <Popover.Content
          ref={contentRef}
          align={align === 'right' ? 'end' : 'start'}
          sideOffset={6}
          collisionPadding={8}
          // Trigger lives in the anchor, so clicks on it are "outside" — let its own toggle handle them.
          onInteractOutside={e => {
            if (anchorRef.current?.contains(e.target as Node)) e.preventDefault();
          }}
          // No Popover.Trigger to restore focus to; send it back to the anchor's control.
          onCloseAutoFocus={e => {
            e.preventDefault();
            const active = document.activeElement;
            if (active && active !== document.body && !contentRef.current?.contains(active)) return; // user moved on
            anchorRef.current?.querySelector<HTMLElement>('button, [tabindex]')?.focus();
          }}
          className={`z-[1100] border rounded-lg shadow-lg animate-fade-in ${panelClassName || 'w-[var(--radix-popover-trigger-width)]'}`}
          style={{ background: 'var(--bg)', borderColor: 'var(--border-muted)', color: 'var(--text)' }}
        >
          <div className={noScrollLimit ? '' : 'max-h-64 overflow-auto'}>
            {children({ close })}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
};
