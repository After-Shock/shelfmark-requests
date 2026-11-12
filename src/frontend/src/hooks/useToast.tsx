import { useCallback } from 'react';
import { toast } from 'sonner';

let nextId = 0;

export const useToast = () => {
  const showToast = useCallback((message: string, type: 'info' | 'success' | 'error' = 'info', persistent: boolean = false): string => {
    const id = `t${++nextId}`;
    // Persistent toasts are progress messages (debug logs, restart): spinner until dismissed.
    if (persistent) toast.loading(message, { id, duration: Infinity });
    else toast[type](message, { id });
    return id;
  }, []);

  const removeToast = useCallback((id: string) => {
    toast.dismiss(id);
  }, []);

  return { showToast, removeToast };
};
