"""
Update FSM data from specification tables.
Run: python scripts/update_fsm_data.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, delete
from app.database import AsyncSessionLocal
from app import models


# =============================================================================
# BẢNG 1: consultation_status
# =============================================================================
CONSULTATION_STATUS_DATA = [
    {"id": "sts00", "code": "NOT_CONTACTED", "name": "Chưa tiếp cận", "phase": "consultation", "stage_id": "stg01", "status_type": "transition", "selectable_mode": "user", "outcome_type": "neutral", "is_final": False, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Lead mới tạo, chưa có tương tác"},
    {"id": "sts01", "code": "NO_ANSWER", "name": "Không nghe máy", "phase": "universal", "stage_id": None, "status_type": "activity", "selectable_mode": "user", "outcome_type": "neutral", "is_final": False, "is_universal": True, "updates_pipeline": False, "counts_for_funnel": False, "description": "Gọi điện không bắt máy"},
    {"id": "sts02", "code": "CONTACTED", "name": "Đã kết nối liên hệ", "phase": "consultation", "stage_id": "stg01", "status_type": "transition", "selectable_mode": "user", "outcome_type": "neutral", "is_final": False, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Đã liên hệ được"},
    {"id": "sts03", "code": "INTERESTED", "name": "Có nhu cầu tìm hiểu", "phase": "consultation", "stage_id": "stg02", "status_type": "transition", "selectable_mode": "user", "outcome_type": "neutral", "is_final": False, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Lead có quan tâm"},
    {"id": "sts04", "code": "CONSULT_REJECTED", "name": "Từ chối tư vấn", "phase": "consultation", "stage_id": "stg02", "status_type": "transition", "selectable_mode": "user", "outcome_type": "negative", "is_final": True, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Từ chối hoàn toàn"},
    {"id": "sts05", "code": "CALLBACK_LATER", "name": "Hẹn liên hệ lại", "phase": "consultation", "stage_id": "stg02", "status_type": "transition", "selectable_mode": "user", "outcome_type": "neutral", "is_final": False, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Hẹn gọi lại"},
    {"id": "sts06", "code": "CONSULT_ACCEPTED", "name": "Đồng ý tư vấn", "phase": "consultation", "stage_id": "stg02", "status_type": "transition", "selectable_mode": "user", "outcome_type": "positive", "is_final": False, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Đồng ý bước tư vấn"},
    {"id": "sts07", "code": "APPLICATION_RECEIVED", "name": "Đã tiếp nhận hồ sơ", "phase": "admission", "stage_id": "stg03", "status_type": "transition", "selectable_mode": "user", "outcome_type": "neutral", "is_final": False, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Đã tạo hồ sơ xét tuyển"},
    {"id": "sts17", "code": "APPLICATION_REVISION", "name": "Yêu cầu bổ sung hồ sơ", "phase": "admission", "stage_id": "stg03", "status_type": "transition", "selectable_mode": "user", "outcome_type": "neutral", "is_final": False, "is_universal": False, "updates_pipeline": False, "counts_for_funnel": False, "description": "Yêu cầu nộp thêm giấy tờ"},
    {"id": "sts16", "code": "APPLICATION_REJECTED", "name": "Hồ sơ không đạt yêu cầu", "phase": "admission", "stage_id": "stg04", "status_type": "transition", "selectable_mode": "role", "outcome_type": "negative", "is_final": True, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Hồ sơ bị từ chối"},
    {"id": "sts08", "code": "APPLICATION_WITHDRAWN", "name": "Không tiếp tục hồ sơ", "phase": "admission", "stage_id": "stg04", "status_type": "transition", "selectable_mode": "user", "outcome_type": "negative", "is_final": True, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Lead tự dừng"},
    {"id": "sts13", "code": "APPLICATION_FEE_PAID", "name": "Đã hoàn tất lệ phí xét tuyển", "phase": "admission", "stage_id": "stg03", "status_type": "system", "selectable_mode": "system", "outcome_type": "positive", "is_final": False, "is_universal": False, "updates_pipeline": False, "counts_for_funnel": False, "description": "System ghi nhận thanh toán lệ phí"},
    {"id": "sts09", "code": "ELIGIBLE_FOR_ENROLLMENT", "name": "Đủ điều kiện nhập học", "phase": "admission", "stage_id": "stg04", "status_type": "system", "selectable_mode": "system", "outcome_type": "positive", "is_final": False, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Hồ sơ được duyệt"},
    {"id": "sts14", "code": "TUITION_PENDING", "name": "Chưa hoàn tất học phí", "phase": "fee", "stage_id": "stg05", "status_type": "transition", "selectable_mode": "user", "outcome_type": "neutral", "is_final": False, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Chưa đóng đủ học phí"},
    {"id": "sts10", "code": "TUITION_PAID", "name": "Đã hoàn tất học phí", "phase": "fee", "stage_id": "stg05", "status_type": "system", "selectable_mode": "system", "outcome_type": "positive", "is_final": False, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Thanh toán học phí thành công"},
    {"id": "sts18", "code": "TUITION_REFUNDED", "name": "Đã hoàn học phí", "phase": "fee", "stage_id": "stg05", "status_type": "system", "selectable_mode": "system", "outcome_type": "negative", "is_final": True, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": False, "description": "Hoàn tiền học phí"},
    {"id": "sts11", "code": "ENROLLED", "name": "Đã xác nhận nhập học", "phase": "enrolled", "stage_id": "stg06", "status_type": "system", "selectable_mode": "system", "outcome_type": "positive", "is_final": True, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Chính thức trở thành sinh viên"},
    {"id": "sts12", "code": "DROPPED_OUT", "name": "Ngừng theo học", "phase": "enrolled", "stage_id": "stg07", "status_type": "transition", "selectable_mode": "role", "outcome_type": "negative", "is_final": True, "is_universal": False, "updates_pipeline": True, "counts_for_funnel": True, "description": "Sinh viên thôi học"},
    {"id": "sts15", "code": "NO_REPLY_MESSAGE", "name": "Nhắn tin không phản hồi", "phase": "universal", "stage_id": None, "status_type": "activity", "selectable_mode": "user", "outcome_type": "neutral", "is_final": False, "is_universal": True, "updates_pipeline": False, "counts_for_funnel": False, "description": "Có gửi tin nhưng không phản hồi"},
]

# Display order (sorted by phase then id)
DISPLAY_ORDER = {
    "sts00": 0,
    "sts02": 10,
    "sts03": 20,
    "sts04": 30,
    "sts05": 40,
    "sts06": 50,
    "sts07": 300,
    "sts17": 310,
    "sts16": 320,
    "sts08": 330,
    "sts13": 340,
    "sts09": 350,
    "sts14": 400,
    "sts10": 410,
    "sts18": 420,
    "sts11": 500,
    "sts12": 510,
    "sts01": 900,
    "sts15": 910,
}

# Color codes
COLOR_CODES = {
    "neutral": "#808080",
    "positive": "#008000",
    "negative": "#FF0000",
}


# =============================================================================
# BẢNG 2: allowed_transitions
# =============================================================================
ALLOWED_TRANSITIONS_DATA = [
    {"from_status_id": "sts00", "to_status_id": "sts02", "trigger_type": "user", "required_phase": "consultation", "description": "Kết nối được"},
    {"from_status_id": "sts00", "to_status_id": "sts04", "trigger_type": "user", "required_phase": "consultation", "description": "Từ chối ngay"},
    {"from_status_id": "sts02", "to_status_id": "sts03", "trigger_type": "user", "required_phase": "consultation", "description": "Quan tâm"},
    {"from_status_id": "sts02", "to_status_id": "sts05", "trigger_type": "user", "required_phase": "consultation", "description": "Hẹn lại"},
    {"from_status_id": "sts02", "to_status_id": "sts04", "trigger_type": "user", "required_phase": "consultation", "description": "Không quan tâm"},
    {"from_status_id": "sts05", "to_status_id": "sts03", "trigger_type": "user", "required_phase": "consultation", "description": "Gọi lại có nhu cầu"},
    {"from_status_id": "sts05", "to_status_id": "sts04", "trigger_type": "user", "required_phase": "consultation", "description": "Gọi lại nhưng từ chối"},
    {"from_status_id": "sts03", "to_status_id": "sts06", "trigger_type": "user", "required_phase": "consultation", "description": "Đồng ý tư vấn"},
    {"from_status_id": "sts03", "to_status_id": "sts04", "trigger_type": "user", "required_phase": "consultation", "description": "Không tiếp tục"},
    {"from_status_id": "sts06", "to_status_id": "sts07", "trigger_type": "system", "required_phase": "admission", "description": "Tạo hồ sơ xét tuyển"},
    {"from_status_id": "sts07", "to_status_id": "sts17", "trigger_type": "user", "required_phase": "admission", "description": "Yêu cầu bổ sung"},
    {"from_status_id": "sts17", "to_status_id": "sts07", "trigger_type": "user", "required_phase": "admission", "description": "Bổ sung xong"},
    {"from_status_id": "sts07", "to_status_id": "sts08", "trigger_type": "user", "required_phase": "admission", "description": "Rút hồ sơ"},
    {"from_status_id": "sts07", "to_status_id": "sts16", "trigger_type": "role", "required_phase": "admission", "description": "Không đạt"},
    {"from_status_id": "sts13", "to_status_id": "sts09", "trigger_type": "system", "required_phase": "admission", "description": "Lệ phí hợp lệ"},
    {"from_status_id": "sts09", "to_status_id": "sts14", "trigger_type": "system", "required_phase": "fee", "description": "Chuyển sang thu học phí"},
    {"from_status_id": "sts14", "to_status_id": "sts10", "trigger_type": "system", "required_phase": "fee", "description": "Thanh toán thành công"},
    {"from_status_id": "sts14", "to_status_id": "sts18", "trigger_type": "system", "required_phase": "fee", "description": "Hoàn tiền"},
    {"from_status_id": "sts10", "to_status_id": "sts11", "trigger_type": "system", "required_phase": "enrolled", "description": "Nhập học"},
    {"from_status_id": "sts11", "to_status_id": "sts12", "trigger_type": "role", "required_phase": "enrolled", "description": "Ngừng học"},
]


async def update_consultation_status(db):
    """Update consultation_status table."""
    print("\n[1/2] Updating consultation_status...")
    updated = 0
    created = 0

    for data in CONSULTATION_STATUS_DATA:
        status_id = data["id"]
        result = await db.execute(
            select(models.ConsultationStatus)
            .where(models.ConsultationStatus.id == status_id)
        )
        status = result.scalar_one_or_none()

        if status:
            # Update existing
            status.code = data["code"]
            status.name = data["name"]
            status.phase = data["phase"]
            status.stage_id = data["stage_id"]
            status.status_type = data["status_type"]
            status.selectable_mode = data["selectable_mode"]
            status.outcome_type = data["outcome_type"]
            status.is_final = data["is_final"]
            status.is_universal = data["is_universal"]
            status.updates_pipeline = data["updates_pipeline"]
            status.counts_for_funnel = data["counts_for_funnel"]
            status.description = data["description"]
            status.display_order = DISPLAY_ORDER.get(status_id, 999)
            status.color_code = COLOR_CODES.get(data["outcome_type"], "#808080")
            # Sync deprecated fields
            status.is_final_status = data["is_final"]
            status.counts_for_kpi = data["counts_for_funnel"]
            status.selectable_by_user = data["selectable_mode"]
            updated += 1
            print(f"  ✅ Updated {status_id}: {data['code']}")
        else:
            # Create new
            new_status = models.ConsultationStatus(
                id=status_id,
                code=data["code"],
                name=data["name"],
                phase=data["phase"],
                stage_id=data["stage_id"],
                status_type=data["status_type"],
                selectable_mode=data["selectable_mode"],
                outcome_type=data["outcome_type"],
                is_final=data["is_final"],
                is_universal=data["is_universal"],
                updates_pipeline=data["updates_pipeline"],
                counts_for_funnel=data["counts_for_funnel"],
                description=data["description"],
                display_order=DISPLAY_ORDER.get(status_id, 999),
                color_code=COLOR_CODES.get(data["outcome_type"], "#808080"),
                # Deprecated fields
                is_final_status=data["is_final"],
                counts_for_kpi=data["counts_for_funnel"],
                selectable_by_user=data["selectable_mode"],
            )
            db.add(new_status)
            created += 1
            print(f"  ➕ Created {status_id}: {data['code']}")

    await db.flush()
    print(f"  Summary: {updated} updated, {created} created")
    return updated + created


async def update_allowed_transitions(db):
    """Update allowed_transitions table."""
    print("\n[2/2] Updating allowed_transitions...")

    # Delete existing transitions and recreate
    await db.execute(delete(models.AllowedTransition))
    print("  🗑️  Cleared existing transitions")

    created = 0
    for idx, data in enumerate(ALLOWED_TRANSITIONS_DATA, start=1):
        transition = models.AllowedTransition(
            id=idx,
            from_status_id=data["from_status_id"],
            to_status_id=data["to_status_id"],
            trigger_type=data["trigger_type"],
            required_phase=data["required_phase"],
            is_active=True,
            description=data["description"],
        )
        db.add(transition)
        created += 1
        print(f"  ✅ {data['from_status_id']} → {data['to_status_id']} ({data['trigger_type']})")

    await db.flush()
    print(f"  Summary: {created} transitions created")
    return created


async def verify_data(db):
    """Verify data integrity."""
    print("\n[3/3] Verifying data...")
    errors = []

    # Check NOT_CONTACTED exists with correct code
    result = await db.execute(
        select(models.ConsultationStatus)
        .where(models.ConsultationStatus.code == "NOT_CONTACTED")
    )
    not_contacted = result.scalar_one_or_none()
    if not not_contacted:
        errors.append("NOT_CONTACTED status not found")
    else:
        print(f"  ✅ NOT_CONTACTED: {not_contacted.id}")

    # Check transition count
    result = await db.execute(select(models.AllowedTransition))
    transitions = list(result.scalars().all())
    if len(transitions) != 20:
        errors.append(f"Expected 20 transitions, got {len(transitions)}")
    else:
        print(f"  ✅ Transitions: {len(transitions)}")

    # Check universal statuses
    result = await db.execute(
        select(models.ConsultationStatus)
        .where(models.ConsultationStatus.is_universal == True)
    )
    universal = list(result.scalars().all())
    if len(universal) != 2:
        errors.append(f"Expected 2 universal statuses, got {len(universal)}")
    else:
        print(f"  ✅ Universal statuses: {[s.code for s in universal]}")

    if errors:
        print("\n⚠️  Validation errors:")
        for e in errors:
            print(f"  ❌ {e}")
        return False

    print("  ✅ All checks passed")
    return True


async def main():
    print("=" * 60)
    print("FSM DATA UPDATE SCRIPT")
    print("=" * 60)

    async with AsyncSessionLocal() as db:
        try:
            await update_consultation_status(db)
            await update_allowed_transitions(db)

            # Commit
            await db.commit()
            print("\n✅ All changes committed")

            # Verify
            valid = await verify_data(db)

            print("\n" + "=" * 60)
            if valid:
                print("✅ FSM DATA UPDATE COMPLETED SUCCESSFULLY")
            else:
                print("⚠️  FSM DATA UPDATE COMPLETED WITH WARNINGS")
            print("=" * 60)

        except Exception as e:
            await db.rollback()
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
