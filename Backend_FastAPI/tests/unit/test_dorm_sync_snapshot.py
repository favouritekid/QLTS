# -*- coding: utf-8 -*-
"""Ảnh chụp nguồn v1 và token xem trước.

🔴 Cả file này canh MỘT bất biến: **thứ người bấm đã nhìn phải là thứ được
ghi**. Dấu băm nguồn trả lời "danh sách có đổi không"; token trả lời "ai duyệt,
cho năm nào, và còn hiệu lực không".

Hai kiểu hỏng ngược nhau, đều phải chặn:

* dấu băm ĐỔI khi dữ liệu không đổi ⇒ chốt chặn nhầm những lượt bình thường,
  rồi có người "sửa" bằng cách bỏ chốt;
* dấu băm KHÔNG đổi khi dữ liệu đã đổi ⇒ chốt cho qua đúng lúc phải chặn.
"""

import uuid

import pytest
from types import SimpleNamespace

from app.services.dorm_sync_snapshot import (
    SNAPSHOT_VERSION,
    TOKEN_TTL_GIAY,
    TOKEN_VERSION,
    build_source_snapshot,
    doc_token,
    hash_source_snapshot,
    phat_hanh_token,
)
from app.utils.exceptions import DormSyncTokenError

pytestmark = pytest.mark.unit

_KHOA = "khoa-ky-test"


def _row(**ghi_de):
    base = dict(
        qlts_profile_id=9001,
        full_name="Nguyễn Văn An",
        source_gender_raw="Nam",
        program_name="Cao đẳng Điều dưỡng",
        degree_level="Cao đẳng",
        academic_year=2026,
        officer_qlts_id=101,
        unit_id=14,
        profile_status="confirmed",
        contact_phone="0912345678",
        contact_phone2=None,
        # Hai trường của LƯỢT — không được vào snapshot.
        last_seen_sync_id=7,
        synced_at="2026-08-07T00:00:00+00:00",
    )
    base.update(ghi_de)
    return SimpleNamespace(**base)


def _bam(rows):
    return hash_source_snapshot(build_source_snapshot(rows))


# ---------------------------------------------------------------------------
# Dấu băm nguồn — ổn định đúng chỗ, đổi đúng chỗ
# ---------------------------------------------------------------------------


def test_cung_du_lieu_thi_cung_dau_bam():
    """Gọi hai lần trên cùng dữ liệu phải ra cùng một chuỗi.

    Không có bất biến này thì chốt chặn MỌI lượt: người bấm xem trước lúc 9h00,
    bấm ghi lúc 9h01, và dấu băm đã khác.
    """
    rows = [_row(), _row(qlts_profile_id=9002)]

    assert _bam(rows) == _bam(rows)
    assert len(_bam(rows)) == 64


@pytest.mark.parametrize(
    "ghi_de",
    [
        {"contact_phone": "0987654321"},
        {"contact_phone2": "0900000000"},
        {"degree_level": "Trung cấp"},
        {"profile_status": "draft"},
        {"full_name": "Nguyễn Văn Bình"},
        {"program_name": "Cao đẳng Dược"},
        {"source_gender_raw": "Nữ"},
        {"officer_qlts_id": 102},
        {"unit_id": 15},
    ],
)
def test_doi_mot_truong_NGUON_thi_dau_bam_doi(ghi_de):
    """Từng trường một, không gộp.

    Ca gộp chỉ chứng minh "có gì đó đổi thì băm đổi" — nó xanh cả khi tám
    trường còn lại bị bỏ quên khỏi ảnh chụp.

    ``profile_status`` nằm trong danh sách vì nó quyết định TƯ CÁCH của hàng:
    một hồ sơ về `draft` rơi khỏi cohort ở lượt sau, và đó là thay đổi thật.
    """
    assert _bam([_row()]) != _bam([_row(**ghi_de)])


@pytest.mark.parametrize(
    "ghi_de",
    [
        {"last_seen_sync_id": 999},
        {"synced_at": "2027-01-01T00:00:00+00:00"},
        {"last_seen_sync_id": 999, "synced_at": "2027-01-01T00:00:00+00:00"},
    ],
)
def test_doi_rieng_dau_vet_cua_LUOT_thi_dau_bam_KHONG_doi(ghi_de):
    """🔴 Vế ngược, và nó quan trọng ngang vế trên.

    ``last_seen_sync_id`` và ``synced_at`` đổi ở MỌI lần chạy. Đưa chúng vào
    ảnh chụp thì hai lần xem trước liên tiếp trên cùng dữ liệu cho hai dấu băm
    khác nhau, và chốt chặn tất cả — rồi cách "sửa" tự nhiên nhất là bỏ chốt.
    """
    assert _bam([_row()]) == _bam([_row(**ghi_de)])


def test_dao_thu_tu_hang_thi_dau_bam_KHONG_doi():
    """Thứ tự từ ``fetch_cohort`` là thứ tự kế hoạch thực thi, không phải dữ liệu."""
    a = _row(qlts_profile_id=9001)
    b = _row(qlts_profile_id=9002)
    c = _row(qlts_profile_id=9003)

    assert _bam([a, b, c]) == _bam([c, a, b]) == _bam([b, c, a])


def test_them_bot_hang_thi_dau_bam_doi():
    """Vế ĐẢO của ca trên: sắp lại thì không đổi, nhưng THIẾU một người thì có."""
    a, b = _row(qlts_profile_id=9001), _row(qlts_profile_id=9002)

    assert _bam([a, b]) != _bam([a])


def test_chuoi_NFD_va_NFC_cho_cung_dau_bam():
    """Tiếng Việt có hai cách mã hoá cùng một chữ, giống hệt trên màn hình.

    Không chuẩn hoá thì một thay đổi vô hình ở tầng nhập liệu làm dấu băm đổi,
    và chốt chặn một lượt bình thường bằng một lý do không ai nhìn thấy được.
    """
    import unicodedata

    ten = "Nguyễn Văn An"
    assert _bam([_row(full_name=unicodedata.normalize("NFC", ten))]) == _bam(
        [_row(full_name=unicodedata.normalize("NFD", ten))]
    )


def test_dau_bam_KHONG_phu_thuoc_THU_TU_KHOA():
    """JSON canonical phải sắp KHOÁ, không dựa vào thứ tự chèn của dict.

    Python giữ thứ tự chèn nên hôm nay hai bên luôn khớp — và chính vì thế
    ``sort_keys=True`` gỡ ra vẫn xanh cả bộ. Nhưng dấu băm này còn phải khớp
    qua những đường không do ta dựng dict: một bản ghi đọc lại từ JSON, từ
    database, hay từ một phiên bản sau có thứ tự trường khác.

    ⚠️ Ca này CỐ Ý dựng lại dict theo thứ tự ngược để phép sắp khoá là thứ
    duy nhất giữ cho hai dấu băm bằng nhau.
    """
    snapshot = build_source_snapshot([_row(), _row(qlts_profile_id=9002)])
    dao_khoa = {
        "version": snapshot["version"],
        "row_count": snapshot["row_count"],
        "rows": [dict(reversed(list(h.items()))) for h in snapshot["rows"]],
    }

    assert hash_source_snapshot(snapshot) == hash_source_snapshot(dao_khoa)


def test_so_chu_ky_dung_compare_digest():
    """🔴 Thuộc tính THỜI GIAN — không có hành vi nào để quan sát.

    ``==`` và ``hmac.compare_digest`` cho cùng kết quả ở mọi đầu vào; thứ khác
    nhau là ``==`` thoát ngay tại byte đầu tiên lệch, và thời gian thoát ấy rò
    rỉ chữ ký đúng từng byte một cho người đang dò.

    Không một ca kiểm hành vi nào phân biệt được hai bản — kiểm ngược đổi sang
    ``==`` cho 34/34 xanh. Nên bất biến này khoá ở MỨC MÃ NGUỒN, và ca này nói
    rõ vì sao nó phải là ngoại lệ thay vì giả vờ kiểm hành vi.
    """
    import inspect

    from app.services.dorm_sync_snapshot import doc_token

    ma = inspect.getsource(doc_token)

    assert "hmac.compare_digest(" in ma
    # Và không có đường so trực tiếp nào lọt lại.
    assert "!= chu_ky" not in ma
    assert "== chu_ky" not in ma


def test_snapshot_KHONG_chua_dau_vet_cua_luot():
    """Soi thẳng cấu trúc, không chỉ dấu băm.

    Dấu băm là một chiều: nó cho biết hai thứ khác nhau, nhưng không cho biết
    thứ gì đang nằm trong đó.
    """
    snapshot = build_source_snapshot([_row()])

    assert snapshot["version"] == SNAPSHOT_VERSION
    assert snapshot["row_count"] == 1

    hang = snapshot["rows"][0]
    assert "last_seen_sync_id" not in hang
    assert "synced_at" not in hang
    assert hang["profile_status"] == "confirmed"
    assert len(hang) == 13, f"phải là 12 trường ổn định + profile_status: {sorted(hang)}"


def test_snapshot_dung_CHUNG_helper_voi_payload_gui_di():
    """🔴 Một nguồn, hai lối vào — không hai dictionary song song.

    Viết hai danh sách trường song song là cách chắc chắn nhất để chúng lệch:
    thêm một cột vào payload mà quên snapshot thì dấu băm nói "không có gì đổi"
    cho một lượt thật sự đổi dữ liệu.
    """
    from app.services.dorm_sync_service import (
        TRUONG_PAYLOAD_ON_DINH,
        build_student_payload,
    )

    payload = build_student_payload(_row(), sync_run_id=7, synced_at="x")
    hang = build_source_snapshot([_row()])["rows"][0]

    for ten in TRUONG_PAYLOAD_ON_DINH:
        assert payload[ten] == hang[ten], ten

    # Payload = phần ổn định + ĐÚNG hai trường của lượt.
    assert set(payload) - set(TRUONG_PAYLOAD_ON_DINH) == {
        "last_seen_sync_id",
        "synced_at",
    }


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------


def _phat(**ghi_de):
    tham_so = dict(
        secret=_KHOA,
        actor_id=7,
        academic_year=2026,
        source_hash="a" * 64,
        target_fingerprint="b" * 32,
        now_ts=1_000_000,
    )
    tham_so.update(ghi_de)
    return phat_hanh_token(**tham_so)


def test_phat_roi_doc_lai_duoc():
    token, claims = _phat()

    doc = doc_token(token, secret=_KHOA, actor_id=7, now_ts=1_000_100)

    assert doc.version == TOKEN_VERSION
    assert doc.operation_id == claims.operation_id
    assert doc.actor_id == 7
    assert doc.academic_year == 2026
    assert doc.source_hash == "a" * 64
    assert doc.target_fingerprint == "b" * 32
    assert doc.expires_at - doc.issued_at == TOKEN_TTL_GIAY


def test_operation_id_do_SERVER_sinh_va_moi_lan_mot_khac():
    """Client không đặt được — nếu đặt được thì chống-replay là vô nghĩa.

    Người gọi tự sinh một giá trị mới ở mỗi lần thử là chạy được bao nhiêu lượt
    tuỳ ý, và sổ cái ``dorm_sync_operations`` không bao giờ thấy trùng.
    """
    _, mot = _phat()
    _, hai = _phat()

    assert mot.operation_id != hai.operation_id
    assert isinstance(mot.operation_id, uuid.UUID)

    # Và hợp đồng HTTP cũng không có cửa cho nó — xem `DormSyncApplyRequest`.
    from app.schemas.dorm_sync import DormSyncApplyRequest

    assert "operation_id" not in DormSyncApplyRequest.model_fields


def test_token_KHONG_chua_du_lieu_ca_nhan():
    """🔴 HMAC ký, KHÔNG mã hoá.

    Thân token là base64url — ai cầm chuỗi cũng đọc được. Nhét họ tên hay số
    điện thoại vào đây là phát tán danh sách người học qua thanh địa chỉ, log
    proxy và lịch sử trình duyệt.

    ⚠️ Giải thân ra rồi SOI, không chỉ tìm chuỗi trong token: base64 làm mọi
    phép `in` trên chuỗi gốc luôn sai âm tính.
    """
    import base64
    import json

    token, _ = _phat()
    than_b64 = token.split(".")[0]
    than = json.loads(
        base64.urlsafe_b64decode(than_b64 + "=" * ((-len(than_b64)) % 4))
    )

    van_ban = json.dumps(than, ensure_ascii=False)
    assert "Nguyễn" not in van_ban
    assert "0912345678" not in van_ban
    assert "full_name" not in than and "rows" not in than
    # Chỉ 8 khoá đã khai, không có gì lọt thêm vào.
    assert set(than) == {"v", "op", "actor", "year", "iat", "exp", "src", "tgt"}


def test_sua_than_token_thi_bi_tu_choi():
    """Sửa một byte của thân là chữ ký không còn khớp."""
    import base64
    import json

    token, _ = _phat()
    than_b64, _chu_ky = token.split(".")
    than = json.loads(
        base64.urlsafe_b64decode(than_b64 + "=" * ((-len(than_b64)) % 4))
    )
    than["year"] = 2025  # đổi năm học — chính là phạm vi của lượt ghi
    than_moi = (
        base64.urlsafe_b64encode(
            json.dumps(than, sort_keys=True, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )

    with pytest.raises(DormSyncTokenError):
        doc_token(f"{than_moi}.{_chu_ky}", secret=_KHOA, actor_id=7, now_ts=1_000_100)


def test_sai_khoa_ky_thi_bi_tu_choi():
    token, _ = _phat()

    with pytest.raises(DormSyncTokenError):
        doc_token(token, secret="khoa-khac", actor_id=7, now_ts=1_000_100)


def test_sai_actor_thi_bi_tu_choi():
    """🔴 Token là giấy phép chạy một lượt hạ cờ, không phải một cái vé chung.

    Một admin khác nhặt được chuỗi này (từ log, từ màn hình chia sẻ) mà dùng
    lại được thì nhật ký ghi tên người phát hành cho thao tác của người khác.
    """
    token, _ = _phat(actor_id=7)

    with pytest.raises(DormSyncTokenError):
        doc_token(token, secret=_KHOA, actor_id=8, now_ts=1_000_100)


def test_het_TTL_thi_bi_tu_choi():
    token, _ = _phat(now_ts=1_000_000)

    # Còn sống ở giây cuối cùng...
    doc_token(token, secret=_KHOA, actor_id=7, now_ts=1_000_000 + TOKEN_TTL_GIAY - 1)

    # ...và chết ngay tại mốc hết hạn.
    with pytest.raises(DormSyncTokenError):
        doc_token(token, secret=_KHOA, actor_id=7, now_ts=1_000_000 + TOKEN_TTL_GIAY)


def test_thoi_diem_phat_hanh_o_TUONG_LAI_thi_bi_tu_choi():
    """Chữ ký đúng mà ``iat`` ở tương lai nghĩa là nó không do đường này sinh ra."""
    token, _ = _phat(now_ts=2_000_000)

    with pytest.raises(DormSyncTokenError):
        doc_token(token, secret=_KHOA, actor_id=7, now_ts=1_000_000)


def test_khoang_song_bat_thuong_thi_bi_tu_choi():
    """``exp - iat`` phải ĐÚNG bằng TTL, dù chữ ký hợp lệ.

    Một token có khoảng sống khác nghĩa là nó được ký bởi một đường phát hành
    khác — ví dụ cùng khoá bị dùng lại ở nơi khác với TTL dài hơn.
    """
    import base64
    import json

    from app.services.dorm_sync_snapshot import _ky

    than = {
        "v": TOKEN_VERSION,
        "op": str(uuid.uuid4()),
        "actor": 7,
        "year": 2026,
        "iat": 1_000_000,
        "exp": 1_000_000 + 86400,  # một ngày, không phải 5 phút
        "src": "a" * 64,
        "tgt": "b" * 32,
    }
    thoi = json.dumps(than, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    token = f"{base64.urlsafe_b64encode(thoi).decode().rstrip('=')}.{_ky(thoi, _KHOA)}"

    with pytest.raises(DormSyncTokenError):
        doc_token(token, secret=_KHOA, actor_id=7, now_ts=1_000_100)


def test_sai_phien_ban_thi_bi_tu_choi():
    import base64
    import json

    from app.services.dorm_sync_snapshot import _ky

    than = {
        "v": TOKEN_VERSION + 1,
        "op": str(uuid.uuid4()),
        "actor": 7,
        "year": 2026,
        "iat": 1_000_000,
        "exp": 1_000_000 + TOKEN_TTL_GIAY,
        "src": "a" * 64,
        "tgt": "b" * 32,
    }
    thoi = json.dumps(than, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    token = f"{base64.urlsafe_b64encode(thoi).decode().rstrip('=')}.{_ky(thoi, _KHOA)}"

    with pytest.raises(DormSyncTokenError):
        doc_token(token, secret=_KHOA, actor_id=7, now_ts=1_000_100)


@pytest.mark.parametrize(
    "xau", ["", "khong-co-cham", "a.b.c", "....", "!!!.???"]
)
def test_token_sai_dinh_dang_thi_tu_choi_chu_khong_no(xau):
    with pytest.raises(DormSyncTokenError):
        doc_token(xau, secret=_KHOA, actor_id=7, now_ts=1_000_100)


def test_thieu_khoa_ky_thi_tu_choi_ca_hai_chieu():
    """Khoá rỗng KHÔNG được coi là một khoá hợp lệ.

    Nếu ``SECRET_KEY`` chưa đặt mà vẫn ký được thì mọi token đều xác thực với
    cùng một khoá rỗng — tức ai cũng ký được.
    """
    with pytest.raises(DormSyncTokenError):
        _phat(secret="")

    token, _ = _phat()
    with pytest.raises(DormSyncTokenError):
        doc_token(token, secret="", actor_id=7, now_ts=1_000_100)
