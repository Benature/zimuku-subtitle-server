from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import ConfigManager, SettingKey
from app.core.mediaserver import (
    EmbyClient,
    JellyfinClient,
    PlexClient,
    UnwatchedIndex,
    build_media_server_client,
    fetch_unwatched_index,
    normalize_media_server_title,
)


def _ok_response(payload) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _build_client_mock(routes: dict[str, list]) -> AsyncMock:
    """按路径依次返回预置响应的 AsyncClient mock。"""
    client_mock = AsyncMock()

    async def _get(path, params=None):
        queue = routes[path]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    client_mock.get.side_effect = _get
    return client_mock


def test_normalize_media_server_title_strips_year_and_case():
    assert normalize_media_server_title("Fresh Show (2024)") == "fresh show"
    assert normalize_media_server_title("  Some Movie  ") == "some movie"
    assert normalize_media_server_title("") == ""


def test_unwatched_index_matches_normalized_titles():
    index = UnwatchedIndex(titles={"fresh show", "some movie"}, item_count=3)
    assert index.matches("Fresh Show (2024)")
    assert index.matches("Some Movie")
    assert not index.matches("Other Show")


def test_config_normalizes_media_server_values():
    assert (
        ConfigManager.normalize_value(SettingKey.MEDIA_SERVER_BASE_URL, "http://ms.local:8096/")
        == "http://ms.local:8096"
    )
    assert ConfigManager.normalize_value(SettingKey.MEDIA_SERVER_TYPE, "EMBY") == "emby"
    assert ConfigManager.normalize_value(SettingKey.MEDIA_SERVER_USER_ID, "ABCDEF12-3456-7890-ABCD-EF1234567890") == (
        "abcdef1234567890abcdef1234567890"
    )
    assert ConfigManager.normalize_value(SettingKey.MEDIA_SERVER_USER_ID, "") == ""


def test_config_rejects_invalid_media_server_values():
    with pytest.raises(ValueError, match="http"):
        ConfigManager.normalize_value(SettingKey.MEDIA_SERVER_BASE_URL, "ms.local:8096")
    with pytest.raises(ValueError, match="jellyfin"):
        ConfigManager.normalize_value(SettingKey.MEDIA_SERVER_TYPE, "fnos")
    with pytest.raises(ValueError, match="GUID"):
        ConfigManager.normalize_value(SettingKey.MEDIA_SERVER_USER_ID, "ben")


@pytest.mark.anyio
async def test_fetch_unwatched_returns_none_when_disabled_or_unconfigured():
    assert await JellyfinClient(base_url="http://ms.local", api_key="key", enabled=False).fetch_unwatched() is None
    assert await JellyfinClient(base_url="", api_key="key", enabled=True).fetch_unwatched() is None
    assert await JellyfinClient(base_url="http://ms.local", api_key="", enabled=True).fetch_unwatched() is None


@pytest.mark.anyio
async def test_jellyfin_fetch_unwatched_builds_index_with_auth_header():
    client_mock = _build_client_mock(
        {
            "/Users/uid123/Items": [
                _ok_response(
                    {
                        "Items": [
                            {"Type": "Episode", "SeriesName": "Fresh Show"},
                            {"Type": "Episode", "SeriesName": "Fresh Show"},
                            {"Type": "Movie", "Name": "Some Movie (2024)"},
                        ]
                    }
                )
            ]
        }
    )

    with patch("app.core.mediaserver.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = JellyfinClient(base_url="http://ms.local", api_key="secret-key", user_id="uid123", enabled=True)
        index = await client.fetch_unwatched()

    assert index is not None
    assert index.titles == {"fresh show", "some movie"}
    assert index.item_count == 3
    # 认证必须通过 Authorization 请求头（Jellyfin 12+），不能带 api_key 查询参数
    headers = client_cls.call_args.kwargs["headers"]
    assert headers["Authorization"] == 'MediaBrowser Token="secret-key"'
    params = client_mock.get.call_args.kwargs["params"]
    assert params["Filters"] == "IsUnplayed"
    assert "api_key" not in params


@pytest.mark.anyio
async def test_emby_fetch_unwatched_uses_x_emby_token_header():
    client_mock = _build_client_mock(
        {
            "/Users/uid123/Items": [_ok_response({"Items": [{"Type": "Movie", "Name": "Some Movie"}]})],
        }
    )

    with patch("app.core.mediaserver.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = EmbyClient(base_url="http://ms.local:8096", api_key="emby-key", user_id="uid123", enabled=True)
        index = await client.fetch_unwatched()

    assert index is not None
    assert index.titles == {"some movie"}
    headers = client_cls.call_args.kwargs["headers"]
    assert headers["X-Emby-Token"] == "emby-key"
    assert "Authorization" not in headers


@pytest.mark.anyio
async def test_emby_like_falls_back_to_first_user():
    client_mock = _build_client_mock(
        {
            "/Users": [_ok_response([{"Id": "auto-uid", "Name": "ben"}])],
            "/Users/auto-uid/Items": [_ok_response({"Items": [{"Type": "Movie", "Name": "Some Movie"}]})],
        }
    )

    with patch("app.core.mediaserver.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = EmbyClient(base_url="http://ms.local", api_key="key", user_id="", enabled=True)
        index = await client.fetch_unwatched()

    assert index is not None
    assert index.titles == {"some movie"}


@pytest.mark.anyio
async def test_emby_like_returns_none_when_no_user_available():
    client_mock = _build_client_mock({"/Users": [_ok_response([])]})

    with patch("app.core.mediaserver.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = JellyfinClient(base_url="http://ms.local", api_key="key", user_id="", enabled=True)
        assert await client.fetch_unwatched() is None


@pytest.mark.anyio
async def test_fetch_unwatched_returns_none_on_http_error():
    client_mock = AsyncMock()
    client_mock.get.side_effect = RuntimeError("connection refused")

    with patch("app.core.mediaserver.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = JellyfinClient(base_url="http://ms.local", api_key="key", user_id="uid", enabled=True)
        assert await client.fetch_unwatched() is None


@pytest.mark.anyio
async def test_plex_fetch_unwatched_builds_index_per_section():
    client_mock = _build_client_mock(
        {
            "/library/sections": [
                _ok_response(
                    {
                        "MediaContainer": {
                            "Directory": [
                                {"key": "1", "type": "show", "title": "剧集"},
                                {"key": "2", "type": "movie", "title": "电影"},
                                {"key": "3", "type": "artist", "title": "音乐"},
                            ]
                        }
                    }
                )
            ],
            "/library/sections/1/all": [
                _ok_response(
                    {
                        "MediaContainer": {
                            "Metadata": [
                                {"type": "episode", "grandparentTitle": "Fresh Show"},
                                {"type": "episode", "grandparentTitle": "Fresh Show"},
                            ]
                        }
                    }
                )
            ],
            "/library/sections/2/all": [
                _ok_response({"MediaContainer": {"Metadata": [{"type": "movie", "title": "Some Movie (2024)"}]}})
            ],
        }
    )

    with patch("app.core.mediaserver.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = PlexClient(base_url="http://ms.local:32400", api_key="plex-token", enabled=True)
        index = await client.fetch_unwatched()

    assert index is not None
    assert index.titles == {"fresh show", "some movie"}
    assert index.item_count == 3
    headers = client_cls.call_args.kwargs["headers"]
    assert headers["X-Plex-Token"] == "plex-token"
    # 剧集按单集（type=4）、电影按 type=1 过滤未观看
    show_call = [call for call in client_mock.get.call_args_list if call.args[0] == "/library/sections/1/all"][0]
    assert show_call.kwargs["params"] == {"type": 4, "unwatched": 1}


@pytest.mark.anyio
async def test_test_connection_reports_server_info():
    jellyfin_mock = _build_client_mock(
        {
            "/System/Info": [_ok_response({"ServerName": "nas-jf", "Version": "10.9.11"})],
        }
    )
    with patch("app.core.mediaserver.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = jellyfin_mock
        client = JellyfinClient(base_url="http://ms.local", api_key="key", user_id="uid", enabled=True)
        connected, message = await client.test_connection()
    assert connected is True
    assert "nas-jf" in message and "10.9.11" in message

    plex_mock = _build_client_mock(
        {
            "/identity": [_ok_response({"MediaContainer": {"version": "1.41.0", "machineIdentifier": "abc"}})],
        }
    )
    with patch("app.core.mediaserver.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = plex_mock
        client = PlexClient(base_url="http://ms.local:32400", api_key="token", enabled=True)
        connected, message = await client.test_connection()
    assert connected is True
    assert "1.41.0" in message


@pytest.mark.anyio
async def test_test_connection_fails_when_unconfigured_or_unreachable():
    connected, message = await JellyfinClient(base_url="", api_key="", enabled=True).test_connection()
    assert connected is False
    assert "未配置" in message

    client_mock = AsyncMock()
    client_mock.get.side_effect = RuntimeError("timeout")
    with patch("app.core.mediaserver.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = PlexClient(base_url="http://ms.local:32400", api_key="token", enabled=True)
        connected, message = await client.test_connection()

    assert connected is False
    assert "连接失败" in message


def test_build_media_server_client_dispatches_by_type():
    assert isinstance(build_media_server_client("jellyfin", base_url="http://h", api_key="k"), JellyfinClient)
    assert isinstance(build_media_server_client("Emby", base_url="http://h", api_key="k"), EmbyClient)
    assert isinstance(build_media_server_client("plex", base_url="http://h", api_key="k"), PlexClient)
    assert build_media_server_client("fnos", base_url="http://h", api_key="k") is None


def _settings_mock(values: dict[str, str], bools: dict[str, bool] | None = None):
    config_mock = MagicMock()
    config_mock.get.side_effect = lambda key, default=None: values.get(key, default if default is not None else "")
    bools = bools or {}
    config_mock.get_bool.side_effect = lambda key, default=False: bools.get(key, default)
    return config_mock


def test_build_media_server_client_reads_new_settings():
    config_mock = _settings_mock(
        {
            SettingKey.MEDIA_SERVER_TYPE: "plex",
            SettingKey.MEDIA_SERVER_BASE_URL: "http://plex.local:32400",
            SettingKey.MEDIA_SERVER_API_KEY: "token",
        },
        {SettingKey.MEDIA_SERVER_ENABLED: True},
    )
    with patch("app.core.mediaserver.ConfigManager", config_mock):
        client = build_media_server_client()
    assert isinstance(client, PlexClient)
    assert client.enabled is True


def test_build_media_server_client_falls_back_to_legacy_jellyfin_settings():
    config_mock = _settings_mock(
        {
            "jellyfin_base_url": "http://jf.local:8096",
            "jellyfin_api_key": "legacy-key",
        },
        {"jellyfin_enabled": True},
    )
    with patch("app.core.mediaserver.ConfigManager", config_mock):
        client = build_media_server_client()
    assert isinstance(client, JellyfinClient)
    assert client.enabled is True
    assert client.configured is True


@pytest.mark.anyio
async def test_fetch_unwatched_index_returns_none_when_not_configured():
    config_mock = _settings_mock({})
    with patch("app.core.mediaserver.ConfigManager", config_mock):
        assert await fetch_unwatched_index() is None
