"""ADM-004 regression: ``validate_activation`` must enforce the same
readiness contract as ``get_coverage_matrix``.

Before the fix, ``validate_activation`` only checked status + quota and
left criteria/documents as "placeholder" comments. The route therefore
let admins activate paths that the coverage matrix flagged as not-ready.
Now both code paths agree:

- status in {draft, inactive}
- academic_info.annual_admission_quota > 0
- path.criteria_id is set
- a DocumentGroup resolves for offering_type + admission_method
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession


import pytest

from app.services.admission_path_service import AdmissionPathService


# Sentinel phân biệt "không truyền" với "truyền rõ None". Xem `_stub_db`.
_KHONG_TRUYEN = object()


def _round(*, round_id: int = 11, is_active: bool = True, archived_at=None):
    """Đợt tuyển sinh giả — chỉ bốn trường mà ``validate_activation`` đọc.

    ``validate_activation`` Check 1b lấy đợt qua ``db.get`` rồi soi
    ``archived_at`` và ``is_active``; ``activate_path`` khoá lại đợt qua
    ``db.execute(...).scalar_one_or_none()`` và soi cùng hai trường ấy, cộng
    ``round_code`` để dựng thông báo lỗi.
    """
    return SimpleNamespace(
        id=round_id,
        round_code="DOT_1",
        is_active=is_active,
        archived_at=archived_at,
    )


def _stub_db(active_round=_KHONG_TRUYEN):
    """Session giả GIỮ ĐÚNG ranh giới async/sync của ``AsyncSession``.

    ``spec=AsyncSession`` là phần quan trọng: một lời gọi sai contract sẽ nổ
    thay vì bị mock nuốt. KHÔNG dùng ``AsyncMock()`` cho cả session —
    ``AsyncSession`` có cả method async lẫn sync, nên mock async nguyên khối
    làm lệch contract và che lỗi mới.

    ``db.get`` phục vụ ``validate_activation`` Check 1b.
    ``db.execute(...).scalar_one_or_none()`` phục vụ khoá đợt trong
    ``activate_path`` — thiếu nó thì ca kích hoạt đỏ ở ``scalar_one_or_none``,
    một root khác bị che sau root ``db.get``.

    Mặc định (``active_round=_KHONG_TRUYEN``) dựng một đợt đang hoạt động.
    Truyền RÕ ``active_round=None`` thì ``db.get`` và ``scalar_one_or_none``
    cùng trả ``None`` — mô phỏng "đợt không tìm thấy".

    Phải dùng sentinel chứ không dùng ``None`` làm mặc định: nếu mặc định là
    ``None`` rồi thân hàm đổi nó thành đợt hoạt động, thì lời truyền ``None``
    tường minh bị nuốt và trạng thái mà docstring hứa KHÔNG dựng được — chú
    thích nói một đằng, mã làm một nẻo.

    ⚠️ "Đợt không tìm thấy" là LỖ COVERAGE của fixture, KHÔNG phải trạng thái
    dựng được trên CSDL thật: cột ``admission_round_id`` là NOT NULL, FK dùng
    ON DELETE RESTRICT, và ``activate_path`` từ chối tường minh khi khoá lại
    không thấy đợt.
    """
    if active_round is _KHONG_TRUYEN:
        active_round = _round()
    db = MagicMock(spec=AsyncSession)
    db.get = AsyncMock(return_value=active_round)
    locked_result = MagicMock()
    locked_result.scalar_one_or_none.return_value = active_round
    db.execute = AsyncMock(return_value=locked_result)
    return db


pytestmark = pytest.mark.unit


def _make_path(
    *,
    status: str = "draft",
    quota: int = 100,
    criteria_id: int | None = 7,
    offering_type_id: int | None = 1,
    admission_method_id: int = 1,
):
    """Build an in-memory AdmissionPath stand-in with just the attrs the
    service touches. Avoids needing a DB session for unit tests."""
    offering = SimpleNamespace(offering_type_id=offering_type_id)
    academic_info = SimpleNamespace(
        annual_admission_quota=quota,
        offering=offering,
    )
    return SimpleNamespace(
        id=1,
        status=status,
        academic_info=academic_info,
        criteria_id=criteria_id,
        admission_method_id=admission_method_id,
        # BẮT BUỘC: `validate_activation` Check 1b đọc trường này để lấy đợt
        # tuyển sinh. Cột thật là NOT NULL (PR-2C v2, đánh dấu ONE-WAY), và
        # schema `AdmissionPathCreate` khai `Field(..., gt=0)` từ PR #338 —
        # stub thiếu nó là stub mô tả một hàng không tồn tại được.
        admission_round_id=11,
    )


def _make_service(
    *,
    method_group: object | None = None,
    shared_groups: list | None = None,
    active_round=_KHONG_TRUYEN,
):
    """Build an AdmissionPathService with a stub DocumentGroupRepository.

    The service constructs ``DocumentGroupRepository(self.db)`` lazily
    inside ``validate_activation``. We patch the import site so the stub
    is returned regardless of the db arg.
    """
    service = AdmissionPathService.__new__(AdmissionPathService)
    service.db = _stub_db(active_round)
    service.repo = MagicMock()

    doc_repo = MagicMock()
    doc_repo.get_method_specific_group = AsyncMock(return_value=method_group)
    doc_repo.get_shared_groups = AsyncMock(return_value=shared_groups or [])
    return service, doc_repo


def _patch_doc_repo(doc_repo):
    return patch(
        "app.repositories.document_group_repository.DocumentGroupRepository",
        return_value=doc_repo,
    )


class TestValidateActivation:
    async def test_ready_path_can_activate(self):
        service, doc_repo = _make_service(method_group=object())
        path = _make_path()

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is True, errors
        assert errors == []

    async def test_active_status_blocks_activation(self):
        service, doc_repo = _make_service(method_group=object())
        path = _make_path(status="active")

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        assert any("status" in e.lower() for e in errors)

    async def test_zero_quota_blocks_activation(self):
        service, doc_repo = _make_service(method_group=object())
        path = _make_path(quota=0)

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        assert any("Quota" in e or "chỉ tiêu" in e.lower() for e in errors)

    async def test_missing_criteria_blocks_activation(self):
        service, doc_repo = _make_service(method_group=object())
        path = _make_path(criteria_id=None)

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        assert any("Criteria" in e or "tiêu chí" in e.lower() for e in errors)

    async def test_missing_documents_blocks_activation(self):
        # Neither method-specific nor shared groups exist
        service, doc_repo = _make_service(method_group=None, shared_groups=[])
        path = _make_path()

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        assert any("Documents" in e or "hồ sơ" in e.lower() for e in errors)

    async def test_shared_documents_satisfy_requirement(self):
        # No method-specific group, but shared group exists
        service, doc_repo = _make_service(
            method_group=None, shared_groups=[object()]
        )
        path = _make_path()

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is True, errors

    async def test_all_missing_collects_all_errors(self):
        """validate_activation should accumulate every gap, not bail early."""
        service, doc_repo = _make_service(method_group=None, shared_groups=[])
        path = _make_path(quota=0, criteria_id=None)

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        # Quota + criteria + documents — three independent gaps
        assert len(errors) >= 3


class TestCheck1bDotTuyenSinh:
    """Check 1b — đợt tuyển sinh archived / tắt thì KHÔNG được kích hoạt.

    Hai ca này tồn tại vì một lý do rất cụ thể: ``validate_activation`` bọc
    Check 1b trong ``if admission_round is not None``. Nếu fixture để ``db.get``
    trả ``None`` — chẳng hạn khi stub gắn một ``admission_round_id`` mồ côi —
    thì toàn bộ Check 1b **bị bỏ qua trong im lặng**, và các ca khác vẫn xanh
    trong khi không phép kiểm nào chạm tới nó.

    Đây là LỖ COVERAGE của fixture, không phải lỗ hổng runtime: trên CSDL thật
    ``admission_round_id`` là NOT NULL và FK dùng ON DELETE RESTRICT, còn
    ``activate_path`` khoá lại đợt rồi từ chối tường minh nếu không tìm thấy.
    """

    async def test_dot_da_luu_tru_khong_kich_hoat_duoc(self):
        service, doc_repo = _make_service(
            method_group=object(),
            active_round=_round(archived_at=datetime(2026, 1, 1)),
        )
        path = _make_path()

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False, (
            "dot da luu tru ma van cho kich hoat — Check 1b khong chay"
        )
        assert any("lưu trữ" in e for e in errors), (
            f"phai co loi ve dot da luu tru, nhan {errors}"
        )

    async def test_dot_bi_tat_khong_kich_hoat_duoc(self):
        service, doc_repo = _make_service(
            method_group=object(),
            active_round=_round(is_active=False),
        )
        path = _make_path()

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False, (
            "dot dang tat ma van cho kich hoat — Check 1b khong chay"
        )
        assert any("is_active=false" in e or "tắt" in e for e in errors), (
            f"phai co loi ve dot dang tat, nhan {errors}"
        )
