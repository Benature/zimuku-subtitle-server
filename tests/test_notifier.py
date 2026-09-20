import base64
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.notifier import FeishuNotifier, ScheduledJobStats, generate_feishu_sign


def test_generate_feishu_sign_matches_official_algorithm():
    timestamp, sign = generate_feishu_sign("test-secret", timestamp=1700000000)

    assert timestamp == "1700000000"
    expected = base64.b64encode(
        hmac.new("1700000000\ntest-secret".encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    assert sign == expected


@pytest.mark.anyio
async def test_send_text_skips_when_webhook_missing():
    notifier = FeishuNotifier(webhook_url="", secret="")
    assert notifier.configured is False
    assert await notifier.send_text("hello") is False


def _ok_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@pytest.mark.anyio
async def test_send_text_posts_payload_with_sign():
    client_mock = AsyncMock()
    client_mock.post.return_value = _ok_response({"code": 0, "msg": "success"})

    with patch("app.core.notifier.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        notifier = FeishuNotifier(webhook_url="https://open.feishu.cn/hook/xxx", secret="sec")
        delivered = await notifier.send_text("hello")

    assert delivered is True
    payload = client_mock.post.call_args.kwargs["json"]
    assert payload["msg_type"] == "text"
    assert payload["content"]["text"] == "hello"
    assert "timestamp" in payload and "sign" in payload


@pytest.mark.anyio
async def test_send_text_returns_false_on_http_error():
    client_mock = AsyncMock()
    client_mock.post.side_effect = RuntimeError("network down")

    with patch("app.core.notifier.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        notifier = FeishuNotifier(webhook_url="https://open.feishu.cn/hook/xxx", secret="")
        delivered = await notifier.send_text("hello")

    assert delivered is False


@pytest.mark.anyio
async def test_send_text_returns_false_on_feishu_error_code():
    client_mock = AsyncMock()
    client_mock.post.return_value = _ok_response({"code": 19021, "msg": "sign match fail"})

    with patch("app.core.notifier.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        notifier = FeishuNotifier(webhook_url="https://open.feishu.cn/hook/xxx", secret="")
        delivered = await notifier.send_text("hello")

    assert delivered is False


@pytest.mark.anyio
async def test_scheduled_report_truncates_long_failure_list():
    sent: list[str] = []
    notifier = FeishuNotifier(webhook_url="https://open.feishu.cn/hook/xxx", secret="")
    notifier.send_text = AsyncMock(side_effect=lambda content: sent.append(content) or True)

    stats = ScheduledJobStats(
        scanned_files=100,
        missing_subtitle=15,
        matched=3,
        failed=12,
        failed_files=[f"file-{index}.mkv" for index in range(12)],
    )
    await notifier.send_scheduled_report(stats)

    content = sent[0]
    assert "扫描文件数：100" in content
    assert "补全成功：3" in content
    assert "file-9.mkv" in content
    assert "file-10.mkv" not in content
    assert "其余 2 个略" in content


@pytest.mark.anyio
async def test_scheduled_report_includes_titles_and_remaining_works():
    sent: list[str] = []
    notifier = FeishuNotifier(webhook_url="https://open.feishu.cn/hook/xxx", secret="")
    notifier.send_text = AsyncMock(side_effect=lambda content: sent.append(content) or True)

    stats = ScheduledJobStats(scanned_files=50, missing_subtitle=3, matched=3, titles=["Show A"], remaining_works=5)
    await notifier.send_scheduled_report(stats)

    content = sent[0]
    assert "本次补全作品：《Show A》" in content
    assert "剩余待补作品：5 部" in content


def _card_client_mock():
    """模拟飞书开放平台的 token / 上传 / webhook 三个端点。"""
    client_mock = AsyncMock()
    uploads: list[dict] = []
    webhook_payloads: list[dict] = []

    async def _post(url, **kwargs):
        if "tenant_access_token" in url:
            return _ok_response({"code": 0, "tenant_access_token": "token-123"})
        if "/im/v1/images" in url:
            uploads.append(kwargs)
            return _ok_response({"code": 0, "data": {"image_key": f"img-key-{len(uploads)}"}})
        webhook_payloads.append(kwargs["json"])
        return _ok_response({"code": 0, "msg": "success"})

    client_mock.post.side_effect = _post
    return client_mock, uploads, webhook_payloads


@pytest.mark.anyio
async def test_scheduled_report_sends_card_with_per_work_images():
    client_mock, uploads, webhook_payloads = _card_client_mock()

    with patch("app.core.notifier.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        notifier = FeishuNotifier(
            webhook_url="https://open.feishu.cn/hook/xxx",
            secret="",
            app_id="cli_x",
            app_secret="sec_x",
        )
        stats = ScheduledJobStats(scanned_files=10, missing_subtitle=2, matched=2, titles=["Show A", "Show B"])
        delivered = await notifier.send_scheduled_report(stats, images={"Show A": b"img-a", "Show B": b"img-b"})

    assert delivered is True
    assert len(uploads) == 2
    assert uploads[0]["headers"]["Authorization"] == "Bearer token-123"
    assert uploads[0]["data"] == {"image_type": "message"}
    assert uploads[0]["files"]["image"][1] == b"img-a"
    assert uploads[1]["files"]["image"][1] == b"img-b"

    payload = webhook_payloads[0]
    assert payload["msg_type"] == "interactive"
    elements = payload["card"]["elements"]
    assert "本次补全作品" in elements[0]["content"]
    img_elements = [e for e in elements if e["tag"] == "img"]
    assert [e["img_key"] for e in img_elements] == ["img-key-1", "img-key-2"]


@pytest.mark.anyio
async def test_scheduled_report_falls_back_to_text_without_app_credentials():
    sent: list[str] = []
    notifier = FeishuNotifier(webhook_url="https://open.feishu.cn/hook/xxx", secret="", app_id="", app_secret="")
    notifier.send_text = AsyncMock(side_effect=lambda content: sent.append(content) or True)

    stats = ScheduledJobStats(scanned_files=1, matched=1, titles=["Show A"])
    delivered = await notifier.send_scheduled_report(stats, images={"Show A": b"img"})

    assert delivered is True
    assert len(sent) == 1


@pytest.mark.anyio
async def test_scheduled_report_falls_back_to_text_when_upload_fails():
    client_mock = AsyncMock()
    client_mock.post.side_effect = RuntimeError("network down")
    sent: list[str] = []

    with patch("app.core.notifier.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        notifier = FeishuNotifier(
            webhook_url="https://open.feishu.cn/hook/xxx",
            secret="",
            app_id="cli_x",
            app_secret="sec_x",
        )
        notifier.send_text = AsyncMock(side_effect=lambda content: sent.append(content) or True)
        stats = ScheduledJobStats(scanned_files=1, matched=1, titles=["Show A"])
        delivered = await notifier.send_scheduled_report(stats, images={"Show A": b"img"})

    assert delivered is True
    assert len(sent) == 1


@pytest.mark.anyio
async def test_send_test_uploads_cover_and_sends_card_when_app_credentials_set():
    client_mock, uploads, webhook_payloads = _card_client_mock()

    with patch("app.core.notifier.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        notifier = FeishuNotifier(
            webhook_url="https://open.feishu.cn/hook/xxx",
            secret="",
            app_id="cli_x",
            app_secret="sec_x",
        )
        delivered = await notifier.send_test()

    assert delivered is True
    assert len(uploads) == 1
    # 上传的是生成的 480x270 PNG 测试封面
    cover = uploads[0]["files"]["image"][1]
    assert cover.startswith(b"\x89PNG\r\n\x1a\n")
    payload = webhook_payloads[0]
    assert payload["msg_type"] == "interactive"
    img_elements = [e for e in payload["card"]["elements"] if e["tag"] == "img"]
    assert len(img_elements) == 1


@pytest.mark.anyio
async def test_send_test_falls_back_to_text_when_cover_upload_fails():
    client_mock = AsyncMock()
    client_mock.post.side_effect = RuntimeError("network down")
    sent: list[str] = []

    with patch("app.core.notifier.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        notifier = FeishuNotifier(
            webhook_url="https://open.feishu.cn/hook/xxx",
            secret="",
            app_id="cli_x",
            app_secret="sec_x",
        )
        notifier.send_text = AsyncMock(side_effect=lambda content: sent.append(content) or True)
        delivered = await notifier.send_test()

    assert delivered is True
    assert "封面上传失败" in sent[0]


@pytest.mark.anyio
async def test_scheduled_report_falls_back_to_text_when_all_uploads_fail():
    client_mock = AsyncMock()

    async def _post(url, **kwargs):
        if "tenant_access_token" in url:
            return _ok_response({"code": 0, "tenant_access_token": "token-123"})
        if "/im/v1/images" in url:
            return _ok_response({"code": 500, "msg": "no permission"})
        return _ok_response({"code": 0, "msg": "success"})

    client_mock.post.side_effect = _post
    sent: list[str] = []

    with patch("app.core.notifier.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client_mock
        notifier = FeishuNotifier(
            webhook_url="https://open.feishu.cn/hook/xxx",
            secret="",
            app_id="cli_x",
            app_secret="sec_x",
        )
        notifier.send_text = AsyncMock(side_effect=lambda content: sent.append(content) or True)
        stats = ScheduledJobStats(scanned_files=1, matched=1, titles=["Show A"])
        delivered = await notifier.send_scheduled_report(stats, images={"Show A": b"img"})

    assert delivered is True
    assert len(sent) == 1
