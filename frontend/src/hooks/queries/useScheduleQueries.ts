import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getScheduleStatus, runScheduleNow, sendFeishuTest } from '../../api';
import { queryKeys } from '../../lib/queryKeys';

export function useScheduleStatusQuery() {
  return useQuery({
    queryKey: queryKeys.schedule.status(),
    queryFn: getScheduleStatus,
    refetchInterval: 10000,
  });
}

export function useRunScheduleNowMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: runScheduleNow,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.schedule.status() });
    },
  });
}

export function useFeishuTestMutation() {
  return useMutation({
    mutationFn: sendFeishuTest,
  });
}
