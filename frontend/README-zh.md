# 前端

[English](./README.md) | 中文

该目录包含 Zimuku Subtitle Server 的 React 前端。

## 技术栈

- React 19
- TypeScript
- Vite
- Tailwind CSS v4
- TanStack React Query
- Zustand
- React Router
- Vitest

## 开发命令

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 代码检查
npm run lint

# 单元测试
npm run test

# 生产构建
npm run build
```

## 当前前端分层

```text
pages
  -> controller hooks
  -> query hooks / UI store
  -> selectors
  -> api modules
```

- `src/api/`
  - 按领域拆分 API：`media`、`tasks`、`search`、`settings`、`system`
- `src/hooks/queries/`
  - 统一封装 React Query 查询与 mutation
- `src/contexts/MediaPollingContext.tsx`
  - 提供媒体页共享轮询状态、刷新能力和乐观状态覆盖
- `src/hooks/useMediaBrowserController.ts`
  - 收口电影页和剧集页的共享控制逻辑
- `src/selectors/`
  - 承载分组、排序、筛选、sidebar 映射、搜索过滤等纯函数
- `src/stores/useUIStore.ts`
  - 仅保存纯 UI 状态

## 数据流约定

- 远程数据统一走 React Query，不再在页面中手写 `useEffect + useState` 获取接口数据
- query key 定义集中在 `src/lib/queryKeys.ts`
- 页面优先依赖 query hooks，而不是直接依赖底层 API 函数
- selector 负责派生数据，page/component 负责状态编排和渲染
- `useMediaPolling()` 是兼容 facade，底层已由 React Query 驱动

## 轮询与刷新

- 媒体任务状态轮询采用动态频率：
  - 活跃任务：2 秒
  - 空闲任务：30 秒
- 后台标签页不持续轮询
- 用户手动触发扫描时，页面会先给出乐观状态，再由 query 失效刷新接管

## 路由与加载

- 首页、搜索、电影、剧集、任务、设置页面已启用路由级懒加载
- `Suspense` fallback 保持最小空白过渡，不引入新的 UI 风格

## 测试范围

当前已补充的前端测试主要覆盖纯逻辑层：

- 媒体分组、排序、筛选
- 媒体侧栏映射与默认选中逻辑
- 搜索结果语言过滤

如需补更多测试，优先继续覆盖 selector 和 controller 的边界行为。
