"""Admission Freeze Middleware (T0-2 cold-cutover prerequisite).

When ``settings.ADMISSION_FROZEN`` is True, this middleware rejects mutating
HTTP methods (POST/PUT/PATCH/DELETE) on the admission API path prefixes with
503 Service Unavailable. Read methods (GET/HEAD/OPTIONS) pass through so
officers can still inspect existing data during the maintenance window.

Defense-in-depth pair with the Nginx admission block (T0-3) shipped later:
Nginx is the edge layer; this middleware is the application-level fallback
for traffic that bypasses Nginx (internal Docker, healthchecks, smoke tests).

Reload semantics: ``Settings`` nạp MỘT LẦN lúc import module
(``app/config.py``), và biến môi trường được nướng vào container lúc **TẠO**.

    ⚠️ KHÔNG dùng ``docker compose restart backend``: ``restart`` không đọc lại
    ``env_file``/``.env``, nên nó trả rc=0 mà cần gạt KHÔNG đổi trạng thái.
    Phải DỰNG LẠI container::

        docker compose -f docker-compose.yml --env-file .env.production \
            --profile production up -d --no-deps --wait backend

Nghiệm thu bằng cặp request thật 200 ↔ 503, không bằng ``nginx -t`` + reload.
Xem ``Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md`` §6.1 và
``tests-e2e/admission-freeze/``.
"""

from typing import Final, Iterable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings

# --- NGUỒN CHUẨN: ba thứ ĐỘC LẬP phải khớp nhau -------------------------------
#
# Bản trước ghim ba tiền tố "verified against ... HEAD 2c57e5d6" — đúng ở thời
# điểm ấy. Các router ``/api/v2/`` ra đời sau và không ai rà lại, nên cần gạt
# đóng băng KHÔNG phủ 39 route ghi v2 ở CẢ hai tầng (middleware + nginx).
# Nightly trên main@0c3031d7 bắt được điều này qua
# ``test_no_admission_route_escapes_freeze_coverage``.
#
# Để lỗi đó không tái diễn qua một nhánh anh em, ba thứ dưới đây được khai báo
# riêng và ``tests/middleware/test_admission_freeze.py`` bắt chúng phải khớp:
#
#   1. ADMISSION_ROUTER_MODULES — AI sở hữu miền tuyển sinh (theo module, không
#      theo chuỗi "admission" trong path: ``/api/v2/admin/rounds`` và
#      ``/api/v2/admin/priority-config`` không chứa chữ đó).
#   2. FROZEN_PREFIXES — thứ hai tầng THẬT SỰ dùng để chặn.
#   3. ADMISSION_WRITE_ROUTES — danh mục (method, path) đã rà tay.
#
# Thêm một route ghi vào bất kỳ router tuyển sinh nào mà quên cập nhật ⇒ ĐỎ.
# Một tiền tố hút nhầm route KHÔNG thuộc tuyển sinh ⇒ cũng ĐỎ.

ADMISSION_ROUTER_MODULES: Final[frozenset[str]] = frozenset(
    {
        "app.routers.admissions",
        "app.routers.admissions_v2",
        "app.routers.admissions_magic_link",
        "app.routers.admission_config",
        "app.routers.admission_paths",
        "app.routers.admin_backfill",
        "app.routers.admin_priority_config",
        "app.routers.admin_v2_admission_round",
        "app.routers.admin_v2_path_subject_group",
        # Hai router dưới đây KHÔNG mang tên tuyển sinh nhưng gắn đường ghi vào
        # miền tuyển sinh; cả hai đã bị đóng băng sẵn qua tiền tố v1.
        "app.routers.document_groups",
        "app.routers.enrollment_letters",
    }
)

# THẾ GIỚI ĐÓNG. Chỉ khai ``ADMISSION_ROUTER_MODULES`` là chưa đủ: một router
# MỚI ở một tiền tố MỚI (ví dụ ``admissions_v3`` phục vụ ``/api/v3/admissions``)
# sẽ không thuộc tập tuyển sinh, không nằm dưới tiền tố nào, nên MỌI phép kiểm
# đều "bỏ qua" nó và xanh — đúng hình dạng đã sinh ra sự cố v2.
#
# Vì vậy mọi module CÓ route ghi phải thuộc ĐÚNG MỘT trong hai tập. Module chưa
# phân loại làm ĐỎ, buộc người thêm router phải quyết định nó có thuộc miền
# tuyển sinh hay không.
NON_ADMISSION_ROUTER_MODULES: Final[frozenset[str]] = frozenset(
    {
        "app.routers.accounting",
        "app.routers.admin.cache",
        "app.routers.admin.config",
        "app.routers.admin.deleted_items",
        "app.routers.admin.installment_plans",
        "app.routers.admin.organization",
        "app.routers.admin.pipeline",
        "app.routers.admin.roles",
        "app.routers.admin.sync",
        "app.routers.admin.system",
        "app.routers.admin.tuition_discount",
        "app.routers.admin.users",
        "app.routers.admin_v2_casbin",
        "app.routers.admin_v2_system_config",
        "app.routers.admin_vn_locality",
        "app.routers.admin_vn_school",
        "app.routers.auth",
        "app.routers.collaborators",
        "app.routers.commissions",
        "app.routers.config_data",
        "app.routers.fees",
        "app.routers.invoices",
        "app.routers.kpi_config",
        "app.routers.kpi_planning",
        "app.routers.leads",
        "app.routers.notification_consents",
        "app.routers.notification_delivery_ops",
        "app.routers.notification_preferences",
        "app.routers.notification_rules",
        "app.routers.notification_templates",
        "app.routers.notifications",
        "app.routers.officer",
        "app.routers.organization",
        "app.routers.overpayments",
        "app.routers.payments",
        "app.routers.profile",
        "app.routers.refunds",
        "app.routers.reopen_requests",
        "app.routers.security",
        "app.routers.sessions",
        "app.routers.sms_campaigns",
        "app.routers.sms_consult",
        "app.routers.sms_contacts",
        "app.routers.sms_export",
        "app.routers.sms_public",
        "app.routers.sms_reports",
        "app.routers.zalo_bot_link",
        "app.routers.zalo_bot_webhooks",
        "app.routers.zalo_webhooks",
    }
)

FROZEN_PREFIXES: Final[tuple[str, ...]] = (
    # v1 — giữ nguyên hành vi cũ.
    "/api/admissions",
    "/api/admission-config",
    # Không có route ghi nào hôm nay; giữ để một route ghi thêm sau vẫn đóng.
    "/api/public/admissions",
    # v2 — phần bị bỏ sót.
    "/api/v2/admissions",
    "/api/v2/admin/admission-backfill-exceptions",
    "/api/v2/admin/admission-paths",
    "/api/v2/admin/path-subject-group-configs",
    "/api/v2/admin/priority-config",
    "/api/v2/admin/rounds",
    "/api/v2/admin/years",
)

# Rà từ bảng route thật của ``fastapi_app`` trên main@0c3031d7 (633 route-method,
# 347 đường ghi). ĐỪNG sửa tay: chạy lại kiểm kê rồi cập nhật cả khối.
ADMISSION_WRITE_ROUTES: Final[tuple[tuple[str, str], ...]] = (
    ("POST", "/api/admission-config/criteria"),
    ("DELETE", "/api/admission-config/criteria/{criteria_id}"),
    ("PUT", "/api/admission-config/criteria/{criteria_id}"),
    ("POST", "/api/admission-config/document-groups"),
    ("PUT", "/api/admission-config/document-groups/shared/{offering_type_id}"),
    ("POST", "/api/admission-config/document-groups/shared/{offering_type_id}/preview"),
    ("DELETE", "/api/admission-config/document-groups/{group_id}"),
    ("PUT", "/api/admission-config/document-groups/{group_id}"),
    ("POST", "/api/admission-config/methods"),
    ("DELETE", "/api/admission-config/methods/{method_id}"),
    ("PUT", "/api/admission-config/methods/{method_id}"),
    ("POST", "/api/admission-config/paths"),
    ("PUT", "/api/admission-config/paths/{path_id}"),
    ("POST", "/api/admission-config/paths/{path_id}/activate"),
    ("POST", "/api/admission-config/paths/{path_id}/archive"),
    ("PUT", "/api/admission-config/paths/{path_id}/criteria"),
    ("POST", "/api/admission-config/paths/{path_id}/deactivate"),
    ("PUT", "/api/admission-config/paths/{path_id}/documents"),
    ("POST", "/api/admission-config/scoring/preview"),
    ("POST", "/api/admission-config/subject-groups"),
    ("DELETE", "/api/admission-config/subject-groups/{group_id}"),
    ("PUT", "/api/admission-config/subject-groups/{group_id}"),
    ("POST", "/api/admission-config/subject-groups/{group_id}/subjects"),
    ("DELETE", "/api/admission-config/subject-groups/{group_id}/subjects/{subject_id}"),
    ("PUT", "/api/admission-config/subject-groups/{group_id}/subjects/{subject_id}"),
    ("POST", "/api/admission-config/subjects"),
    ("DELETE", "/api/admission-config/subjects/{subject_id}"),
    ("PUT", "/api/admission-config/subjects/{subject_id}"),
    ("POST", "/api/admissions"),
    ("POST", "/api/admissions/bulk/approve"),
    ("POST", "/api/admissions/bulk/assign"),
    ("POST", "/api/admissions/bulk/reject"),
    ("POST", "/api/admissions/confirm/{token}"),
    ("DELETE", "/api/admissions/{profile_id}"),
    ("PUT", "/api/admissions/{profile_id}"),
    ("POST", "/api/admissions/{profile_id}/approve"),
    ("POST", "/api/admissions/{profile_id}/cancel-withdrawal"),
    ("POST", "/api/admissions/{profile_id}/claim"),
    ("POST", "/api/admissions/{profile_id}/documents/{doc_code}/graduation-proof"),
    ("POST", "/api/admissions/{profile_id}/documents/{doc_code}/paper-submitted"),
    ("POST", "/api/admissions/{profile_id}/documents/{doc_code}/reject"),
    ("POST", "/api/admissions/{profile_id}/documents/{doc_code}/reset"),
    ("POST", "/api/admissions/{profile_id}/documents/{doc_code}/upload"),
    ("PATCH", "/api/admissions/{profile_id}/documents/{doc_code}/verify-format"),
    ("POST", "/api/admissions/{profile_id}/drop"),
    ("POST", "/api/admissions/{profile_id}/enroll"),
    ("POST", "/api/admissions/{profile_id}/enrollment-letter"),
    ("POST", "/api/admissions/{profile_id}/finalize"),
    ("POST", "/api/admissions/{profile_id}/minor-correction"),
    ("POST", "/api/admissions/{profile_id}/override"),
    ("POST", "/api/admissions/{profile_id}/record-fee-payment"),
    ("POST", "/api/admissions/{profile_id}/reject"),
    ("POST", "/api/admissions/{profile_id}/request-revision"),
    ("POST", "/api/admissions/{profile_id}/resubmit"),
    ("POST", "/api/admissions/{profile_id}/send-confirmation"),
    ("POST", "/api/admissions/{profile_id}/send-magic-link"),
    ("POST", "/api/admissions/{profile_id}/submit"),
    ("POST", "/api/admissions/{profile_id}/unclaim"),
    ("POST", "/api/admissions/{profile_id}/withdraw"),
    ("POST", "/api/v2/admin/admission-backfill-exceptions/bulk-resolve"),
    ("PATCH", "/api/v2/admin/admission-backfill-exceptions/{exception_id}/resolve"),
    ("PATCH", "/api/v2/admin/admission-paths/{admission_path_id}/quota"),
    ("POST", "/api/v2/admin/admission-paths/{admission_path_id}/subject-group-configs"),
    ("DELETE", "/api/v2/admin/path-subject-group-configs/{config_id}"),
    ("PATCH", "/api/v2/admin/path-subject-group-configs/{config_id}"),
    ("POST", "/api/v2/admin/path-subject-group-configs/{config_id}/items"),
    ("DELETE", "/api/v2/admin/path-subject-group-configs/{config_id}/items/{item_id}"),
    ("PATCH", "/api/v2/admin/path-subject-group-configs/{config_id}/items/{item_id}"),
    ("DELETE", "/api/v2/admin/priority-config/areas/{area_id}"),
    ("PATCH", "/api/v2/admin/priority-config/areas/{area_id}"),
    ("POST", "/api/v2/admin/priority-config/clone"),
    ("DELETE", "/api/v2/admin/priority-config/objects/{object_id}"),
    ("PATCH", "/api/v2/admin/priority-config/objects/{object_id}"),
    ("POST", "/api/v2/admin/priority-config/seed-defaults"),
    ("POST", "/api/v2/admin/priority-config/years/{academic_year}/areas"),
    ("POST", "/api/v2/admin/priority-config/years/{academic_year}/objects"),
    ("DELETE", "/api/v2/admin/rounds/{round_id}"),
    ("PATCH", "/api/v2/admin/rounds/{round_id}"),
    ("POST", "/api/v2/admin/rounds/{round_id}/extend"),
    ("POST", "/api/v2/admin/rounds/{round_id}/restore"),
    (
        "POST",
        "/api/v2/admin/rounds/{target_round_id}/clone-paths-from/{source_round_id}",
    ),
    ("POST", "/api/v2/admin/years/{academic_year}/rounds"),
    ("POST", "/api/v2/admin/years/{academic_year}/rounds/bulk-create"),
    ("POST", "/api/v2/admissions/magic-link/{action}/{token}"),
    ("POST", "/api/v2/admissions/{profile_id}/admin-rollback"),
    ("POST", "/api/v2/admissions/{profile_id}/choices"),
    ("DELETE", "/api/v2/admissions/{profile_id}/choices/{choice_id}"),
    ("PATCH", "/api/v2/admissions/{profile_id}/choices/{choice_id}"),
    ("PATCH", "/api/v2/admissions/{profile_id}/choices/{choice_id}/scores"),
    ("POST", "/api/v2/admissions/{profile_id}/override-priority-kv"),
    ("POST", "/api/v2/admissions/{profile_id}/preview-priority-kv"),
    ("DELETE", "/api/v2/admissions/{profile_id}/priority-evidence/{sub_code}"),
    ("POST", "/api/v2/admissions/{profile_id}/priority-evidence/{sub_code}/upload"),
    ("PATCH", "/api/v2/admissions/{profile_id}/priority-objects/{sub_code}/reject"),
    ("PATCH", "/api/v2/admissions/{profile_id}/priority-objects/{sub_code}/verify"),
    ("POST", "/api/v2/admissions/{profile_id}/publish-result"),
    ("POST", "/api/v2/admissions/{profile_id}/waitlist-promote"),
    ("POST", "/api/v2/admissions/{profile_id}/waitlist-reject"),
)

FROZEN_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AdmissionFreezeMiddleware(BaseHTTPMiddleware):
    """Block admission writes with 503 while ``settings.ADMISSION_FROZEN`` is True."""

    def __init__(self, app, *, prefixes: Iterable[str] = FROZEN_PREFIXES) -> None:
        super().__init__(app)
        self._prefixes: tuple[str, ...] = tuple(prefixes)

    async def dispatch(self, request: Request, call_next):
        if settings.ADMISSION_FROZEN and request.method in FROZEN_METHODS:
            path = request.url.path
            matched = next(
                (prefix for prefix in self._prefixes if _path_under(path, prefix)),
                None,
            )
            if matched is not None:
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "detail": (
                            "Admission intake is frozen for maintenance. "
                            "Please retry after the maintenance window completes."
                        ),
                        "code": "ADMISSION_FROZEN",
                        "frozen_prefix": matched,
                    },
                )
        return await call_next(request)


def _path_under(path: str, prefix: str) -> bool:
    # Path-segment match so `/api/admissionsfoo` does not match `/api/admissions`.
    return path == prefix or path.startswith(prefix + "/")
