"""Unit tests for #184 Wave 5-D migration ``phase1_16_create_archived_admission_profile_table``.

Pure-text + AST contract tests — locks the revision chain, table name, the
column-mirror invariant against the live ``AdmissionProfile`` model, the
archive metadata column, the ``(lead_id, academic_year)`` index per PLAN line
931-934, the no-constraint shape (FK/UQ/CHECK), the ENUM reuse pattern, and the
idempotent guard surface.

Live alembic roundtrip is DEFERRED to staging clone D12-D14 because the dev DB
is in a stamped-without-upgrade drift state for Wave 2 (``phase1_09a`` ENUM +
columns, ``phase1_10`` status_history). Production deploy will have the proper
chain so the ``conduct conduct_grade`` reference resolves.

What lives here:
1. Revision row + chain (``phase1_16`` → ``phase1_19c``).
2. Underscore-prefixed table name ``_archived_admission_profile``.
3. Mirror parity — every ``AdmissionProfile`` column name appears in the
   migration source (re-derived, NOT hardcoded).
4. Archive metadata column ``archived_at`` shape.
5. ``ix_archived_profile_lead_year`` composite index per PLAN line 933-934.
6. NO FK / UQ / CHECK constraints (archive must accept historical violators).
7. ``conduct conduct_grade`` ENUM uses ``create_type=False`` reuse pattern.
8. Idempotent guards (``table_exists`` + ``index_exists``) on both upgrade and
   downgrade paths.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_16 = (
    _VERSIONS_DIR / "phase1_16_create_archived_admission_profile_table.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_16.stem, _PHASE1_16)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_migration_by_revision(revision_id: str):
    """Nạp module migration theo revision id, không theo TÊN TỆP.

    Tên tệp không phải khoá: một revision có thể được đổi tên tệp mà id vẫn
    nguyên. Quét `revision: str = "<id>"` trong từng tệp rồi mới nạp.
    """
    for f in sorted(_VERSIONS_DIR.glob("*.py")):
        noi_dung = f.read_text(encoding="utf-8")
        if re.search(rf'^revision(?::\s*str)?\s*=\s*"{re.escape(revision_id)}"',
                     noi_dung, re.M):
            spec = importlib.util.spec_from_file_location(f.stem, f)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise AssertionError(f"khong tim thay migration co revision {revision_id!r}")


@pytest.fixture
def phase1_16():
    return _load_migration()


@pytest.fixture
def src() -> str:
    return _PHASE1_16.read_text(encoding="utf-8")


_TABLE = "_archived_admission_profile"


# ---------------------------------------------------------------------------
# Bộ dò "SELECT * ghi vào bảng archive" — tầng MODULE, không lồng trong test
# ---------------------------------------------------------------------------
#
# Để ở tầng module vì hai lý do, và lý do thứ hai mới là lý do thật:
#   1. hai ca kiểm dùng chung;
#   2. nằm trong thân test thì KHÔNG parameterize được, nên các dạng bypass
#      chỉ kiểm được bằng đột biến thủ công — thứ không ai chạy lại sau này.
#      Bộ đối chứng bypass phải nằm TRONG kho, chạy mỗi lượt CI.

_MOC = chr(0)  # chỗ một biểu thức động đã bị rút gọn

_NHAY = "[" + chr(92) + chr(34) + chr(39) + chr(96) + "]?"
_DINH_DANH = "(?:" + _NHAY + r"\w+" + _NHAY + "|" + _MOC + ")"
_SCHEMA = "(?:" + _DINH_DANH + r"\s*\.\s*)?"
_ALIAS = "(?:" + _DINH_DANH + r"\s*\.\s*)?"

_MAU_SELECT_SAO = re.compile(
    r"insert\s+into\s+"
    + "(?:" + _SCHEMA + _NHAY + re.escape(_TABLE) + _NHAY + "|" + _MOC + ")"
    + r"[^;]*?" + chr(92) + "bselect" + r"\s+(?:distinct\s+)?"
    + _ALIAS + r"\*",
    re.I | re.S,
)

# %s / %d / %r / %(ten)s  và  {} / {0} / {ten} / {ten!r:>10}
_MAU_PHAN_TRAM = re.compile(r"%(?:\([^)]*\))?[-+ #0-9.*]*[hlL]?[a-zA-Z%]")
_MAU_NGOAC_NHON = re.compile(r"\{[^{}]*\}")


def _phan_tu(nut):
    """Các phần tử của một list/tuple hằng; None nếu không phải."""
    if isinstance(nut, (ast.List, ast.Tuple, ast.Set)):
        return list(nut.elts)
    return None


def _ket_xuat_chuoi(nut) -> str:
    """Rút một biểu thức chuỗi về văn bản SQL gần đúng.

    Mọi mảnh KHÔNG phải hằng trở thành ``_MOC``; mẫu regex chấp nhận ``_MOC``
    ở vị trí schema, tên bảng và alias, nên đích/alias động vẫn bị bắt.

    Từng nhánh dưới đây tương ứng một đường lọt đã được chứng minh bằng ca
    kiểm parameterized ``test_bo_do_select_sao_bat_moi_dang``, chứ không phải
    suy đoán:

      ``a + b``            -> nối hai vế
      f-string             -> nối các mảnh, mảnh động thành _MOC
      ``"…%s…" % x``       -> THAY chỗ %s bằng _MOC (nối vào cuối là SAI:
                              câu lệnh vỡ chỗ khác, mẫu không khớp nữa)
      ``"…{}…".format(x)`` -> THAY chỗ {} bằng _MOC (giữ nguyên {} cũng SAI)
      ``sep.join([...])``  -> nối THẬT các phần tử bằng sep (biến cả danh
                              sách thành một _MOC là mất trắng câu lệnh)
      ``x.strip()`` v.v.   -> trả phần gốc, để mọi hàm bọc chuỗi không cắt
                              đứt chuỗi kết xuất
      ``dedent(x)``        -> nối các đối số
    """
    if isinstance(nut, ast.Constant):
        return nut.value if isinstance(nut.value, str) else _MOC
    if isinstance(nut, ast.JoinedStr):
        return "".join(_ket_xuat_chuoi(x) for x in nut.values)
    if isinstance(nut, ast.FormattedValue):
        return _MOC
    if isinstance(nut, ast.BinOp):
        if isinstance(nut.op, ast.Add):
            return _ket_xuat_chuoi(nut.left) + _ket_xuat_chuoi(nut.right)
        if isinstance(nut.op, ast.Mod):
            return _MAU_PHAN_TRAM.sub(_MOC, _ket_xuat_chuoi(nut.left))
    if isinstance(nut, ast.Call):
        if isinstance(nut.func, ast.Attribute):
            goc = _ket_xuat_chuoi(nut.func.value)
            if nut.func.attr == "format":
                return _MAU_NGOAC_NHON.sub(_MOC, goc)
            if nut.func.attr == "join":
                pt = None
                if len(nut.args) == 1:
                    pt = _phan_tu(nut.args[0])
                if pt is None:
                    pt = list(nut.args)
                return goc.join(_ket_xuat_chuoi(x) for x in pt) if pt else goc
            return goc
        if nut.args:
            return "".join(_ket_xuat_chuoi(a) for a in nut.args)
    return _MOC


def _van_ban_trong_ma(cay) -> list:
    """Mọi biểu thức chuỗi trong MÃ, đã kết xuất — NGOẠI TRỪ docstring.

    Quét nguyên văn bản là sai: docstring và comment nói VỀ ``SELECT *``
    (chính docstring của ``arch20260829`` giải thích vì sao nó không an toàn)
    sẽ bị tính là vi phạm — đúng lớp lỗi "biểu thức khớp trúng dòng thông báo
    thay vì dòng lệnh". Comment không nằm trong AST nên tự rụng; docstring
    thì phải loại tay.
    """
    doc = set()
    for nut in ast.walk(cay):
        if isinstance(
            nut, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            than = getattr(nut, "body", None)
            if (
                than
                and isinstance(than[0], ast.Expr)
                and isinstance(than[0].value, ast.Constant)
                and isinstance(than[0].value.value, str)
            ):
                doc.add(id(than[0].value))
    ra = []
    for nut in ast.walk(cay):
        if id(nut) in doc:
            continue
        if isinstance(nut, (ast.JoinedStr, ast.BinOp, ast.Call)) or (
            isinstance(nut, ast.Constant) and isinstance(nut.value, str)
        ):
            ra.append(_ket_xuat_chuoi(nut))
    return ra


def _co_ghi_select_sao(ma_nguon: str) -> bool:
    """True nếu mã nguồn chứa một đường ghi archive dùng ``SELECT *``."""
    return any(
        _MAU_SELECT_SAO.search(vb) for vb in _van_ban_trong_ma(ast.parse(ma_nguon))
    )


def _cot_khai_o_moi_migration() -> set:
    """Bộ cột của bảng archive, GỘP từ MỌI migration chạm tới nó.

    Bất biến thật không phải "phase1_16 liệt kê đủ cột" mà là "BẢNG archive soi
    gương ``AdmissionProfile``" — và một bảng hoàn toàn có thể được bồi thêm cột
    bằng ``op.add_column`` ở migration sau. Neo vào một tệp duy nhất làm phép
    kiểm sai theo cả hai chiều: đỏ oan khi cột được thêm ở nơi khác, và (nguy
    hơn) xanh oan nếu ai đó dựng lại bảng ở migration khác.

    Khoanh vùng bằng AST theo ĐÚNG lời gọi nhắm bảng này, không phải "tệp có
    nhắc tên bảng": ``phase1_17`` và ``phase2_01_v2`` đều nhắc tên bảng trong
    docstring/comment nhưng khai cột của BẢNG KHÁC (outbox, round). Lọc theo
    tên tệp sẽ nuốt trọn 28 cột lạ và làm phép đếm vô nghĩa.
    """
    return set(_dac_ta_cot_tu_migration())


def _dac_ta_cot_tu_migration() -> dict:
    """Như trên, nhưng trả {tên: (kiểu, nullable)} chứ không chỉ tên.

    Dựng THẬT đối tượng ``sa.Column`` bằng cách eval biểu thức trong
    namespace CỦA CHÍNH module migration — nhờ vậy tên như ``_conduct_grade``
    (ENUM dùng lại của phase1_09a) giải được, và hai bên được so bằng cùng
    một từ vựng SQLAlchemy thay vì so chuỗi văn bản.

    Không eval được thì NÉM, không bỏ qua: một cột lặng lẽ rơi khỏi phép so
    sẽ làm test xanh trong khi parity đã gãy.
    """
    dac_ta = {}
    for f in sorted(_VERSIONS_DIR.glob("*.py")):
        noi_dung = f.read_text(encoding="utf-8")
        if _TABLE not in noi_dung:
            continue
        cay = ast.parse(noi_dung)
        nut = []

        # Hằng module trỏ đúng bảng này — migration dùng ``op.create_table(TABLE, …)``
        ten_hang = {
            t.id
            for n in ast.walk(cay)
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
            and n.value.value == _TABLE
            for t in n.targets
            if isinstance(t, ast.Name)
        }

        def tro_dung_bang(nut) -> bool:
            if isinstance(nut, ast.Constant):
                return nut.value == _TABLE
            return isinstance(nut, ast.Name) and nut.id in ten_hang

        for n in ast.walk(cay):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            if n.func.attr not in ("create_table", "add_column"):
                continue
            if not n.args or not tro_dung_bang(n.args[0]):
                continue
            for con in ast.walk(n):
                if (
                    isinstance(con, ast.Call)
                    and isinstance(con.func, ast.Attribute)
                    and con.func.attr == "Column"
                    and con.args
                    and isinstance(con.args[0], ast.Constant)
                ):
                    nut.append(con)
        if not nut:
            continue
        spec = importlib.util.spec_from_file_location(f.stem, f)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for con in nut:
            bieu_thuc = ast.unparse(con)
            try:
                col = eval(bieu_thuc, dict(vars(module)))
            except Exception as e:
                raise AssertionError(
                    f"khong dung lai duoc cot tu {f.name}: {bieu_thuc!r} ({e})"
                ) from e
            dac_ta[col.name] = (str(col.type), col.nullable)
    return dac_ta


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_16_revision_id(phase1_16) -> None:
    assert phase1_16.revision == "phase1_16"


def test_phase1_16_chains_off_phase1_19c(phase1_16) -> None:
    """Wave 5 ship-order chốt 2026-05-05 Codex round 19: alembic chain
    string-based, NOT numeric monotonic. ``phase1_16`` follows
    ``phase1_19c`` (Wave 5-A) so the archive table can be created before
    ``phase1_17`` (5-E) and ``phase1_19d`` (5-B) which depend on it."""
    # `a9312d02` CHÈN `phase1_19c5` vào giữa `phase1_19c` và mắt xích này
    # (chuyển seed HOA sang thường trước pre-flight của `phase3_01`). Đổi chain
    # là CỐ Ý, nên khẳng định cha trực tiếp theo trạng thái thật...
    assert phase1_16.down_revision == "phase1_19c5"

    # ...nhưng vẫn khoá ý định GỐC: chuỗi phải còn đi QUA `phase1_19c`. Nếu chỉ
    # sửa hằng số ở trên thành cha mới thì lần chèn kế tiếp lại âm thầm cắt
    # `phase1_19c` khỏi chuỗi mà không ca nào đỏ.
    ke = _load_migration_by_revision("phase1_19c5")
    assert ke.down_revision == "phase1_19c", (
        f"phase1_19c5 phải nối tiếp phase1_19c, đang là {ke.down_revision!r}"
    )


# ---------------------------------------------------------------------------
# 2. Table name + archive contract
# ---------------------------------------------------------------------------


def test_phase1_16_uses_underscore_prefixed_table_name(phase1_16) -> None:
    """PLAN line 124, 195, 562, 914, 931, 934 ALL use the leading-underscore
    convention to mark this as an internal/archive table, not a domain
    entity."""
    assert phase1_16.TABLE == "_archived_admission_profile"


def test_phase1_16_index_constant_matches_plan_line_933(phase1_16) -> None:
    assert phase1_16.INDEX_LEAD_YEAR == "ix_archived_profile_lead_year"


# ---------------------------------------------------------------------------
# 3. Column mirror parity — re-derived from AdmissionProfile model
# ---------------------------------------------------------------------------


def test_phase1_16_mirrors_every_admission_profile_column(src) -> None:
    """Re-derive the column list from the live ``AdmissionProfile`` model
    instead of hardcoding it. Memory ``verify-schema-before-proposing``: a
    later schema rename to source must not silently drift from the archive
    mirror — this check catches it."""
    from app.models.admission import AdmissionProfile

    source_columns = {c.name for c in AdmissionProfile.__table__.columns}
    missing = sorted(source_columns - _cot_khai_o_moi_migration())
    assert not missing, (
        f"bảng archive thiếu cột của AdmissionProfile: {missing}"
    )


def test_phase1_16_column_count_matches_source_plus_one(src) -> None:
    """Archive table = source columns + exactly 1 archive-metadata column
    (``archived_at``). No extra audit/discriminator columns until a
    multi-trigger archive lands."""
    from app.models.admission import AdmissionProfile

    source_count = len(AdmissionProfile.__table__.columns)
    unique = _cot_khai_o_moi_migration()
    assert len(unique) == source_count + 1, (
        f"Expected {source_count + 1} columns "
        f"({source_count} source + 1 archived_at), got {len(unique)}: {unique}"
    )


# ---------------------------------------------------------------------------
# 4. Archive metadata column
# ---------------------------------------------------------------------------


def test_phase1_16_archived_at_is_not_null_with_now_default(src) -> None:
    """``archived_at`` is the cron's INSERT marker — must not be nullable so
    every row carries a timestamp, and must default to ``now()`` so the cron
    INSERT statement does not need to set it explicitly."""
    # Match the multi-line column declaration via a single regex.
    pattern = re.compile(
        r'sa\.Column\(\s*"archived_at"[^)]*?'
        r'sa\.DateTime\(timezone=True\)[^)]*?'
        r'nullable=False[^)]*?'
        r'server_default=sa\.text\("now\(\)"\)',
        re.DOTALL,
    )
    assert pattern.search(src), "archived_at column shape mismatch"


# ---------------------------------------------------------------------------
# 5. Index per PLAN line 933-934
# ---------------------------------------------------------------------------


def test_phase1_16_creates_lead_year_composite_index(src) -> None:
    """PLAN line 931-934 mandates ``ix_archived_profile_lead_year`` on
    ``(lead_id, academic_year)`` — keeps ``Lead.current_admission_profile``
    UNION query (P1 fix #6 v2.12, PLAN line 911-928) fast against archive."""
    assert "ix_archived_profile_lead_year" in src
    # Regex tolerant to whitespace inside the column list.
    assert re.search(
        r'\[\s*"lead_id"\s*,\s*"academic_year"\s*\]', src
    ), "Index columns must be (lead_id, academic_year) in that order"


# ---------------------------------------------------------------------------
# 6. No FK / UQ / CHECK constraints
# ---------------------------------------------------------------------------


def test_phase1_16_declares_no_foreign_keys(src) -> None:
    """Archive must outlive source row deletes — no FK dependency on
    ``admission_profile.id`` / ``lead.id`` / ``user.id``."""
    assert "ForeignKey(" not in src


def test_phase1_16_declares_no_unique_constraints(src) -> None:
    """Wave 4 will swap the ``(lead_id)`` UNIQUE on ``admission_profile`` to
    composite ``(lead_id, academic_year)``. An archive row from BEFORE that
    swap must not be retroactively rejected — so the archive table mirrors
    NO unique surface."""
    assert "UniqueConstraint" not in src
    assert "unique=True" not in src


def test_phase1_16_declares_no_check_constraints(src) -> None:
    """Wave 3 ``phase1_11`` extends the status CHECK from 10 to 14 values.
    An archive row inserted before that extend must round-trip when the
    archive is re-queried — no CHECK on the archive table preserves it."""
    assert "CheckConstraint" not in src


# ---------------------------------------------------------------------------
# 7. ENUM reuse pattern
# ---------------------------------------------------------------------------


def test_phase1_16_reuses_conduct_grade_enum_without_creating(src) -> None:
    """``conduct_grade`` is owned by ``phase1_09a``. Archive table column
    must reference it with ``create_type=False`` so the migration does NOT
    try to ``CREATE TYPE`` again on a DB that already has it."""
    pattern = re.compile(
        r'postgresql\.ENUM\([^)]*?'
        r'name="conduct_grade"[^)]*?'
        r'create_type=False',
        re.DOTALL,
    )
    assert pattern.search(src), "conduct_grade ENUM must use create_type=False"


# ---------------------------------------------------------------------------
# 8. Idempotent guards
# ---------------------------------------------------------------------------


def test_phase1_16_upgrade_guards_table_create(src) -> None:
    """Idempotent re-run: a half-applied upgrade re-running must skip the
    ``CREATE TABLE`` if the table already exists."""
    assert "if not table_exists(TABLE):" in src


def test_phase1_16_upgrade_guards_index_create(src) -> None:
    assert "if not index_exists(TABLE, INDEX_LEAD_YEAR):" in src


def test_phase1_16_downgrade_short_circuits_when_table_missing(src) -> None:
    """Per ``phase1_19a`` template — drop_index against a missing parent
    table raises; downgrade returns early when the table is already gone."""
    pattern = re.compile(
        r"def downgrade\(\) -> None:\s*"
        r"(?:#[^\n]*\n\s*)*"
        r"if not table_exists\(TABLE\):\s*\n\s*return",
        re.MULTILINE,
    )
    assert pattern.search(src), (
        "downgrade() must short-circuit when the table is already gone"
    )


def test_phase1_16_downgrade_drops_index_before_table(src) -> None:
    """Even though ``DROP TABLE`` cascades indexes, the explicit
    ``drop_index`` call lets a half-applied downgrade resume safely."""
    # Find the relative ordering of drop_index and drop_table in downgrade.
    downgrade_block = src[src.index("def downgrade("):]
    drop_index_pos = downgrade_block.index("op.drop_index(")
    drop_table_pos = downgrade_block.index("op.drop_table(")
    assert drop_index_pos < drop_table_pos


# ---------------------------------------------------------------------------
# 9. Module sanity
# ---------------------------------------------------------------------------


def test_phase1_16_defines_upgrade_and_downgrade(phase1_16) -> None:
    assert callable(getattr(phase1_16, "upgrade", None))
    assert callable(getattr(phase1_16, "downgrade", None))


# ---------------------------------------------------------------------------
# 9. Parity KIỂU + NULLABLE (không chỉ tên cột)
# ---------------------------------------------------------------------------


def test_archive_khop_kieu_va_nullable_voi_admission_profile() -> None:
    """Parity theo TÊN thôi là chưa đủ cho câu INSERT liệt kê cột tường minh.

    Ca `..._mirrors_every_admission_profile_column` chỉ so TẬP TÊN. Một cột đúng
    tên nhưng sai kiểu (``String(20)`` cho chỗ cần ``String(40)``) hay sai
    nullability vẫn lọt, rồi vỡ đúng lúc cron archive chạy — nơi khó phát hiện
    nhất.

    Cố ý KHÔNG so ``server_default`` và KHÔNG so THỨ TỰ CỘT:
      - ``id``/``created_at``/``updated_at`` khác default một cách CỐ Ý (hàng
        archive giữ id + dấu thời gian GỐC, không sinh lại bằng nextval/now).
      - 62/64 cột chung nằm ở ordinal_position khác nhau; giao ước ghi archive
        vì thế là INSERT liệt kê cột tường minh, không phải SELECT * theo vị
        trí. Xem `test_khong_duong_ghi_nao_dung_select_sao_vao_bang_archive`.
    """
    from app.models.admission import AdmissionProfile

    dac_ta = _dac_ta_cot_tu_migration()
    lech = []
    for mc in AdmissionProfile.__table__.columns:
        if mc.name not in dac_ta:
            lech.append(f"{mc.name}: KHÔNG có trong bảng archive")
            continue
        kieu, nullable = dac_ta[mc.name]
        if kieu != str(mc.type):
            lech.append(f"{mc.name}: kiểu model={mc.type} archive={kieu}")
        if nullable != mc.nullable:
            lech.append(
                f"{mc.name}: nullable model={mc.nullable} archive={nullable}"
            )
    assert not lech, (
        "archive lech kieu/nullability so voi AdmissionProfile:\n"
        + "\n".join(lech)
    )


# ---------------------------------------------------------------------------
# 10. Cấm SELECT * ghi vào bảng archive
# ---------------------------------------------------------------------------


def test_khong_duong_ghi_nao_dung_select_sao_vao_bang_archive() -> None:
    """``INSERT INTO _archived_admission_profile … SELECT *`` là KHÔNG an toàn.

    Đo trên PostgreSQL 29-08-2026: 62 trên 64 cột chung nằm ở
    ``ordinal_position`` khác nhau — ngay cột thứ 3 của nguồn là ``citizen_id``
    còn của archive là ``offering_admission_config_id``. Ngoài ra ``archived_at``
    ở vị trí 65 nên mọi cột thêm về sau rơi xuống 66..77, SAU cột metadata.

    Hậu quả, phân loại 63 cặp lệch: 49 cặp kiểu KHÔNG tương thích, 12 cặp
    tương thích, 2 cặp khớp tên. Nên hôm nay ``SELECT *`` làm archive job ĐỔ
    chứ KHÔNG ghi sai im lặng — Postgres từ chối ngay cặp đầu::

        ERROR: column "offering_admission_config_id" is of type integer
               but expression is of type character varying

    Cái bẫy nằm ở 12 cặp tương thích: ở đó Postgres ghi im lặng (đo bằng bản
    thu nhỏ — hai cột ``varchar`` hoán vị cho ``INSERT 0 1``, không lỗi, giá
    trị đổi chỗ). Nên lối "sửa" bằng ``CAST`` cho vừa bộ kiểu là bẫy: nó dập
    tắt 49 cặp đang kêu và để nguyên 12 cặp hỏng. Ca này vì thế cấm hẳn dạng
    ``SELECT *``, không phải chỉ cấm dạng gây lỗi kiểu.

    Docstring gốc của phase1_16 hứa ngược lại (đã đính chính tại chỗ). Ca này
    tồn tại để lời hứa cũ không sống lại thành mã: cron
    ``archive_expired_rounds_task`` chưa được nối, nên đây là hàng rào dựng
    TRƯỚC khi có đường ghi, chứ không phải sau khi mất dữ liệu.
    """
    goc = _VERSIONS_DIR.parents[1]
    vi_pham = [
        str(f.relative_to(goc))
        for thu_muc in ("app", "alembic")
        for f in sorted((goc / thu_muc).rglob("*.py"))
        if _TABLE in f.read_text(encoding="utf-8")
        and _co_ghi_select_sao(f.read_text(encoding="utf-8"))
    ]
    assert not vi_pham, (
        "đường ghi archive dùng SELECT * theo vị trí (phải liệt kê cột đích "
        f"tường minh): {vi_pham}"
    )


# ---------------------------------------------------------------------------
# 11. arch20260829 — fail-closed khi bảng archive thiếu
# ---------------------------------------------------------------------------


class _InspectorGia:
    def __init__(self, ten_bang, ten_cot=()):
        self._bang = list(ten_bang)
        self._cot = [{"name": n} for n in ten_cot]

    def get_table_names(self):
        return self._bang

    def get_columns(self, _t):
        return self._cot


def test_arch20260829_nem_khi_bang_archive_thieu(monkeypatch) -> None:
    """Bảng THIẾU phải làm migration ĐỔ, không được lặng lẽ ``return``.

    Bản đầu trả về tập rỗng rồi return ngay. Alembic khi đó vẫn ghi
    ``arch20260829`` vào ``alembic_version`` và báo thành công trong khi KHÔNG
    cột nào được thêm — đúng lớp lỗi "lệnh trả 0 mà việc không xảy ra", và tệ
    hơn là lần chạy sau sẽ BỎ QUA revision này vĩnh viễn vì nó đã được đánh dấu
    là đã áp.

    Probe upgrade/downgrade không canh được nhánh này: nó luôn dựng sẵn bảng vỏ.
    """
    mod = _load_migration_by_revision("arch20260829")
    monkeypatch.setattr(mod.op, "get_bind", lambda: object())
    monkeypatch.setattr(mod, "inspect", lambda _bind: _InspectorGia([]))

    with pytest.raises(mod.BangArchiveThieu):
        mod.upgrade()
    with pytest.raises(mod.BangArchiveThieu):
        mod.downgrade()


def test_arch20260829_bo_qua_dung_cot_da_co(monkeypatch) -> None:
    """Bảng CÓ + một số cột đã tồn tại -> chỉ thêm đúng phần còn thiếu.

    Trạng thái này KHÁC hẳn "bảng thiếu" và phải được xử lý khác: nó là đường
    chạy lại bình thường (migration bị ngắt giữa chừng, hoặc cột đã được thêm
    tay), nên phải im lặng bỏ qua chứ không đổ.
    """
    mod = _load_migration_by_revision("arch20260829")
    da_them = []
    monkeypatch.setattr(mod.op, "get_bind", lambda: object())
    monkeypatch.setattr(mod.op, "add_column", lambda _t, col: da_them.append(col.name))

    # (a) đã có ĐỦ 12 cột -> không thêm gì
    monkeypatch.setattr(
        mod, "inspect", lambda _bind: _InspectorGia([mod.TABLE], ("id",) + mod._TEN_COT)
    )
    mod.upgrade()
    assert da_them == [], f"đã có đủ cột mà vẫn thêm: {da_them}"

    # (b) thiếu đúng hai cột -> thêm đúng hai cột ấy, không hơn không kém
    thieu = ("document_debt", "cached_readiness")
    con_lai = tuple(c for c in mod._TEN_COT if c not in thieu)
    monkeypatch.setattr(
        mod, "inspect", lambda _bind: _InspectorGia([mod.TABLE], ("id",) + con_lai)
    )
    da_them.clear()
    mod.upgrade()
    assert sorted(da_them) == sorted(thieu), f"thêm sai tập cột: {da_them}"


# ---------------------------------------------------------------------------
# 12. Bộ dò SELECT * — đối chứng bypass, PARAMETERIZED
# ---------------------------------------------------------------------------
#
# Trước đây các dạng bypass chỉ được kiểm bằng đột biến THỦ CÔNG ngoài kho:
# không ai chạy lại, và bản thân ca guard vẫn xanh dù bộ dò đã thủng. Bảng
# dưới đây đưa mọi dạng ấy VÀO kho, chạy mỗi lượt CI.
#
# Mỗi dòng là (nhãn, mã nguồn, có_phải_vi_phạm). Các dòng False là ĐỐI CHỨNG
# ÂM — chúng quan trọng ngang các dòng True: một bộ dò bắt tất cả, kể cả dạng
# đúng, thì vô dụng y như bộ dò không bắt gì.
#
# Đã audit ca nào canh cái gì, bằng cách TẮT hẳn renderer (chỉ chừa nhánh
# ``ast.Constant``) rồi xem ca nào còn xanh:
#
#   canh RENDERER (7): f-string-dich, noi-cong, format, phan-tram, join,
#                      alias-dong, ham-boc-ghep
#   canh REGEX    (5): literal, schema-qualified, alias-wildcard,
#                      select-distinct, ham-boc-literal
#
# Nhóm thứ hai đi qua đường chuỗi hằng nên xanh kể cả khi renderer chết — hữu
# ích cho mẫu regex, nhưng ĐỪNG đọc chúng thành bằng chứng renderer còn sống.

_T = "_archived_admission_profile"

_CA_BO_DO = [
    # ----- phải BẮT -----
    ("literal", 'op.execute("INSERT INTO ' + _T + ' SELECT *, now() FROM ap")', True),
    (
        "schema-qualified",
        'op.execute("INSERT INTO public.' + _T + ' SELECT * FROM ap")',
        True,
    ),
    (
        "alias-wildcard",
        'op.execute("INSERT INTO ' + _T + ' SELECT ap.* FROM admission_profile ap")',
        True,
    ),
    ("f-string-dich", 'op.execute(f"INSERT INTO {TABLE} SELECT * FROM ap")', True),
    (
        "noi-cong",
        'op.execute("INSERT INTO " + TABLE + " SELECT * FROM ap")',
        True,
    ),
    (
        "format",
        'op.execute("INSERT INTO {} SELECT * FROM ap".format(TABLE))',
        True,
    ),
    (
        "phan-tram",
        'op.execute("INSERT INTO %s SELECT * FROM ap" % TABLE)',
        True,
    ),
    (
        "join",
        'op.execute(" ".join(["INSERT INTO", TABLE, "SELECT * FROM ap"]))',
        True,
    ),
    (
        "alias-dong",
        'op.execute(f"INSERT INTO ' + _T + ' SELECT {ALIAS}.* FROM ap {ALIAS}")',
        True,
    ),
    (
        "ham-boc-literal",
        'op.execute(textwrap.dedent("INSERT INTO ' + _T + ' SELECT * FROM ap"))',
        True,
    ),
    # Ca ham-boc-GHEP mới là ca load-bearing cho nhánh "hàm bọc" của renderer.
    # Ca literal ngay trên KHÔNG phải: `ast.walk` vẫn thấy chuỗi hằng nằm bên
    # trong `dedent(...)` nên nó bị bắt kể cả khi nhánh hàm bọc bị gỡ — đã đo
    # bằng đột biến. Ở đây câu lệnh bị CẮT ĐÔI qua một lời gọi, nên không nút
    # đơn lẻ nào chứa cả INSERT lẫn SELECT; nhánh hàm bọc phải trả đúng phần
    # gốc thì hai nửa mới nối lại được.
    (
        "ham-boc-ghep",
        'op.execute(("INSERT INTO " + TABLE).strip() + " SELECT * FROM ap")',
        True,
    ),
    (
        "select-distinct",
        'op.execute("INSERT INTO ' + _T
        + ' SELECT DISTINCT * FROM ap")',
        True,
    ),
    # ----- KHÔNG được bắt (đối chứng âm) -----
    (
        "liet-ke-cot",
        'op.execute("INSERT INTO ' + _T + ' (id, lead_id) SELECT id, lead_id FROM ap")',
        False,
    ),
    (
        "select-sao-bang-khac",
        'op.execute("INSERT INTO bang_khac SELECT * FROM ap")',
        False,
    ),
    (
        "chi-doc",
        'rows = conn.execute("SELECT * FROM ' + _T + '")',
        False,
    ),
    (
        "docstring-noi-ve-no",
        'def f():\n    """INSERT INTO ' + _T
        + ' SELECT * — mô tả vì sao KHÔNG được làm."""\n    return 1',
        False,
    ),
]


@pytest.mark.parametrize(
    "nhan, ma_nguon, vi_pham",
    _CA_BO_DO,
    ids=[c[0] for c in _CA_BO_DO],
)
def test_bo_do_select_sao_bat_moi_dang(nhan: str, ma_nguon: str, vi_pham: bool) -> None:
    """Bộ dò phải bắt mọi dạng dựng chuỗi, và CHỈ bắt dạng thật sự sai."""
    assert _co_ghi_select_sao(ma_nguon) is vi_pham, (
        f"dạng {nhan!r}: mong {'BẮT' if vi_pham else 'BỎ QUA'}, "
        f"nhưng bộ dò trả {not vi_pham}"
    )
