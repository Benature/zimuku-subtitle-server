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
| POST | `/media/tv/match-season` | 剧集季批量补全 | `title`, `season` |
| POST | `/media/match` | 触发全局扫描 | `path_type?` |
| GET | `/media/task-status` | 获取当前任务状态 | - |
| GET | `/media/files/{id}/subtitles` | 查询媒体文件已有字幕及实际语言分析（双语/单语判定与对白采样） | path: `id` |
| GET | `/media/files/{id}/subtitles/content` | 读取媒体文件已有字幕的具体文本内容与对白 | path: `id`, `filename?`, `max_lines?`, `clean_text?` |

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
| POST | `/tasks/` | 创建下载任务 | `title`, `source_url` |
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

# 下载字幕
curl -X POST "http://127.0.0.1:8000/tasks/?title=xxx&source_url=https://www.zimuku.cn/..."

# 查询任务
curl "http://127.0.0.1:8000/tasks/1"

# 查询字幕语言目录
curl "http://127.0.0.1:8000/system/subtitle-languages"
```
