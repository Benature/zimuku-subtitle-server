# API 参考

基础 URL: `http://127.0.0.1:8000` | Swagger: `/docs`

---

## Media `/media`

| 方法 | 端点 | 说明 | 参数 |
|------|------|------|------|
| GET | `/media/paths` | 获取扫描路径列表 | - |
| POST | `/media/paths` | 添加扫描路径 | `path`, `path_type?` |
| DELETE | `/media/paths/{id}` | 删除扫描路径 | path: `id` |
| PATCH | `/media/paths/{id}` | 更新路径配置 | path: `id`, query: `enabled?`, `path_type?` |
| GET | `/media/files` | 获取扫描的文件列表 | `path_type?` |
| GET | `/media/library` | 按电影、剧、季、集聚合媒体库，支持 NFO 标题、原始标题、别名搜索 | `level?`, `media_type?`, `query?`, `title?`, `season?`, `offset?`, `limit?` |
| POST | `/media/files/{id}/auto-match` | 单文件自动匹配 | path: `id` |
| POST | `/media/works/allow-no-subtitle` | 按作品设置「允许无字幕」标记，标记作品在批量/季补全中跳过；新扫描文件自动继承同作品标记 | body: `media_type`, `title`, `allow` |
| POST | `/media/tv/match-season` | 剧集季批量补全 | `title`, `season` |
| POST | `/media/series/align-subtitles` | 剧集级批量字幕音轨对齐（后台顺序执行，自动备份 .orig，单条失败不中断；启动前检查系统负载，繁忙返回 503） | body/query: `title`, body: `force?` |
| POST | `/media/match` | 触发全局扫描 | `path_type?` |
| GET | `/media/task-status` | 获取当前任务状态 | - |
| GET | `/media/metadata/{file_id}` | 获取媒体文件 NFO 及元数据（包含海报路径、简介、别名等） | path: `file_id` |
| GET | `/media/poster` | 获取媒体本地海报图像文件 | query: `path` |
| GET | `/media/files/{id}/subtitles` | 查询媒体文件已有字幕及实际语言分析（双语/单语判定与对白采样） | path: `id` |
| GET | `/media/files/{id}/subtitles/content` | 读取媒体文件已有字幕的具体文本内容与对白 | path: `id`, `filename?`, `max_lines?`, `clean_text?` |
| POST | `/media/files/{id}/download-subtitle` | 按详情页为媒体文件下载关联字幕并自动归档 | path: `id`, body: `source_url`, `title?`, `language?` |
| POST | `/media/files/{id}/subtitles/trash` | 将媒体文件的字幕安全移入系统回收站（非永久删除，支持还原） | path: `id`, query/body: `filename?`, `subtitle_path?` |
| POST | `/media/subtitles/trash` | 通用字幕移入回收站接口（支持 file_id+filename 或绝对路径定位） | body: `file_id?`, `filename?`, `subtitle_path?` |
| GET | `/media/subtitles/trash` | 分页查询回收站字幕记录 | `file_id?`, `offset?`, `limit?`, `include_restored?` |
| POST | `/media/subtitles/trash/restore` | 从回收站还原字幕至原视频目录 | body: `trash_id?` 或 `file_id?`+`filename?` 或 `subtitle_path?`, `overwrite?` |
| POST | `/media/subtitles/trash/purge` | 按保留策略彻底删除过期回收站条目（默认保留 365 天，可在系统设置 `trash_retention_days` 中配置，0 表示永久保留） | body: `retention_days?`（可选覆盖系统配置） |

---

## Search `/search`

| 方法 | 端点 | 说明 | 参数 |
|------|------|------|------|
| GET | `/search/` | 搜索字幕(带缓存) | `q` |

---

## Tasks `/tasks`

| 方法 | 端点 | 说明 | 参数 |
|------|------|------|------|
| GET | `/tasks/` | 任务列表(分页) | `offset?`, `limit?`, `status?` |
| POST | `/tasks/` | 创建下载任务（target_path 支持传入视频文件绝对路径，亦可直接传 file_id） | `title?`, `source_url`, `file_id?`, `target_path?`, `target_type?`, `season?`, `episode?`, `language?` |
| GET | `/tasks/{id}` | 获取任务状态 | path: `id` |
| DELETE | `/tasks/{id}` | 删除任务 | path: `id`, `delete_files?` |
| POST | `/tasks/{id}/retry` | 重试失败任务 | path: `id` |
| POST | `/tasks/clear-completed` | 清理已完成任务 | - |

---

## Settings `/settings`

| 方法 | 端点 | 说明 | 参数 |
|------|------|------|------|
| GET | `/settings/` | 获取所有配置 | - |
| POST | `/settings/` | 创建/更新配置 | body: `key`, `value`, `description?` |

---

## System `/system`

| 方法 | 端点 | 说明 | 参数 |
|------|------|------|------|
| GET | `/system/stats` | 系统统计 | - |
| GET | `/system/logs` | 获取日志 | `lines?` |
| GET | `/system/subtitle-languages` | 获取只读字幕语言目录 | - |

---

## MCP 字幕上传

MCP 工具 `list_subtitle_languages` 返回上传可用的语言代码、显示名称和文件名标签。

`upload_subtitle_file` 使用以下参数将字幕关联到已扫描媒体：

| 参数 | 必填 | 说明 |
|------|------|------|
| `file_id` | 是 | `/media/files` 返回的已扫描媒体文件 ID |
| `filename` | 是 | 原始文件名，支持 srt、ass、ssa、vtt、sub、sup、zip、7z |
| `content_base64` | 是 | 文件内容的原始 Base64 编码，解码后最大 10 MiB |
| `language` | 否 | `list_subtitle_languages` 返回的语言代码 |

字幕写入视频所在目录并自动使用视频文件名；同名文件不会被覆盖，而是追加 `.2`、`.3` 等序号。ZIP/7z 最多包含 100 个文件，解压总量不得超过 50 MiB，其中所有受支持的字幕都会被保存。

## MCP 字幕管理与内容检验

除了 `upload_subtitle_file` 上传外，系统提供了字幕内容读取与实际语言检测接口，用于直接验证已有字幕的具体语言（如是否为双语）与对白内容：

- `list_media_subtitles`:
  查询媒体文件关联的所有已有字幕文件，解析其编码，自动通过内容统计分析（中文字符数、英文字词数、双语对白比例）判定其实际语言（`is_bilingual`、`detected_language`），并提取样本对白。
  - 参数：`file_id` (必填)

- `read_subtitle_content`:
  读取字幕文件的实际文本内容或纯对白列表（过滤时间轴和样式代码），并附带语言分析结果。
  - 参数：`file_id` (必填), `filename` (可选，多字幕时需指定), `max_lines` (默认 100), `clean_text` (默认 true)

- `download_subtitle_for_file`:
  指定已扫描媒体文件与 Zimuku 详情页 URL 直接下载并关联归档字幕，自动处理视频同名命名、语言后缀标记与扫描状态更新。
  - 参数：`file_id` (必填), `source_url` (必填), `title` (可选), `language` (可选)

- `create_download_task`:
  创建通用字幕下载任务。支持传入 `file_id`，或在 `target_path` 中直接传入视频文件的完整路径（如 `/path/to/S02E04.mkv`），系统会自动解析视频基准名并移动归档。

## MCP 字幕回收站（Trash）

系统提供安全的字幕回收站机制：字幕文件被**移动**至独立回收站目录（默认 `storage/trash/subtitles/`，可通过环境变量 `ZIMUKU_TRASH_PATH` 覆盖），同时保留 `trashinfo.json` 元数据与 SQLite 记录（`SubtitleTrash` 表），支持查询与一键还原。**绝不执行永久删除（rm/unlink）**，也不会以永久删除冒充 trash。若存在音轨对齐的 `.orig` 原版备份，会一并移入回收站并在还原时一同恢复。

回收站保留时长由系统设置项 `trash_retention_days` 控制（默认 **365 天**，0 表示永久保留），可在前端「设置 → 系统属性」页面直接修改，或通过 `/settings/` API / MCP `update_setting` 配置。每次移入新字幕时会自动按该策略清理过期条目，也可通过 `POST /media/subtitles/trash/purge` 或 MCP `purge_trashed_subtitles` 手动触发彻底删除。

- `trash_subtitle` / `trash_media_subtitle`（别名，二者等价）:
  将指定字幕安全移入系统回收站，返回 `trash_id`、回收站路径、剩余字幕列表与更新后的 `has_subtitle` 状态。
  - 参数：`file_id`（可选，配合 `filename` 定位媒体字幕）, `filename`（多字幕时必填）, `subtitle_path`（可选，直接传字幕绝对路径，自动反查关联媒体）
  - 二者至少需提供 `file_id` 或 `subtitle_path` 之一。

- `list_trashed_subtitles`:
  分页查询回收站中的字幕记录（默认仅返回未还原记录）。
  - 参数：`file_id`（可选过滤）, `offset`, `limit`, `include_restored`（默认 false）

- `restore_trashed_subtitle`:
  将回收站中的字幕还原至原视频目录，若有 `.orig` 备份一并还原；目标位置已存在同名文件时需显式 `overwrite=true`。
  - 参数：`trash_id`，或 `file_id` + `filename`，或 `subtitle_path`；`overwrite`（默认 false）

- `purge_trashed_subtitles`:
  按保留策略（系统配置 `trash_retention_days`，默认 365 天，0 表示永久保留）彻底删除回收站中过期的字幕文件与记录。
  - 参数：`retention_days`（可选，覆盖系统配置）

---

## 快速示例

```bash
# 搜索字幕
curl "http://127.0.0.1:8000/search/?q=盗梦空间"

# 添加媒体路径
curl -X POST "http://127.0.0.1:8000/media/paths?path=/mnt/media/movies&path_type=movie"

# 触发扫描
curl -X POST "http://127.0.0.1:8000/media/match?path_type=tv"

# 按剧集层级模糊搜索，避免返回每一集文件
curl "http://127.0.0.1:8000/media/library?level=show&query=Foundation"

# 在指定剧集内查询季，再按季查询集
curl "http://127.0.0.1:8000/media/library?level=season&title=Foundation"
curl "http://127.0.0.1:8000/media/library?level=episode&title=Foundation&season=1"

# 查询媒体文件已有关联字幕及其实际语言分析（是否为双语、抽样对白）
curl "http://127.0.0.1:8000/media/files/1/subtitles"

# 读取已有字幕的内容与纯文本对白
curl "http://127.0.0.1:8000/media/files/1/subtitles/content?clean_text=true&max_lines=50"

# 为指定媒体文件直接下载字幕并归档
curl -X POST "http://127.0.0.1:8000/media/files/1/download-subtitle" \
  -H "Content-Type: application/json" \
  -d '{"source_url":"https://zimuku.org/detail/123.html","language":"zh-CN"}'

# 查询媒体文件元数据与海报
curl "http://127.0.0.1:8000/media/metadata/1"
curl "http://127.0.0.1:8000/media/poster?path=/media/movies/Avatar/poster.jpg" --output poster.jpg

# 将字幕安全移入回收站（非永久删除）
curl -X POST "http://127.0.0.1:8000/media/files/1/subtitles/trash?filename=Movie.zh-CN.srt"

# 查询回收站记录
curl "http://127.0.0.1:8000/media/subtitles/trash?file_id=1"

# 从回收站还原字幕
curl -X POST "http://127.0.0.1:8000/media/subtitles/trash/restore" \
  -H "Content-Type: application/json" -d '{"trash_id": 1}'

# 下载字幕
curl -X POST "http://127.0.0.1:8000/tasks/?title=xxx&source_url=https://www.zimuku.cn/..."

# 查询任务
curl "http://127.0.0.1:8000/tasks/1"

# 查询字幕语言目录
curl "http://127.0.0.1:8000/system/subtitle-languages"
```
