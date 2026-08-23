# tests/services/test_mfa_backup_code_cost.py
"""Cổng chi phí cho backup code MFA — chặn khuếch đại bcrypt tuyến tính.

## Vì sao có tệp này

Bản trước lưu backup code dạng ``json.dumps(list[bcrypt_hash])`` và xác minh
bằng cách quét TUYẾN TÍNH, bcrypt từng mục, bằng CHÍNH context mật khẩu
(rounds=15). Đo trong container backend:

    một phép bcrypt-15 verify  = 1,77s
    một mã sai (8 mục)         = 8 × 1,77 ≈ 14,1s CPU, CHẶN event loop
    sinh 8 mã (enable/regen)   ≈ 14,1s, cũng chặn event loop

Tệ hơn: ``verify_mfa_code`` thử TOTP trước rồi **rơi xuống** backup code, nên
một mã TOTP 6 số gõ nhầm cũng trả giá đầy đủ. Nightly ``32513696715`` có 8 node
MFA chết vì ``Timeout (>60.0s)`` — chúng không "chậm", chúng đang đo một
endpoint tốn 14s CPU mỗi request.

Các ca ở đây khoá CHI PHÍ, không chỉ khoá tính đúng: đếm số phép bcrypt thật sự
chạy. Một bản vá làm đúng nhưng vẫn quét O(n) sẽ ĐỎ ở đây.
"""
import json

import pytest
from passlib.context import CryptContext

from app.config import settings
from app.services import mfa_service
from app.utils.exceptions import BusinessRuleViolation


_PEPPER = "test-pepper-khong-dung-ngoai-test"


@pytest.fixture(autouse=True)
def _set_backup_pepper(monkeypatch):
    """Pepper cho selector. Thiếu nó thì đường backup code fail-closed."""
    monkeypatch.setattr(settings, "MFA_BACKUP_CODE_PEPPER", _PEPPER)


class _DemBcrypt:
    """Bọc một CryptContext và ĐẾM số phép hash/verify thật sự chạy."""

    def __init__(self, inner):
        self._inner = inner
        self.verify_calls = 0
        self.hash_calls = 0

    def verify(self, *args, **kwargs):
        self.verify_calls += 1
        return self._inner.verify(*args, **kwargs)

    def hash(self, *args, **kwargs):
        self.hash_calls += 1
        return self._inner.hash(*args, **kwargs)

    def to_dict(self):
        return self._inner.to_dict()


class _Dem:
    def __init__(self, v2, legacy):
        self.v2 = v2
        self.legacy = legacy

    @property
    def tong_verify(self):
        return self.v2.verify_calls + self.legacy.verify_calls


@pytest.fixture
def dem_bcrypt(monkeypatch):
    """Đếm bcrypt của CẢ hai đường: context v2 và context mật khẩu (legacy).

    Vá theo BINDING trên chính module đang test, không vá thuộc tính của
    ``passlib``/``bcrypt`` — vá module dùng chung sẽ đổi hành vi của mọi thứ
    khác trong cùng tiến trình.
    """
    v2 = _DemBcrypt(
        CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)
    )
    legacy = _DemBcrypt(
        CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)
    )
    monkeypatch.setattr(mfa_service, "_backup_context", lambda: v2)
    monkeypatch.setattr(mfa_service, "_pwd_context", legacy)
    return _Dem(v2, legacy)


def _tao_kho_v2(dem, count=8):
    """Sinh count mã + blob lưu trữ v2, rồi reset bộ đếm."""
    plaintext, entries = mfa_service.generate_backup_codes(count=count)
    dem.v2.hash_calls = 0
    dem.v2.verify_calls = 0
    dem.legacy.hash_calls = 0
    dem.legacy.verify_calls = 0
    return plaintext, json.dumps(entries)


# =============================================================================
# 1. HÌNH DẠNG — phân tuyến trước mọi chi phí
# =============================================================================


@pytest.mark.unit
class TestPhanTuyenHinhDang:

    @pytest.mark.parametrize(
        "code,mong",
        [
            ("123456", mfa_service.CODE_SHAPE_TOTP),
            ("000000", mfa_service.CODE_SHAPE_TOTP),
            ("0123456789", mfa_service.CODE_SHAPE_BACKUP),
            ("deadbeef00", mfa_service.CODE_SHAPE_BACKUP),
            ("DEADBEEF00", mfa_service.CODE_SHAPE_INVALID),   # hoa → không nhận
            ("12345", mfa_service.CODE_SHAPE_INVALID),
            ("1234567", mfa_service.CODE_SHAPE_INVALID),
            ("invalid!", mfa_service.CODE_SHAPE_INVALID),
            ("zzzzzzzzzz", mfa_service.CODE_SHAPE_INVALID),
            ("", mfa_service.CODE_SHAPE_INVALID),
            (None, mfa_service.CODE_SHAPE_INVALID),
        ],
    )
    def test_phan_loai(self, code, mong):
        assert mfa_service.classify_code_shape(code) == mong

    def test_sai_hinh_dang_khong_ton_bcrypt(self, dem_bcrypt):
        """Mã không thể là backup code thì không được tốn một phép bcrypt nào."""
        _, blob = _tao_kho_v2(dem_bcrypt)
        for code in ["invalid!", "12345", "DEADBEEF00", "zzzzzzzzzz", ""]:
            matched, updated = mfa_service.verify_backup_code(code, blob)
            assert matched is False
            assert updated == blob
        assert dem_bcrypt.tong_verify == 0, (
            "sai hinh dang van chay %d phep bcrypt" % dem_bcrypt.tong_verify
        )

    def test_ma_totp_6_so_khong_cham_backup_bcrypt(self, dem_bcrypt):
        """Đây là chỗ 14,1s CPU sinh ra: TOTP sai rơi xuống quét backup."""
        _, blob = _tao_kho_v2(dem_bcrypt)
        matched, _ = mfa_service.verify_backup_code("000000", blob)
        assert matched is False
        assert dem_bcrypt.tong_verify == 0


# =============================================================================
# 2. STORAGE v2 — selector chọn đúng MỘT candidate
# =============================================================================


@pytest.mark.unit
class TestStorageV2:

    def test_sinh_ma_dung_dinh_dang_nguoi_dung(self, dem_bcrypt):
        plaintext, entries = mfa_service.generate_backup_codes(count=8)
        assert len(plaintext) == 8
        for code in plaintext:
            assert len(code) == 10
            int(code, 16)                    # vẫn là hex
            assert code == code.lower()
        for e in entries:
            assert e["v"] == 2
            assert e["sel"] and e["vfy"]
        assert dem_bcrypt.v2.hash_calls == 8, "moi ma phai co dung 1 bcrypt"

    def test_selector_co_khoa_theo_pepper(self, monkeypatch):
        """Đổi pepper ⇒ selector đổi. Selector không khoá thì người đọc được DB
        có thể precompute bảng tra cho toàn bộ không gian 40-bit."""
        s1 = mfa_service._selector("deadbeef00")
        monkeypatch.setattr(settings, "MFA_BACKUP_CODE_PEPPER", "pepper-khac")
        s2 = mfa_service._selector("deadbeef00")
        assert s1 != s2

    def test_selector_khong_khop_thi_0_bcrypt(self, dem_bcrypt):
        """Đúng hình dạng nhưng không phải mã của user: KHÔNG bcrypt."""
        _, blob = _tao_kho_v2(dem_bcrypt)
        matched, updated = mfa_service.verify_backup_code("00112233ff", blob)
        assert matched is False
        assert updated == blob
        assert dem_bcrypt.tong_verify == 0

    def test_ma_hop_le_dung_1_bcrypt_va_dung_mot_lan(self, dem_bcrypt):
        plaintext, blob = _tao_kho_v2(dem_bcrypt)

        matched, updated = mfa_service.verify_backup_code(plaintext[3], blob)
        assert matched is True
        assert dem_bcrypt.tong_verify == 1, (
            "mong DUNG 1 phep bcrypt, thay %d" % dem_bcrypt.tong_verify
        )
        assert len(json.loads(updated)) == 7

        # Tái dùng chính mã đó trên kho ĐÃ cập nhật: trượt, và 0 bcrypt thêm
        dem_bcrypt.v2.verify_calls = 0
        lai, updated2 = mfa_service.verify_backup_code(plaintext[3], updated)
        assert lai is False
        assert updated2 == updated
        assert dem_bcrypt.tong_verify == 0

    def test_chi_tieu_thu_dung_muc_khop(self, dem_bcrypt):
        plaintext, blob = _tao_kho_v2(dem_bcrypt)
        _, updated = mfa_service.verify_backup_code(plaintext[1], blob)
        ok, updated2 = mfa_service.verify_backup_code(plaintext[0], updated)
        assert ok is True
        assert len(json.loads(updated2)) == 6

    def test_chi_phi_khong_tang_theo_so_ma(self, dem_bcrypt):
        """Bất biến cốt lõi: chi phí O(1), không phải O(n)."""
        for count in (4, 8, 32):
            _, blob = _tao_kho_v2(dem_bcrypt, count=count)
            mfa_service.verify_backup_code("00112233ff", blob)   # trượt
            assert dem_bcrypt.tong_verify == 0
            dem_bcrypt.v2.verify_calls = 0
            plaintext = json.loads(blob)
            assert len(plaintext) == count


# =============================================================================
# 3. PEPPER — fail closed
# =============================================================================


@pytest.mark.unit
@pytest.mark.security
class TestPepperFailClosed:

    @pytest.mark.parametrize("gia_tri", ["", None])
    def test_thieu_pepper_thi_sinh_ma_that_bai(self, monkeypatch, gia_tri):
        monkeypatch.setattr(settings, "MFA_BACKUP_CODE_PEPPER", gia_tri)
        with pytest.raises(BusinessRuleViolation):
            mfa_service.generate_backup_codes(count=2)

    @pytest.mark.parametrize("gia_tri", ["", None])
    def test_thieu_pepper_thi_xac_minh_that_bai(self, monkeypatch, gia_tri, dem_bcrypt):
        _, blob = _tao_kho_v2(dem_bcrypt)
        monkeypatch.setattr(settings, "MFA_BACKUP_CODE_PEPPER", gia_tri)
        with pytest.raises(BusinessRuleViolation):
            mfa_service.verify_backup_code("deadbeef00", blob)

    def test_khong_co_default_yeu(self):
        """Field phải mặc định rỗng — không được có giá trị 'tiện dụng'."""
        field = type(settings).model_fields["MFA_BACKUP_CODE_PEPPER"]
        assert field.default == ""


# =============================================================================
# 4. LEGACY — không tự vô hiệu mã đang phát hành
# =============================================================================


@pytest.mark.unit
class TestTuongThichLegacy:

    def _kho_legacy(self, dem, codes):
        return json.dumps([dem.legacy.hash(c) for c in codes])

    def test_legacy_hop_le_van_dung_duoc(self, dem_bcrypt):
        codes = ["aabbccdd00", "1122334455"]
        blob = self._kho_legacy(dem_bcrypt, codes)
        dem_bcrypt.legacy.verify_calls = 0

        matched, updated = mfa_service.verify_backup_code(codes[1], blob)
        assert matched is True
        assert len(json.loads(updated)) == 1

    def test_legacy_sai_van_0_bcrypt_neu_sai_hinh_dang(self, dem_bcrypt):
        blob = self._kho_legacy(dem_bcrypt, ["aabbccdd00"])
        dem_bcrypt.legacy.verify_calls = 0
        matched, _ = mfa_service.verify_backup_code("000000", blob)
        assert matched is False
        assert dem_bcrypt.tong_verify == 0, (
            "mot ma TOTP khong duoc quet kho legacy"
        )

    def test_legacy_sai_dung_hinh_dang_thi_quet(self, dem_bcrypt):
        """Quét tuyến tính là cái giá của định dạng cũ — ghi nhận tường minh."""
        blob = self._kho_legacy(dem_bcrypt, ["aabbccdd00", "1122334455"])
        dem_bcrypt.legacy.verify_calls = 0
        matched, _ = mfa_service.verify_backup_code("ffffffff00", blob)
        assert matched is False
        assert dem_bcrypt.legacy.verify_calls == 2

    def test_kho_tron_legacy_va_v2(self, dem_bcrypt):
        """v2 phải được ưu tiên tra selector; legacy vẫn dùng được."""
        v2_plain, v2_entries = mfa_service.generate_backup_codes(count=2)
        legacy_code = "aabbccdd00"
        entries = list(v2_entries) + [dem_bcrypt.legacy.hash(legacy_code)]
        blob = json.dumps(entries)

        ok1, updated = mfa_service.verify_backup_code(v2_plain[0], blob)
        assert ok1 is True
        ok2, updated2 = mfa_service.verify_backup_code(legacy_code, updated)
        assert ok2 is True
        assert len(json.loads(updated2)) == 1
