import { ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';

export { Dialog };

/**
 * Radix Dialog root for our modals. The modal component mounts/unmounts itself (and plays its own
 * exit animation), so the dialog is always open while rendered; dismiss requests go to onClose.
 * Inside, wrap the backdrop in <Dialog.Overlay asChild> and the panel in <Dialog.Content asChild>
 * to get focus trap/restore, Esc, outside-click, scroll lock and aria-hidden background.
 */
export const ModalRoot = ({ onClose, children }: { onClose: () => void; children: ReactNode }) => (
  <Dialog.Root open onOpenChange={open => { if (!open) onClose(); }}>
    <Dialog.Portal>{children}</Dialog.Portal>
  </Dialog.Root>
);

/** Pass as onPointerDownOutside so clicking a toast doesn't dismiss the modal. */
export const ignoreToastClicks = (e: { target: EventTarget | null; preventDefault: () => void }) => {
  if ((e.target as Element | null)?.closest?.('[data-sonner-toaster]')) e.preventDefault();
};

/** Pass as onOpenAutoFocus: focus the dialog itself rather than its first button (no stray focus ring on open). */
export const focusDialog = (e: Event) => {
  e.preventDefault();
  (e.currentTarget as HTMLElement | null)?.focus();
};
