# tests/services/conftest.py
"""
Minimal conftest for services tests.

This conftest mocks external dependencies to allow running unit tests
without the full application environment.
"""
import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add the Backend_FastAPI directory to the path so we can import app modules
backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# ============================================================================
# Mock external dependencies that aren't installed in test environment
# ============================================================================

# Mock pydantic and pydantic-settings
class MockBaseModel:
    pass

class MockBaseSettings:
    pass

mock_pydantic = MagicMock()
mock_pydantic.ConfigDict = MagicMock(return_value={})
mock_pydantic.Field = MagicMock(return_value=None)
mock_pydantic.BaseModel = MockBaseModel
sys.modules['pydantic'] = mock_pydantic

mock_pydantic_settings = MagicMock()
mock_pydantic_settings.BaseSettings = MockBaseSettings
sys.modules['pydantic_settings'] = mock_pydantic_settings

# Mock SQLAlchemy (we need to provide select, and_, or_ for the services)
mock_select = MagicMock()
mock_and = MagicMock()
mock_or = MagicMock()
mock_func = MagicMock()

mock_sqlalchemy = MagicMock()
mock_sqlalchemy.select = mock_select
mock_sqlalchemy.and_ = mock_and
mock_sqlalchemy.or_ = mock_or
mock_sqlalchemy.func = mock_func
sys.modules['sqlalchemy'] = mock_sqlalchemy
sys.modules['sqlalchemy.ext'] = MagicMock()
sys.modules['sqlalchemy.ext.asyncio'] = MagicMock()
sys.modules['sqlalchemy.orm'] = MagicMock()

# Mock aiobreaker
sys.modules['aiobreaker'] = MagicMock()

# Mock redis
sys.modules['redis'] = MagicMock()
sys.modules['redis.asyncio'] = MagicMock()
sys.modules['redis.exceptions'] = MagicMock()

# Mock structlog
mock_structlog = MagicMock()
mock_structlog.get_logger = MagicMock(return_value=MagicMock())
sys.modules['structlog'] = mock_structlog

# Mock Celery
mock_celery = MagicMock()
mock_celery.Celery = MagicMock()
mock_celery.signals = MagicMock()
mock_celery.signals.worker_process_init = MagicMock()
mock_celery.signals.worker_process_init.connect = MagicMock()
mock_celery.signals.worker_process_shutdown = MagicMock()
mock_celery.signals.worker_process_shutdown.connect = MagicMock()
sys.modules['celery'] = mock_celery
sys.modules['celery.signals'] = mock_celery.signals

# ============================================================================
# Mock app.config and app.database to avoid loading real settings
# ============================================================================

# Create a mock settings object
mock_settings = MagicMock()
mock_settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"
mock_settings.CELERY_BROKER_URL = "memory://"
mock_settings.CELERY_RESULT_BACKEND_URL = "memory://"
mock_settings.LOG_LEVEL = "INFO"
mock_settings.REDIS_URL = "redis://localhost:6379"

# Create mock config module
mock_config_module = MagicMock()
mock_config_module.settings = mock_settings
sys.modules['app.config'] = mock_config_module

# Mock database
mock_database = MagicMock()
sys.modules['app.database'] = mock_database

# ============================================================================
# Mock app.models
# ============================================================================

mock_models = MagicMock()
mock_models.Notification = MagicMock()
mock_models.Notification.id = MagicMock()
mock_models.Notification.user_id = MagicMock()
mock_models.Notification.data = MagicMock()

mock_models.Lead = MagicMock()
mock_models.Lead.id = MagicMock()
mock_models.Lead.assigned_officer_id = MagicMock()

mock_models.User = MagicMock()
mock_models.User.id = MagicMock()
mock_models.User.status = MagicMock()
mock_models.User.role = MagicMock()

mock_models.UserUnitAssignment = MagicMock()
mock_models.UserUnitAssignment.user_id = MagicMock()
mock_models.UserUnitAssignment.unit_id = MagicMock()
mock_models.UserUnitAssignment.is_active = MagicMock()
mock_models.UserUnitAssignment.role = MagicMock()

mock_models.NotificationPreference = MagicMock()
mock_models.NotificationPreference.user_id = MagicMock()
mock_models.NotificationPreference.type_preferences = MagicMock()

sys.modules['app.models'] = mock_models

# Mock app.celery_utils
mock_celery_utils = MagicMock()
mock_celery_utils.broadcast_notification_task = MagicMock()
mock_celery_utils.broadcast_notification_task.delay = MagicMock()
sys.modules['app.celery_utils'] = mock_celery_utils

# Mock app.schemas (to avoid loading pydantic-based schemas)
mock_schemas = MagicMock()
sys.modules['app.schemas'] = mock_schemas
sys.modules['app.schemas.lead'] = MagicMock()
sys.modules['app.schemas.organization'] = MagicMock()
sys.modules['app.schemas.notification'] = MagicMock()

# ============================================================================
# DO NOT mock app, app.core, or app.services - let them import naturally
# ============================================================================
