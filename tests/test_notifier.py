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
