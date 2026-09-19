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

- **`app/api/`** - REST API 路由（media、search、tasks、settings、system）
- **`app/core/`** - 核心业务逻辑
  - `scraper.py` - Zimuku 网页爬虫，实现三层递进匹配策略（搜索页 → 季详情页 → 兜底模式）
  - `archive.py` - ZIP/7z 压缩包解压，解决文件名乱码（CP437 → GBK）
  - `ocr.py` - 轻量级像素采样 OCR 引擎，用于验证码识别
  - `aligner.py` - 字幕音轨对齐引擎，封装 alass/ffsubsync 调用、ffmpeg 依赖检测与 UTF-8 编码规整
  - `config.py` - 配置管理
- **`app/db/`** - SQLModel 数据库模型与会话管理
- **`app/services/`** - Service 服务层（MediaService、TaskService、SearchService、SystemService）
- **`app/mcp/`** - MCP 协议服务器实现
- **`app/main.py`** - FastAPI 应用入口

### 前端结构（`/frontend`）

- **React 19** + Vite + Tailwind CSS v4 + TypeScript
- 页面组件：SearchPage、MoviesPage、SeriesPage、TasksPage、SettingsPage
- 共享组件：MediaConfigPanel、MediaSidebar、MediaInfoCard、EmptySelectionState
- 自定义 Hook：useMediaPolling、useMediaGrouping

### 数据库

使用 SQLite + SQLModel，主要数据表：

- `Setting` - 系统配置
- `SearchCache` - 搜索结果缓存（24小时 TTL）
- `SubtitleTask` - 后台下载任务
- `MediaPath` - 媒体扫描目录
- `ScannedFile` - 已扫描的视频文件
- `SubtitleTrash` - 字幕回收站记录（安全移入回收站的文件、元数据与还原状态）

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

- `/media` - 媒体库管理（路径、文件、自动匹配、字幕音轨对齐与还原、对齐状态检查）
- `/search` - 字幕搜索（带 SQLite 缓存）
- `/tasks` - 任务管理（创建、重试、清理已完成）
- `/settings` - 系统配置
- `/system` - 系统统计与日志
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
