# tests/services/test_distribution_service.py
"""
Tests for Lead Distribution Service - Weighted Round Robin Algorithm

Test Coverage:
- Basic weighted distribution
- Priority-based tier selection
- Redis cursor atomicity
- Fallback behavior (no config, Redis failure)
- Safety checks (no active officers)
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import distribution_service
from app.config import settings


# =============================================================================
# FIXTURE
# =============================================================================


@pytest_asyncio.fixture
async def organization_unit(db: AsyncSession) -> models.OrganizationUnit:
    """Một đơn vị tổ chức dùng riêng cho bộ phân phối.

    KHÔNG tái dùng ``second_unit`` của ``tests/services/conftest.py``: nó ghim
    cứng ``id=2001`` cho các ca IDOR cross-unit. Mượn nó ở đây thì hai bộ test
    dùng chung một hàng, và một bên đổi id là bên kia đỏ vì lý do không liên
    quan gì tới phân phối.
    """
    unit = models.OrganizationUnit(
        name="Distribution Test Unit",
        type="department",
    )
    db.add(unit)
    await db.flush()
    await db.refresh(unit)
    return unit


@pytest_asyncio.fixture(autouse=True)
async def co_lap_cursor(test_redis_client):
    """Xoá con trỏ phân phối trước VÀ sau mỗi ca.

    Con trỏ sống trong Redis, ngoài tầm với của ``truncate_all_tables`` — nên
    một ca để lại ``distribution:offering:<id>:cursor`` thì ca sau bắt đầu ở
    giữa chu kỳ và phép kiểm tỷ lệ chập chờn. Chính vì DB tái dùng id offering
    mà lỗi này khó truy: cùng một mã, khác lần chạy.

    Xoá ĐÚNG các khoá phân phối, không ``flushdb``: một fixture reset toàn cục
    sẽ cuốn theo dữ liệu mà fixture khác vừa dựng.

    ``try/finally`` để dọn cả khi ca ném lỗi giữa chừng.
    """
    async def _don():
        mau = "distribution:offering:*:cursor"
        khoa = [k async for k in test_redis_client.scan_iter(mau)]
        if khoa:
            await test_redis_client.delete(*khoa)
        return len(khoa)

    await _don()
    try:
        yield test_redis_client
    finally:
        await _don()


@pytest.mark.asyncio
class TestOfferingDistribution:
    """Test suite for Weighted Round Robin distribution logic."""

    async def test_get_target_unit_no_config_uses_fallback(self, db):
        """When no distribution config exists, should return DEFAULT_ADMISSIONS_UNIT_ID."""
        # Arrange: Offering without distribution config
        offering_id = 9999  # Non-existent offering

        # Act
        result_unit_id = await distribution_service.get_target_unit_for_offering(
            db, offering_id
        )

        # Assert
        assert result_unit_id == settings.DEFAULT_ADMISSIONS_UNIT_ID

    async def test_get_target_unit_single_config(self, db, organization_unit):
        """With single config, should always return that unit."""
        # Arrange: Create offering and single distribution config
        program = models.MajorProgram(
            name="Test Program",
            degree_level="Cao đẳng",
            code="TP001",
            unit_id=organization_unit.id
        )
        db.add(program)
        await db.flush()

        offering = models.ProgramOffering(
            program_id=program.id,
            offering_type="Regular",
            is_active=True
        )
        db.add(offering)
        await db.flush()

        config = models.OfferingDistributionConfig(
            offering_id=offering.id,
            unit_id=organization_unit.id,
            weight=5,
            priority=1,
            is_active=True
        )
        db.add(config)
        await db.commit()

        # Act: Call distribution 3 times
        results = []
        for _ in range(3):
            unit_id = await distribution_service.get_target_unit_for_offering(
                db, offering.id
            )
            results.append(unit_id)

        # Assert: All should return same unit
        assert all(uid == organization_unit.id for uid in results)

    async def test_weighted_round_robin_distribution(self, db):
        """Weighted distribution should allocate leads proportionally."""
        # Arrange: Create 2 units with weight 3:1 ratio
        unit1 = models.OrganizationUnit(
            name="Unit A",
            type="department",
            is_active=True
        )
        unit2 = models.OrganizationUnit(
            name="Unit B",
            type="department",
            is_active=True
        )
        db.add_all([unit1, unit2])
        await db.flush()

        program = models.MajorProgram(
            name="Shared Program",
            degree_level="Cao đẳng",
            code="SP001",
            unit_id=unit1.id
        )
        db.add(program)
        await db.flush()

        offering = models.ProgramOffering(
            program_id=program.id,
            offering_type="Regular",
            is_active=True
        )
        db.add(offering)
        await db.flush()

        # Unit A: weight=3, Unit B: weight=1
        # Expected pattern: [A, A, A, B, A, A, A, B, ...]
        config_a = models.OfferingDistributionConfig(
            offering_id=offering.id,
            unit_id=unit1.id,
            weight=3,
            priority=1,
            is_active=True
        )
        config_b = models.OfferingDistributionConfig(
            offering_id=offering.id,
            unit_id=unit2.id,
            weight=1,
            priority=1,
            is_active=True
        )
        db.add_all([config_a, config_b])
        await db.commit()

        # Act: Distribute 8 leads
        results = []
        for _ in range(8):
            unit_id = await distribution_service.get_target_unit_for_offering(
                db, offering.id
            )
            results.append(unit_id)

        # Assert: Count distribution
        count_a = results.count(unit1.id)
        count_b = results.count(unit2.id)

        # With weight 3:1, expect 6 for A and 2 for B in 8 leads
        assert count_a == 6, f"Expected 6 leads for Unit A, got {count_a}"
        assert count_b == 2, f"Expected 2 leads for Unit B, got {count_b}"

    async def test_priority_tiers_prefer_higher_priority(self, db):
        """Higher priority units (lower number) should be selected."""
        # Arrange: Create 2 units with different priorities
        unit_high_priority = models.OrganizationUnit(
            name="Priority 1 Unit",
            type="department",
            is_active=True
        )
        unit_low_priority = models.OrganizationUnit(
            name="Priority 2 Unit",
            type="department",
            is_active=True
        )
        db.add_all([unit_high_priority, unit_low_priority])
        await db.flush()

        program = models.MajorProgram(
            name="Priority Test Program",
            degree_level="Cao đẳng",
            code="PTP001",
            unit_id=unit_high_priority.id
        )
        db.add(program)
        await db.flush()

        offering = models.ProgramOffering(
            program_id=program.id,
            offering_type="Regular",
            is_active=True
        )
        db.add(offering)
        await db.flush()

        # High priority unit: priority=1
        # Low priority unit: priority=2 (should be ignored)
        config_high = models.OfferingDistributionConfig(
            offering_id=offering.id,
            unit_id=unit_high_priority.id,
            weight=1,
            priority=1,
            is_active=True
        )
        config_low = models.OfferingDistributionConfig(
            offering_id=offering.id,
            unit_id=unit_low_priority.id,
            weight=1,
            priority=2,  # Lower priority (higher number)
            is_active=True
        )
        db.add_all([config_high, config_low])
        await db.commit()

        # Act: Distribute several leads
        results = []
        for _ in range(5):
            unit_id = await distribution_service.get_target_unit_for_offering(
                db, offering.id
            )
            results.append(unit_id)

        # Assert: All should go to high priority unit
        assert all(uid == unit_high_priority.id for uid in results), \
            "All leads should go to priority 1 unit"

    async def test_inactive_config_excluded(self, db, organization_unit):
        """Inactive configs should be excluded from distribution."""
        # Arrange: Create offering with inactive config
        program = models.MajorProgram(
            name="Inactive Test",
            degree_level="Cao đẳng",
            code="IT001",
            unit_id=organization_unit.id
        )
        db.add(program)
        await db.flush()

        offering = models.ProgramOffering(
            program_id=program.id,
            offering_type="Regular",
            is_active=True
        )
        db.add(offering)
        await db.flush()

        config = models.OfferingDistributionConfig(
            offering_id=offering.id,
            unit_id=organization_unit.id,
            weight=5,
            priority=1,
            is_active=False  # Inactive
        )
        db.add(config)
        await db.commit()

        # Act
        result_unit_id = await distribution_service.get_target_unit_for_offering(
            db, offering.id
        )

        # Assert: Should fallback since no active config
        assert result_unit_id == settings.DEFAULT_ADMISSIONS_UNIT_ID

    async def test_reset_distribution_cursor(
        self, db, organization_unit, co_lap_cursor
    ):
        """Reset cursor should allow distribution to restart from beginning."""
        # Arrange: Create offering with config
        program = models.MajorProgram(
            name="Reset Test",
            degree_level="Cao đẳng",
            code="RT001",
            unit_id=organization_unit.id
        )
        db.add(program)
        await db.flush()

        offering = models.ProgramOffering(
            program_id=program.id,
            offering_type="Regular",
            is_active=True
        )
        db.add(offering)
        await db.flush()

        config = models.OfferingDistributionConfig(
            offering_id=offering.id,
            unit_id=organization_unit.id,
            weight=1,
            priority=1,
            is_active=True
        )
        db.add(config)
        await db.commit()

        cursor_key = distribution_service.DISTRIBUTION_CURSOR_KEY_PATTERN.format(
            offering_id=offering.id
        )

        # Act 1: phát vài lead để con trỏ THẬT SỰ được tạo trong Redis.
        for _ in range(3):
            await distribution_service.get_target_unit_for_offering(db, offering.id)

        # Điều kiện tiên quyết: khoá phải TỒN TẠI trước khi reset. Thiếu bước
        # này thì ca "sau reset khoá không còn" vẫn xanh trên một hệ chưa bao
        # giờ tạo khoá — nó khẳng định một chuyện không xảy ra.
        assert await co_lap_cursor.exists(cursor_key) == 1, (
            f"con tro {cursor_key} phai ton tai sau 3 lan phat lead — "
            "neu khong, ca nay dang do/xanh vi ly do khac"
        )
        truoc = await co_lap_cursor.get(cursor_key)
        assert truoc is not None and int(truoc) == 3, (
            f"con tro phai = 3 sau 3 lan phat, nhan {truoc!r}"
        )

        # Act 2
        success = await distribution_service.reset_distribution_cursor(offering.id)

        # Assert: đọc TRẠNG THÁI THẬT trong Redis, không tin giá trị trả về.
        #
        # Bản trước chỉ khẳng định `success is True` và `stats is not None` —
        # biến `reset_distribution_cursor` thành no-op `return True` vẫn xanh
        # trọn. Một phép kiểm mà đột biến no-op đi qua được là phép kiểm không
        # canh gì.
        assert success, "reset phai bao thanh cong"
        assert await co_lap_cursor.exists(cursor_key) == 0, (
            f"khoa {cursor_key} VAN CON sau reset — reset khong xoa gi"
        )
        assert await co_lap_cursor.get(cursor_key) is None, (
            "doc lai con tro sau reset phai ra None"
        )

        # Và stats phải phản ánh đúng: cursor_value None khi chưa phát lead mới.
        stats = await distribution_service.get_distribution_stats(db, offering.id)
        assert stats["cursor_value"] is None, (
            f"stats.cursor_value phai None sau reset, nhan {stats['cursor_value']!r}"
        )


@pytest.mark.asyncio
class TestDistributionStats:
    """Test suite for distribution statistics/analytics."""

    async def test_get_distribution_stats_no_config(self, db):
        """Stats for offering without config should return empty."""
        # Act
        stats = await distribution_service.get_distribution_stats(
            db, offering_id=9999
        )

        # Assert
        assert stats["offering_id"] == 9999
        assert stats["configs"] == []
        assert stats["total_slots"] == 0

    async def test_get_distribution_stats_with_configs(self, db):
        """Stats should accurately reflect weighted slot allocation."""
        # Arrange: Create 2 units with different weights
        unit1 = models.OrganizationUnit(
            name="Stats Unit A",
            type="department",
            is_active=True
        )
        unit2 = models.OrganizationUnit(
            name="Stats Unit B",
            type="department",
            is_active=True
        )
        db.add_all([unit1, unit2])
        await db.flush()

        program = models.MajorProgram(
            name="Stats Program",
            degree_level="Cao đẳng",
            code="STAT001",
            unit_id=unit1.id
        )
        db.add(program)
        await db.flush()

        offering = models.ProgramOffering(
            program_id=program.id,
            offering_type="Regular",
            is_active=True
        )
        db.add(offering)
        await db.flush()

        # Unit A: weight=4, Unit B: weight=2
        config_a = models.OfferingDistributionConfig(
            offering_id=offering.id,
            unit_id=unit1.id,
            weight=4,
            priority=1,
            is_active=True
        )
        config_b = models.OfferingDistributionConfig(
            offering_id=offering.id,
            unit_id=unit2.id,
            weight=2,
            priority=1,
            is_active=True
        )
        db.add_all([config_a, config_b])
        await db.commit()

        # Act
        stats = await distribution_service.get_distribution_stats(
            db, offering.id
        )

        # Assert
        assert stats["offering_id"] == offering.id
        assert len(stats["configs"]) == 2
        assert stats["total_slots"] == 6  # 4 + 2 = 6

        # Find config details
        config_details = {c["unit_id"]: c for c in stats["configs"]}
        assert config_details[unit1.id]["slots_in_cycle"] == 4
        assert config_details[unit2.id]["slots_in_cycle"] == 2


@pytest.mark.asyncio
class TestMixedPriorityParity:
    """Preview và selector phải nói cùng một chu kỳ.

    ``get_target_unit_for_offering`` gom config theo tier rồi lấy
    ``min(priority)`` — chỉ tier cao nhất tham gia chu kỳ. ``get_distribution_stats``
    có chú thích "same logic as get_target_unit_for_offering" nhưng lặp qua
    **mọi** config, không lọc tier.

    Đó không phải chuyện riêng của analytics. Chuỗi khép kín:

        distribution_service.get_distribution_stats
          → routers/leads.py  /distribution-preview
          → LeadDialog.tsx    hiển thị next_unit_name

    Người trực nhìn thấy một đơn vị, lead thật đi tới đơn vị khác. Routing đúng,
    **preview sai** — và preview là thứ con người tin để ra quyết định.
    """

    async def _dung_hai_tier(self, db, ten_top, ten_duoi):
        """Hai đơn vị, hai tier, weight bằng nhau — trọng số không che parity gap.

        Weight cùng 1 là cố ý: nếu top weight lớn hơn, chu kỳ của bản cũ vẫn
        bắt đầu bằng top và ca có thể xanh nhầm ở cursor nhỏ.
        """
        unit_top = models.OrganizationUnit(name=ten_top, type="department")
        unit_duoi = models.OrganizationUnit(name=ten_duoi, type="department")
        db.add_all([unit_top, unit_duoi])
        await db.flush()

        program = models.MajorProgram(
            name="Mixed Priority Program",
            degree_level="Cao đẳng",
            code="MPP001",
            unit_id=unit_top.id,
        )
        db.add(program)
        await db.flush()

        offering = models.ProgramOffering(
            program_id=program.id, offering_type="Regular", is_active=True
        )
        db.add(offering)
        await db.flush()

        db.add_all([
            models.OfferingDistributionConfig(
                offering_id=offering.id, unit_id=unit_top.id,
                weight=1, priority=1, is_active=True,
            ),
            models.OfferingDistributionConfig(
                offering_id=offering.id, unit_id=unit_duoi.id,
                weight=1, priority=2, is_active=True,
            ),
        ])
        await db.commit()
        return offering, unit_top, unit_duoi

    async def test_preview_trung_don_vi_selector_se_chon(
        self, db, organization_unit, co_lap_cursor
    ):
        """Kịch bản quyết định: cursor=1, preview vs lượt phát kế tiếp.

        Trình tự cố ý:
          1. gọi selector MỘT lần  → cursor = 1
          2. đọc stats             → ``next_unit_id`` là dự báo cho lượt kế
          3. gọi selector lần HAI  → đơn vị THẬT của lượt kế

        Bản cũ: chu kỳ của stats là ``[top, duoi]`` (mọi tier) nên
        ``cursor 1 % 2 = 1`` → preview trỏ **tier dưới**; còn selector dùng chu
        kỳ ``[top]`` nên ``1 % 1 = 0`` → vẫn trả **tier trên**. Hai bên lệch.
        """
        offering, unit_top, unit_duoi = await self._dung_hai_tier(
            db, "Tier Tren", "Tier Duoi"
        )

        lan_1 = await distribution_service.get_target_unit_for_offering(db, offering.id)
        assert lan_1 == unit_top.id, (
            "selector phai luon chon tier cao nhat; neu khong, ca nay do vi ly do khac"
        )

        stats = await distribution_service.get_distribution_stats(db, offering.id)
        du_bao = stats["next_unit_id"]

        that_su = await distribution_service.get_target_unit_for_offering(
            db, offering.id
        )

        assert du_bao == that_su, (
            "PREVIEW LECH SELECTOR: /distribution-preview bao don vi "
            f"{du_bao} nhung lead thuc te di toi {that_su}. "
            f"(tier tren={unit_top.id}, tier duoi={unit_duoi.id}) "
            "Nguoi truc nhin mot don vi, he thong gui sang don vi khac."
        )

    async def test_total_slots_chi_dem_tier_cao_nhat(
        self, db, organization_unit, co_lap_cursor
    ):
        """``total_slots`` là "Total weighted slots in distribution cycle".

        Chu kỳ chỉ gồm tier cao nhất, nên đếm cả tier dưới là đếm những chỗ
        không bao giờ tới lượt.
        """
        offering, unit_top, unit_duoi = await self._dung_hai_tier(
            db, "Slots Tren", "Slots Duoi"
        )

        stats = await distribution_service.get_distribution_stats(db, offering.id)

        assert stats["total_slots"] == 1, (
            "chu ky chi gom tier priority=1 (weight 1) nen total_slots phai la 1, "
            f"nhan {stats['total_slots']} — dang dem ca tier duoi"
        )

    async def test_configs_van_liet_ke_moi_config_active(
        self, db, organization_unit, co_lap_cursor
    ):
        """API visibility KHÔNG được thu hẹp.

        Sửa parity không có nghĩa là giấu tier dưới: người trực vẫn cần thấy
        cấu hình tier dưới đang có những gì. Nhưng đó KHÔNG phải dự phòng —
        selector chỉ chọn ``min(priority)`` và không có đường nào chuyển lead
        xuống tier sau, kể cả khi đơn vị được chọn không còn officer nào
        (``distribution_service`` chỉ ghi log rồi vẫn trả đơn vị ấy).
        ``slots_in_cycle`` và ``total_slots`` nói đúng điều đó.
        """
        offering, unit_top, unit_duoi = await self._dung_hai_tier(
            db, "Visible Tren", "Visible Duoi"
        )

        stats = await distribution_service.get_distribution_stats(db, offering.id)
        ids = {c["unit_id"] for c in stats["configs"]}

        assert ids == {unit_top.id, unit_duoi.id}, (
            f"configs phai liet ke CA HAI config active, nhan {ids}"
        )
        theo_unit = {c["unit_id"]: c for c in stats["configs"]}
        assert theo_unit[unit_top.id]["slots_in_cycle"] == 1
        assert theo_unit[unit_duoi.id]["slots_in_cycle"] == 0, (
            "tier khong tham gia chu ky phai co slots_in_cycle = 0, "
            f"nhan {theo_unit[unit_duoi.id]['slots_in_cycle']}"
        )


class TestChuKyTatDinh:
    """Cùng tập config, thứ tự nhận vào khác nhau ⇒ chu kỳ phải GIỐNG HỆT.

    Hai hàm gọi ``_chu_ky_top_tier`` chạy hai truy vấn RIÊNG. Cả hai chỉ
    ``ORDER BY priority ASC, weight DESC`` — mà khi hai config trùng cả priority
    lẫn weight thì PostgreSQL **không hứa gì** về thứ tự các hàng bằng nhau.
    Hai lượt quét có thể trả hai thứ tự khác nhau.

    Vì chỉ số trong chu kỳ quyết định đơn vị nào nhận lead, thứ tự khác nhau =
    chu kỳ khác nhau = xem trước lại lệch định tuyến, dù cả hai đã dùng chung
    helper. Sửa parity mà bỏ qua chỗ này là vá nửa vời.

    Ca này gọi thẳng hàm thuần: nó không phụ thuộc DB, nên nó đo đúng bất biến
    "thứ tự do helper quyết định", không đo may rủi của một lần quét.
    """

    class _Cfg:
        """Bản sao tối thiểu của ``OfferingDistributionConfig``.

        Chỉ ba trường mà helper thật sự đọc.
        """

        def __init__(self, unit_id, weight, priority):
            self.unit_id = unit_id
            self.weight = weight
            self.priority = priority

    def test_thu_tu_dao_nguoc_cho_cung_chu_ky(self):
        # Ba config CÙNG priority, CÙNG weight — đúng ca PostgreSQL bỏ ngỏ.
        a = self._Cfg(unit_id=30, weight=2, priority=1)
        b = self._Cfg(unit_id=10, weight=2, priority=1)
        c = self._Cfg(unit_id=20, weight=2, priority=1)

        _p1, _t1, xuoi = distribution_service._chu_ky_top_tier([a, b, c])
        _p2, _t2, nguoc = distribution_service._chu_ky_top_tier([c, b, a])

        assert xuoi == nguoc, (
            "cung tap config nhung hai thu tu nhan vao cho HAI chu ky khac nhau: "
            f"{xuoi} vs {nguoc}. Thieu moc pha hoa on dinh trong helper."
        )
        # Và phải là thứ tự xác định được, không chỉ "bằng nhau tình cờ".
        assert xuoi == [10, 10, 20, 20, 30, 30], (
            f"chu ky phai sap theo (-weight, unit_id), nhan {xuoi}"
        )

    def test_weight_van_uu_tien_truoc_unit_id(self):
        """Mốc phá hoà KHÔNG được lấn ý định gốc của query.

        ``unit_id`` chỉ dùng khi weight bằng nhau. Nếu nó lấn lên trước thì
        đơn vị weight thấp có thể chiếm đầu chu kỳ — đổi hẳn ai nhận lead đầu.
        """
        nang = self._Cfg(unit_id=99, weight=3, priority=1)
        nhe = self._Cfg(unit_id=1, weight=1, priority=1)

        _p, _t, chu_ky = distribution_service._chu_ky_top_tier([nhe, nang])

        assert chu_ky == [99, 99, 99, 1], (
            f"weight lon phai dung truoc du unit_id lon hon, nhan {chu_ky}"
        )

    def test_chi_tier_cao_nhat_vao_chu_ky(self):
        """Mốc phá hoà không được kéo tier dưới vào chu kỳ."""
        tren = self._Cfg(unit_id=50, weight=1, priority=1)
        duoi = self._Cfg(unit_id=5, weight=9, priority=2)

        top_priority, top_tier, chu_ky = distribution_service._chu_ky_top_tier(
            [duoi, tren]
        )

        assert top_priority == 1
        assert [c.unit_id for c in top_tier] == [50]
        assert chu_ky == [50], f"tier duoi khong duoc vao chu ky, nhan {chu_ky}"
