"""Trợ giúp chung cho test GĐ2-C C1 (quyền "Thư ký Hội đồng"). KHÔNG có ca kiểm nào ở tệp này.

- ``gan`` / ``thu_hoi``: Admin gán / thu hồi qua HTTP THẬT (router → deps → dịch vụ → CSDL).
- ``dong_quyen`` / ``vet``: đọc CSDL từ phiên RIÊNG (không qua dịch vụ).
- ``ung_dung_cong``: ứng dụng FastAPI NHỎ chỉ để đo cổng ``deps.require_review_secretary`` — C1 chưa có route Ban thư ký
  thật (route lần xét mở cho Ban thư ký từ C2). Dùng ĐÚNG dependency thật (``deps.require_review_secretary`` →
  ``check_permission`` → xác thực thật; ``database.get_db`` thật; bộ xử lý lỗi thật). Casbin thay bằng bộ cho-qua: lớp VAI
  của route Ban thư ký là Casbin ở C2; ở đây đo lớp QUYỀN GÁN. Route ``POST /thu-ky-thu/ghi`` GHI trên CÙNG phiên của cổng
  (một dòng ``entity_audit_log`` loại ``gd2c_c1_thu``) rồi commit — đúng hình dạng route ghi của Ban thư ký ở C2.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from app.database import AsyncSessionLocal
from tests.api.gd1b_lo_tro_giup import Diem, dn

P = "/api/admission-config/review-secretaries"
#: Loại thực thể của dòng nhật ký do route thử ghi — đếm để biết lần bấm của Thư ký ĐÃ ghi hay chưa.
LOAI_GHI_THU = "gd2c_c1_thu"
DUONG_GHI_THU = "/thu-ky-thu/ghi"


async def gan(client, admin: dict, user_id: int, ly_do: str = "Ban thư ký đợt 1") -> dict:
    h = await dn(client, admin)
    r = await client.post(P, headers=h, json={"user_id": user_id, "reason": ly_do})
    assert r.status_code == 201, r.text
    return r.json()


async def thu_hoi(client, admin: dict, grant_id: int, ly_do: str = "Hết nhiệm vụ") -> dict:
    h = await dn(client, admin)
    r = await client.post(f"{P}/{grant_id}/revoke", headers=h, json={"reason": ly_do})
    assert r.status_code == 200, r.text
    return r.json()


async def dong_quyen(grant_id: int) -> Optional[dict]:
    async with AsyncSessionLocal() as s:
        r = (
            await s.execute(text("SELECT * FROM admission_review_secretary_grant WHERE id = :g"), {"g": grant_id})
        ).mappings().first()
        return dict(r) if r else None


async def vet(grant_id: int) -> list:
    """Dòng ``entity_audit_log`` của một quyền (cũ trước)."""
    async with AsyncSessionLocal() as s:
        return [
            dict(r)
            for r in (
                await s.execute(
                    text(
                        "SELECT action, actor_user_id, reason FROM entity_audit_log"
                        " WHERE entity_type = 'admission_review_secretary_grant' AND entity_id = :g ORDER BY id"
                    ),
                    {"g": grant_id},
                )
            ).mappings().all()
        ]


async def so_lan_ghi_thu(user_id: int) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                text("SELECT count(*) FROM entity_audit_log WHERE entity_type = :t AND actor_user_id = :u"),
                {"t": LOAI_GHI_THU, "u": user_id},
            )
        ).scalar_one()


class _ChoQuaHet:
    """Bộ Casbin cho-qua — CHỈ cho ứng dụng thử (lớp vai của route Ban thư ký đến ở C2)."""

    def enforce(self, *a, **kw) -> bool:
        return True


def ung_dung_cong(diem: Optional[Diem] = None):
    """Ứng dụng thử: ``POST /thu-ky-thu/ghi`` = cổng THẬT + một câu ghi trên CÙNG phiên + commit. Trả ``{khoa_quyen}``:
    giao dịch của route (đo TRƯỚC câu ghi) đang giữ khoá ``ROW SHARE`` trên bảng quyền — dấu vết CSDL của ``SELECT … FOR
    SHARE`` chạy trong CHÍNH giao dịch ấy. ``diem``: dừng sau khi đo, trước câu ghi (giữ nguyên mọi khoá của cổng)."""
    from fastapi import Depends, FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from app import database, models
    from app.core import deps
    from app.middleware import register_exception_handlers
    from app.services.audit_service import log_audit

    app = FastAPI()
    register_exception_handlers(app)
    app.state.enforcer = _ChoQuaHet()

    @app.post(DUONG_GHI_THU)
    async def ghi_thu(
        user: models.User = Depends(deps.require_review_secretary),
        db: AsyncSession = Depends(database.get_db),
    ):
        khoa = (
            await db.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'relation'"
                    " AND relation = CAST('admission_review_secretary_grant' AS regclass) AND mode = 'RowShareLock'"
                )
            )
        ).scalar_one()
        if diem is not None:
            await diem.cho()
        await log_audit(db, LOAI_GHI_THU, user.id, "ghi_thu", actor_user_id=user.id, source="api")
        await db.commit()
        return {"khoa_quyen": khoa > 0}

    return app
