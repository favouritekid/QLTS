# -*- coding: utf-8 -*-
"""Sổ cái chống replay: hai request cùng ``operation_id`` trên PostgreSQL THẬT.

🔴 Vì sao phải là database thật chứ không phải mock: thứ đang được kiểm là hành
vi của **khoá unique dưới READ COMMITTED** — bên thua CHỜ bên thắng rồi mới
biết mình thua. Không có đối tượng giả nào tái hiện được điều đó; một fake chỉ
diễn lại đúng giả định của người viết test.

⚠️ Ca đua ở đây khẳng định KHOÁ bằng ``pg_blocking_pids``, không bằng
``asyncio.gather()`` và cũng không bằng đo thời gian. Hai cách sau xanh cả khi
hai lệnh chạy tuần tự — tức xanh cả khi ràng buộc đã bị gỡ.
"""

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.database import AsyncSessionLocal
from app.models.dorm_sync_operation import DormSyncOperation
from app.repositories.dorm_sync_operation_repository import (
    chen_neu_chua_co,
    lay_theo_operation_id,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_HASH = "0" * 64


@pytest_asyncio.fixture
async def actor_id(admin_user_in_db) -> int:
    """ID người bấm, ĐÃ COMMIT.

    🔴 Chỉ ``flush`` là không đủ: hai session của ca đua là hai kết nối khác,
    và một hàng chưa commit thì vô hình với chúng — khoá ngoại ``actor_id`` sẽ
    vỡ ở cả hai bên và ca đua chết vì một lý do không liên quan gì tới thứ nó
    định kiểm.
    """
    uid = (
        admin_user_in_db["id"]
        if isinstance(admin_user_in_db, dict)
        else admin_user_in_db.id
    )

    # ⚠️ Khẳng định TỪ MỘT KẾT NỐI KHÁC, không tin fixture.
    #
    # "Đã tạo" và "đã commit" là hai chuyện; log của fixture chỉ nói chuyện thứ
    # nhất. Nếu nó mới `flush`, hàng này vô hình với hai session của ca đua và
    # cả hai bên chết vì khoá ngoại — một thất bại nói về fixture chứ không nói
    # gì về ràng buộc unique đang được kiểm.
    async with AsyncSessionLocal() as s:
        thay = await s.scalar(
            text("select id from \"user\" where id = :i"), {"i": uid}
        )
    assert thay == uid, "người bấm chưa được commit — hai session kia không thấy"
    return uid


async def _dem_hang(operation_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as s:
        return await s.scalar(
            select(func.count())
            .select_from(DormSyncOperation)
            .where(DormSyncOperation.operation_id == operation_id)
        )


async def _cho_bi_chan(pid_can_theo: int, pid_giu_khoa: int, giay: float = 10.0):
    """Chờ tới khi Postgres XÁC NHẬN ``pid_can_theo`` đang bị chặn.

    Trả về danh sách pid đang chặn. Hết giờ thì ném — im lặng bỏ qua ở đây
    nghĩa là ca đua tự hạ xuống thành hai lệnh tuần tự.
    """
    async with AsyncSessionLocal() as s:
        het = asyncio.get_running_loop().time() + giay
        while asyncio.get_running_loop().time() < het:
            pids = (
                await s.execute(text("select pg_blocking_pids(:p)"), {"p": pid_can_theo})
            ).scalar()
            # ⚠️ Đọc lại ở mỗi vòng: `pg_blocking_pids` là ảnh chụp tức thời.
            await s.rollback()
            if pids and pid_giu_khoa in list(pids):
                return list(pids)
            await asyncio.sleep(0.05)
    raise AssertionError(
        f"Hết {giay}s mà pid {pid_can_theo} vẫn KHÔNG bị pid {pid_giu_khoa} chặn. "
        "Hai lệnh đang chạy tuần tự — ca đua này không kiểm được gì."
    )


async def test_hai_request_cung_operation_id_chi_sinh_MOT_hang(actor_id):
    """🔴 Bên thua CHỜ, rồi nhận ``None`` — không phải ``IntegrityError``.

    Đây là ca đúng như production: người dùng bấm hai lần, hoặc trình duyệt
    retry. Nếu bên thua nhận ``IntegrityError`` thì nó nổ ngay trong ``flush()``
    của service và thoát ra thành 500 trước khi ai kịp bắt — trong khi thứ vừa
    xảy ra là một chuyện hoàn toàn bình thường.
    """
    op_id = uuid.uuid4()

    s1 = AsyncSessionLocal()
    s2 = AsyncSessionLocal()
    try:
        # Mở transaction ở cả hai và lấy pid — pid là thứ duy nhất cho phép hỏi
        # Postgres "ai đang chặn ai".
        pid1 = await s1.scalar(text("select pg_backend_pid()"))
        pid2 = await s2.scalar(text("select pg_backend_pid()"))
        assert pid1 != pid2, "hai session phải là hai kết nối khác nhau"

        # T1 chèn và GIỮ transaction — chưa commit.
        hang1 = await chen_neu_chua_co(
            s1,
            operation_id=op_id,
            actor_id=actor_id,
            academic_year=2026,
            snapshot_hash=_HASH,
            snapshot_version=1,
        )
        assert hang1 is not None, "bên thắng phải nhận được hàng"

        # T2 bắt đầu cùng lời gọi. Nó sẽ CHỜ ở khoá unique.
        viec2 = asyncio.create_task(
            chen_neu_chua_co(
                s2,
                operation_id=op_id,
                actor_id=actor_id,
                academic_year=2026,
                snapshot_hash=_HASH,
                snapshot_version=1,
            )
        )

        # 🔴 Bằng chứng KHOÁ THẬT, hỏi thẳng Postgres.
        #
        # `gather()` hay `time.monotonic()` đều xanh khi hai lệnh chạy tuần tự,
        # tức xanh cả khi ràng buộc unique đã bị gỡ. Chỉ `pg_blocking_pids` mới
        # phân biệt được "đã chờ" với "tình cờ chạy sau".
        chan_boi = await _cho_bi_chan(pid2, pid1)
        assert pid1 in chan_boi
        assert not viec2.done(), "T2 phải còn đang chờ trong lúc T1 giữ khoá"

        await s1.commit()

        hang2 = await viec2
        assert hang2 is None, (
            "bên thua phải nhận None — `ON CONFLICT DO NOTHING` không trả hàng"
        )

        # Đúng MỘT hàng tồn tại, và nó là hàng của bên thắng.
        assert await _dem_hang(op_id) == 1

        # Bên thua đọc lại được hàng của bên thắng...
        doc_lai = await lay_theo_operation_id(s2, op_id)
        assert doc_lai is not None
        assert doc_lai.id == hang1.id
        assert doc_lai.status == "running"

        # ...và session của nó VẪN DÙNG ĐƯỢC. Một `IntegrityError` sẽ đẩy
        # transaction sang trạng thái hỏng, và mọi câu sau đó chết bằng
        # "current transaction is aborted" — người gọi hết đường xử tử tế.
        assert await s2.scalar(text("select 1")) == 1
        await s2.commit()
    finally:
        for s in (s1, s2):
            await s.rollback()
            await s.close()


async def test_lan_goi_thu_hai_TUAN_TU_cung_tra_None(actor_id):
    """Không có đua: gọi lại sau khi đã commit vẫn phải là ``None``, không nổ.

    Ca đua ở trên chứng minh hành vi khi hai bên chồng nhau; ca này chứng minh
    hành vi ở đường thường — retry sau vài giây, mà đó mới là ca hay gặp.
    """
    op_id = uuid.uuid4()

    async with AsyncSessionLocal() as s:
        hang = await chen_neu_chua_co(
            s,
            operation_id=op_id,
            actor_id=actor_id,
            academic_year=2026,
            snapshot_hash=_HASH,
            snapshot_version=1,
        )
        assert hang is not None
        await s.commit()

    async with AsyncSessionLocal() as s:
        lai = await chen_neu_chua_co(
            s,
            operation_id=op_id,
            actor_id=actor_id,
            academic_year=2026,
            snapshot_hash=_HASH,
            snapshot_version=1,
        )
        assert lai is None
        assert (await lay_theo_operation_id(s, op_id)) is not None
        await s.commit()

    assert await _dem_hang(op_id) == 1


async def test_database_tu_choi_trung_khi_di_vong_qua_repository(actor_id):
    """Hàng rào nằm ở DATABASE, không ở tầng Python.

    Repository dùng ``ON CONFLICT`` nên nó không bao giờ thấy lỗi — và chính vì
    thế phải có ca chứng minh ràng buộc thật sự tồn tại. Không có ca này thì gỡ
    hẳn ``UNIQUE`` đi mọi test khác vẫn xanh, chỉ khác là hai lượt hạ cờ cùng
    chạy trên production.
    """
    op_id = uuid.uuid4()

    async with AsyncSessionLocal() as s:
        s.add(
            DormSyncOperation(
                operation_id=op_id,
                actor_id=actor_id,
                academic_year=2026,
                snapshot_hash=_HASH,
                snapshot_version=1,
                status="running",
            )
        )
        await s.commit()

    async with AsyncSessionLocal() as s:
        s.add(
            DormSyncOperation(
                operation_id=op_id,
                actor_id=actor_id,
                academic_year=2026,
                snapshot_hash=_HASH,
                snapshot_version=1,
                status="running",
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()

    assert await _dem_hang(op_id) == 1


@pytest.mark.parametrize("xau", ["pending", "RUNNING", "", "done"])
async def test_database_tu_choi_status_ngoai_bon_gia_tri(actor_id, xau):
    """State machine khai ở CHECK constraint, không chỉ ở chú thích.

    Một trạng thái thứ năm lọt vào sổ nghĩa là mọi câu hỏi "lượt này xong
    chưa" đều có một câu trả lời không ai lường trước — và sổ đối soát mất
    đúng thứ khiến nó là sổ.
    """
    async with AsyncSessionLocal() as s:
        s.add(
            DormSyncOperation(
                operation_id=uuid.uuid4(),
                actor_id=actor_id,
                academic_year=2026,
                snapshot_hash=_HASH,
                snapshot_version=1,
                status=xau,
            )
        )
        with pytest.raises((IntegrityError, DBAPIError)):
            await s.commit()
        await s.rollback()


async def test_catalog_chi_co_MOT_chi_muc_tren_operation_id(setup_test_database):
    """Đúng một chỉ mục, và nó là UNIQUE.

    ``unique=True`` đã tự sinh một unique index. Thêm ``index=True`` sinh cái
    thứ hai trên CÙNG cột, cùng thứ tự: một bản sao phải cập nhật ở mọi lần ghi
    mà không truy vấn nào dùng tới.

    ⚠️ Hỏi CATALOG chứ không đọc lại mã nguồn model — thứ quyết định là những
    gì thật sự tồn tại trong database.
    """
    async with AsyncSessionLocal() as s:
        hang = (
            await s.execute(
                text(
                    "select indexname, indexdef from pg_indexes "
                    "where tablename = 'dorm_sync_operations' "
                    "and indexdef like :mau"
                ),
                # ⚠️ Mẫu LIKE đi bằng THAM SỐ RÀNG. Viết thẳng
                # ``like '%(operation_id)%'`` vào chuỗi thì ``%(...)`` bị đọc
                # như một placeholder paramstyle và câu lệnh chết trước khi
                # chạm database — một ca kiểm đỏ vì lý do chẳng liên quan gì
                # tới thứ nó canh.
                {"mau": "%operation_id%"},
            )
        ).all()

    ten = [h[0] for h in hang]
    assert len(hang) == 1, f"phải đúng MỘT chỉ mục trên operation_id, đang có: {ten}"
    assert "UNIQUE" in hang[0][1].upper(), "chỉ mục duy nhất đó phải là UNIQUE"
    assert "ix_dorm_sync_operations_operation_id" not in ten
