import pytest
from fastapi.testclient import TestClient

from app.core.config import ConfigManager, SettingKey
from app.db.session import create_db_and_tables
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    create_db_and_tables()


def test_default_schedule_and_feishu_settings_seeded():
    defaults = {setting.key: setting.value for setting in ConfigManager.default_settings()}

    assert defaults[SettingKey.SCHEDULE_ENABLED] == "false"
    assert defaults[SettingKey.SCHEDULE_CRON] == "0 3 * * *"
    assert defaults[SettingKey.SCHEDULE_MAX_WORKS_PER_RUN] == "1"
    assert defaults[SettingKey.FEISHU_NOTIFY_ENABLED] == "false"
    assert defaults[SettingKey.FEISHU_WEBHOOK_URL] == ""
    assert defaults[SettingKey.FEISHU_WEBHOOK_SECRET] == ""


def test_normalize_schedule_cron_accepts_valid_expression():
    assert ConfigManager.normalize_value(SettingKey.SCHEDULE_CRON, "*/30 * * * *") == "*/30 * * * *"


def test_normalize_schedule_cron_rejects_invalid_expression():
    with pytest.raises(ValueError, match="schedule_cron"):
        ConfigManager.normalize_value(SettingKey.SCHEDULE_CRON, "not-a-cron")


def test_normalize_schedule_enabled_requires_bool():
    assert ConfigManager.normalize_value(SettingKey.SCHEDULE_ENABLED, "ON") == "true"

    with pytest.raises(ValueError, match=SettingKey.SCHEDULE_ENABLED):
        ConfigManager.normalize_value(SettingKey.SCHEDULE_ENABLED, "maybe")


def test_normalize_schedule_max_works_per_run():
    assert ConfigManager.normalize_value(SettingKey.SCHEDULE_MAX_WORKS_PER_RUN, "3") == "3"
    assert ConfigManager.normalize_value(SettingKey.SCHEDULE_MAX_WORKS_PER_RUN, "0") == "0"

    with pytest.raises(ValueError, match=SettingKey.SCHEDULE_MAX_WORKS_PER_RUN):
        ConfigManager.normalize_value(SettingKey.SCHEDULE_MAX_WORKS_PER_RUN, "-1")

    with pytest.raises(ValueError, match=SettingKey.SCHEDULE_MAX_WORKS_PER_RUN):
        ConfigManager.normalize_value(SettingKey.SCHEDULE_MAX_WORKS_PER_RUN, "abc")


def test_normalize_feishu_webhook_requires_http_url():
    assert ConfigManager.normalize_value(SettingKey.FEISHU_WEBHOOK_URL, "") == ""
    assert (
        ConfigManager.normalize_value(SettingKey.FEISHU_WEBHOOK_URL, "https://open.feishu.cn/hook/x")
        == "https://open.feishu.cn/hook/x"
    )

    with pytest.raises(ValueError, match=SettingKey.FEISHU_WEBHOOK_URL):
        ConfigManager.normalize_value(SettingKey.FEISHU_WEBHOOK_URL, "ftp://bad")


def test_schedule_status_api():
    response = client.get("/schedule/status")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["cron"] == "0 3 * * *"
    assert data["running"] is False
    assert data["next_run_time"] is None


def test_schedule_run_now_api():
    response = client.post("/schedule/run-now")
    assert response.status_code == 200
    data = response.json()
    assert data["task_kind"] == "scheduled_scan"


def test_feishu_test_api_without_webhook():
    response = client.post("/schedule/feishu/test")
    assert response.status_code == 200
    data = response.json()
    assert data["delivered"] is False
    assert "未配置" in data["message"]


def test_update_schedule_cron_rejects_invalid_value():
    response = client.post("/settings/", json={"key": SettingKey.SCHEDULE_CRON, "value": "bad-cron"})
    assert response.status_code == 400
