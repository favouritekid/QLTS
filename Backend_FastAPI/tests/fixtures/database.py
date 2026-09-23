# tests/fixtures/database.py
"""
Track T: Extracted database management fixtures from conftest.py.

Contains: safety check, schema init, table truncation.
Uses NullPool to avoid asyncpg prepared-statement cache pollution.
"""
import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine as _create_engine
from sqlalchemy.pool import NullPool

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MỘT NGUỒN CHUẨN cho câu hỏi "URL này có an toàn để test ghi/xoá không?"
# và cho câu hỏi "in URL này ra log thế nào thì không lộ mật khẩu?".
#
# Trước 23-09 câu hỏi thứ nhất có HAI bản trả lời khác nhau: bản ở đây
# fail-closed, còn bản ở `tests/conftest.py` chỉ `log.warning` rồi in
# "Safety check passed" VÔ ĐIỀU KIỆN. Hai nhánh cạnh nhau, một chặn một
# không (nợ N4.01). Nay cả hai đi qua `kiem_url_csdl_test()`.
# ---------------------------------------------------------------------------

#: Che toàn bộ vùng userinfo (``user:password``) bằng đúng chuỗi này.
CHE = "***"

#: Backend (dialect) mà guard này biết cách suy luận về TÊN CSDL. Kiểu nằm
#: ngoài danh sách là "kiểu không xác định" ⇒ TỪ CHỐI: guard không đoán hộ ngữ
#: nghĩa tên CSDL của một hệ nó chưa từng thấy. Sai về phía chặn.
BACKEND_BIET = frozenset(("postgresql", "sqlite"))

#: TÊN CSDL của dev/production — tên ĐẦY ĐỦ, không phải mẫu chuỗi con. Danh
#: sách này CHỈ đổi LỜI VĂN của thông điệp: không tên nào trong đây chứa
#: "test", nên tất cả đã bị tiêu chí chính chặn từ trước. Giữ lại vì "trỏ vào
#: CSDL dev/production" nói đúng bệnh hơn "tên CSDL không chứa test".
TEN_CSDL_NGUY_HIEM = frozenset(
    ("qlts_dev", "qlts_prod", "qlts_production", "production", "prod")
)


def che_url_csdl(url) -> str:
    """Trả về URL CSDL đã CHE credential — chỉ còn scheme + host + tên CSDL.

    Vì sao không cắt ngắn: ``postgresql+asyncpg://qlts:`` dài 25 ký tự, nên
    ``url[:30]`` in ra đúng 5 ký tự ĐẦU của mật khẩu, và ``url[:60]`` in gần
    trọn nó. Kho này PUBLIC ⇒ log GitHub Actions ai cũng đọc. Cắt ngắn KHÔNG
    phải biện pháp che; bỏ hẳn vùng userinfo mới là (nợ N5.01).

    Cách cắt là ``rfind('@')`` trên TOÀN BỘ phần sau ``://``, cố ý:

    * mật khẩu được phép chứa ``@``, ``/``, ``?`` — cắt theo dấu ``/`` đầu
      tiên hay theo dấu ``?`` đầu tiên đều có thể xẻ ngang mật khẩu và đẩy
      phần đuôi của nó ra output;
    * lấy dấu ``@`` CUỐI CÙNG thì mọi ký tự thuộc vùng userinfo đều bị bỏ,
      kể cả khi chúng trông như tên host.

    Nếu chuỗi truy vấn cũng chứa ``@`` thì hàm che NHIỀU hơn mức cần —
    đó là hướng sai an toàn, và nó được chọn có chủ đích.
    """
    if not isinstance(url, str) or not url:
        return "(khong co URL)"
    vi_tri_scheme = url.find("://")
    if vi_tri_scheme < 0:
        # Không phân giải được thì KHÔNG trả lại nguyên văn: một chuỗi lạ
        # vẫn có thể là secret. Fail-closed cả ở đường che.
        return "(khong phan giai duoc URL)"

    scheme = url[:vi_tri_scheme]
    phan_sau = url[vi_tri_scheme + 3 :]

    vi_tri_at = phan_sau.rfind("@")
    if vi_tri_at >= 0:
        con_lai = phan_sau[vi_tri_at + 1 :]
        tien_to = f"{scheme}://{CHE}@"
    else:
        con_lai = phan_sau
        tien_to = f"{scheme}://"

    # Chỉ CẮT query/fragment SAU khi đã bỏ userinfo — `?password=...` cũng là
    # credential, mà cắt trước thì mật khẩu chứa '?' bị xẻ đôi.
    for dau in ("?", "#"):
        k = con_lai.find(dau)
        if k >= 0:
            con_lai = con_lai[:k]

    return tien_to + con_lai


def kiem_url_csdl_test(db_url) -> str | None:
    """Trả ``None`` khi URL đủ an toàn cho test; ngược lại trả LÝ DO (str).

    Quyền cho phép chỉ phụ thuộc vào **TÊN CSDL đã phân giải**
    (``sqlalchemy.engine.make_url(...).database``) — không phải một phép tìm
    chuỗi con trên toàn URL. Đây đúng là hợp đồng mà
    ``Backend_FastAPI/.env.test.example`` đã ghi từ đầu::

        DATABASE_URL MUST contain "test" in database name

    Bản trước kiểm ``"test" in db_url.lower()``, tức **chưa thực thi hợp đồng
    ấy**. Đo thật trên SQLAlchemy 2.0, bốn URL production dưới đây đều LỌT vì
    chữ "test" nằm NGOÀI tên CSDL::

        //test:pw@prod-db:5432/qlts_production             (username)
        //qlts:test123@prod-db:5432/qlts_production        (password)
        //qlts:pw@testing-host:5432/qlts_production        (host)
        //qlts:pw@prod-db:5432/qlts_production?mode=test   (query)

    Tiêu chí sau khi siết:

    1. Không phân giải được ⇒ từ chối. Một chuỗi hỏng vẫn có thể chứa chữ
       "test"; ``make_url`` ném ``ArgumentError`` thì đó là câu trả lời cuối.
    2. Backend ngoài :data:`BACKEND_BIET` ⇒ từ chối.
    3. Thiếu tên CSDL ⇒ từ chối. Đo thật: ``sqlite://`` cho ``database=None``
       dù SQLAlchemy coi nó là in-memory. Guard KHÔNG suy diễn hộ — muốn
       in-memory thì viết ``:memory:`` tường minh.
    4. ``:memory:`` chỉ được miễn khi backend ĐÚNG là ``sqlite``. Đo thật:
       ``postgresql+asyncpg://…/:memory:`` phân giải ra ``database=':memory:'``
       — miễn theo TÊN thì một CSDL PostgreSQL thật tên ``:memory:`` sẽ lọt.
    5. Còn lại: ``test`` phải nằm trong chính ``url.database``.

    Ngoài ra tên CSDL còn mang ``#`` hoặc ``?`` thì bị từ chối. ``make_url``
    KHÔNG mô hình hoá fragment — đo thật:
    ``…/qlts_production#test`` cho ``database='qlts_production#test'``, và nó
    sẽ lọt bước 5. Một ký tự như thế còn sót lại nghĩa là chuỗi mang thành
    phần mà trình phân giải không mô hình hoá ⇒ từ chối, KHÔNG tự cắt: cắt hộ
    là đoán, mà đoán sai ở đây thì DROP SCHEMA chạy trên CSDL thật.

    ⚠️ Cố ý KHÔNG dùng :func:`che_url_csdl` để phân giải. Hàm ấy có nhiệm vụ
    DUY NHẤT là bỏ credential trước khi in; nó cắt theo ``rfind('@')``, sai
    hướng cho việc quyết định quyền. Một hàm che dùng làm parser an toàn là
    cách sinh ra lỗ thứ hai.
    """
    if not isinstance(db_url, str) or not db_url.strip():
        return "DATABASE_URL rỗng hoặc không phải chuỗi"

    try:
        dia_chi = make_url(db_url.strip())
    except Exception:
        # Bắt rộng có chủ đích: mọi lỗi phân giải đều quy về một câu — "không
        # biết URL này trỏ vào đâu" — và câu ấy phải dẫn tới TỪ CHỐI.
        return "DATABASE_URL không phân giải được thành URL SQLAlchemy"

    backend = (dia_chi.get_backend_name() or "").lower()
    if backend not in BACKEND_BIET:
        return (
            "DATABASE_URL dùng kiểu CSDL không xác định (%s)"
            % (backend or "rỗng")
        )

    ten_csdl = dia_chi.database
    if not ten_csdl:
        return "DATABASE_URL không nêu tên CSDL"

    if "#" in ten_csdl or "?" in ten_csdl:
        return (
            "tên CSDL còn ký tự '#'/'?' — trình phân giải không mô hình hoá "
            "fragment nên phần sau dấu ấy KHÔNG phải tên CSDL"
        )
    if backend != "sqlite" and "/" in ten_csdl:
        return "tên CSDL chứa '/' — không phải một tên CSDL hợp lệ"

    thap = ten_csdl.lower()

    if thap == ":memory:":
        if backend == "sqlite":
            return None
        return (
            "DATABASE_URL đặt tên CSDL là ':memory:' trên backend %s — chỉ "
            "sqlite mới có CSDL in-memory" % backend
        )

    if thap in TEN_CSDL_NGUY_HIEM:
        return "DATABASE_URL trỏ vào CSDL dev/production"

    if "test" not in thap:
        return (
            "tên CSDL không chứa 'test' và cũng không phải sqlite ':memory:'"
        )

    return None


def verify_test_database_safety(settings, pytest_fail):
    """
    Verify we're using a safe test database before allowing DROP operations.

    Safety criteria:
    1. APP_ENV must be "test"
    2. TÊN CSDL đã phân giải phải chứa "test" (hoặc là sqlite
       ":memory:") — xem `kiem_url_csdl_test`. Chữ "test" ở
       user/password/host/port/query/fragment KHÔNG tính.
    """
    current_env = settings.APP_ENV
    if current_env != "test":
        pytest_fail(
            f"SAFETY CHECK FAILED! APP_ENV is '{current_env}', not 'test'."
        )
        return

    ly_do = kiem_url_csdl_test(settings.DATABASE_URL)
    if ly_do is not None:
        pytest_fail(
            f"SAFETY CHECK FAILED! {ly_do}: {che_url_csdl(settings.DATABASE_URL)}"
        )
        return

    log.info(
        "Safety check passed: APP_ENV=%s, DB_URL=%s",
        current_env,
        che_url_csdl(settings.DATABASE_URL),
    )


async def init_schema_once(settings, AppBase, CasbinBase=None):
    """
    Create the full schema from scratch. Called once per pytest session.

    Uses a SEPARATE short-lived engine (NullPool) for DDL to avoid
    asyncpg prepared-statement cache pollution.

    The pg_terminate_backend cleanup runs in its own short-lived engine and
    transaction, BEFORE any DDL. Doing it inline with DROP SCHEMA / CREATE
    SCHEMA inside the same transaction caused intermittent
    ConnectionDoesNotExistError flakes — pg_terminate_backend is async at
    PostgreSQL level (sends SIGTERM but doesn't wait for cleanup), so the
    killed backends could still hold locks when the next DDL statement ran.
    """
    # Phase 0: Kill orphaned backends from any previous test process /
    # interrupted run, in its own dedicated engine + transaction. After this
    # connection closes, PostgreSQL has time to actually reap the killed
    # backends before the schema-reset engine opens its first connection.
    kill_engine = _create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args={"command_timeout": 60},
    )
    try:
        async with kill_engine.begin() as kill_conn:
            await kill_conn.execute(text(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND pid <> pg_backend_pid()"
            ))
        log.info("[Schema Init] Phase 0: orphan backend cleanup complete")
    finally:
        await kill_engine.dispose()

    # Brief pause so PostgreSQL can actually finish releasing the locks
    # held by the just-killed backends. 200ms is empirically enough; without
    # it, DROP SCHEMA in Phase 1 can race with backend teardown.
    await asyncio.sleep(0.2)

    # Phase 1: DROP + CREATE schema in a fresh engine + transaction.
    # No more pg_terminate_backend mixed in here.
    setup_engine = _create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args={"command_timeout": 60},
    )

    try:
        async with setup_engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        log.info("[Schema Init] Phase 1: DROP SCHEMA CASCADE complete")

        await setup_engine.dispose()

        # Phase 2: Recreate tables with another fresh engine
        setup_engine = _create_engine(
            settings.DATABASE_URL,
            poolclass=NullPool,
            connect_args={"command_timeout": 60},
        )
        async with setup_engine.begin() as conn:
            # Drop stale enum types (legacy + current names)
            for enum_type in (
                "discount_type_enum",
                "outcometype", "statustype", "selectablemode", "triggertype",
                "administrativenodelevel",
                # cutover-introduced ENUMs (cleanup defensive)
                "subject_kind",
                "admission_audience",
                "conduct_grade",
                "transition_role_legacy",
                "actor_actual_role",
                "effective_transition_role",
                "outcome_type_enum",
                "status_type_enum",
                "selectable_mode_enum",
                "trigger_type_enum",
            ):
                await conn.execute(text(f"DROP TYPE IF EXISTS {enum_type} CASCADE"))

            # Re-create migration-managed enums BEFORE Base.metadata.create_all().
            #
            # All ENUMs here use ``create_type=False`` in the model column
            # definition because their DDL is owned by Alembic migrations.
            # Test DB uses ``Base.metadata.create_all()`` (NOT alembic) per
            # ``tests/fixtures/database.py:123`` + memory
            # ``test-db-schema-source`` — so SQLAlchemy SKIPs ENUM creation
            # for ``create_type=False`` columns and the table CREATE fails
            # with ``UndefinedObjectError: type "foo" does not exist``.
            #
            # Every ``create_type=False`` ENUM in app/models MUST be listed
            # below. The lock test ``tests/unit/test_fixture_enum_coverage.
            # py`` greps the codebase + asserts each name appears here —
            # adding a new ``create_type=False`` ENUM without updating
            # this fixture fails the lock test loudly.

            # tuition_discount_policy.py — pre-cutover existing
            await conn.execute(text(
                "CREATE TYPE discount_type_enum AS ENUM ('amount', 'percentage')"
            ))

            # phase1_03 (#184 Wave 1 PR-1B') — admission_path.applicable_to
            await conn.execute(text(
                "CREATE TYPE admission_audience AS ENUM "
                "('POST_THCS', 'POST_THPT', 'LIEN_THONG_TC', "
                "'LIEN_THONG_CD', 'VLVH')"
            ))

            # phase1_05 (#184 Wave 1 PR-1C') — subject.subject_kind
            await conn.execute(text(
                "CREATE TYPE subject_kind AS ENUM "
                "('ACADEMIC_SUBJECT', 'TERM_AVERAGE', 'ABILITY_TEST', "
                "'CERTIFICATE')"
            ))

            # phase1_09a (#184 Wave 2) — admission_profile.conduct_grade
            await conn.execute(text(
                "CREATE TYPE conduct_grade AS ENUM ('TB', 'KHA', 'TOT')"
            ))

            # phase1_10 (#184 Wave 2) — status_history 3-role triplet
            await conn.execute(text(
                "CREATE TYPE transition_role_legacy AS ENUM "
                "('system', 'officer', 'admin', 'candidate')"
            ))
            await conn.execute(text(
                "CREATE TYPE actor_actual_role AS ENUM "
                "('candidate', 'officer', 'manager', 'accountant', "
                "'admin', 'system')"
            ))
            await conn.execute(text(
                "CREATE TYPE effective_transition_role AS ENUM "
                "('candidate', 'officer', 'admin', 'system')"
            ))

            # pipeline.py — pre-cutover existing FSM enums
            await conn.execute(text(
                "CREATE TYPE outcome_type_enum AS ENUM "
                "('positive', 'neutral', 'negative')"
            ))
            await conn.execute(text(
                "CREATE TYPE status_type_enum AS ENUM "
                "('transition', 'activity', 'system')"
            ))
            await conn.execute(text(
                "CREATE TYPE selectable_mode_enum AS ENUM "
                "('user', 'role', 'system')"
            ))
            await conn.execute(text(
                "CREATE TYPE trigger_type_enum AS ENUM "
                "('user', 'role', 'system', 'event')"
            ))

            await conn.run_sync(AppBase.metadata.create_all)

            # Sequences not tracked by SQLAlchemy
            await conn.execute(text(
                "CREATE SEQUENCE IF NOT EXISTS collaborator_code_seq "
                "START WITH 1 INCREMENT BY 1"
            ))

            # Partial unique indexes (match Alembic migrations)
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_email_unit_active "
                "ON lead (lower(email), unit_id) "
                "WHERE email IS NOT NULL AND deleted_at IS NULL"
            ))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_phone_active "
                "ON lead_phone_identity (phone_normalized) "
                "WHERE deleted_at IS NULL"
            ))

            # Diacritic-insensitive lead name search (migration leadsrch01).
            # Test DB uses create_all() (no Alembic), so the unaccent extension
            # + f_unaccent() wrapper must be created here — otherwise the lead
            # search branch (lead_repository._build_filters), which always
            # evaluates f_unaccent(full_name), fails with "function does not
            # exist" on ANY lead list/search query. pg_trgm + GIN trgm index
            # are skipped (perf-only; seq scan is fine at test scale).
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
            await conn.execute(text(
                "CREATE OR REPLACE FUNCTION f_unaccent(text) "
                "RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT "
                "AS $func$ SELECT public.unaccent('public.unaccent', $1) $func$"
            ))

            if CasbinBase:
                await conn.run_sync(CasbinBase.metadata.create_all)
                await conn.execute(text("""
                    DO $$ BEGIN
                        ALTER TABLE casbin_rule
                        ADD COLUMN IF NOT EXISTS template_id VARCHAR(50),
                        ADD COLUMN IF NOT EXISTS applied_at TIMESTAMP,
                        ADD COLUMN IF NOT EXISTS applied_by INTEGER;
                        CREATE INDEX IF NOT EXISTS ix_casbin_rule_template_id
                        ON casbin_rule(template_id);
                    EXCEPTION WHEN undefined_table THEN
                        NULL;
                    END $$;
                """))

            tc = await conn.execute(text(
                "SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'"
            ))
            table_count = tc.scalar()
            log.info(f"[Schema Init] Phase 2: Created {table_count} tables")
            if table_count == 0:
                raise RuntimeError("Schema init produced 0 tables!")
    finally:
        await setup_engine.dispose()

    log.info("[Schema Init] Schema initialization complete")


async def truncate_all_tables(settings, engine):
    """
    Truncate all data from all tables in a single statement.

    Uses a DEDICATED short-lived engine (NullPool) to avoid deadlocks
    with the app's connection pool.
    """
    truncate_engine = _create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args={"command_timeout": 60},
    )
    try:
        await engine.dispose()

        async with truncate_engine.begin() as conn:
            await conn.execute(text("SET LOCAL statement_timeout = 0"))
            result = await conn.execute(text(
                "SELECT string_agg(quote_ident(tablename), ', ') "
                "FROM pg_tables WHERE schemaname = 'public'"
            ))
            tables = result.scalar()
            if tables:
                await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
                await conn.execute(text("SELECT setval('collaborator_code_seq', 1, false)"))
    finally:
        await truncate_engine.dispose()
