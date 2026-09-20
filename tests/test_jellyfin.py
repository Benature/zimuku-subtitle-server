from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import ConfigManager, SettingKey
from app.core.jellyfin import JellyfinClient, UnwatchedIndex, normalize_jellyfin_title


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


def test_normalize_jellyfin_title_strips_year_and_case():
    assert normalize_jellyfin_title("Fresh Show (2024)") == "fresh show"
    assert normalize_jellyfin_title("  Some Movie  ") == "some movie"
    assert normalize_jellyfin_title("") == ""


def test_unwatched_index_matches_normalized_titles():
    index = UnwatchedIndex(titles={"fresh show", "some movie"}, item_count=3)
    assert index.matches("Fresh Show (2024)")
    assert index.matches("Some Movie")
    assert not index.matches("Other Show")


def test_config_normalizes_jellyfin_values():
    assert (
        ConfigManager.normalize_value(SettingKey.JELLYFIN_BASE_URL, "http://jf.local:8096/") == "http://jf.local:8096"
    )
    assert ConfigManager.normalize_value(SettingKey.JELLYFIN_USER_ID, "ABCDEF12-3456-7890-ABCD-EF1234567890") == (
        "abcdef1234567890abcdef1234567890"
    )
    assert ConfigManager.normalize_value(SettingKey.JELLYFIN_USER_ID, "") == ""


def test_config_rejects_invalid_jellyfin_values():
    with pytest.raises(ValueError, match="http"):
        ConfigManager.normalize_value(SettingKey.JELLYFIN_BASE_URL, "jf.local:8096")
    with pytest.raises(ValueError, match="GUID"):
        ConfigManager.normalize_value(SettingKey.JELLYFIN_USER_ID, "ben")


@pytest.mark.anyio
async def test_fetch_unwatched_returns_none_when_disabled_or_unconfigured():
    assert await JellyfinClient(base_url="http://jf.local", api_key="key", enabled=False).fetch_unwatched() is None
    assert await JellyfinClient(base_url="", api_key="key", enabled=True).fetch_unwatched() is None
    assert await JellyfinClient(base_url="http://jf.local", api_key="", enabled=True).fetch_unwatched() is None


@pytest.mark.anyio
async def test_fetch_unwatched_builds_index_with_auth_header():
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

    with patch("app.core.jellyfin.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = JellyfinClient(base_url="http://jf.local", api_key="secret-key", user_id="uid123", enabled=True)
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
async def test_fetch_unwatched_falls_back_to_first_user():
    client_mock = _build_client_mock(
        {
            "/Users": [_ok_response([{"Id": "auto-uid", "Name": "ben"}])],
            "/Users/auto-uid/Items": [_ok_response({"Items": [{"Type": "Movie", "Name": "Some Movie"}]})],
        }
    )

    with patch("app.core.jellyfin.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = JellyfinClient(base_url="http://jf.local", api_key="key", user_id="", enabled=True)
        index = await client.fetch_unwatched()

    assert index is not None
    assert index.titles == {"some movie"}


@pytest.mark.anyio
async def test_fetch_unwatched_returns_none_when_no_user_available():
    client_mock = _build_client_mock({"/Users": [_ok_response([])]})

    with patch("app.core.jellyfin.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = JellyfinClient(base_url="http://jf.local", api_key="key", user_id="", enabled=True)
        assert await client.fetch_unwatched() is None


@pytest.mark.anyio
async def test_fetch_unwatched_returns_none_on_http_error():
    client_mock = AsyncMock()
    client_mock.get.side_effect = RuntimeError("connection refused")

    with patch("app.core.jellyfin.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = JellyfinClient(base_url="http://jf.local", api_key="key", user_id="uid", enabled=True)
        assert await client.fetch_unwatched() is None


@pytest.mark.anyio
async def test_test_connection_reports_server_info():
    client_mock = _build_client_mock(
        {
            "/System/Info": [_ok_response({"ServerName": "nas-jf", "Version": "10.9.11"})],
        }
    )

    with patch("app.core.jellyfin.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = JellyfinClient(base_url="http://jf.local", api_key="key", user_id="uid", enabled=True)
        connected, message = await client.test_connection()

    assert connected is True
    assert "nas-jf" in message and "10.9.11" in message


@pytest.mark.anyio
async def test_test_connection_fails_when_unconfigured_or_unreachable():
    connected, message = await JellyfinClient(base_url="", api_key="", enabled=True).test_connection()
    assert connected is False
    assert "未配置" in message

    client_mock = AsyncMock()
    client_mock.get.side_effect = RuntimeError("timeout")
    with patch("app.core.jellyfin.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        client = JellyfinClient(base_url="http://jf.local", api_key="key", user_id="uid", enabled=True)
        connected, message = await client.test_connection()

    assert connected is False
    assert "连接失败" in message
