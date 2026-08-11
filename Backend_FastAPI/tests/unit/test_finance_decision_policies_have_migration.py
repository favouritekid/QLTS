"""Quyền QUYẾT ĐỊNH tiền trong template phải có migration cấp nó.

Bài học đứng sau bộ này: `policy_templates.py` cấp cho manager quyền
verify/reject payment, mọi test API đều xanh, mà production vẫn 403 — vì
**không migration nào** đưa hai dòng ấy vào `casbin_rule`.

Vì sao cả một bộ test API không bắt được: ở dev/test, `AUTO_SYNC_TEMPLATES`
đồng bộ template vào DB lúc app khởi động (`main.py`), nên enforcer trong test
đọc được policy dù bảng thật chưa từng có nó. Production KHÔNG tự sync —
`alembic upgrade head` là đường duy nhất. Nên mọi ca "manager verify được"
đang đo template, không đo thứ sẽ tồn tại sau deploy.

Bộ này đo đúng khoảng trống đó: với các quyền quyết định tiền, đòi có một
migration nhắc tới cả vai trò lẫn route. Không thay thế test API — nó khoá một
tính chất khác: **thứ chạy được ở dev phải lên tới được prod.**
"""

import ast
from pathlib import Path

import pytest

from app.casbin_config.policy_templates import (
    ACCOUNTANT_TEMPLATE,
    MANAGER_TEMPLATE,
)

pytestmark = pytest.mark.unit

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"

# Chỉ những route ĐỔI trạng thái tiền theo maker-checker. Cố ý không quét toàn
# bộ template: phần lớn quyền đọc vô hại nếu thiếu (màn hình trống, ai cũng
# thấy ngay), còn thiếu ở đây thì tiền kẹt mà nhìn màn hình vẫn thấy nút.
_ROUTE_QUYET_DINH = (
    "/api/payments/{id}/verify",
    "/api/payments/{id}/reject",
)

_VAI_TRO = {
    "role:manager": MANAGER_TEMPLATE,
    "role:accountant": ACCOUNTANT_TEMPLATE,
}


def _routes_trong_template(template) -> set[str]:
    return {
        p["object"]
        for p in template["policies"]
        if p["object"] in _ROUTE_QUYET_DINH
    }


def _cap_policy_trong_migrations() -> set[tuple[str, str]]:
    """Mọi cặp (vai trò, route) được cấp trong một migration.

    🔴 Đọc bằng AST, và chỉ nhận khi hai chuỗi nằm TRONG CÙNG MỘT literal
    (tuple/list/dict). Bản đầu của bộ test này chỉ hỏi "file có chứa cả hai
    chuỗi không" — và nó KHÔNG THỂ ĐỎ: `rbac20260131001` có 'role:manager' ở
    phần g-rules và '/api/payments/{id}/verify' ở phần policy của accountant,
    hai chỗ chẳng liên quan gì nhau trong cùng một file. Gỡ hẳn migration mới
    ra mà bộ test vẫn xanh.
    """
    files = sorted(_VERSIONS.glob("*.py"))
    assert files, f"không đọc được migration nào ở {_VERSIONS}"

    cap: set[tuple[str, str]] = set()
    for f in files:
        try:
            cay = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — migration hỏng thì test khác lo
            continue
        for node in ast.walk(cay):
            if isinstance(node, (ast.Tuple, ast.List)):
                chuoi = [
                    e.value
                    for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
            elif isinstance(node, ast.Dict):
                chuoi = [
                    v.value
                    for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                ]
            else:
                continue
            vai = [c for c in chuoi if c.startswith("role:")]
            routes = [c for c in chuoi if c in _ROUTE_QUYET_DINH]
            for v in vai:
                for r in routes:
                    cap.add((v, r))
    return cap


@pytest.mark.parametrize("vai_tro", sorted(_VAI_TRO))
def test_quyen_quyet_dinh_tien_co_migration(vai_tro: str):
    template = _VAI_TRO[vai_tro]
    routes = _routes_trong_template(template)
    assert routes, (
        f"{vai_tro} không còn route quyết định tiền nào trong template — "
        "nếu đó là chủ ý thì sửa _ROUTE_QUYET_DINH, đừng để bộ test này xanh rỗng"
    )

    da_cap = _cap_policy_trong_migrations()
    thieu = [r for r in sorted(routes) if (vai_tro, r) not in da_cap]

    assert not thieu, (
        f"{vai_tro} được cấp {thieu} trong policy_templates.py nhưng KHÔNG "
        "migration nào cấp chúng.\n"
        "Deploy chạy `alembic upgrade head` chứ không chạy "
        "scripts/sync_casbin_templates.py, nên những quyền này sẽ không bao "
        "giờ tới production và enforcer sẽ DENY đúng vai trò mà tính năng nhắm "
        "tới. Thêm một migration idempotent cấp đúng các dòng còn thiếu."
    )
