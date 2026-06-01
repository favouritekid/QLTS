"""Unit tests: suspicious-login email/zalo risk-gate (Phase 2 PR-B).

The decision "which channels does a suspicious-login dispatch use?" is
extracted into ``auth._suspicious_login_only_channels`` so it can be tested
without driving a full login flow. risk_score weights come from
``login_history_service.RISK_WEIGHTS`` (new_ip 30 / new_device 40 /
new_location 50 / impossible_travel 80, −20% trusted).
"""


class TestSuspiciousLoginChannelGate:
    def test_new_ip_only_below_threshold_browser_only(self):
        from app.routers.auth import _suspicious_login_only_channels
        # bare new_ip = 30 < 40 → in-app banner only, NO email
        assert _suspicious_login_only_channels(30) == ["browser"]

    def test_trusted_new_ip_below_threshold_browser_only(self):
        from app.routers.auth import _suspicious_login_only_channels
        # new_ip on a trusted device = int(30 * 0.8) = 24 < 40
        assert _suspicious_login_only_channels(24) == ["browser"]

    def test_new_device_at_threshold_all_channels(self):
        from app.routers.auth import _suspicious_login_only_channels
        # new_device = 40 >= 40 → all channels (email fires)
        assert _suspicious_login_only_channels(40) is None

    def test_new_ip_plus_new_device_all_channels(self):
        from app.routers.auth import _suspicious_login_only_channels
        # 30 + 40 = 70 >= 40 → all channels
        assert _suspicious_login_only_channels(70) is None

    def test_zero_risk_is_browser_only(self):
        from app.routers.auth import _suspicious_login_only_channels
        assert _suspicious_login_only_channels(0) == ["browser"]

    def test_threshold_is_config_tunable_not_hardcoded(self, monkeypatch):
        from app.config import settings
        from app.routers import auth
        # Raise the bar to 50 → new_device (40) now falls below → browser-only.
        monkeypatch.setattr(settings, "SUSPICIOUS_LOGIN_EMAIL_RISK_THRESHOLD", 50)
        assert auth._suspicious_login_only_channels(40) == ["browser"]
        assert auth._suspicious_login_only_channels(50) is None
