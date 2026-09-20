import { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, NavLink, Link } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { queryClient } from './lib/queryClient';
import { MediaPollingProvider } from './contexts/MediaPollingContext';
import { ToastProvider } from './contexts/ToastContext';
import './i18n';

const HomePage = lazy(() => import('./pages/HomePage'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const MoviesPage = lazy(() => import('./pages/MoviesPage'));
const SeriesPage = lazy(() => import('./pages/SeriesPage'));
const TasksPage = lazy(() => import('./pages/TasksPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));

function RouteFallback() {
  // 懒加载切页时保持既有布局，仅让内容区维持空白过渡，避免引入新的视觉占位。
  return <div className="h-full w-full" aria-hidden="true" />;
}

function Sidebar() {
  const { t } = useTranslation();
  const navItems = [
    { path: '/', label: t('nav.home'), icon: 'dashboard' },
    { path: '/search', label: t('nav.search'), icon: 'search' },
    { path: '/movies', label: t('nav.movies'), icon: 'movie' },
    { path: '/series', label: t('nav.series'), icon: 'tv' },
    { path: '/tasks', label: t('nav.tasks'), icon: 'task' },
    { path: '/settings', label: t('nav.settings'), icon: 'settings', mt: true },
  ];

  return (
    <nav className="fixed left-4 top-4 bottom-4 w-20 hover:w-64 transition-all duration-500 rounded-2xl z-50 overflow-hidden bg-[#060e20]/70 backdrop-blur-xl shadow-[0_0_40px_rgba(138,149,255,0.06)] flex flex-col h-full py-8 gap-2 group border border-outline-variant/10">
      {/* Logo Area */}
      <Link to="/" className="flex items-center gap-4 px-6 mb-8 overflow-hidden group/logo">
        <div className="min-w-[32px] h-8 bg-gradient-to-br from-primary to-primary-container rounded-lg flex items-center justify-center shadow-lg group-hover/logo:scale-110 transition-transform">
          <span className="material-symbols-outlined text-on-primary text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>movie</span>
        </div>
        <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-300 whitespace-nowrap">
          <p className="text-2xl font-bold tracking-tight text-[#bdc2ff] font-headline -mt-1">Zimuku</p>
          <p className="text-[10px] text-on-surface-variant font-label uppercase tracking-widest mt-0.5">Subtitle Server</p>
        </div>
      </Link>
      {/* ...rest of navigation items remain the same... */}
      <div className="flex-1 space-y-1 flex flex-col">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              `flex items-center gap-4 px-4 py-3 mx-2 rounded-xl transition-all ${item.mt ? 'mt-auto' : ''
              } ${isActive
                ? 'bg-primary/10 text-primary active:scale-95 shadow-sm'
                : 'text-slate-400 hover:bg-surface-container-high/60 hover:text-white'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span className="material-symbols-outlined shrink-0" style={{ fontVariationSettings: isActive ? "'FILL' 1" : "'FILL' 0" }}>{item.icon}</span>
                <span className="opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap font-body font-medium">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen w-full bg-background overflow-hidden relative">
      <Sidebar />
      <main className="ml-28 lg:ml-32 mr-6 lg:mr-8 my-6 h-[calc(100vh-3rem)] min-h-0 flex w-full relative">
        {children}
      </main>
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MediaPollingProvider>
        <Router>
          <Layout>
            <Suspense fallback={<RouteFallback />}>
              <Routes>
                <Route path="/" element={<HomePage />} />
                <Route path="/search" element={<SearchPage />} />
                <Route path="/movies" element={<MoviesPage />} />
                <Route path="/series" element={<SeriesPage />} />
                <Route path="/tasks" element={<TasksPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Routes>
            </Suspense>
          </Layout>
        </Router>
        </MediaPollingProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default App;
