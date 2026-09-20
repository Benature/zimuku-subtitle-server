import { API_ENDPOINTS } from '../lib/config';
import type { Setting } from '../types/api';
import { getData, postData } from './shared';

export async function listSettings(): Promise<Setting[]> {
  return getData(API_ENDPOINTS.SETTINGS);
}

export async function updateSetting(
  key: string,
  value: string,
  description?: string
): Promise<void> {
  return postData(API_ENDPOINTS.SETTINGS, { key, value, description });
}

export interface JellyfinTestResult {
  status: string;
  message: string;
  connected: boolean;
}

export async function testJellyfinConnection(): Promise<JellyfinTestResult> {
  return postData(API_ENDPOINTS.SETTINGS_JELLYFIN_TEST);
}
