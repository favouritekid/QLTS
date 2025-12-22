# tests/core/test_config_loading.py
# -*- coding: utf-8 -*-
import importlib
import logging
import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

# Import module config thay vì instance settings
from app import config as config_module

log = logging.getLogger(__name__)


# --- Fixture để Reload Settings và Dọn dẹp Env (Giữ nguyên) ---
@pytest.fixture(autouse=True)
def reload_settings_and_clear_env():
    """Fixture để reload module config và dọn dẹp os.environ."""
    log.debug("Saving original os.environ and reloading config module before test...")
    original_environ = os.environ.copy()
    # Reload lần đầu
    importlib.reload(config_module)
    yield
    log.debug("Restoring os.environ and reloading config module after test...")
    # Khôi phục os.environ
    os.environ.clear()
    os.environ.update(original_environ)
    # Reload lại lần cuối
    importlib.reload(config_module)


# === Helper (Giữ nguyên) ===
def get_minimal_required_env():
    return {
        "SECRET_KEY": "required_secret",
        "DATABASE_URL": "required_db_url",
        "JWT_SECRET_KEY": "required_jwt_secret",
        "MAIL_USERNAME": "required_mail_user",
        "MAIL_PASSWORD": "required_mail_pass",
        "MAIL_FROM": "required_mail_from@example.com",
        "MAIL_SERVER": "required_mail_server.com",
    }


# === Tests (Sửa test_required_variables_missing) ===


# (test_load_defaults, test_simulate_load_from_env_file, test_override_simulated_env_file_with_os_env giữ nguyên như bản sửa lần 2)
def test_load_defaults(reload_settings_and_clear_env):
    """Test config loading khi không có env file và OS env (chỉ test default)."""
    log.info("--- Running: test_load_defaults ---")
    required_env = get_minimal_required_env()
    env_vars_to_set = {"APP_ENV": "force_defaults", **required_env}
    with patch.dict(os.environ, env_vars_to_set, clear=True):
        with patch("app.config.os.path.exists", return_value=False):
            importlib.reload(config_module)
            Settings = config_module.Settings
            settings = Settings()
            assert settings.APP_ENV == "force_defaults"
            assert settings.LOG_LEVEL == "DEBUG"
            assert settings.JWT_ALGORITHM == "HS256"
            assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 15
            assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 30.0
            assert settings.REDIS_URL == "redis://localhost:6379/1"
            assert settings.CELERY_BROKER_URL == "redis://localhost:6379/2"
            assert settings.CELERY_RESULT_BACKEND_URL == "redis://localhost:6379/3"
            assert settings.MAIL_PORT == 587
            assert settings.MAIL_STARTTLS is True
            assert settings.MAIL_SSL_TLS is False
            log.info("Default values loaded correctly.")


def test_simulate_load_from_env_file(reload_settings_and_clear_env):
    """Test giả lập việc đọc từ file .env bằng cách set OS env."""
    log.info("--- Running: test_simulate_load_from_env_file ---")
    file_values = {
        "APP_ENV": "test",
        "SECRET_KEY": "test_secret_from_file",
        "DATABASE_URL": "postgresql+asyncpg://test_user:test_pass@localhost:5432/test_db_from_file",
        "JWT_SECRET_KEY": "test_jwt_secret_from_file",
        "MAIL_USERNAME": "test_mail_user_from_file",
        "MAIL_PASSWORD": "test_mail_pass_from_file",
        "MAIL_FROM": "test_mail_from@example.com",
        "MAIL_SERVER": "smtp.test_from_file.com",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
        "CELERY_BROKER_URL": "redis://file_broker/9",
        "REFRESH_TOKEN_EXPIRE_DAYS": "0.001",
        "MAIL_PORT": "2525",
    }
    with patch.dict(os.environ, file_values, clear=True):
        with patch("app.config.os.path.exists", return_value=False):
            importlib.reload(config_module)
            Settings = config_module.Settings
            settings = Settings()
            assert settings.SECRET_KEY == "test_secret_from_file"
            assert "test_db_from_file" in settings.DATABASE_URL
            assert settings.JWT_SECRET_KEY == "test_jwt_secret_from_file"
            assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 60
            assert settings.CELERY_BROKER_URL == "redis://file_broker/9"
            assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 0.001
            assert settings.MAIL_PORT == 2525
            assert settings.REDIS_URL == "redis://localhost:6379/1"
            log.info("Simulated file load via OS env successful.")


def test_override_simulated_env_file_with_os_env(reload_settings_and_clear_env):
    """Test OS env ghi đè giá trị (đã giả lập từ file)."""
    log.info("--- Running: test_override_simulated_env_file_with_os_env ---")
    file_values = {
        "APP_ENV": "test",
        "SECRET_KEY": "test_secret_from_file",
        "DATABASE_URL": "db_from_file",
        "JWT_SECRET_KEY": "jwt_from_file",
        "MAIL_USERNAME": "user_from_file",
        "MAIL_PASSWORD": "pass_from_file",
        "MAIL_FROM": "from@file.com",
        "MAIL_SERVER": "server.file.com",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
    }
    override_values = {
        "SECRET_KEY": "secret_from_os_env",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "99",
        "REDIS_URL": "redis://os_redis/12",
    }
    final_env = {**file_values, **override_values}
    with patch.dict(os.environ, final_env, clear=True):
        with patch("app.config.os.path.exists", return_value=False):
            importlib.reload(config_module)
            Settings = config_module.Settings
            settings = Settings()
            assert settings.SECRET_KEY == "secret_from_os_env"
            assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 99
            assert settings.REDIS_URL == "redis://os_redis/12"
            assert settings.DATABASE_URL == "db_from_file"
            assert settings.JWT_SECRET_KEY == "jwt_from_file"
            assert settings.MAIL_PORT == 587
            log.info(
                "OS environment variables correctly override simulated file values."
            )


# === SỬA BÀI TEST NÀY ===
def test_required_variables_missing(reload_settings_and_clear_env):
    """Test lỗi validation khi thiếu biến bắt buộc (cô lập hoàn toàn)."""
    log.info("--- Running: test_required_variables_missing ---")
    env_vars_to_set = {"APP_ENV": "test_missing"}

    with patch.dict(os.environ, env_vars_to_set, clear=True):
        with patch("app.config.os.path.exists", return_value=False):
            # === SỬA LỖI: Bắt lỗi ngay tại importlib.reload ===
            with pytest.raises(ValidationError) as exc_info:
                importlib.reload(config_module)  # Lỗi sẽ xảy ra ở đây

            # Kiểm tra lỗi validation cụ thể (Giữ nguyên phần này)
            log.debug(f"Validation Error Info: {exc_info.value}")
            error_str = str(exc_info.value)
            assert "SECRET_KEY" in error_str and "Field required" in error_str
            assert "DATABASE_URL" in error_str and "Field required" in error_str
            assert "JWT_SECRET_KEY" in error_str and "Field required" in error_str
            assert "MAIL_USERNAME" in error_str and "Field required" in error_str
            assert "MAIL_PASSWORD" in error_str and "Field required" in error_str
            assert "MAIL_FROM" in error_str and "Field required" in error_str
            assert "MAIL_SERVER" in error_str and "Field required" in error_str
            log.info(
                "ValidationError raised correctly during reload when required variables are missing."
            )


# (test_calculated_values, test_type_coercion giữ nguyên như bản sửa lần 2)
AVATAR_FOLDER_PATH_IN_CONFIG = os.path.join(
    os.path.dirname(config_module.__file__), "static", "uploads", "avatars"
)


@patch("app.config.os.path.join", return_value=AVATAR_FOLDER_PATH_IN_CONFIG)
@patch("app.config.os.makedirs")
def test_calculated_values(
    mock_makedirs, mock_path_join, reload_settings_and_clear_env
):
    """Test các giá trị được tính toán (MAX_AVATAR_CONTENT_LENGTH, AVATAR_UPLOAD_FOLDER)."""
    log.info("--- Running: test_calculated_values ---")
    env_vars = {"MAX_AVATAR_SIZE_MB": "5", **get_minimal_required_env()}
    with patch.dict(os.environ, env_vars, clear=True):
        with patch("app.config.os.path.exists", return_value=False):
            importlib.reload(config_module)
            Settings = config_module.Settings
            settings = Settings()
            expected_length = 5 * 1024 * 1024
            assert settings.MAX_AVATAR_SIZE_MB == 5
            assert settings.MAX_AVATAR_CONTENT_LENGTH == expected_length
            assert settings.AVATAR_UPLOAD_FOLDER == AVATAR_FOLDER_PATH_IN_CONFIG
            mock_makedirs.assert_called_with(
                settings.AVATAR_UPLOAD_FOLDER, exist_ok=True
            )
            log.info("Calculated values (content length, upload folder) are correct.")


def test_type_coercion(reload_settings_and_clear_env):
    """Test ép kiểu dữ liệu (vd: string sang int/bool/float)."""
    log.info("--- Running: test_type_coercion ---")
    env_vars = {
        **get_minimal_required_env(),
        "ACCESS_TOKEN_EXPIRE_MINUTES": "35",
        "REFRESH_TOKEN_EXPIRE_DAYS": "7.5",
        "MAIL_PORT": "1025",
        "MAIL_STARTTLS": "false",
        "MAIL_SSL_TLS": "True",
        "CONFIG_CACHE_TTL_SECONDS": "1800",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        with patch("app.config.os.path.exists", return_value=False):
            importlib.reload(config_module)
            Settings = config_module.Settings
            settings = Settings()
            assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 35
            assert isinstance(settings.ACCESS_TOKEN_EXPIRE_MINUTES, int)
            assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 7.5
            assert isinstance(settings.REFRESH_TOKEN_EXPIRE_DAYS, float)
            assert settings.MAIL_PORT == 1025
            assert isinstance(settings.MAIL_PORT, int)
            assert settings.MAIL_STARTTLS is False
            assert isinstance(settings.MAIL_STARTTLS, bool)
            assert settings.MAIL_SSL_TLS is True
            assert isinstance(settings.MAIL_SSL_TLS, bool)
            assert settings.CONFIG_CACHE_TTL_SECONDS == 1800
            assert isinstance(settings.CONFIG_CACHE_TTL_SECONDS, int)
            log.info("Type coercion for int, float, bool works correctly.")
