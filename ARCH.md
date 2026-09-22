# 系统架构

## 整体架构

```
┌─────────────────┐     ┌─────────────────┐
│   Web UI        │     │   AI Agent       │
│   (React)       │     │   (MCP)          │
└────────┬────────┘     └────────┬────────┘
         │                        │
         ▼                        ▼
┌─────────────────────────────────────────┐
│           FastAPI Server                │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
│  │  API    │  │ Service │  │  Core   │  │
│  │  Layer  │──│  Layer  │──│  Logic  │  │
│  └─────────┘  └─────────┘  └─────────┘  │
└────────────────┬────────────────────────┘
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
   ┌───────┐ ┌───────┐ ┌───────┐
   │SQLite │ │ File  │ │Zimuku │
   │  DB   │ │System │ │  Web  │
   └───────┘ └───────┘ └───────┘
```

## 分层设计

### API Layer (`app/api/`)

| 文件 | 职责 |
|------|------|
| `media.py` | 媒体库管理、扫描、自动匹配、已有字幕检验与内容读取、指定文件字幕直下 |
| `search.py` | 字幕搜索（带缓存） |
| `tasks.py` | 异步任务管理与视频文件关联创建 |
| `settings.py` | 系统配置 CRUD |
| `system.py` | 系统状态、日志与字幕语言目录 |

### Service Layer (`app/services/`)

| 服务 | 职责 |
|------|------|
| `media_service.py` | 媒体路径管理与扫描/自动匹配入口编排 |
| `media_scan_pipeline.py` | 扫描阶段拆分、文件遍历、记录对账 |
| `auto_match_workflow.py` | 单文件自动匹配、整季补全、候选结果应用 |
| `task_service.py` | 下载任务创建、状态更新、后台执行入口 |
| `download_workflow.py` | 下载链路编排、解压、候选选择、最终落盘 |
| `search_service.py` | 搜索封装、SQLite 缓存 |
| `settings_service.py` | 设置读写与默认值管理 |
| `metadata_service.py` | NFO、海报与文本元数据读取 |
| `subtitle_inspection_service.py` | 媒体已有字幕检查、对白读取清洗、字符词频统计与真实语言/双语检测 |
| `subtitle_upload_service.py` | 字幕文件与压缩包 Base64 上传、安全解压、同名追加序号避让与媒体状态绑定 |
| `system_service.py` | 系统统计、日志获取、运行时配置与字幕语言目录暴露 |

### Core Layer (`app/core/`)

| 模块 | 职责 |
|------|------|
| `scraper/agent.py` | Zimuku 爬虫，三层匹配策略、请求退避、限速与重试 |
| `archive/manager.py` | ZIP/7z 解压与安全校验 |
| `ocr.py` | 验证码识别 |
| `config.py` | 配置管理 |
| `subtitle_detector.py` | 文本编码探测、时间轴与样式过滤、中英字符/词频统计与双语判定算法 |
| `subtitle_languages.py` | 系统标准化字幕语言代码定义与标签目录映射 |
| `observability.py` | 统一日志格式与任务级关联上下文 |
| `metadata.py` | NFO、海报、TXT 元数据抽取 |
| `utils.py` | 媒体解析与通用辅助函数 |

### Data Layer (`app/db/`)

- SQLModel 模型定义
- 数据库会话管理
- 迁移脚本

### Frontend Layer (`frontend/src/`)

| 目录 / 模块 | 职责 |
|------|------|
| `api/` | 按领域拆分前端接口调用，保留后端契约不变 |
| `hooks/queries/` | React Query 查询与 mutation 封装 |
| `contexts/MediaPollingContext.tsx` | 媒体轮询状态、刷新能力与乐观状态合并 |
| `hooks/useMediaBrowserController.ts` | 电影页 / 剧集页共享控制器 |
| `selectors/` | 分组、排序、筛选、sidebar 映射、搜索过滤等纯函数 |
| `stores/useUIStore.ts` | 纯 UI 状态，如侧边栏开关 |
| `pages/` | 页面编排与渲染，避免直接拼装底层远程数据逻辑 |

## 数据模型

### SubtitleTask

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| file_id | int? | 外键 ScannedFile，关联具体视频文件 |
| title | str | 字幕标题 |
| source_url | str | 下载源 URL |
| status | enum | pending/downloading/completed/failed |
| file_path | str | 下载后文件路径 |
| target_type | str? | 媒体类型 (movie / tv) |
| season | int? | 剧集季数 |
| episode | int? | 剧集集数 |
| language | str? | 语言标记 |
| error_msg | str? | 失败错误详情 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### MediaPath

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| path | str | 扫描路径 |
| path_type | enum | movie / tv |
| enabled | bool | 是否启用 |

### ScannedFile

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| media_path_id | int | 外键 MediaPath |
| file_name | str | 文件名 |
| file_path | str | 完整路径 |
| has_subtitle | bool | 是否已有字幕 |

## 核心流程

### 剧集匹配（三层策略）

```
1. 搜索页直接匹配 SxxExx 格式
         ↓
2. 季详情页搜索
         ↓
3. 兜底返回全部结果
         ↓
4. double_filter 二次按集号筛选
         ↓
5. get_sub_score 打分算法选最优
```

### 自动下载

```
提取下载链接 → 轮询镜像 → 下载校验(Magic Bytes) → 解压归档 → 重命名
```

### 任务状态轮询

- 后端：任务状态持久化在 SQLite `SubtitleTask` 表，`/system/stats` 暴露 `task_state_backend=database`
- 前端：动态轮询频率（活跃 2s / 空闲 30s），后台标签页不持续轮询

### 前端数据流

```text
api -> query hooks -> selectors / controller -> pages -> components
```

- 远程数据统一由 React Query 托管
- `queryKeys` 集中定义缓存标识
- 页面层优先消费 query hooks，不直接维护接口请求生命周期
- `useMediaPolling()` 作为兼容 facade，对外保留媒体页共享轮询入口

## 运行时约束

- 搜索、下载、自动匹配链路会注入 `correlation_id`、任务名和实体 ID，便于串联日志。
- 爬虫请求统一走超时、最小请求间隔、指数退避和 5xx/429 重试策略。
- 后台任务和测试都使用显式的数据库会话边界，避免依赖请求生命周期。

## 延后技术债

- 任务状态目前仍以数据库轮询为主，尚未引入更细粒度的事件推送。
- 搜索/下载的远端策略仍以站点特征为中心，后续若站点变化较大仍需进一步抽象。
- 目前没有独立的架构决策记录，后续若继续扩展后端模块，建议补 ADR。
