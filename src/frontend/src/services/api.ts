import { Book, StatusData, AppConfig, LoginCredentials, AuthResponse, ReleaseSource, ReleasesResponse, BookRequest, CreateBookRequestResponse, RequestsListResponse, RequestCounts, RequestQuota, ContentType, ProblemType, MediaReport, LibraryMatch, CreateReportResponse } from '../types';
import { SettingsResponse, ActionResult, UpdateResult } from '../types/settings';
import { MetadataBookData, transformMetadataToBook } from '../utils/bookTransformers';
import { getApiBase } from '../utils/basePath';

const API_BASE = getApiBase();

// API endpoints
const API = {
  search: `${API_BASE}/search`,
  metadataSearch: `${API_BASE}/metadata/search`,
  info: `${API_BASE}/info`,
  download: `${API_BASE}/download`,
  status: `${API_BASE}/status`,
  cancelDownload: `${API_BASE}/download`,
  setPriority: `${API_BASE}/queue`,
  clearCompleted: `${API_BASE}/queue/clear`,
  config: `${API_BASE}/config`,
  login: `${API_BASE}/auth/login`,
  logout: `${API_BASE}/auth/logout`,
  authCheck: `${API_BASE}/auth/check`,
  settings: `${API_BASE}/settings`,
  absCheck: `${API_BASE}/abs/check`,
};

// Custom error class for authentication failures
export class AuthenticationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AuthenticationError';
  }
}

// Custom error class for request timeouts
export class TimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TimeoutError';
  }
}

// Default request timeout in milliseconds (30 seconds)
const DEFAULT_TIMEOUT_MS = 30000;

// Utility function for JSON fetch with credentials and timeout
async function fetchJSON<T>(
  url: string,
  opts: RequestInit = {},
  timeoutMs: number | null = DEFAULT_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = timeoutMs && timeoutMs > 0
    ? setTimeout(() => controller.abort(), timeoutMs)
    : null;

  try {
    const res = await fetch(url, {
      ...opts,
      credentials: 'include',  // Enable cookies for session
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...opts.headers,
      },
    });

    if (!res.ok) {
      // Try to parse error message from response body
      let errorMessage = `${res.status} ${res.statusText}`;
      let hasServerMessage = false;
      try {
        const errorData = await res.json();
        // Prefer user-friendly 'message' field, fall back to 'error'
        if (errorData.message) {
          errorMessage = errorData.message;
          hasServerMessage = true;
        } else if (errorData.error) {
          errorMessage = errorData.error;
          hasServerMessage = true;
        }
      } catch (e) {
        // Log parse failure for debugging - server may have returned non-JSON (e.g., HTML error page)
        console.warn(`Failed to parse error response from ${url}:`, e instanceof Error ? e.message : e);
      }

      // Provide helpful message for gateway/proxy errors
      if (res.status === 502 || res.status === 503 || res.status === 504) {
        if (!hasServerMessage) {
          errorMessage = `Server unavailable (${res.status}). If using a reverse proxy, check its configuration.`;
        }
      }

      // Throw appropriate error based on status code
      if (res.status === 401) {
        throw new AuthenticationError(errorMessage);
      }

      throw Object.assign(new Error(errorMessage), { status: res.status });
    }

    return res.json();
  } catch (error) {
    // Handle abort/timeout errors
    if (error instanceof Error && error.name === 'AbortError') {
      throw new TimeoutError('Request timed out. Check your network connection or proxy configuration.');
    }
    throw error;
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
  }
}

// API functions
export const searchBooks = async (query: string): Promise<Book[]> => {
  if (!query) return [];
  return fetchJSON<Book[]>(`${API.search}?${query}`);
};

// Metadata search response type (internal)
interface MetadataSearchResponse {
  books: MetadataBookData[];
  provider: string;
  query: string;
  page?: number;
  total_found?: number;
  has_more?: boolean;
}

// Metadata search result with pagination info
export interface MetadataSearchResult {
  books: Book[];
  page: number;
  totalFound: number;
  hasMore: boolean;
}

// Search metadata providers and normalize to Book format
export const searchMetadata = async (
  query: string,
  limit: number = 40,
  sort: string = 'relevance',
  fields: Record<string, string | number | boolean> = {},
  page: number = 1,
  contentType: string = 'ebook'
): Promise<MetadataSearchResult> => {
  const hasFields = Object.values(fields).some(v => v !== '' && v !== false);

  if (!query && !hasFields) {
    return { books: [], page: 1, totalFound: 0, hasMore: false };
  }

  const params = new URLSearchParams();
  if (query) {
    params.set('query', query);
  }
  params.set('limit', String(limit));
  params.set('sort', sort);
  params.set('page', String(page));
  params.set('content_type', contentType);

  // Add custom search field values
  Object.entries(fields).forEach(([key, value]) => {
    if (value !== '' && value !== false) {
      params.set(key, String(value));
    }
  });

  const response = await fetchJSON<MetadataSearchResponse>(`${API.metadataSearch}?${params.toString()}`);

  return {
    books: response.books.map(transformMetadataToBook),
    page: response.page || page,
    totalFound: response.total_found || 0,
    hasMore: response.has_more || false,
  };
};

export const getBookInfo = async (id: string): Promise<Book> => {
  return fetchJSON<Book>(`${API.info}?id=${encodeURIComponent(id)}`);
};

// Get full book details from a metadata provider
export const getMetadataBookInfo = async (provider: string, bookId: string): Promise<Book> => {
  const response = await fetchJSON<MetadataBookData>(
    `${API_BASE}/metadata/book/${encodeURIComponent(provider)}/${encodeURIComponent(bookId)}`
  );

  return transformMetadataToBook(response);
};

export const downloadBook = async (id: string, emailRecipient?: string): Promise<void> => {
  const params = new URLSearchParams();
  params.set('id', id);
  if (emailRecipient) {
    params.set('email_recipient', emailRecipient);
  }
  await fetchJSON(`${API.download}?${params.toString()}`);
};

// Download a specific release (from ReleaseModal)
export const downloadRelease = async (release: {
  source: string;
  source_id: string;
  title: string;
  author?: string;   // Author from metadata provider
  year?: string;     // Year from metadata provider
  format?: string;
  size?: string;
  size_bytes?: number;
  download_url?: string;
  protocol?: string;
  indexer?: string;
  seeders?: number;
  extra?: Record<string, unknown>;
  preview?: string;  // Book cover from metadata provider
  content_type?: string;  // "ebook" or "audiobook" - for directory routing
  series_name?: string;
  series_position?: number;
  subtitle?: string;
  isbn?: string;  // Written into EPUBs so Calibre matches metadata by ISBN
  search_author?: string;
  email_recipient?: string;
}): Promise<void> => {
  await fetchJSON(`${API_BASE}/releases/download`, {
    method: 'POST',
    body: JSON.stringify(release),
  });
};

export const getStatus = async (): Promise<StatusData> => {
  return fetchJSON<StatusData>(API.status);
};

export const cancelDownload = async (id: string): Promise<void> => {
  await fetchJSON(`${API.cancelDownload}/${encodeURIComponent(id)}/cancel`, { method: 'DELETE' });
};

export const retryDownload = async (id: string): Promise<void> => {
  await fetchJSON(`${API.cancelDownload}/${encodeURIComponent(id)}/retry`, { method: 'POST' });
};

export const markDownloadComplete = async (id: string): Promise<void> => {
  await fetchJSON(`${API.cancelDownload}/${encodeURIComponent(id)}/mark-complete`, { method: 'POST' });
};

export const clearCompleted = async (): Promise<void> => {
  await fetchJSON(`${API_BASE}/queue/clear`, { method: 'DELETE' });
};

export const getConfig = async (): Promise<AppConfig> => {
  return fetchJSON<AppConfig>(API.config);
};

// Authentication functions
export const login = async (credentials: LoginCredentials): Promise<AuthResponse> => {
  return fetchJSON<AuthResponse>(API.login, {
    method: 'POST',
    body: JSON.stringify(credentials),
  });
};

export const logout = async (): Promise<AuthResponse> => {
  return fetchJSON<AuthResponse>(API.logout, {
    method: 'POST',
  });
};

export const checkAuth = async (): Promise<AuthResponse> => {
  return fetchJSON<AuthResponse>(API.authCheck);
};

// Settings API functions
export const getSettings = async (): Promise<SettingsResponse> => {
  return fetchJSON<SettingsResponse>(API.settings);
};

export const updateSettings = async (
  tabName: string,
  values: Record<string, unknown>
): Promise<UpdateResult> => {
  return fetchJSON<UpdateResult>(`${API.settings}/${tabName}`, {
    method: 'PUT',
    body: JSON.stringify(values),
  });
};

export const executeSettingsAction = async (
  tabName: string,
  actionKey: string,
  currentValues?: Record<string, unknown>
): Promise<ActionResult> => {
  return fetchJSON<ActionResult>(`${API.settings}/${tabName}/action/${actionKey}`, {
    method: 'POST',
    body: currentValues ? JSON.stringify(currentValues) : undefined,
  });
};

// Onboarding API functions

export interface OnboardingStepCondition {
  field: string;
  value: unknown;
}

export interface OnboardingStep {
  id: string;
  title: string;
  tab: string;
  fields: import('../types/settings').SettingsField[];
  showWhen?: OnboardingStepCondition[];  // Array of conditions (all must be true)
  optional?: boolean;
}

export interface OnboardingConfig {
  steps: OnboardingStep[];
  values: Record<string, unknown>;
  complete: boolean;
}

export const getOnboarding = async (): Promise<OnboardingConfig> => {
  return fetchJSON<OnboardingConfig>(`${API_BASE}/onboarding`);
};

export const saveOnboarding = async (
  values: Record<string, unknown>
): Promise<{ success: boolean; message: string }> => {
  return fetchJSON<{ success: boolean; message: string }>(`${API_BASE}/onboarding`, {
    method: 'POST',
    body: JSON.stringify(values),
  });
};

export const skipOnboarding = async (): Promise<{ success: boolean; message: string }> => {
  return fetchJSON<{ success: boolean; message: string }>(`${API_BASE}/onboarding/skip`, {
    method: 'POST',
  });
};

// Release source API functions

// Get available release sources from plugin registry
export const getReleaseSources = async (): Promise<ReleaseSource[]> => {
  return fetchJSON<ReleaseSource[]>(`${API_BASE}/release-sources`);
};

// Search for releases of a book
export const getReleases = async (
  provider: string,
  bookId: string,
  source?: string,
  title?: string,
  author?: string,
  expandSearch?: boolean,
  languages?: string[],
  contentType?: string,
  manualQuery?: string,
  indexers?: string[]
): Promise<ReleasesResponse> => {
  const params = new URLSearchParams({
    provider,
    book_id: bookId,
  });
  if (source) {
    params.set('source', source);
  }
  if (title) {
    params.set('title', title);
  }
  if (author) {
    params.set('author', author);
  }
  if (expandSearch) {
    params.set('expand_search', 'true');
  }
  if (languages && languages.length > 0) {
    params.set('languages', languages.join(','));
  }
  if (contentType) {
    params.set('content_type', contentType);
  }
  if (manualQuery) {
    params.set('manual_query', manualQuery);
  }
  if (indexers && indexers.length > 0) {
    params.set('indexers', indexers.join(','));
  }
  // Let the backend control timeouts for release searches (can be long-running).
  return fetchJSON<ReleasesResponse>(`${API_BASE}/releases?${params.toString()}`, {}, null);
};

// Admin user management API

export interface InviteCode {
  id: number;
  code: string;
  created_by: number | null;
  created_at: string;
  used_by: number | null;
  used_at: string | null;
  expires_at: string | null;
}

export const getInviteCodes = async (): Promise<InviteCode[]> => {
  return fetchJSON<InviteCode[]>(`${API_BASE}/admin/invites`);
};

export const createInviteCode = async (expiresInHours?: number | null): Promise<InviteCode> => {
  return fetchJSON<InviteCode>(`${API_BASE}/admin/invites`, {
    method: 'POST',
    body: JSON.stringify(expiresInHours ? { expires_in_hours: expiresInHours } : {}),
  });
};

export const deleteInviteCode = async (inviteId: number): Promise<{ success: boolean }> => {
  return fetchJSON<{ success: boolean }>(`${API_BASE}/admin/invites/${inviteId}`, {
    method: 'DELETE',
  });
};

export interface PasswordResetCode {
  id: number;
  user_id: number;
  username: string;
  code: string;
  created_by: number | null;
  created_at: string;
  used_at: string | null;
  expires_at: string;
}

export const getPasswordResetCodes = async (): Promise<PasswordResetCode[]> => {
  return fetchJSON<PasswordResetCode[]>(`${API_BASE}/admin/password-resets`);
};

export const createPasswordResetCode = async (
  userId: number,
  expiresInHours = 24,
): Promise<PasswordResetCode> => {
  return fetchJSON<PasswordResetCode>(`${API_BASE}/admin/password-resets`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, expires_in_hours: expiresInHours }),
  });
};

export const deletePasswordResetCode = async (resetId: number): Promise<{ success: boolean }> => {
  return fetchJSON<{ success: boolean }>(`${API_BASE}/admin/password-resets/${resetId}`, {
    method: 'DELETE',
  });
};

export interface AdminUser {
  id: number;
  username: string;
  email: string | null;
  display_name: string | null;
  role: string;
  oidc_subject: string | null;
  auth_source?: string;
  warnings?: string[];
  created_at: string;
  weekly_request_limit?: number | null;
  request_quota?: RequestQuota | null;
  weekly_report_limit?: number | null;
  report_quota?: RequestQuota | null;
}

export const getAdminUsers = async (): Promise<AdminUser[]> => {
  return fetchJSON<AdminUser[]>(`${API_BASE}/admin/users`);
};

export const getAdminUser = async (userId: number): Promise<AdminUser> => {
  return fetchJSON<AdminUser>(`${API_BASE}/admin/users/${userId}`);
};

export const createAdminUser = async (
  data: { username: string; password: string; email?: string; display_name?: string; role?: string }
): Promise<AdminUser> => {
  return fetchJSON<AdminUser>(`${API_BASE}/admin/users`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
};

export const updateAdminUser = async (
  userId: number,
  data: Partial<Pick<AdminUser, 'role' | 'email' | 'display_name' | 'weekly_request_limit' | 'weekly_report_limit'>> & {
    password?: string;
  }
): Promise<AdminUser> => {
  return fetchJSON<AdminUser>(`${API_BASE}/admin/users/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
};

export const getRequestLimits = async (): Promise<{ default: number }> => {
  return fetchJSON<{ default: number }>(`${API_BASE}/admin/request-limits`);
};

export const updateDefaultRequestLimit = async (value: number): Promise<{ default: number }> => {
  return fetchJSON<{ default: number }>(`${API_BASE}/admin/request-limits`, {
    method: 'PUT',
    body: JSON.stringify({ default: value }),
  });
};

/** Start the weekly request count over for one user, or for everyone when userId is omitted. */
export const resetRequestLimits = async (userId?: number): Promise<{ success: boolean }> => {
  return fetchJSON<{ success: boolean }>(`${API_BASE}/admin/request-limits/reset`, {
    method: 'POST',
    body: JSON.stringify(userId === undefined ? {} : { user_id: userId }),
  });
};

export const getReportLimits = async (): Promise<{ default: number }> => {
  return fetchJSON<{ default: number }>(`${API_BASE}/admin/report-limits`);
};

export const updateDefaultReportLimit = async (value: number): Promise<{ default: number }> => {
  return fetchJSON<{ default: number }>(`${API_BASE}/admin/report-limits`, {
    method: 'PUT',
    body: JSON.stringify({ default: value }),
  });
};

/** Start the weekly report count over for one user, or for everyone when userId is omitted. */
export const resetReportLimits = async (userId?: number): Promise<{ success: boolean }> => {
  return fetchJSON<{ success: boolean }>(`${API_BASE}/admin/report-limits/reset`, {
    method: 'POST',
    body: JSON.stringify(userId === undefined ? {} : { user_id: userId }),
  });
};

export const deleteAdminUser = async (userId: number): Promise<{ success: boolean }> => {
  return fetchJSON<{ success: boolean }>(`${API_BASE}/admin/users/${userId}`, {
    method: 'DELETE',
  });
};

export interface DownloadDefaults {
  OIDC_ADMIN_GROUP: string;
  OIDC_USE_ADMIN_GROUP: boolean;
  OIDC_AUTO_PROVISION: boolean;
}

export const getDownloadDefaults = async (): Promise<DownloadDefaults> => {
  return fetchJSON<DownloadDefaults>(`${API_BASE}/admin/download-defaults`);
};

// Auth setup and registration

export const setupAdmin = async (data: {
  username: string;
  password: string;
  email?: string;
}): Promise<{ success: boolean; user: { id: number; username: string; role: string } }> => {
  return fetchJSON(`${API_BASE}/auth/setup`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
};

export const registerUser = async (data: {
  username: string;
  password: string;
  email?: string;
  invite_code: string;
  services?: {
    audiobookshelf?: boolean;
    calibre_web?: boolean;
  };
}): Promise<{ success: boolean; warnings?: string[]; link_offers?: LibraryService[] }> => {
  return fetchJSON(`${API_BASE}/auth/register`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
};

export const resetPassword = async (data: {
  username: string;
  code: string;
  password: string;
}): Promise<{ success: boolean; warnings?: string[] }> => {
  return fetchJSON(`${API_BASE}/auth/reset-password`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
};

export const requestPasswordResetEmail = async (identifier: string): Promise<{ success: boolean }> => {
  return fetchJSON(`${API_BASE}/auth/forgot-password`, {
    method: 'POST',
    body: JSON.stringify({ identifier }),
  });
};

export const completePasswordResetEmail = async (data: {
  token: string;
  password: string;
}): Promise<{ success: boolean; username: string; updated: string[]; warnings?: string[] }> => {
  return fetchJSON(`${API_BASE}/auth/forgot-password/complete`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
};

export const changePassword = async (data: {
  new_password: string;
}): Promise<{ success: boolean; message: string }> => {
  const result = await fetchJSON<{ warnings?: string[] }>(`${API_BASE}/users/me`, {
    method: 'PUT',
    body: JSON.stringify({ password: data.new_password }),
  });
  const warn = result.warnings?.length ? ` Some library passwords could not be updated: ${result.warnings.join('; ')}` : '';
  return { success: true, message: warn };
};

export type LibraryService = 'audiobookshelf' | 'calibre_web';
export type LibraryAccounts = Record<LibraryService, {
  offered: boolean;
  has_account: boolean;
  linked: boolean;
  unavailable?: boolean; // offered, but couldn't be reached just now
  app_url?: string | null;
  kindle_sender?: string | null; // Calibre-Web's Send-to-Kindle From address
}>;

export const getLibraryAccounts = async (): Promise<LibraryAccounts> => {
  return fetchJSON(`${API_BASE}/users/me/library-accounts`);
};

export const addLibraryAccount = async (data: {
  service: LibraryService;
  password: string;
  app_password?: string;
}): Promise<{ success: boolean; message: string; app_url?: string | null; username?: string }> => {
  return fetchJSON(`${API_BASE}/users/me/library-accounts`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
};

// Audiobookshelf library ownership check
export const checkAbsOwned = async (
  title: string,
  author: string
): Promise<{ owned: boolean; match: { title: string; author: string } | null }> => {
  const params = new URLSearchParams({ title, author });
  return fetchJSON(`${API.absCheck}?${params.toString()}`);
};

// Book request API functions

export const createBookRequest = async (
  data: {
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
    prefer_alternate_version?: boolean;
    is_manual_request?: boolean;
    is_released?: boolean | null;
    expected_release_date?: string | null;
  }
): Promise<CreateBookRequestResponse> => {
  return fetchJSON<CreateBookRequestResponse>(`${API_BASE}/requests`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
};

export const getRequests = async (
  status?: string,
  limit: number = 100,
  offset: number = 0
): Promise<RequestsListResponse> => {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  return fetchJSON<RequestsListResponse>(`${API_BASE}/requests?${params.toString()}`);
};

export const getRequestCounts = async (): Promise<RequestCounts> => {
  return fetchJSON<RequestCounts>(`${API_BASE}/requests/counts`);
};

export const approveRequest = async (requestId: number): Promise<BookRequest> => {
  return fetchJSON<BookRequest>(`${API_BASE}/requests/${requestId}/approve`, {
    method: 'POST',
  });
};

export const denyRequest = async (
  requestId: number,
  adminNote?: string
): Promise<BookRequest> => {
  return fetchJSON<BookRequest>(`${API_BASE}/requests/${requestId}/deny`, {
    method: 'POST',
    body: JSON.stringify({ admin_note: adminNote }),
  });
};

export const retryRequest = async (requestId: number): Promise<BookRequest> => {
  return fetchJSON<BookRequest>(`${API_BASE}/requests/${requestId}/retry`, {
    method: 'POST',
  });
};

export const respondToSeriesPack = async (requestId: number, accept: boolean): Promise<BookRequest> => {
  return fetchJSON<BookRequest>(`${API_BASE}/requests/${requestId}/series-pack`, {
    method: 'POST',
    body: JSON.stringify({ accept }),
  });
};

export const activatePrereleaseRequest = async (requestId: number): Promise<BookRequest> => {
  return fetchJSON<BookRequest>(`${API_BASE}/requests/${requestId}/activate`, {
    method: 'POST',
  });
};

export const moveRequestToPrerelease = async (
  requestId: number,
  expectedReleaseDate: string
): Promise<BookRequest> => {
  return fetchJSON<BookRequest>(`${API_BASE}/requests/${requestId}/move-to-prerelease`, {
    method: 'POST',
    body: JSON.stringify({ expected_release_date: expectedReleaseDate }),
  });
};

export const deleteBookRequest = async (requestId: number): Promise<{ success: boolean }> => {
  return fetchJSON<{ success: boolean }>(`${API_BASE}/requests/${requestId}`, {
    method: 'DELETE',
  });
};

export const markRequestsViewed = async (): Promise<{ success: boolean }> => {
  return fetchJSON<{ success: boolean }>(`${API_BASE}/requests/mark-viewed`, {
    method: 'POST',
  });
};

export const updateRequestStatus = async (
  requestId: number,
  status: string,
  adminNote?: string
): Promise<BookRequest> => {
  return fetchJSON<BookRequest>(`${API_BASE}/requests/${requestId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status, admin_note: adminNote }),
  });
};


export interface AdminLibraryAccount {
  id: string;
  username: string;
  email: string | null;
  owner_user_id?: number | null;
  owner_username?: string | null;
}
export interface AdminLibraryService {
  offered: boolean;
  linked: boolean;
  account: AdminLibraryAccount | null;
  candidates: AdminLibraryAccount[];
  state?: string;
  error?: string;
}
export type AdminLibraryStatus = { services: Record<LibraryService, AdminLibraryService> };
export interface LibraryPasswordResult {
  status: 'updated' | 'skipped' | 'error';
  message?: string;
}
export type LibraryPasswordResults = { results: Partial<Record<LibraryService | 'requests', LibraryPasswordResult>> };

export const getAdminLibraryAccounts = (userId: number): Promise<AdminLibraryStatus> =>
  fetchJSON(`${API_BASE}/admin/users/${userId}/library-accounts`);

export const linkAdminLibraryAccount = (userId: number, service: LibraryService, accountId: string): Promise<{ success: boolean }> =>
  fetchJSON(`${API_BASE}/admin/users/${userId}/library-accounts/${service}`, {
    method: 'PUT', body: JSON.stringify({ account_id: accountId }),
  });

export const unlinkAdminLibraryAccount = (userId: number, service: LibraryService): Promise<{ success: boolean }> =>
  fetchJSON(`${API_BASE}/admin/users/${userId}/library-accounts/${service}`, { method: 'DELETE' });

export const setAdminLibraryPassword = (userId: number, password: string, confirmation: string): Promise<LibraryPasswordResults> =>
  fetchJSON(`${API_BASE}/admin/users/${userId}/library-accounts/password`, {
    method: 'POST', body: JSON.stringify({ password, confirmation }),
  }, 60000);

// --- Media issue reports ---

export const getLibraryMatches = async (
  title: string, author: string, contentType: ContentType
): Promise<LibraryMatch[]> => {
  const params = new URLSearchParams({ title, author, content_type: contentType });
  const data = await fetchJSON<{ matches: LibraryMatch[] }>(`${API_BASE}/library/matches?${params}`);
  return data.matches;
};

export const createReport = async (data: {
  problem_type: ProblemType;
  title: string;
  author?: string;
  content_type: ContentType;
  note?: string;
  library_item_id?: string;
  request_id?: number;
  provider?: string;
  provider_id?: string;
}): Promise<CreateReportResponse> => {
  return fetchJSON<CreateReportResponse>(`${API_BASE}/reports`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
};

export const getMyReports = async (): Promise<MediaReport[]> => {
  return fetchJSON<MediaReport[]>(`${API_BASE}/reports`);
};

export const getAdminReports = async (statuses: string[]): Promise<MediaReport[]> => {
  return fetchJSON<MediaReport[]>(`${API_BASE}/admin/reports?status=${statuses.join(',')}`);
};

export type ReportAction = 'approve' | 'dismiss' | 'undo' | 'retry';

/** The server answers 202 and works in the background; a 409 throws with the server's text. */
export const adminReportAction = async (reportId: number, action: ReportAction): Promise<MediaReport> => {
  const data = await fetchJSON<{ report: MediaReport }>(`${API_BASE}/admin/reports/${reportId}/${action}`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
  return data.report;
};
