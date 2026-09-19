<div align="center">

# 🎬 Zimuku Subtitle Server

**An intelligent subtitle management & scraping service for your media library.**

[![CI](https://github.com/Cynosure159/zimuku-subtitle-server/actions/workflows/ci.yml/badge.svg)](https://github.com/Cynosure159/zimuku-subtitle-server/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

[中文](./README-zh.md) | English

</div>

---

## ✨ Features

| Feature | Description |
|---|---|
| 🎯 **Three-Layer Matching** | Precise TV series subtitle matching through search page → season detail → fallback mode |
| 📂 **Media Library Scanning** | Automatically detect movies & TV series files, filter by subtitle availability |
| 🤖 **MCP Protocol Integration** | Expose search & download as AI-callable tools via [Model Context Protocol](https://modelcontextprotocol.io/) |
| 🔄 **Multi-Mirror Fallback** | Automatically try all available download mirrors for maximum reliability |
| 📦 **Archive Extraction** | ZIP/7z extraction with smart encoding detection (CP437 → GBK) |
| 🎬 **Full Media Support** | Works seamlessly with both movies and TV series |

## 🏗️ Architecture

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

> For detailed architecture documentation, see [ARCH.md](./ARCH.md).

## 🛠️ Tech Stack

| Layer | Technologies |
|---|---|
| **Backend** | Python 3.12 · FastAPI · SQLModel · SQLite |
| **Frontend** | React 19 · TypeScript · Vite · Tailwind CSS v4 |
| **Infra** | Docker · Docker Compose · GitHub Actions CI |

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20+
- npm

### Backend

```bash
# Create & activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start development server
uvicorn app.main:app --reload

# Print debug logs (optional)
LOG_LEVEL=DEBUG uvicorn app.main:app --reload
```

- 🌐 API: `http://127.0.0.1:8000`
- 📖 Swagger Docs: `http://127.0.0.1:8000/docs`

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

- 🌐 Frontend: `http://localhost:5173`

## 🐳 Docker Deployment

The easiest way to get started in production:

```bash
# Pull backend and frontend images
docker pull cynosure159/zimuku-subtitle-server-backend:latest
docker pull cynosure159/zimuku-subtitle-server-frontend:latest

# Validate compose config only
docker compose config

# Start with the production env template
docker compose --env-file .env.production up -d

# Start with the test env template
docker compose --env-file .env.test up -d

# Build and start the develop backend variant with the override file
docker compose -f docker-compose.yml -f docker-compose.develop.yml --env-file .env.test up --build
```

| Service | URL | Description |
|---|---|---|
| Frontend | `http://localhost` | Nginx-served React app |
| Backend | `http://localhost:8000` | FastAPI server |

<details>
<summary>🔧 Run services individually</summary>

```bash
# Backend only
docker compose up backend

# Frontend only
docker compose up frontend
```

</details>

> **Notes:**
> - Backend storage is mounted to `./storage` on the host
> - Movie and TV libraries can be mounted read-only into `/media/movies` and `/media/tv`
> - Backend runs as a non-root user for security
> - Frontend proxies `/api/*` requests to the backend, and the upstream can be overridden with `BACKEND_UPSTREAM`
> - The default production images are `cynosure159/zimuku-subtitle-server-backend:latest` and `cynosure159/zimuku-subtitle-server-frontend:latest`
> - The develop override switches the backend to a local `develop` target build and uses `cynosure159/zimuku-subtitle-server-backend:develop` as the default tag
> - Local Docker verification can start with `docker compose config` and `docker compose -f docker-compose.yml -f docker-compose.develop.yml config`
> - Use `.env.production.example` / `.env.test.example` as Compose environment templates

### Docker Image Rules

- Production backend images use tags without a suffix, such as `latest` or `1.0.0`
- Develop backend images use the `-develop` suffix, such as `develop` or `1.0.0-develop`
- Production frontend images use tags without a suffix, such as `latest` or `1.0.0`
- The default [`docker-compose.yml`](docker-compose.yml) uses DockerHub images directly
- [`docker-compose.develop.yml`](docker-compose.develop.yml) switches the backend to the `develop` target, builds locally, and bind-mounts backend source files for development

When using Docker-mounted media libraries, configure media paths in the app as `/media/movies` and `/media/tv`, not as the original host paths.

## 🤖 MCP Integration

Zimuku Subtitle Server exposes its capabilities as AI-callable tools through the [Model Context Protocol](https://modelcontextprotocol.io/):

```bash
# Local client via stdio
python -m app.mcp.run_stdio

# Expose MCP on the same backend server/port (mounted at /mcp by default)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The default HTTP MCP endpoint is `http://127.0.0.1:8000/mcp`. You can override it with:

- `MCP_HTTP_PATH`: MCP path, default `/mcp`

When using Compose deployment, MCP is mounted directly on the backend service port, for example `http://<server-ip>:8000/mcp`.

The current MCP coverage includes:

- Subtitle search and download
- Direct subtitle download and association for scanned media (`file_id`), with automatic renaming and language tagging
- Existing subtitle inspection and content reading (with automatic language detection, bilingual verification, and dialogue sampling)
- Base64 subtitle upload for individual files and ZIP/7z archives
- Safe subtitle trash (`trash_subtitle` / `trash_media_subtitle`): moves subtitles into a dedicated trash directory with metadata (`trashinfo.json`) and database records, supports listing and one-click restore — never a permanent delete in disguise; retention is configurable (`trash_retention_days`, default 365 days, 0 = keep forever) and expired entries are purged automatically or manually (`purge_trashed_subtitles`)
- Read-only subtitle language catalog lookup
- Media library path management, hierarchical media listing (movie/show/season/episode) with NFO title and alias search, scanned file listing, library scan, and auto-match
- Download task creation, lookup, pagination, retry, deletion, and cleanup
- Settings listing and updates
- System stats and recent log retrieval

`upload_subtitle_file` associates a subtitle with a scanned media `file_id`. It accepts Base64 content up to 10 MiB in srt, ass, ssa, vtt, sub, sup, zip, or 7z format. Call `list_subtitle_languages` first to discover valid language codes. Existing subtitle files are preserved by adding a numeric suffix to new uploads.

This allows AI agents to programmatically search for, upload, and download subtitles.

## 📖 API Reference

See [API.md](./API.md) for the complete REST API documentation.

**Quick example:**

```bash
# Search for subtitles
curl "http://127.0.0.1:8000/search/?q=Inception"

# Add a media path
curl -X POST "http://127.0.0.1:8000/media/paths?path=/mnt/media/movies&path_type=movie"

# Trigger library scan
curl -X POST "http://127.0.0.1:8000/media/match?path_type=tv"

# List supported subtitle languages
curl "http://127.0.0.1:8000/system/subtitle-languages"

# Search shows by title and return one aggregated record per show
curl "http://127.0.0.1:8000/media/library?level=show&query=Foundation"
```

## 🧪 Development

```bash
# Activate virtual environment
source .venv/bin/activate

# Lint & format (required before committing)
ruff check .
ruff format .

# Run tests
pytest

# Run a specific test file
pytest tests/test_scraper.py
```

### CI Pipeline

This project uses [GitHub Actions](https://github.com/Cynosure159/zimuku-subtitle-server/actions/workflows/ci.yml) for continuous integration:

- **Backend**: install `requirements.txt` → Ruff lint & format checks → Pytest
- **Frontend**: `npm ci` → Build → ESLint
- **Docker**: `docker compose config` → backend image build → frontend image build
- **Docker**: validate default/develop compose configs → build backend `runtime`/`develop` targets → build frontend image

## 📁 Project Structure

```
zimuku-subtitle-server/
├── app/                    # Backend application
│   ├── api/                #   REST API routes
│   ├── core/               #   Business logic (scraper, archive, OCR)
│   ├── db/                 #   Database models & session
│   ├── mcp/                #   MCP protocol server
│   ├── services/           #   Service layer
│   └── main.py             #   FastAPI entry point
├── frontend/               # React frontend
├── tests/                  # Test suite
├── .github/workflows/      # CI configuration
├── docker-compose.yml      # Docker orchestration
├── docker-compose.develop.yml # Develop Docker override
├── Dockerfile              # Backend Docker image
├── requirements.txt        # Development Python dependencies
└── requirements.prod.txt   # Locked production Python dependencies
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please make sure to run `ruff check .` and `ruff format .` before submitting.

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](./LICENSE) file for details.

---
