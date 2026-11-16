import type { CreateBookRequestResponse, RequestQuota } from '../types';

/** "4 of 6 requests left this week" for limited users. */
export const formatQuotaLeft = (quota: RequestQuota): string =>
  `${quota.remaining} of ${quota.limit} request${quota.limit === 1 ? '' : 's'} left this week`;

export const getRequestOutcomeMessage = (
  response: CreateBookRequestResponse,
  title: string,
): { message: string; type: 'success' | 'info' } => {
  if (response.already_joined) {
    return { message: `You are already tracking this request: ${title}`, type: 'info' };
  }
  if (response.joined_existing) {
    return { message: `Joined existing request: ${title}`, type: 'success' };
  }
  if (response.warning) {
    return {
      message: 'Standard version already in library — request submitted for graphic/dramatized version.',
      type: 'info',
    };
  }
  const left = response.quota ? ` · ${formatQuotaLeft(response.quota)}` : '';
  return { message: `Requested: ${title}${left}`, type: 'success' };
};
