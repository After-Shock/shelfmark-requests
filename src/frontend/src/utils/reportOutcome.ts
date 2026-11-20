import type { ProblemType, ReportStatus, RequestQuota } from '../types';

export const PROBLEM_LABELS: Record<ProblemType, string> = {
  wrong_language: 'Wrong language',
  wrong_edition: 'Wrong book or edition',
  broken_file: "Won't open / broken / bad formatting",
  audio_problem: 'Audio problem',
  wrong_cover: 'Wrong cover',
  wrong_details: 'Wrong title or author',
  other: 'Something else',
};

export const REPORT_LIMIT_MESSAGE = "You've used all your reports this week. They reset Monday.";
export const NOT_IN_LIBRARY_MESSAGE =
  "We couldn't find this in the library yet — your report will go to the admin.";

/** "2 of 6 reports left this week" for limited users. */
export const formatReportQuotaLeft = (quota: RequestQuota): string =>
  `${quota.remaining} of ${quota.limit} report${quota.limit === 1 ? '' : 's'} left this week`;

/** What the reporter sees for each report status. */
export const reportStatusText = (status: ReportStatus): string => {
  switch (status) {
    case 'open':
    case 'fixing':
      return "We're on it";
    case 'awaiting_approval':
    case 'needs_action':
      return 'Waiting on admin';
    case 'fixed':
      return 'Fixed';
    default:
      return 'Closed';
  }
};
