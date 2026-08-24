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


# =============================================================================
# Thông báo lỗi pepper: nêu TÊN BIẾN, không mang GIÁ TRỊ
# =============================================================================
# Hai tầng chặn pepper hỏng, và chúng đi qua hai đường lỗi KHÁC nhau:
#   * thiếu hẳn    → ``_validate_production_secrets`` raise ``LoiCauHinh``;
#   * có nhưng sai → ``field_validator`` raise ``ValueError`` ⇒ pydantic gói
#                    thành ``ValidationError``.
# Cả hai phải đi qua ``mo_ta_loi_an_toan`` và giữ đúng một cân bằng: đủ để
# người vận hành biết THIẾU BIẾN NÀO, mà không in giá trị.
#
# Vì sao ``LoiCauHinh`` chứ không ``RuntimeError``: bộ mô tả chỉ in message của
# exception đã được chứng minh an toàn theo KIỂU. Một ``RuntimeError`` trần rơi
# vào nhánh "chỉ in tên lớp" — không rò gì, nhưng thông báo mất hẳn tên biến,
# đúng lúc backend không khởi động được vì thiếu chính biến ấy.

_CANARY_PEPPER = "pepper-canary-khong-duoc-log"


class TestThongBaoPepperKhongMangGiaTri:
    def test_thieu_pepper_neu_ten_bien(self):
        from app.utils.redact import LoiCauHinh, mo_ta_loi_an_toan

        with pytest.raises(LoiCauHinh) as thong_tin:
            _dung_production(MFA_BACKUP_CODE_PEPPER="")

        ra = mo_ta_loi_an_toan(thong_tin.value)
        assert "MFA_BACKUP_CODE_PEPPER" in ra, (
            "thông báo không nêu tên biến — người vận hành không biết thiếu gì: "
            + ra
        )

    def test_thieu_pepper_dung_LoiCauHinh_chu_khong_RuntimeError_tran(self):
        """Kiểu quyết định bộ mô tả in gì — phép kiểm về KIỂU, không về chuỗi."""
        from app.utils.redact import LoiCauHinh

        with pytest.raises(LoiCauHinh):
            _dung_production(MFA_BACKUP_CODE_PEPPER="")

    def test_pepper_sai_khong_ro_gia_tri_nhung_van_neu_ten_bien(self):
        """``field_validator`` raise ``ValueError`` mang giá trị ⇒ pydantic đưa
        nguyên văn vào ``msg``. Bộ mô tả bỏ ``msg``, lấy tên biến từ ``loc``."""
        from app.utils.redact import mo_ta_loi_an_toan

        with pytest.raises(ValidationError) as thong_tin:
            Settings(**_cau_hinh_production(MFA_BACKUP_CODE_PEPPER=_CANARY_PEPPER))

        ra = mo_ta_loi_an_toan(thong_tin.value)
        assert _CANARY_PEPPER not in ra, "giá trị pepper lọt vào log: " + ra
        assert "MFA_BACKUP_CODE_PEPPER" in ra, "mất tên biến ⇒ vô dụng: " + ra

    def test_kiem_nguoc_str_exc_that_su_mang_canary(self):
        """Chứng minh mối nguy có thật: ``str(exc)`` — thứ bộ mô tả cố ý KHÔNG
        dùng — vẫn chứa canary. Không có ca này thì ba ca trên chỉ nói rằng bộ
        mô tả im lặng, chưa nói rằng nó im lặng về một thứ nguy hiểm."""
        with pytest.raises(ValidationError) as thong_tin:
            Settings(**_cau_hinh_production(MFA_BACKUP_CODE_PEPPER=_CANARY_PEPPER))

        assert _CANARY_PEPPER in str(thong_tin.value), (
            "str(exc) KHÔNG còn mang canary — phép kiểm ngược mất ý nghĩa, "
            "hãy đọc lại vì sao bộ mô tả tồn tại"
        )
