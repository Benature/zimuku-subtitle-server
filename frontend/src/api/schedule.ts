import { API_ENDPOINTS } from '../lib/config';
import { getData, postData } from './shared';

export interface ScheduleLastRun {
  started_at: string;
  finished_at: string;
  trigger: string;
  stats: {
    scanned_files?: number;
    missing_subtitle?: number;
    matched?: number;
    failed?: number;
    failed_files?: string[];
    titles?: string[];
    remaining_works?: number;
  };
  error?: string | null;
}

export interface ScheduleStatus {
  enabled: boolean;
  cron: string;
  next_run_time: string | null;
  running: boolean;
  last_run: ScheduleLastRun | null;
}

export interface FeishuTestResult {
  status: string;
  message: string;
  delivered: boolean;
}

export async function getScheduleStatus(): Promise<ScheduleStatus> {
  return getData(API_ENDPOINTS.SCHEDULE_STATUS);
}

export async function runScheduleNow(): Promise<void> {
  return postData(API_ENDPOINTS.SCHEDULE_RUN_NOW);
}

export async function sendFeishuTest(): Promise<FeishuTestResult> {
  return postData(API_ENDPOINTS.SCHEDULE_FEISHU_TEST);
}
