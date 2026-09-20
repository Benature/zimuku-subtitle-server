import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query';
import { listSettings, testJellyfinConnection, updateSetting } from '../../api';
import { queryKeys } from '../../lib/queryKeys';
import type { Setting } from '../../types/api';

type SettingsQueryOptions = Omit<
  UseQueryOptions<Setting[], Error, Setting[], ReturnType<typeof queryKeys.settings.list>>,
  'queryKey' | 'queryFn'
>;

async function invalidateSettingsQuery(queryClient: QueryClient): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: queryKeys.settings.list() });
}

export function useSettingsQuery(options?: SettingsQueryOptions) {
  return useQuery({
    queryKey: queryKeys.settings.list(),
    queryFn: listSettings,
    ...options,
  });
}

export function useUpdateSettingMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ key, value, description }: { key: string; value: string; description?: string }) =>
      updateSetting(key, value, description),
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient);
    },
  });
}

export function useJellyfinTestMutation() {
  return useMutation({
    mutationFn: testJellyfinConnection,
  });
}
