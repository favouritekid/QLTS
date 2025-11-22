# tests/services/conftest.py
"""
Minimal conftest for services tests.
"""
import sys
from unittest.mock import MagicMock

# Mock the app modules to avoid loading full application
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
sys.modules['app'] = MagicMock()
sys.modules['app.models'] = mock_models
