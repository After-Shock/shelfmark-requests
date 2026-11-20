import { useCallback, useEffect, useRef, useState } from 'react';
import { MediaReport } from '../types';
import { adminReportAction, getAdminReports, getMyReports, ReportAction } from '../services/api';

interface UseReportsOptions {
  enabled: boolean;
  isAdmin: boolean;
  /** Reports reload whenever the requests sidebar opens. */
  isOpen: boolean;
  /** Called after an admin action settles, so counts can refresh. */
  onChanged?: () => void;
}

const REFETCH_AFTER_ACTION_MS = 2000;

export const useReports = ({ enabled, isAdmin, isOpen, onChanged }: UseReportsOptions) => {
  const [reports, setReports] = useState<MediaReport[]>([]);
  const [adminReports, setAdminReports] = useState<MediaReport[]>([]);
  const timers = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      if (isAdmin) setAdminReports(await getAdminReports(['needs_action', 'awaiting_approval', 'fixed']));
      else setReports(await getMyReports());
    } catch (err) {
      console.error('Failed to fetch reports:', err);
    }
  }, [enabled, isAdmin]);

  useEffect(() => {
    if (isOpen) refresh();
  }, [isOpen, refresh]);

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach(clearTimeout);
  }, []);

  /** Actions answer 202 and finish in the background: show the row now, refetch once shortly after. */
  const act = useCallback(async (reportId: number, action: ReportAction) => {
    const row = await adminReportAction(reportId, action);
    setAdminReports((prev) => prev.map((r) => (r.id === reportId ? { ...r, ...row } : r)));
    const timer = setTimeout(() => {
      timers.current.delete(timer);
      refresh();
      onChanged?.();
    }, REFETCH_AFTER_ACTION_MS);
    timers.current.add(timer);
  }, [refresh, onChanged]);

  return { reports, adminReports, refreshReports: refresh, handleReportAction: act };
};
