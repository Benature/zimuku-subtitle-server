import { useQuery } from '@tanstack/react-query';
import { listSubtitleLanguages } from '../../api';
import { queryKeys } from '../../lib/queryKeys';

export function useSubtitleLanguagesQuery() {
  return useQuery({
    queryKey: queryKeys.system.subtitleLanguages(),
    queryFn: listSubtitleLanguages,
  });
}
