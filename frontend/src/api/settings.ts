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

export interface MediaServerTestResult {
  status: string;
  message: string;
  connected: boolean;
}

export async function testMediaServerConnection(): Promise<MediaServerTestResult> {
  return postData(API_ENDPOINTS.SETTINGS_MEDIA_SERVER_TEST);
}
