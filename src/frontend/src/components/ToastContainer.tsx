import { useEffect, useState } from 'react';
import { Toast } from '../types';
import { theme } from '../theme';

interface ToastContainerProps {
  toasts: Toast[];
}

export const ToastContainer = ({ toasts }: ToastContainerProps) => {
  const [visibleToasts, setVisibleToasts] = useState<Set<string>>(new Set());

  useEffect(() => {
    toasts.forEach(toast => {
      if (!visibleToasts.has(toast.id)) {
        setTimeout(() => {
          setVisibleToasts(prev => new Set([...prev, toast.id]));
        }, 10);
      }
    });
  }, [toasts]);

  const toastTypeStyles: Record<Toast['type'], { backgroundColor: string; color: string }> = {
    success: { backgroundColor: '#9333ea', color: 'white' },  // Purple for success notifications
    error: { backgroundColor: '#dc2626', color: 'white' },
    info: { backgroundColor: theme.primary.turquoise, color: 'white' },
  };

  return (
    <div id="toast-container" className="fixed bottom-4 right-4 z-[100] space-y-2">
      {toasts.map(toast => (
        <div
          key={toast.id}
          className={`toast-notification px-4 py-3 rounded-md shadow-lg text-sm font-medium transition-all duration-300 ${
            visibleToasts.has(toast.id) ? 'toast-visible' : ''
          }`}
          style={toastTypeStyles[toast.type]}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
};
