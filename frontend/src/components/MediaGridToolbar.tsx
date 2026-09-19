import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { SortOption, FilterOption, SortOrder } from '../types/api';

const SORT_OPTIONS: SortOption[] = ['name', 'year', 'created', 'status'];
const FILTER_OPTIONS: FilterOption[] = ['all', 'missing'];

interface MediaGridToolbarProps {
  title: string;
  searchTerm: string;
  onSearchTermChange: (val: string) => void;
  searchPlaceholder: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  sortOption?: SortOption;
  onSortOptionChange?: (opt: SortOption) => void;
  sortOrder?: SortOrder;
  filterOption?: FilterOption;
  onFilterOptionChange?: (opt: FilterOption) => void;
}

function getSortLabel(
  sortOption: SortOption,
  t: ReturnType<typeof useTranslation>['t'],
): string {
  switch (sortOption) {
    case 'name':
      return t('sort.name');
    case 'year':
      return t('sort.year');
    case 'created':
      return t('sort.created');
    case 'status':
      return t('sort.subtitleStatus');
    default:
      return '';
  }
}

function getFilterLabel(
  filterOption: FilterOption,
  t: ReturnType<typeof useTranslation>['t'],
): string {
  return filterOption === 'all' ? t('filter.all') : t('filter.missing');
}

function getFilterButtonClass(activeFilter: FilterOption, filterOption: FilterOption): string {
  if (activeFilter === filterOption) {
    return 'bg-primary-container text-primary shadow-[0_4px_12px_rgba(189,194,255,0.3)]';
  }

  return 'text-on-surface-variant hover:bg-surface-container-high';
}

export function MediaGridToolbar({
  title,
  searchTerm,
  onSearchTermChange,
  searchPlaceholder,
  onRefresh,
  isRefreshing,
  sortOption = 'name',
  onSortOptionChange,
  sortOrder = 'asc',
  filterOption = 'all',
  onFilterOptionChange,
}: MediaGridToolbarProps): React.JSX.Element {
  const { t } = useTranslation();
  const [isSortOpen, setIsSortOpen] = useState(false);

  const currentSortLabel = useMemo(() => getSortLabel(sortOption, t), [sortOption, t]);

  return (
    <div className="flex flex-wrap items-center gap-3 px-6 py-4 border-b border-outline-variant/10 shrink-0">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-bold font-headline text-on-surface">{title}</h1>
        <button
          onClick={onRefresh}
          disabled={isRefreshing}
          className={`w-8 h-8 rounded-full bg-surface-container flex items-center justify-center text-primary hover:bg-primary hover:text-surface-container transition-all active:scale-90 ${isRefreshing ? 'opacity-50 cursor-not-allowed' : ''}`}
          title={t('status.rescan')}
        >
          <span className={`material-symbols-outlined text-sm ${isRefreshing ? 'animate-spin' : ''}`}>sync</span>
        </button>
      </div>

      <div className="relative group flex-1 min-w-[180px]">
        <input
          type="text"
          placeholder={searchPlaceholder}
          value={searchTerm}
          onChange={e => onSearchTermChange(e.target.value)}
          className="w-full bg-surface-container rounded-xl py-2.5 pl-10 pr-4 border-none focus:ring-1 focus:ring-primary/40 text-sm font-body transition-all placeholder:text-outline text-on-surface outline-none"
        />
        <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-outline text-xl group-focus-within:text-primary transition-colors">search</span>
      </div>

      <div className="flex p-1 bg-surface-container rounded-xl border border-outline-variant/5 shadow-inner">
        {FILTER_OPTIONS.map(option => (
          <button
            key={option}
            onClick={() => onFilterOptionChange?.(option)}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-all duration-300 ${getFilterButtonClass(filterOption, option)}`}
          >
            {getFilterLabel(option, t)}
          </button>
        ))}
      </div>

      <div className="relative">
        <button
          onClick={() => setIsSortOpen(!isSortOpen)}
          className="flex items-center gap-2 bg-surface-container hover:bg-surface-container-high text-on-surface-variant font-bold py-2.5 px-4 rounded-xl transition-all border border-outline-variant/10 active:scale-95 shadow-sm"
        >
          <span className="material-symbols-outlined text-sm">sort</span>
          <span className="text-xs uppercase tracking-wider">{currentSortLabel}</span>
          <span className={`material-symbols-outlined text-[14px] transition-transform duration-300 ${sortOrder === 'desc' ? 'rotate-180' : ''}`}>straight</span>
        </button>

        {isSortOpen && (
          <div className="absolute right-0 mt-2 w-40 bg-surface-container-high rounded-xl shadow-2xl border border-outline-variant/10 z-50 overflow-hidden backdrop-blur-md">
            {SORT_OPTIONS.map(option => (
              <button
                key={option}
                onClick={() => {
                  onSortOptionChange?.(option);
                  setIsSortOpen(false);
                }}
                className={`w-full text-left px-4 py-3 text-xs font-bold transition-colors hover:bg-primary/10 ${sortOption === option ? 'text-primary bg-primary/5' : 'text-on-surface-variant'}`}
              >
                {getSortLabel(option, t)}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
