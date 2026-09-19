<div align="center">

# 🎬 Zimuku Subtitle Server

**一款智能的字幕管理与刮削服务，为你的媒体库提供自动化字幕解决方案。**

[![CI](https://github.com/Cynosure159/zimuku-subtitle-server/actions/workflows/ci.yml/badge.svg)](https://github.com/Cynosure159/zimuku-subtitle-server/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

[English](./README.md) | 中文

</div>

---

## ✨ 核心特性

| 特性 | 说明 |
|---|---|
| 🎯 **三层递进匹配** | 通过搜索页 → 季详情页 → 兜底模式，精准匹配剧集字幕 |
| 📂 **自动媒体库扫描** | 自动检测电影和剧集文件，支持按字幕状态筛选 |
| 🤖 **MCP 协议集成** | 通过 [Model Context Protocol](https://modelcontextprotocol.io/) 将功能暴露为 AI 可调用工具 |
| 🔄 **多镜像自动切换** | 自动轮询所有可用下载镜像，确保下载可靠性 |
| 📦 **压缩包自动提取** | 支持 ZIP/7z 解压，智能识别编码（CP437 → GBK） |
| 🎬 **全面媒体支持** | 同时支持电影和剧集 |

## 🏗️ 系统架构

```
┌─────────────────┐     ┌─────────────────┐
│   Web UI        │     │   AI Agent       │
│   (React)       │     │   (MCP)          │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────┐
│           FastAPI Server                │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │  API    │→ │ Service │→ │  Core   │ │
│  │  Layer  │  │  Layer  │  │  Logic  │ │
│  └─────────┘  └─────────┘  └─────────┘ │
└────────────────┬────────────────────────┘
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
   ┌───────┐ ┌───────┐ ┌───────┐
   │SQLite │ │ File  │ │Zimuku │
   │  DB   │ │System │ │  Web  │
   └───────┘ └───────┘ └───────┘
```

> 详细架构文档请参阅 [ARCH.md](./ARCH.md)。

## 🛠️ 技术栈

| 层级 | 技术 |
|---|---|
| **后端** | Python 3.12 · FastAPI · SQLModel · SQLite |
| **前端** | React 19 · TypeScript · Vite · Tailwind CSS v4 |
| **基础设施** | Docker · Docker Compose · GitHub Actions CI |

## 🚀 快速开始

### 环境要求

- Python 3.12+
- Node.js 20+
- npm

### 后端

```bash
# 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
uvicorn app.main:app --reload

# 打印调试日志（可选）
LOG_LEVEL=DEBUG uvicorn app.main:app --reload
```

- 🌐 API 地址：`http://127.0.0.1:8000`
- 📖 Swagger 文档：`http://127.0.0.1:8000/docs`

### 前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

- 🌐 前端地址：`http://localhost:5173`

## 🐳 Docker 部署

生产环境推荐使用 Docker 一键部署：

```bash
# 拉取前后端镜像
docker pull cynosure159/zimuku-subtitle-server-backend:latest
docker pull cynosure159/zimuku-subtitle-server-frontend:latest

# 仅校验 compose 配置
docker compose config

# 使用生产环境变量模板启动
docker compose --env-file .env.production up -d

# 使用测试环境变量模板启动
docker compose --env-file .env.test up -d

# 使用 develop 覆盖文件构建并启动开发版后端
docker compose -f docker-compose.yml -f docker-compose.develop.yml --env-file .env.test up --build
```

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端 | `http://localhost` | Nginx 托管的 React 应用 |
| 后端 | `http://localhost:8000` | FastAPI 服务 |

<details>
<summary>🔧 单独运行服务</summary>

```bash
# 仅后端
docker compose up backend

# 仅前端
docker compose up frontend
```

</details>

> **注意事项：**
> - 后端存储挂载到宿主机的 `./storage` 目录
> - 电影和剧集媒体库会以只读方式挂载到 `/media/movies` 和 `/media/tv`
> - 后端以非 root 用户运行，确保安全性
> - 前端会将 `/api/*` 请求代理到后端，并可通过 `BACKEND_UPSTREAM` 覆盖代理目标
> - 默认生产镜像为 `cynosure159/zimuku-subtitle-server-backend:latest` 和 `cynosure159/zimuku-subtitle-server-frontend:latest`
> - develop 覆盖文件会将后端切换到本地 `develop` target 构建，并使用 `cynosure159/zimuku-subtitle-server-backend:develop` 作为默认 tag
> - 本地验证 Docker 改动时，可先执行 `docker compose config` 和 `docker compose -f docker-compose.yml -f docker-compose.develop.yml config`
> - 可基于 `.env.production.example` / `.env.test.example` 生成 Compose 环境变量文件

### Docker 镜像规则

- 正式版后端镜像使用无后缀 tag，例如 `latest` 或 `1.0.0`
- develop 版后端镜像使用 `-develop` 后缀，例如 `develop` 或 `1.0.0-develop`
- 正式版前端镜像使用无后缀 tag，例如 `latest` 或 `1.0.0`
- 默认 [`docker-compose.yml`](docker-compose.yml) 直接使用 DockerHub 镜像
- [`docker-compose.develop.yml`](docker-compose.develop.yml) 会覆盖为 `develop` target，本地构建后端镜像，并挂载后端源码目录用于开发调试

如果使用 Docker 挂载的媒体库，请在应用中配置媒体路径为 `/media/movies` 和 `/media/tv`，不要填写宿主机原始路径。

## 🤖 MCP 集成

Zimuku Subtitle Server 通过 [Model Context Protocol](https://modelcontextprotocol.io/) 将其功能暴露为 AI 可调用的工具：

```bash
# 本机客户端通过 stdio 接入
python -m app.mcp.run_stdio

# 通过后端服务同端口暴露 MCP（默认挂载到 /mcp）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

默认 HTTP MCP 地址为 `http://127.0.0.1:8000/mcp`，可通过以下环境变量调整：

- `MCP_HTTP_PATH`：MCP 路径，默认 `/mcp`

如果使用 Compose 部署，MCP 会直接挂载在后端服务的同一端口下，例如 `http://<服务器IP>:8000/mcp`。

当前 MCP 已覆盖：

- 字幕搜索与下载
- 指定媒体文件（file_id）直接下载并关联归档字幕，自动处理命名与双语标记
- 已有字幕查询与内容读取（支持自动分析字幕实际语言、双语判定、中英行数统计及对白样本查看）
- Base64 字幕文件上传，支持单个字幕及 ZIP/7z 字幕包
- 只读字幕语言目录查询
- 媒体库路径管理、文件列表查看、媒体库列表刷新
- 单文件自动匹配、剧集季批量字幕匹配
- 下载任务创建、查询、分页、重试、删除、清理
- 系统设置查看与更新
- 系统统计信息与最近日志查看

`upload_subtitle_file` 通过已扫描媒体的 `file_id` 关联字幕，接受最大 10 MiB 的 Base64 内容，支持 srt、ass、ssa、vtt、sub、sup、zip 和 7z。可先调用 `list_subtitle_languages` 查询合法语言代码；同名字幕会自动追加序号，不会覆盖已有文件。

这使得 AI 代理可以通过编程方式搜索、上传和下载字幕，实现自动化字幕管理。

## 📖 API 文档

完整的 REST API 文档请参阅 [API.md](./API.md)。

**快速示例：**

```bash
# 搜索字幕
curl "http://127.0.0.1:8000/search/?q=盗梦空间"

# 添加媒体路径
curl -X POST "http://127.0.0.1:8000/media/paths?path=/mnt/media/movies&path_type=movie"

# 触发库扫描
curl -X POST "http://127.0.0.1:8000/media/match?path_type=tv"

# 查询字幕语言目录
curl "http://127.0.0.1:8000/system/subtitle-languages"
```

## 🧪 开发指南

```bash
# 激活虚拟环境
source .venv/bin/activate

# 代码检查与格式化（提交前必须执行）
ruff check .
ruff format .

# 运行测试
pytest

# 运行单个测试文件
pytest tests/test_scraper.py
```

### CI 流水线

项目使用 [GitHub Actions](https://github.com/Cynosure159/zimuku-subtitle-server/actions/workflows/ci.yml) 进行持续集成：

- **后端**：安装 `requirements.txt` → Ruff 代码检查与格式化 → Pytest 单元测试
- **前端**：`npm ci` → 构建 → ESLint 检查
- **Docker**：`docker compose config` → 后端镜像构建 → 前端镜像构建
- **Docker**：校验默认/开发版 compose 配置 → 构建后端 `runtime`/`develop` 双 target → 构建前端镜像

## 📁 项目结构

```
zimuku-subtitle-server/
├── app/                    # 后端应用
│   ├── api/                #   REST API 路由
│   ├── core/               #   核心业务逻辑（爬虫、解压、OCR）
│   ├── db/                 #   数据库模型与会话管理
│   ├── mcp/                #   MCP 协议服务器
│   ├── services/           #   Service 服务层
│   └── main.py             #   FastAPI 应用入口
├── frontend/               # React 前端
├── tests/                  # 测试套件
├── .github/workflows/      # CI 配置
├── docker-compose.yml      # Docker 编排
├── docker-compose.develop.yml # 开发版 Docker 覆盖配置
├── Dockerfile              # 后端 Docker 镜像
├── requirements.txt        # 开发环境 Python 依赖
└── requirements.prod.txt   # 锁定的生产环境 Python 依赖
```

## 🤝 参与贡献

欢迎贡献！请随时提交 Pull Request。

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 发起 Pull Request

提交前请确保执行 `ruff check .` 和 `ruff format .`。

## 📄 许可证

本项目基于 MIT 许可证开源 — 详情请查看 [LICENSE](./LICENSE) 文件。
