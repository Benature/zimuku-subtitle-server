# Frontend

[中文](./README-zh.md) | English

This directory contains the React frontend for Zimuku Subtitle Server.

## Tech Stack

- React 19
- TypeScript
- Vite
- Tailwind CSS v4
- TanStack React Query
- Zustand
- React Router
- Vitest

## Development Commands

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev

# Lint
npm run lint

# Unit tests
npm run test

# Production build
npm run build
```

## Current Frontend Layers

```text
pages
  -> controller hooks
  -> query hooks / UI store
  -> selectors
  -> api modules
```

- `src/api/`
  - Domain-based API modules: `media`, `tasks`, `search`, `settings`, `system`
- `src/hooks/queries/`
  - Shared React Query queries and mutations
- `src/contexts/MediaPollingContext.tsx`
  - Shared media polling state, refresh methods, and optimistic status overlay
- `src/hooks/useMediaBrowserController.ts`
  - Shared controller for Movies and Series pages
- `src/selectors/`
  - Pure functions for grouping, sorting, filtering, sidebar mapping, and search filtering
- `src/stores/useUIStore.ts`
  - UI-only state

## Data Flow Conventions

- Remote data should go through React Query instead of page-local `useEffect + useState` fetching
- Query keys are centralized in `src/lib/queryKeys.ts`
- Pages should consume query hooks instead of calling low-level API functions directly
- Selectors handle derived data; pages and components focus on orchestration and rendering
- `useMediaPolling()` remains as a compatibility facade, but is now backed by React Query

## Polling And Refresh

- Media task polling uses a dynamic interval:
  - Active tasks: 2 seconds
  - Idle tasks: 30 seconds
- Background tabs do not keep polling continuously
- Manual refresh actions use optimistic UI first, then hand over to query invalidation and refetch

## Routing And Loading

- Home, Search, Movies, Series, Tasks, and Settings pages are route-level lazy loaded
- The `Suspense` fallback stays visually minimal to avoid introducing a new loading style

## Test Coverage

Current frontend tests focus on pure logic:

- Media grouping, sorting, and filtering
- Media sidebar mapping and default selection logic
- Search result language filtering

If more tests are added later, selector and controller edge cases should remain the first priority.
