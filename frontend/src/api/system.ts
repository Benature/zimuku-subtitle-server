import { API_ENDPOINTS } from '../lib/config';
import type { SubtitleLanguage } from '../types/api';
import { getData } from './shared';

export async function listSubtitleLanguages(): Promise<SubtitleLanguage[]> {
  return getData(API_ENDPOINTS.SUBTITLE_LANGUAGES);
}
