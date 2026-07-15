import { describe, expect, it } from 'vitest';
import type { CreateBookRequestResponse } from '../types';
import { getRequestOutcomeMessage } from './requestOutcome';

const response = { id: 1, title: 'Dune' } as CreateBookRequestResponse;

const alternateWarning = {
  message: 'Standard version already in library — request submitted for graphic/dramatized version.',
  type: 'info',
} as const;

describe('getRequestOutcomeMessage', () => {
  it('reports a newly requested book', () => {
    expect(getRequestOutcomeMessage(response, 'Dune')).toEqual({
      message: 'Requested: Dune', type: 'success',
    });
  });

  it('reports a joined request', () => {
    expect(getRequestOutcomeMessage({ ...response, joined_existing: true }, 'Dune')).toEqual({
      message: 'Joined existing request: Dune', type: 'success',
    });
  });

  it('reports an idempotent repeat', () => {
    expect(getRequestOutcomeMessage({ ...response, already_joined: true }, 'Dune')).toEqual({
      message: 'You are already tracking this request: Dune', type: 'info',
    });
  });

  it('reports the exact alternate-version warning', () => {
    expect(getRequestOutcomeMessage({ ...response, warning: 'alternate' }, 'Dune')).toEqual(alternateWarning);
  });

  it('prioritizes an alternate-version warning over joining a request', () => {
    expect(getRequestOutcomeMessage({ ...response, warning: 'alternate', joined_existing: true }, 'Dune')).toEqual(alternateWarning);
  });

  it('prioritizes an alternate-version warning over an idempotent repeat', () => {
    expect(getRequestOutcomeMessage({ ...response, warning: 'alternate', already_joined: true }, 'Dune')).toEqual(alternateWarning);
  });
});
