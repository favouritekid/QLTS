"""Biên của cấu hình MFA backup code — dựng ``Settings`` THẬT, không vá singleton.

Vì sao không monkeypatch `settings`: vá thuộc tính của singleton bỏ qua đúng
thứ cần kiểm — lớp validator chạy lúc DỰNG. Một giá trị như ``"x"`` hay
``"CHANGE_ME_..."`` gán bằng monkeypatch sẽ "chạy được", nên ca kiểm kiểu đó
xanh trong khi production vẫn nhận cấu hình rỗng ruột.

Hai tầng đang được kiểm:
  * ``field_validator`` — chạy ở MỌI môi trường khi dựng Settings;
  * ``_validate_production_secrets()`` — chỉ production, gọi tường minh vì mã
    sản phẩm cũng gọi nó tường minh sau khi dựng singleton (config.py cuối tệp).
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings

pytestmark = [pytest.mark.unit, pytest.mark.security]

PEPPER_TOT = "Zk3n8QwPz1vY7sR4tU6wA9bC2dE5fG0hJkLmNoPq"   # 40 ký tự
_FERNET = Fernet.generate_key().decode()


def _cau_hinh_production(**ghi_de):
    """Bộ giá trị production hợp lệ tối thiểu, cho ghi đè từng phần.

    ``ALLOW_DOCKER_INTERNAL_NETWORK=True`` để bỏ qua nhánh kiểm TLS — nhánh đó
    không phải chủ đề của tệp này và giữ nó chỉ làm ca kiểm đỏ vì lý do khác.
    """
    gia_tri = dict(
        APP_ENV="production",
        SECRET_KEY="s" * 64,
        JWT_SECRET_KEY="j" * 64,
        DEVICE_FINGERPRINT_SALT="salt-that-is-not-the-default-value",
        MFA_ENCRYPTION_KEY=_FERNET,
        MFA_BACKUP_CODE_PEPPER=PEPPER_TOT,
        LOG_LEVEL="INFO",
        FRONTEND_URL="https://qlts.example.edu.vn",
        PUBLIC_BACKEND_URL="https://api.qlts.example.edu.vn",
        DATABASE_URL="postgresql+asyncpg://u:p@db.internal:5432/qlts",
        ALLOW_DOCKER_INTERNAL_NETWORK=True,
    )
    gia_tri.update(ghi_de)
    return gia_tri


def _dung_production(**ghi_de):
    s = Settings(**_cau_hinh_production(**ghi_de))
    s._validate_production_secrets()
    return s


class TestPepperCoBien:
    def test_cau_hinh_hop_le_thi_dung_duoc(self):
        s = _dung_production()
        assert s.MFA_BACKUP_CODE_PEPPER == PEPPER_TOT

    def test_pepper_duoc_trim(self):
        s = Settings(**_cau_hinh_production(
            MFA_BACKUP_CODE_PEPPER="  " + PEPPER_TOT + "\n"
        ))
        assert s.MFA_BACKUP_CODE_PEPPER == PEPPER_TOT

    @pytest.mark.parametrize("xau", ["x", "abc", "a" * 31, "   " + "a" * 20 + "  "])
    def test_pepper_qua_ngan_bi_tu_choi(self, xau):
        """"Khác rỗng" KHÔNG phải là một hàng rào: 'x' vẫn khác rỗng."""
        with pytest.raises(ValidationError) as e:
            Settings(**_cau_hinh_production(MFA_BACKUP_CODE_PEPPER=xau))
        assert "MFA_BACKUP_CODE_PEPPER" in str(e.value)

    @pytest.mark.parametrize(
        "xau",
        [
            "CHANGE_ME_python_secrets_token_urlsafe_32",
            "your-backup-code-pepper-here-change-me-later",
            "TODO_dat_gia_tri_that_truoc_khi_len_production",
            "placeholder-placeholder-placeholder-value",
        ],
    )
    def test_pepper_placeholder_bi_tu_choi(self, xau):
        """Đủ dài nhưng vẫn là chữ chép từ tệp mẫu ⇒ 0 entropy."""
        assert len(xau) >= 32, "ca kiểm phải đủ dài, nếu không nó đỏ vì độ dài"
        with pytest.raises(ValidationError):
            Settings(**_cau_hinh_production(MFA_BACKUP_CODE_PEPPER=xau))

    def test_pepper_rong_van_dung_duoc_ngoai_production(self):
        """Rỗng = CHƯA cấu hình: hợp lệ ở dev/test, fail closed lúc chạy."""
        s = Settings(APP_ENV="development", MFA_BACKUP_CODE_PEPPER="")
        assert s.MFA_BACKUP_CODE_PEPPER == ""

    def test_pepper_rong_thi_production_do(self):
        with pytest.raises(RuntimeError, match="MFA_BACKUP_CODE_PEPPER"):
            _dung_production(MFA_BACKUP_CODE_PEPPER="")


class TestRoundsVaWorkersCoBien:
    @pytest.mark.parametrize("rounds", [10, 12, 14])
    def test_rounds_trong_mien_thi_nhan(self, rounds):
        s = _dung_production(MFA_BACKUP_CODE_BCRYPT_ROUNDS=rounds)
        assert s.MFA_BACKUP_CODE_BCRYPT_ROUNDS == rounds

    @pytest.mark.parametrize("rounds", [0, 4, 9, 15, 31])
    def test_rounds_ngoai_mien_bi_tu_choi(self, rounds):
        """15 nằm NGOÀI miền có chủ ý: đo được 1,78s/phép, vượt mốc OWASP <1s —
        và chính chi phí đó là lỗ hổng đang vá."""
        with pytest.raises(ValidationError):
            Settings(**_cau_hinh_production(MFA_BACKUP_CODE_BCRYPT_ROUNDS=rounds))

    @pytest.mark.parametrize("n", [1, 2, 8])
    def test_workers_trong_mien_thi_nhan(self, n):
        s = _dung_production(MFA_BCRYPT_MAX_WORKERS=n)
        assert s.MFA_BCRYPT_MAX_WORKERS == n

    @pytest.mark.parametrize("n", [0, -1, 9, 1000])
    def test_workers_ngoai_mien_bi_tu_choi(self, n):
        """1000 là ca quan trọng nhất: nó KHÔNG lỗi ở đâu cả, chỉ lặng lẽ vô
        hiệu hoá resource governor."""
        with pytest.raises(ValidationError):
            Settings(**_cau_hinh_production(MFA_BCRYPT_MAX_WORKERS=n))


class TestCoWriterV2:
    def test_mac_dinh_TAT(self):
        s = Settings(APP_ENV="development")
        assert s.MFA_BACKUP_CODE_V2_WRITER_ENABLED is False

    def test_bat_duoc_tuong_minh(self):
        s = _dung_production(MFA_BACKUP_CODE_V2_WRITER_ENABLED=True)
        assert s.MFA_BACKUP_CODE_V2_WRITER_ENABLED is True
