# AGENTS.md

本文档为 Agent 在本项目中工作时提供指导。
!回答时始终使用简体中文

## 项目概述

Zimuku Subtitle Server 是一个独立的字幕管理与刮削服务，支持高效的 TV 剧集精确匹配、自动化媒体库扫描及 MCP（Model Context Protocol）协议集成，方便 AI 驱动实现自动化字幕管理。

## 常用命令

### 后端（Python）

```bash
# 激活虚拟环境（执行任何 Python 操作前必须先激活）
source .venv/bin/activate

# 运行开发服务器
uvicorn app.main:app --reload

# 打印调试日志（可选）
LOG_LEVEL=DEBUG uvicorn app.main:app --reload

# 运行代码检查和格式化（测试前必须执行）
ruff check .
ruff format .

# 运行测试
pytest

# 运行单个测试文件
pytest tests/test_scraper.py
```

### 前端（React）

```bash
cd frontend

# 安装依赖
npm install

# 运行开发服务器
npm run dev

# 构建生产版本
npm run build

# 代码检查
npm run lint
```

## 架构设计

### 后端结构（`/app`）

- **`app/api/`** - REST API 路由（media、search、tasks、settings、schedule、system）
- **`app/core/`** - 核心业务逻辑
  - `scraper.py` - Zimuku 网页爬虫，实现三层递进匹配策略（搜索页 → 季详情页 → 兜底模式）
  - `archive.py`（`app/core/archive/`）- ZIP/7z/RAR 压缩包解压，解决文件名乱码（CP437 → GBK）；RAR 直接调用系统 bsdtar（libarchive）解压
  - `ocr.py` - 轻量级像素采样 OCR 引擎，用于验证码识别
  - `aligner.py` - 字幕音轨对齐引擎，封装 alass/ffsubsync 调用、ffmpeg 依赖检测与 UTF-8 编码规整
  - `notifier.py` - 飞书自定义机器人通知（支持加签 secret），发送失败仅记录日志；配置自建应用凭据（`feishu_app_id` / `feishu_app_secret`）后，可先将封面图上传飞书换取 image_key，再以卡片消息内嵌每部作品的横屏封面，上传/卡片发送失败自动回退纯文本；测试通知在配置凭据后附带程序内置生成的 16:9 测试封面，用于验证 token → 上传 → 卡片完整链路
  - `mediaserver.py` - 媒体服务器客户端（Jellyfin/Emby/Plex），拉取用户未观看索引（`UnwatchedIndex`），供批量补全排序使用；Jellyfin 走 `Authorization: MediaBrowser Token="..."`（兼容 12+），Emby 走 `X-Emby-Token`，Plex 走 `X-Plex-Token`，均不使用 `?api_key=` 查询参数；失败仅记录日志并返回 None；`build_media_server_client` 对旧版 `jellyfin_*` 设置自动兼容回退；启动建表时 `_migrate_legacy_jellyfin_settings` 会将旧版 `jellyfin_*` 设置合并进 `media_server_*` 并删除旧键（新键已有非空值时不覆盖），避免旧键残留出现在系统属性通用列表；`fetch_backdrops(titles)` 按规范化标题拉取各作品横屏封面（Jellyfin/Emby 优先 Backdrop、缺失回退 Primary，Plex 用条目 `art`），供飞书通知内嵌封面使用
  - `config.py` - 配置管理
- **`app/db/`** - SQLModel 数据库模型与会话管理
- **`app/services/`** - Service 服务层（MediaService、TaskService、SearchService、SystemService、SchedulerService）
  - `scheduler_service.py` - APScheduler 定时调度（cron 触发媒体库扫描 + 全库缺失字幕批量补全 + 飞书汇总通知），随 FastAPI lifespan 启停，配置变更自动 reload
- **`app/mcp/`** - MCP 协议服务器实现
- **`app/main.py`** - FastAPI 应用入口

### 前端结构（`/frontend`）

- **React 19** + Vite + Tailwind CSS v4 + TypeScript
- 页面组件：SearchPage、MoviesPage、SeriesPage、TasksPage、SettingsPage
- 共享组件：MediaConfigPanel、MediaCard、MediaGridToolbar、MediaInfoCard
- 电影/剧集页采用「卡片墙 + 侧边详情」布局：主体为影视海报卡片网格，点击卡片在右侧（移动端为抽屉）展开详情面板
- 自定义 Hook：useMediaPolling、useMediaGrouping、useToast
- 用户提示统一使用内部顶栏 Toast（`ToastProvider` + `useToast().showToast(message, type)`，type 为 success/error/info），禁止使用浏览器 `alert()` 弹窗；确认交互统一使用内部 `ConfirmDialog` 组件（基于 `Modal`），禁止 `window.confirm()`

### 数据库

使用 SQLite + SQLModel，主要数据表：

- `Setting` - 系统配置
- `SearchCache` - 搜索结果缓存（24小时 TTL）
- `SubtitleTask` - 后台下载任务
- `MediaPath` - 媒体扫描目录
- `ScannedFile` - 已扫描的视频文件（含 `allow_no_subtitle` 作品级标记：允许无字幕的作品在批量/季补全中跳过，新扫描文件自动继承同作品标记）
- `SubtitleTrash` - 字幕回收站记录（安全移入回收站的文件、元数据与还原状态）
- `SubtitleAlignmentState` - 字幕与音轨对齐状态（unknown/aligned/misaligned），以文件签名（大小+mtime）校验有效性，字幕文件一旦被修改，读取时状态自动回落为 unknown

## 核心工作流

### 剧集精确匹配（三层策略）

1. 直接在搜索页匹配 `SxxExx` 格式
2. 退回到季详情页搜索
3. 最后兜底返回全部结果
4. 通过 `double_filter` 二次按集号筛选
5. 评分算法选择最优字幕

### 自动下载流程

1. 从详情页提取真实下载跳转 URL
2. 轮询所有可用镜像链接
3. 下载后进行 `FILE_MIN_SIZE` 校验
4. 移动至目标目录并重命名为视频同名

## API 接口

基础 URL：`http://127.0.0.1:8000`
Swagger 文档：`http://127.0.0.1:8000/docs`

- `/media` - 媒体库管理（路径、文件、自动匹配、字幕音轨对齐与还原、对齐状态检查、`/subtitle-summary` 按文件汇总对齐状态与字幕语言供卡片墙展示）
- `/search` - 字幕搜索（带 SQLite 缓存）
- `/tasks` - 任务管理（创建、重试、清理已完成）
- `/settings` - 系统配置（含 `POST /settings/media-server/test` 媒体服务器连接测试）
- `/system` - 系统统计与日志
- `/schedule` - 定时任务（状态查询、立即执行一次、飞书测试通知）
- `/health` - 健康检查

## MCP 集成

MCP 服务器将搜索、下载、字幕检查、音轨对齐（`align_subtitle` 手动触发、`check_subtitle_alignment` 对齐状态判定）等功能暴露为 AI 可调用的工具。运行方式：

```bash
python -m app.mcp.run_stdio
```

## 开发注意事项

- Python 开发必须使用 `.venv` 虚拟环境
- 运行测试前必须先执行 `ruff check` 和 `ruff format`
- 测试必须使用隔离运行目录 `.tmp/test-runtime-<pid>`（按进程隔离，避免并发 pytest 互相干扰），不得连接真实 `storage/zimuku.db` 或写入真实 `storage/` 目录
- 测试产生的数据库、下载文件、日志等临时数据应仅落在 `.tmp/test-runtime-<pid>`，测试结束后应自动清理，不得在项目根目录留下残留文件
- 前端使用动态轮询频率（后台任务活跃时 2s，空闲时 10s）
- 剧集季补全采用顺序执行模式（间隔 2s），避免并发导致封禁
- 字幕下载完成后默认自动执行音轨对齐（设置项 `auto_align_after_download`，前端系统设置页可关闭；对齐前自动备份 `.orig` 原字幕，可随时还原；对齐失败仅记录日志，不影响任务状态）
- 对齐状态是字幕级属性：对齐/检查成功写入 `SubtitleAlignmentState`，还原原字幕时重置为 unknown；批量全库检查可用 `python -m app.scripts.check_library_alignment`（支持分片并行与 `--import-report` 历史报告回写）
- 剧集级批量对齐：剧集详情面板的「全剧音轨对齐」按钮调用 `POST /media/series/align-subtitles`（body/query: `title`，body 支持 `force`），后台对整部剧所有集的全部关联字幕顺序执行对齐（单条失败不中断，自动备份 .orig）；因系统负载守卫返回 503 时，前端先 Toast 展示后端繁忙原因，随后通过内部确认弹窗（`ConfirmDialog`）允许以 `force=true` 强制执行；任务状态通过 `/media/task-status` 的 `aligning_series`（剧集标题列表）与 `aligning_files`（文件 ID 列表）暴露，前端轮询展示「对齐中」状态（卡片墙左上角 tag 旋转）
- 对齐资源守卫：alass/ffsubsync 以 `nice -n 10` 低优先级运行；所有对齐类操作（单文件对齐、对齐检查、任务对齐、剧集批量对齐）执行前通过 `app/core/system_load.py` 检查系统负载（load1/核数 ≥ 1.0 或可用内存 < 10% 判定繁忙），繁忙时 API 返回 503、MCP 返回错误提示；下载后自动对齐在系统繁忙时直接跳过；MCP 工具 `align_subtitle` / `check_subtitle_alignment` 及各 API body 均支持 `force` 参数（默认 false）跳过守卫；批量入口守卫一次，批量中途不再重复检查
- 自动匹配搜索词按优先级回退：NFO 元数据（nfo_title → nfo_original_title → nfo_aliases）优先，最后回退到目录名提取的 extracted_title（`build_search_queries`），第一个有搜索结果的词即被采用
- 定时扫描补字幕：设置项 `schedule_enabled` / `schedule_cron`（默认每天 03:00），触发后先刷新媒体库，再对缺字幕的作品顺序补全（间隔 2s）；`schedule_max_works_per_run`（默认 1，0 表示不限）限制每次运行补全的作品数量，作品单位为「剧集的一季 / 一部电影」（同一标题的不同季算不同作品，作品标签如 "剧名 S02"，封面图按去除季后缀的基础标题拉取），作品优先级为：媒体服务器未观看作品（启用联动且拉取成功时）→ 能检索到 NFO 元数据（nfo_title / nfo_original_title）的作品 → 按缺字幕文件数降序、标题升序兜底；完成后可按 `feishu_notify_enabled` / `feishu_webhook_url` / `feishu_webhook_secret`（加签可选）推送飞书汇总通知（含本次补全作品与剩余待补数）；再配置 `feishu_app_id` / `feishu_app_secret`（自建应用凭据，可选）后，通知升级为卡片消息，每部补全作品内嵌一张媒体服务器横屏封面图；前端系统设置页有专属配置卡片，支持立即执行与发送测试通知
- 媒体服务器联动：设置项 `media_server_enabled` / `media_server_type`（jellyfin/emby/plex）/ `media_server_base_url` / `media_server_api_key` / `media_server_user_id`（Jellyfin/Emby 的 32 位 GUID，留空自动使用首个用户，Plex 无需填写）；启用后批量补全（`LibraryMatchWorkflow`）优先处理未观看的作品（按规范化标题匹配，剧集用 SeriesName/grandparentTitle、电影用 Name/title）；`POST /settings/media-server/test` 可测试连接与凭据有效性；拉取失败自动回退原优先级，不影响主流程
- 「允许无字幕」作品标记：电影/剧集详情面板的开关调用 `POST /media/works/allow-no-subtitle`（body: `media_type`, `title`, `allow`），按作品下全部文件置位 `ScannedFile.allow_no_subtitle`；批量补全（`LibraryMatchWorkflow`）与季补全（`SeasonMatchWorkflow`）跳过已标记文件，媒体扫描时新发现文件自动继承同作品（类型 + 规范化标题）标记；前端卡片墙显示「无需字幕」徽标且不计入缺字幕筛选/统计，已标记文件的对齐状态与字幕语言标签也不在卡片墙聚合展示（`getGroupSubtitleSummary` 过滤），手动单文件匹配不受影响
- 扫描清理守卫：媒体根目录不可访问（挂载缺失、磁盘未挂载等）时，`MediaScanPipeline` 跳过该路径的扫描与全部记录清理（`cleanup_missing_files` 与发现清理均不生效），仅记录 warning，防止挂载异常导致记录被批量误删
- 修改代码后，按照需要修订文档；有功能修改需要看是否修改、添加对应的单元测试

## Docker 与 Compose 约定

- 后端 `Dockerfile` 使用双 target 结构：
  - `runtime` 用于正式镜像
  - `develop` 用于开发镜像
- 正式镜像 tag 不带后缀，例如 `latest`、`1.0.0`
- 开发镜像 tag 带 `-develop` 后缀，例如 `develop`、`1.0.0-develop`
- 默认 [`docker-compose.yml`](docker-compose.yml) 面向正式环境，后端构建应使用 `runtime` target
- 开发模式应叠加 [`docker-compose.develop.yml`](docker-compose.develop.yml)，只覆盖与正式配置不同的部分，例如 develop target、源码挂载和调试日志
- 生产和测试环境变量分别参考 `.env.production.example` 与 `.env.test.example`
- 媒体库目录应通过 Compose `volumes` 挂载到容器内；在应用中配置媒体路径时，应填写容器内路径而不是宿主机原始路径
- 音轨对齐依赖：镜像内置 `ffmpeg`（apk）与 `alass` 静态二进制（`docker/binaries/alass`，v2.0.0，x86_64）；升级 alass 时直接替换该二进制文件。其他架构可通过环境变量 `ZIMUKU_ALASS_PATH` / `ZIMUKU_FFMPEG_PATH` 指定外部工具路径
- RAR 解压依赖：镜像内置 `libarchive-tools`（apk，提供 bsdtar），`ArchiveManager._extract_rar` 直接以子进程调用（rarfile 库对 7zz/bsdtar 后端的输出解析不可靠，且 Alpine 的 7zip 未编译 RAR 支持）；本地开发环境如需真实解压 RAR 需自行安装 bsdtar
- 修改 Dockerfile、Compose 文件或环境模板后，至少执行以下校验：
  - `docker compose config`
  - 相关镜像的 `docker compose build` 或 `docker build --target ...`

### Git 操作规范

- **除非用户明确要求**，禁止执行任何 Git 提交 (`git commit`) 或推送 (`git push`) 操作
- 在执行 Git 操作前，请确保相关文档已更新

### 安全规范

- 严禁泄露、打印或提交任何敏感信息（如 API 密钥、私钥、凭据等）
- 始终遵循安全编码最佳实践
- 遵循 RESTful API 设计规范
