import { useState, useEffect, useCallback, useRef } from 'react';
import { BookRequest, RequestCounts } from '../types';
import {
  createBookRequest,
  getRequests,
  getRequestCounts,
  approveRequest,
  denyRequest,
  retryRequest,
  deleteBookRequest,
} from '../services/api';
import { useSocket } from '../contexts/SocketContext';

interface UseRequestsOptions {
  enabled?: boolean;
}

interface UseRequestsReturn {
  requests: BookRequest[];
  counts: RequestCounts;
  isLoading: boolean;
  submitRequest: (data: {
    title: string;
    content_type?: string;
    author?: string;
    year?: string;
    cover_url?: string;
    description?: string;
    isbn_10?: string;
    isbn_13?: string;
    provider?: string;
    provider_id?: string;
    series_name?: string;
    series_position?: number;
  }) => Promise<BookRequest>;
  handleApprove: (requestId: number) => Promise<void>;
  handleDeny: (requestId: number, adminNote?: string) => Promise<void>;
  handleRetry: (requestId: number) => Promise<void>;
  handleDelete: (requestId: number) => Promise<void>;
  refreshRequests: () => Promise<void>;
}

const EMPTY_COUNTS: RequestCounts = {
  pending: 0,
  approved: 0,
  denied: 0,
  downloading: 0,
  fulfilled: 0,
  failed: 0,
  total: 0,
};

export const useRequests = ({
  enabled = true,
}: UseRequestsOptions = {}): UseRequestsReturn => {
  const { socket, connected } = useSocket();
  const [requests, setRequests] = useState<BookRequest[]>([]);
  const [counts, setCounts] = useState<RequestCounts>(EMPTY_COUNTS);
  const [isLoading, setIsLoading] = useState(false);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchAll = useCallback(async () => {
    if (!enabled) return;
    try {
      const [reqsResult, countsResult] = await Promise.all([
        getRequests(),
        getRequestCounts(),
      ]);
      setRequests(reqsResult.requests);
      setCounts(countsResult);
    } catch (err) {
      console.error('Failed to fetch requests:', err);
    }
  }, [enabled]);

  // WebSocket: listen for request_update events
  useEffect(() => {
    if (!enabled || !socket) return;

    const handleRequestUpdate = () => {
      fetchAll();
    };

    socket.on('request_update', handleRequestUpdate);
    return () => {
      socket.off('request_update', handleRequestUpdate);
    };
  }, [socket, enabled, fetchAll]);

  // Polling fallback when WebSocket is unavailable
  useEffect(() => {
    if (!enabled) return;

    if (connected) {
      // WebSocket active - stop polling
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    } else {
      // No WebSocket - poll every 15s
      if (!pollIntervalRef.current) {
        pollIntervalRef.current = setInterval(fetchAll, 15000);
      }
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [connected, enabled, fetchAll]);

  // Initial fetch
  useEffect(() => {
    if (enabled) {
      fetchAll();
    }
  }, [enabled, fetchAll]);

  const submitRequest = useCallback(async (data: Parameters<typeof createBookRequest>[0]) => {
    setIsLoading(true);
    try {
      const req = await createBookRequest(data);
      await fetchAll();
      return req;
    } finally {
      setIsLoading(false);
    }
  }, [fetchAll]);

  const handleApprove = useCallback(async (requestId: number) => {
    try {
      // Don't do optimistic update for approve - status changes rapidly (approved->downloading->fulfilled)
      // Let the server and WebSocket handle the updates
      await approveRequest(requestId);
      // Force immediate refresh to show the updated status
      await fetchAll();
    } catch (error) {
      console.error('Failed to approve request:', error);
      throw error;
    }
  }, [fetchAll]);

  const handleDeny = useCallback(async (requestId: number, adminNote?: string) => {
    try {
      // Don't do optimistic update - let server handle it
      await denyRequest(requestId, adminNote);
      // Force immediate refresh to show the updated status
      await fetchAll();
    } catch (error) {
      console.error('Failed to deny request:', error);
      throw error;
    }
  }, [fetchAll]);

  const handleRetry = useCallback(async (requestId: number) => {
    try {
      // Don't do optimistic update for retry - status changes rapidly (approved->downloading->fulfilled)
      // Let the server and WebSocket handle the updates
      await retryRequest(requestId);
      // Force immediate refresh to show the updated status
      await fetchAll();
    } catch (error) {
      console.error('Failed to retry request:', error);
      throw error;
    }
  }, [fetchAll]);

  const handleDelete = useCallback(async (requestId: number) => {
    // Optimistic update: remove from UI immediately
    const previousRequests = requests;
    const previousCounts = counts;

    // Remove from local state
    setRequests(prev => prev.filter(r => r.id !== requestId));

    // Update counts optimistically
    const deletedRequest = requests.find(r => r.id === requestId);
    if (deletedRequest) {
      setCounts(prev => ({
        ...prev,
        [deletedRequest.status]: Math.max(0, prev[deletedRequest.status as keyof RequestCounts] - 1),
        total: Math.max(0, prev.total - 1),
      }));
    }

    try {
      // Delete on server in background
      await deleteBookRequest(requestId);
      // Let WebSocket or polling refresh the data naturally
      // No need to await fetchAll() here
    } catch (error) {
      // Rollback on error
      console.error('Failed to delete request:', error);
      setRequests(previousRequests);
      setCounts(previousCounts);
      throw error; // Re-throw so caller can handle
    }
  }, [requests, counts]);

  return {
    requests,
    counts,
    isLoading,
    submitRequest,
    handleApprove,
    handleDeny,
    handleRetry,
    handleDelete,
    refreshRequests: fetchAll,
  };
};
