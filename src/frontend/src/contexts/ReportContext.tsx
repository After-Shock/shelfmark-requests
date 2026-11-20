import { createContext, useContext } from 'react';
import type { ContentType } from '../types';
import type { ReportTarget } from '../components/ReportProblemModal';

/** Lets result buttons open the report modal without threading props through every results view. */
export interface ReportContextValue {
  contentType: ContentType;
  openReport: (target: ReportTarget) => void;
}

export const ReportContext = createContext<ReportContextValue | null>(null);
export const useReportContext = () => useContext(ReportContext);
