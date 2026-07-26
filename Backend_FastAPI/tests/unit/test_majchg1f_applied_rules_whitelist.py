"""Lock-in whitelist `majchg1f` ⟷ key mà đổi ngành THỰC SỰ ghi vào applied_rules.

VÌ SAO CẦN: prod có trigger `enforce_applied_rules_immutability` (function
`prevent_applied_rules_update`) chặn mọi key ngoài whitelist — đổi 1 key không có
trong danh sách là `RAISE EXCEPTION` ⇒ 500 ⇒ rollback cả giao dịch nộp lại. Nhưng
test DB dựng bằng `Base.metadata.create_all` (memory ``test-db-schema-source``) nên
KHÔNG có trigger nào: mọi test tích hợp vẫn xanh dù prod chặn thẳng nhánh chính.

Lần này đã xảy ra thật: `_path_dependent_applied_rules` (đổi ngành = đổi phương
thức xét tuyển) ghi 19 key criteria/tổ-hợp/method/lệ-phí mà whitelist chỉ có 10 →
tính năng sẽ chết 100% trên prod, 56 test vẫn xanh. Test này là lưới duy nhất bắt
được lớp lỗi đó ở môi trường không trigger, nên nó so **danh sách trong migration**
với **key hàm re-snapshot thật sự trả về**, không hard-code lại danh sách lần hai.

Hành vi trigger sống được verify riêng bằng alembic CLI roundtrip trên DB dev (cùng
cách ``test_ardockeys01_applied_rules_doc_keys.py`` ghi).
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    _BACKEND_ROOT / "alembic" / "versions" / "majchg1f_applied_rules_20260723.py"
)
SERVICE_PATH = _BACKEND_ROOT / "app" / "services" / "admission_service.py"


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "majchg1f_migration", str(MIGRATION_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resnapshot_keys() -> set[str]:
    """Key mà `_path_dependent_applied_rules` ghi — đọc từ AST, không chạy DB.

    Lấy mọi khoá chuỗi của dict literal gán cho biến `rebuilt`, cộng các key gán
    sau bằng `rebuilt["..."] = ...` (nhánh lệ phí giữ 'paid').
    """
    tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_path_dependent_applied_rules"
        ),
        None,
    )
    assert fn is not None, "không tìm thấy _path_dependent_applied_rules"

    keys: set[str] = set()
    for node in ast.walk(fn):
        # rebuilt: Dict[str, Any] = { "min_gpa": ..., ... }
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
        # rebuilt["fee_status"] = ...
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            if isinstance(node.slice.value, str):
                keys.add(node.slice.value)
    assert keys, "AST không bắt được key nào — sửa parser trước khi tin test này"
    return keys


def test_revision_chain():
    mod = _load_migration_module()
    assert mod.revision == "majchg1f_applied_rules_20260723"
    assert mod.down_revision == "majchg1b_profile_col_20260723"
    # Postgres cột alembic_version là VARCHAR(32) — id dài hơn là vỡ lúc stamp.
    assert len(mod.revision) <= 32


def test_every_resnapshot_key_is_whitelisted():
    """MỌI key đổi-ngành ghi PHẢI nằm trong whitelist, nếu không prod raise 500."""
    mod = _load_migration_module()
    allowed = set(mod.ALLOWED_KEYS)
    missing = sorted(_resnapshot_keys() - allowed)
    assert not missing, (
        "Các key sau bị trigger applied_rules CHẶN trên prod (test DB không có "
        f"trigger nên không tự đỏ): {missing}. Thêm vào ALLOWED_KEYS của "
        "majchg1f (cả tuple Python LẪN mảng allowed_keys trong SQL) hoặc bỏ key "
        "khỏi _path_dependent_applied_rules."
    )


def test_sql_array_matches_python_tuple():
    """Tuple Python chỉ là tài liệu — mảng trong SQL mới là thứ chạy thật."""
    mod = _load_migration_module()
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_sql = src[src.index("def upgrade()"):src.index("def downgrade()")]
    for key in mod.ALLOWED_KEYS:
        assert f"'{key}'" in upgrade_sql, (
            f"key {key!r} có trong ALLOWED_KEYS nhưng THIẾU trong mảng SQL "
            "allowed_keys của upgrade() → trigger vẫn chặn nó"
        )


def test_fee_and_doc_keys_survive():
    """Nới cho đổi ngành không được làm mất 7 key gốc (thu lệ phí + doc-resolve)."""
    mod = _load_migration_module()
    for key in (
        "fee_status",
        "fee_paid_at",
        "fee_payment_data",
        "fee_calculated_at",
        "fee_invoice_id",
        "mandatory_docs",
        "doc_configs",
    ):
        assert key in mod.ALLOWED_KEYS


def test_downgrade_restores_seven_keys():
    """downgrade phải trả whitelist về đúng 7 key của ardockeys01."""
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    downgrade_sql = src[src.index("def downgrade()"):]
    for key in ("fee_status", "mandatory_docs", "doc_configs"):
        assert f"'{key}'" in downgrade_sql
    # Không được sót key đổi-ngành trong downgrade (nếu sót thì downgrade không
    # thật sự siết lại và migration mất tính đối xứng).
    for key in ("min_gpa", "scoring_method", "admission_method_id", "method_quota"):
        assert f"'{key}'" not in downgrade_sql
