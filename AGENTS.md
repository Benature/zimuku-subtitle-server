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
  - `scraper/` - Zimuku 网页爬虫，包含请求重试、退避限速与三层递进匹配策略
  - `archive/` - 压缩包管理器，支持 ZIP/7z 解压安全校验与编码乱码纠正（CP437 → GBK）
  - `ocr.py` - 轻量级像素采样 OCR 引擎，用于验证码识别
  - `subtitle_detector.py` - 字幕编码检测、纯对白清洗与基于字符/词频采样的双语与多语言判定
  - `subtitle_languages.py` - 标准化字幕语言代码定义与标签目录映射
  - `metadata.py` - NFO、海报图片与本地元数据抽取
  - `observability.py` - 统一日志格式与任务级上下文追踪
  - `config.py` - 配置管理
- **`app/db/`** - SQLModel 数据库模型与会话管理
- **`app/services/`** - Service 服务层（MediaService、TaskService、SearchService、SystemService、SettingsService、MetadataService、SubtitleInspectionService、SubtitleUploadService）
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
- `SubtitleTask` - 后台下载任务（支持 `file_id` 外键关联视频，以及指定类型/季/集）
- `MediaPath` - 媒体扫描目录
- `ScannedFile` - 已扫描的视频文件

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

- `/media` - 媒体库管理（路径配置、扫描、聚合库查询、单文件/整季匹配、已有字幕检测分析、对白内容读取、按文件直下归档）
- `/search` - 字幕搜索（带 SQLite 缓存）
- `/tasks` - 任务管理（创建、重试、清理已完成，支持 `file_id` 关联与视频绝对路径）
- `/settings` - 系统配置 CRUD
- `/system` - 系统统计、最近日志与标准化字幕语言目录
- `/health` - 健康检查

## MCP 集成

MCP 服务器支持 stdio 与 HTTP 两种挂载模式，为 AI 提供以下主要工具：
- 字幕搜索与下载（支持 `file_id` 自动归档或直接传入视频路径）
- 已有字幕检验与内容读取（真实语言检测、双语判定、纯对白文本提取）
- Base64 字幕/压缩包上传并关联视频（`upload_subtitle_file`）
- 标准化字幕语言目录（`list_subtitle_languages`）
- 媒体路径管理与扫描，单文件/整季自动匹配
- 下载任务与系统设置管理

运行方式：

```bash
# 本地 stdio 模式
python -m app.mcp.run_stdio

# HTTP 模式（FastAPI 服务同端口暴露在 /mcp）
uvicorn app.main:app --reload
```

## 开发注意事项

- Python 开发必须使用 `.venv` 虚拟环境
- 运行测试前必须先执行 `ruff check` 和 `ruff format`
- 测试必须使用隔离运行目录 `.tmp/test-runtime`，不得连接真实 `storage/zimuku.db` 或写入真实 `storage/` 目录
- 测试产生的数据库、下载文件、日志等临时数据应仅落在 `.tmp/test-runtime`，测试结束后应自动清理，不得在项目根目录留下残留文件
- 前端使用动态轮询频率（后台任务活跃时 2s，空闲时 10s）
- 剧集季补全采用顺序执行模式（间隔 2s），避免并发导致封禁
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
