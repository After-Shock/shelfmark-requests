import type { CreateBookRequestResponse } from '../types';

export const getRequestOutcomeMessage = (
  response: CreateBookRequestResponse,
  title: string,
): { message: string; type: 'success' | 'info' } => {
  if (response.warning) {
    return {
      message: 'Standard version already in library — request submitted for graphic/dramatized version.',
      type: 'info',
    };
  }
  if (response.already_joined) {
    return { message: `You are already tracking this request: ${title}`, type: 'info' };
  }
  if (response.joined_existing) {
    return { message: `Joined existing request: ${title}`, type: 'success' };
  }
  return { message: `Requested: ${title}`, type: 'success' };
};
