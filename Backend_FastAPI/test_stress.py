# test_stress.py
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from time import sleep  # Thêm sleep để chờ worker xử lý (cách đơn giản)

# Thêm đường dẫn dự án
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

# ✅ THÊM IMPORT: delete, case
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

try:
    from app import models
    from app.celery_utils import process_automatic_lead_assignment_task
    from app.config import settings
    from app.database import engine
    from app.models.base import Base as AppBase

    try:
        from casbin_async_sqlalchemy_adapter import Base as CasbinBase
    except ImportError:
        CasbinBase = None
    from app.security import get_password_hash
except ImportError as e:
    print(f"Lỗi Import: {e}")
    print("Hãy chắc chắn bạn đang chạy script này từ thư mục gốc Backend_FastAPI")
    sys.exit(1)

# === CẤU HÌNH STRESS TEST ===
LEAD_COUNT = 100
# ✅ TĂNG SỐ OFFICER VÀ CAPACITY
NUM_OFFICERS = 10
OFFICER_START_ID = 201  # Bắt đầu ID officer test cao hơn để tránh trùng
# Phân bổ capacity, ví dụ: 5 người capacity 8, 5 người capacity 7 (Tổng 75)
OFFICER_CAPACITIES = [9] * 5 + [8] * 5
# Đảm bảo OFFICERS_CAPACITIES có đủ NUM_OFFICERS phần tử
assert (
    len(OFFICER_CAPACITIES) == NUM_OFFICERS
), "OFFICER_CAPACITIES length must match NUM_OFFICERS"

UNIT_ID_TO_TEST = 1  # Unit 1
UNIT_ID_OTHER = 2  # Unit 2 (Vẫn giữ để test độc lập)
MAJOR_ID_TO_TEST = 1
INITIAL_STATUS_ID = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
ASSIGNED_STATUS_ID = settings.DEFAULT_ASSIGNED_LEAD_STATUS
UNASSIGNED_STATUS_ID = settings.DEFAULT_UNASSIGNED_LEAD_STATUS
LOST_STATUS_ID = settings.DEFAULT_LOST_LEAD_STATUS_ID
STAGE_A_ID = "STAGE_A_W"  # Worker Stage A
STAGE_LOST_ID = "STAGE_L_W"  # Worker Stage Lost

# Password hash cho tất cả user test
TEST_PASSWORD_HASH = get_password_hash("ValidPassword123!")

# ✅ THỜI GIAN CHỜ PHÂN TÍCH KẾT QUẢ (giây) - Cần điều chỉnh!
RESULTS_ANALYSIS_DELAY_SECONDS = 45
# ==============================

log = logging.getLogger("test_stress")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

# Tạo SessionLocal mới cho script
StressSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ✅ HÀM MỚI: Xóa dữ liệu test cũ
async def clear_existing_test_data(session: AsyncSession):
    """Xóa dữ liệu cũ liên quan đến stress test để đảm bảo môi trường sạch."""
    log.info("Clearing existing stress test data...")

    # Xác định các ID officer sẽ được tạo
    officer_ids_to_clear = list(
        range(OFFICER_START_ID, OFFICER_START_ID + NUM_OFFICERS)
    )
    # Thêm cả officer_other nếu có (ID 104 cũ) - hoặc bỏ nếu không cần
    officer_ids_to_clear.append(104)  # Thêm officer cũ từ unit khác
    # Thêm các ID cũ nếu cần (101, 102, 103)
    officer_ids_to_clear.extend([101, 102, 103])

    # 1. Xóa Assignment Logs liên quan đến officers hoặc leads cũ
    # (Xóa theo officer ID trước để tránh lỗi FK khi xóa Lead/User)
    await session.execute(
        delete(models.AssignmentLog).where(
            models.AssignmentLog.officer_id.in_(officer_ids_to_clear)
        )
    )
    # Xóa log của các lead tạo bởi stress test cũ (nếu có cách xác định, ví dụ qua source)
    await session.execute(
        delete(models.AssignmentLog).where(
            models.AssignmentLog.lead.has(models.Lead.source == "stress_test")
        )
    )

    # 2. Xóa Leads tạo bởi stress test
    await session.execute(
        delete(models.Lead).where(models.Lead.source == "stress_test")
    )
    # Xóa cả leads cũ của officer_busy (nếu bạn muốn sạch hoàn toàn)
    await session.execute(
        delete(models.Lead).where(
            models.Lead.assigned_officer_id.in_([102])
        )  # ID cũ của officer_busy
    )

    # 3. Xóa Officers được tạo bởi stress test
    await session.execute(
        delete(models.User).where(models.User.id.in_(officer_ids_to_clear))
    )

    # 4. Xóa Majors & Units (Cẩn thận hơn, chỉ xóa nếu chắc chắn)
    await session.execute(
        delete(models.Major).where(models.Major.id == MAJOR_ID_TO_TEST)
    )
    await session.execute(
        delete(models.OrganizationUnit).where(
            models.OrganizationUnit.id.in_([UNIT_ID_TO_TEST, UNIT_ID_OTHER])
        )
    )

    # 5. Xóa Statuses & Stages (Cẩn thận hơn)
    await session.execute(
        delete(models.ConsultationStatus).where(
            models.ConsultationStatus.id.in_(
                [
                    INITIAL_STATUS_ID,
                    ASSIGNED_STATUS_ID,
                    UNASSIGNED_STATUS_ID,
                    LOST_STATUS_ID,
                ]
            )
        )
    )
    await session.execute(
        delete(models.PipelineStage).where(
            models.PipelineStage.id.in_([STAGE_A_ID, STAGE_LOST_ID])
        )
    )

    await session.commit()  # Commit các thay đổi xóa
    log.info("Finished clearing data.")


async def seed_database_for_stress_test():
    """
    Tạo các bảng (nếu cần) VÀ seed dữ liệu cơ bản.
    Đã thêm bước xóa dữ liệu cũ.
    Tạo 10 officers với capacity được định nghĩa.
    """
    log.info("Connecting to DB to check/create tables and seed data...")

    # --- Tạo bảng (nếu chưa có) ---
    async with engine.begin() as conn:
        await conn.run_sync(AppBase.metadata.create_all)
        if CasbinBase:
            await conn.run_sync(CasbinBase.metadata.create_all)

    async with StressSessionLocal() as session:
        # --- XÓA DỮ LIỆU CŨ TRƯỚC ---
        await clear_existing_test_data(session)

        # --- Bắt đầu seed mới ---
        log.info("Seeding database with required data...")
        async with session.begin():  # Bắt đầu transaction mới cho việc seed

            # 1. Seed Units & Major
            unit1 = models.OrganizationUnit(
                id=UNIT_ID_TO_TEST, name="Worker Test Unit 1", type="Faculty"
            )
            unit2 = models.OrganizationUnit(
                id=UNIT_ID_OTHER, name="Worker Test Unit 2", type="Faculty"
            )  # Vẫn tạo unit khác
            major1 = models.Major(
                id=MAJOR_ID_TO_TEST,
                name="Worker Test Major 1",
                code="WTM1",
                unit_id=UNIT_ID_TO_TEST,
            )
            session.add_all([unit1, unit2, major1])

            # 2. Seed Stages & Statuses
            stage_a = models.PipelineStage(
                id=STAGE_A_ID, name="Worker Stage A", order=10
            )
            stage_lost = models.PipelineStage(
                id=STAGE_LOST_ID, name="Worker Stage Lost", order=99
            )
            session.add_all([stage_a, stage_lost])

            statuses_to_create = [
                models.ConsultationStatus(
                    id=INITIAL_STATUS_ID,
                    name="Initial Worker",
                    color_code="#AAAAAA",
                    stage_id=STAGE_A_ID,
                ),
                models.ConsultationStatus(
                    id=ASSIGNED_STATUS_ID,
                    name="Assigned Worker",
                    color_code="#BBBBBB",
                    stage_id=STAGE_A_ID,
                ),
                models.ConsultationStatus(
                    id=UNASSIGNED_STATUS_ID,
                    name="Unassigned Worker",
                    color_code="#CCCCCC",
                    stage_id=STAGE_A_ID,
                ),
                models.ConsultationStatus(
                    id=LOST_STATUS_ID,
                    name="Lost Worker",
                    color_code="#DDDDDD",
                    stage_id=STAGE_LOST_ID,
                ),
            ]
            session.add_all(statuses_to_create)

            # 3. ✅ Seed 10 Officers (Thay thế code cũ)
            officers_to_add = []
            for i in range(NUM_OFFICERS):
                officer_id = OFFICER_START_ID + i
                capacity = OFFICER_CAPACITIES[i]
                officers_to_add.append(
                    models.User(
                        id=officer_id,
                        username=f"stress_officer_{i+1}",
                        email=f"stress{i+1}@worker.com",
                        unit_id=UNIT_ID_TO_TEST,
                        max_capacity=capacity,
                        last_assigned_at=None,
                        role="officer",
                        status="active",
                        availability_status="available",
                        password_hash=TEST_PASSWORD_HASH,
                    )
                )
            # Thêm officer cho unit khác (nếu cần)
            officer_other = models.User(
                id=104,
                username="worker_other",
                email="other@worker.com",
                unit_id=UNIT_ID_OTHER,
                max_capacity=5,
                last_assigned_at=None,
                role="officer",
                status="active",
                availability_status="available",
                password_hash=TEST_PASSWORD_HASH,
            )
            session.add_all(officers_to_add)
            session.add(officer_other)
            log.info(
                f"Seeded {len(officers_to_add)} officers for Unit {UNIT_ID_TO_TEST} with capacities: {OFFICER_CAPACITIES}"
            )

            # 4. (Bỏ qua) Seed Leads cho Officer Busy cũ (không cần nữa)

            log.info("Database seeding complete.")
            # Kết thúc transaction seed
        return True  # Luôn trả về True vì đã xóa và seed lại


async def create_leads_in_db():
    """Tạo LEAD_COUNT leads mới (sau khi đã seed data)."""
    log.info(f"Creating {LEAD_COUNT} new leads for stress test...")
    tasks_to_dispatch = []
    lead_source = "stress_test"  # Đặt source để dễ truy vấn sau

    async with StressSessionLocal() as session:
        async with session.begin():
            # Lấy status ban đầu
            status_obj = await session.get(models.ConsultationStatus, INITIAL_STATUS_ID)
            if not status_obj:
                log.error(
                    f"FATAL: Initial status {INITIAL_STATUS_ID} not found after seeding."
                )
                return []

            leads_to_add = []
            for i in range(LEAD_COUNT):
                lead = models.Lead(
                    # ID sẽ tự tăng từ 1 vì đã clear data
                    full_name=f"Stress Lead {i+1}",
                    email=f"stress{i+1}@example.com",
                    phone=f"091000{i+1:04d}",  # Đổi format phone chút
                    source=lead_source,  # Gán source
                    unit_id=UNIT_ID_TO_TEST,
                    major_id=MAJOR_ID_TO_TEST,
                    status=INITIAL_STATUS_ID,  # Trạng thái ban đầu
                    consultation_status_id=INITIAL_STATUS_ID,
                    pipeline_stage_id=status_obj.stage_id,
                    assigned_officer_id=None,
                )
                leads_to_add.append(lead)

            session.add_all(leads_to_add)
            await session.flush()  # Flush để lấy IDs
            tasks_to_dispatch = [
                lead.id for lead in leads_to_add if lead.id is not None
            ]

        log.info(
            f"Created {len(tasks_to_dispatch)} leads. IDs from {tasks_to_dispatch[0]} to {tasks_to_dispatch[-1]}"
        )

    return tasks_to_dispatch


async def dispatch_tasks(lead_ids):
    """Gửi tasks tới Celery"""
    log.info(f"Dispatching {len(lead_ids)} tasks to Celery...")
    dispatched_count = 0
    for lead_id in lead_ids:
        try:
            process_automatic_lead_assignment_task.delay(lead_id)
            dispatched_count += 1
        except Exception as e:
            log.error(f"Failed to dispatch task for lead_id: {lead_id}", exc_info=True)
    log.info(f"Finished dispatching {dispatched_count}/{len(lead_ids)} tasks.")


# ✅ HÀM MỚI: Phân tích kết quả
async def analyze_results():
    """Truy vấn DB và thống kê kết quả phân công sau khi chạy stress test."""
    log.info(
        f"Waiting {RESULTS_ANALYSIS_DELAY_SECONDS} seconds for workers to process tasks..."
    )
    await asyncio.sleep(RESULTS_ANALYSIS_DELAY_SECONDS)  # Chờ worker xử lý
    log.info("Analyzing assignment results from database...")

    total_leads = 0
    assigned_leads = 0
    unassigned_leads = 0
    other_status_leads = 0
    assignment_counts = {}  # {officer_id: count}

    # Xác định ID các officer trong unit test
    officer_ids_in_unit = list(range(OFFICER_START_ID, OFFICER_START_ID + NUM_OFFICERS))

    async with StressSessionLocal() as session:
        # Đếm tổng số lead được tạo bởi test này
        total_leads_result = await session.execute(
            select(func.count(models.Lead.id)).where(
                models.Lead.source == "stress_test"
            )
        )
        total_leads = total_leads_result.scalar_one_or_none() or 0

        if total_leads == 0:
            log.warning(
                "No leads found with source 'stress_test'. Cannot analyze results."
            )
            return

        # Đếm số lead được assign cho các officer trong unit test
        assigned_leads_result = await session.execute(
            select(func.count(models.Lead.id)).where(
                models.Lead.source == "stress_test",
                models.Lead.assigned_officer_id.in_(officer_ids_in_unit),
                # Có thể thêm điều kiện status == ASSIGNED_STATUS_ID nếu muốn chặt chẽ hơn
                # models.Lead.status == ASSIGNED_STATUS_ID
            )
        )
        assigned_leads = assigned_leads_result.scalar_one_or_none() or 0

        # Đếm số lead ở trạng thái unassigned
        unassigned_leads_result = await session.execute(
            select(func.count(models.Lead.id)).where(
                models.Lead.source == "stress_test",
                models.Lead.status == UNASSIGNED_STATUS_ID,
            )
        )
        unassigned_leads = unassigned_leads_result.scalar_one_or_none() or 0

        # Đếm số lead vẫn ở trạng thái ban đầu (có thể chưa được xử lý hoặc lỗi khác)
        initial_state_leads_result = await session.execute(
            select(func.count(models.Lead.id)).where(
                models.Lead.source == "stress_test",
                models.Lead.status == INITIAL_STATUS_ID,
                models.Lead.assigned_officer_id.is_(None),  # Chưa gán
            )
        )
        initial_state_leads = initial_state_leads_result.scalar_one_or_none() or 0

        # Tính các trạng thái khác (nếu có)
        other_status_leads = (
            total_leads - assigned_leads - unassigned_leads - initial_state_leads
        )

        # Lấy số lượng lead được gán cho mỗi officer
        assignment_counts_result = await session.execute(
            select(
                models.Lead.assigned_officer_id,
                func.count(models.Lead.id).label("count"),
            )
            .where(
                models.Lead.source == "stress_test",
                models.Lead.assigned_officer_id.isnot(None),
            )
            .group_by(models.Lead.assigned_officer_id)
            .order_by(models.Lead.assigned_officer_id)
        )
        assignment_counts = {
            row.assigned_officer_id: row.count for row in assignment_counts_result
        }

    # In kết quả
    log.info("--- Stress Test Results ---")
    log.info(f"Total Leads Created: {total_leads}")
    log.info(
        f"Leads Assigned (Unit {UNIT_ID_TO_TEST}): {assigned_leads} ({assigned_leads/total_leads:.1%})"
    )
    log.info(f"Leads Unassigned ({UNASSIGNED_STATUS_ID}): {unassigned_leads}")
    log.info(f"Leads Still Initial ({INITIAL_STATUS_ID}): {initial_state_leads}")
    if other_status_leads > 0:
        log.warning(f"Leads in Other Statuses: {other_status_leads}")

    log.info("Assignments per Officer:")
    for officer_id in officer_ids_in_unit:
        count = assignment_counts.get(officer_id, 0)
        # Lấy capacity tương ứng (cẩn thận index)
        capacity = OFFICER_CAPACITIES[officer_id - OFFICER_START_ID]
        log.info(f"  - Officer {officer_id}: {count} / {capacity}")

    if 104 in assignment_counts:  # Check officer unit khác
        log.info(f"  - Officer {104} (Unit {UNIT_ID_OTHER}): {assignment_counts[104]}")

    log.info("--- End of Results ---")

    # Kiểm tra mục tiêu assignment
    target_assigned = int(LEAD_COUNT * 0.7)
    if assigned_leads >= target_assigned:
        log.info(
            f"✅ Assignment goal met ({assigned_leads}/{LEAD_COUNT} assigned >= {target_assigned})"
        )
    else:
        log.warning(
            f"⚠️ Assignment goal NOT met ({assigned_leads}/{LEAD_COUNT} assigned < {target_assigned})"
        )
        log.warning(
            "   Consider increasing RESULTS_ANALYSIS_DELAY_SECONDS or checking worker logs for errors."
        )


async def main():
    if settings.APP_ENV != "test":
        log.error(
            f"LỖI: APP_ENV không phải là 'test' (hiện tại là '{settings.APP_ENV}')."
        )
        log.error("Vui lòng đặt biến môi trường: export APP_ENV=test")
        return

    log.info(f"APP_ENV='test'. Target DB: {settings.DATABASE_URL[:50]}...")
    log.info(f"Target Broker: {settings.CELERY_BROKER_URL}")
    log.info(
        f"Lead Count: {LEAD_COUNT}, Num Officers: {NUM_OFFICERS}, Capacities: {OFFICER_CAPACITIES}"
    )

    try:
        # 1. Xóa dữ liệu cũ VÀ seed data mới
        ready = await seed_database_for_stress_test()

        if not ready:
            log.error("Database seeding failed. Aborting stress test.")
            await engine.dispose()
            return

        # 2. Tạo Leads mới
        lead_ids = await create_leads_in_db()

        # 3. Gửi Tasks
        if lead_ids:
            await dispatch_tasks(lead_ids)
            log.info("Stress test initiated. Workers processing tasks...")

            # 4. ✅ PHÂN TÍCH KẾT QUẢ
            await analyze_results()

        else:
            log.warning("No leads were created, stopping stress test.")

    except Exception as e:
        log.error(f"Lỗi nghiêm trọng trong quá trình main(): {e}", exc_info=True)
    finally:
        await engine.dispose()
        log.info("Script finished. Engine disposed.")


if __name__ == "__main__":
    asyncio.run(main())
