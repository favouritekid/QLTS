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


# ---------------------------------------------------------------------------
# Ca CHÉO — số liệu trên màn hình đổi thì dấu băm phải đổi
# ---------------------------------------------------------------------------
#
# 🔴 Khoảng hở đã đo được, không phải giả định.
#
# Bảy số liệu khuyến cáo đếm trên giá trị THÔ; `rows` mang giá trị đã qua
# `chuan_hoa_so`. Có những thay đổi chỉ MỘT bên nhìn thấy — và với chúng, admin
# xem một bộ số, dữ liệu đổi trước khi ghi, mà phiếu vẫn hợp lệ.


def test_CHEO_so_qua_dai_doi_thanh_de_trong():
    """🔴 Số dài quá trần → để trống: hai con số trên màn hình đổi CHỖ cho nhau.

    "Không có số liên hệ" tăng, "số bị bỏ vì quá dài" giảm. Nhưng
    ``chuan_hoa_so`` biến số quá dài thành ``None`` từ trước, nên phần ``rows``
    của ảnh chụp GIỐNG HỆT ở cả hai trạng thái.

    Đo trước khi vá: số liệu đổi từ (không có số=0, quá dài=1) sang (1, 0) mà
    ``source_hash`` không đổi một ký tự.
    """
    dai = "0" * 21
    truoc = [_row(contact_phone=dai, contact_phone2=None)]
    sau = [_row(contact_phone=None, contact_phone2=None)]

    # Bằng chứng khoảng hở CÓ THẬT: phần `rows` của hai bên là một.
    assert (
        build_source_snapshot(truoc)["rows"] == build_source_snapshot(sau)["rows"]
    ), "ca dựng sai: hai trạng thái phải trùng nhau ở phần payload"
    # Nhưng số liệu thì khác...
    assert (
        build_source_snapshot(truoc)["counts"]
        != build_source_snapshot(sau)["counts"]
    )
    # ...nên dấu băm PHẢI khác.
    assert _bam(truoc) != _bam(sau)


def test_CHEO_so_phu_khac_o_dang_tho_nhung_trung_sau_chuan_hoa():
    """🔴 " 0912 " → "0912" trùng số chính: "có số phụ" về 0.

    ``chuan_hoa_so`` cắt khoảng trắng rồi loại ô phụ vì trùng ô chính, nên
    payload đã là ``None`` ở cả hai trạng thái. Chỉ phép đếm — vốn nhìn giá trị
    thô — thấy sự khác biệt.
    """
    chinh = "0912345678"
    truoc = [_row(contact_phone=chinh, contact_phone2=f"  {chinh}  ")]
    sau = [_row(contact_phone=chinh, contact_phone2=chinh)]

    assert (
        build_source_snapshot(truoc)["rows"] == build_source_snapshot(sau)["rows"]
    ), "ca dựng sai: hai trạng thái phải trùng nhau ở phần payload"
    assert _bam(truoc) != _bam(sau)


def test_CHEO_payload_va_so_lieu_deu_khong_doi_thi_dau_bam_KHONG_doi():
    """Vế ĐẢO — giữ cho bản vá không đi quá tay.

    Nếu ``counts`` nhặt thêm thứ gì đổi theo mỗi lần chạy (mốc thời gian, thứ
    tự, id lượt) thì hai lần xem trước liên tiếp cho hai dấu băm khác nhau và
    chốt chặn tất cả — đúng kiểu hỏng mà cả bộ này đang canh ở chiều ngược lại.
    """
    rows = [_row(), _row(qlts_profile_id=9002, contact_phone2="0900000002")]

    assert _bam(rows) == _bam(list(rows))
    # Và một thay đổi KHÔNG chạm cả payload lẫn số liệu cũng không được đổi băm.
    assert _bam(rows) == _bam(
        [_row(last_seen_sync_id=999), _row(qlts_profile_id=9002, contact_phone2="0900000002")]
    )


def test_so_lieu_trong_anh_chup_LA_bo_hien_thi_cho_nguoi_bam():
    """Cùng MỘT helper, không hai công thức.

    Viết một phép đếm thứ hai cho ảnh chụp là dựng lại đúng khoảng hở vừa bịt:
    hai công thức sẽ lệch ngay lần sửa đầu, và lúc đó cái được ký lại không
    phải cái được hiển thị.
    """
    from dataclasses import asdict

    from app.services.dorm_sync_snapshot import dem_so_lieu_nguon

    rows = [_row(), _row(qlts_profile_id=9002, source_gender_raw="?")]

    assert build_source_snapshot(rows)["counts"] == asdict(dem_so_lieu_nguon(rows))


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
    # Đảo thứ tự khoá ở CẢ root, CẢ từng hàng, CẢ khối `counts`.
    dao_khoa = dict(
        reversed(
            list(
                {
                    **snapshot,
                    "counts": dict(reversed(list(snapshot["counts"].items()))),
                    "rows": [
                        dict(reversed(list(h.items()))) for h in snapshot["rows"]
                    ],
                }.items()
            )
        )
    )

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


def test_token_mang_SNAPSHOT_VERSION_va_dau_bam_gop():
    """🔴 Sổ cái lưu hai giá trị này, nên token phải chở đủ cả hai.

    ``snapshot_version`` KHÁC ``TOKEN_VERSION``: hai thứ đổi vì hai lý do —
    một cái khi tập trường ảnh chụp đổi, một cái khi hình dạng token đổi. Ghi
    ``TOKEN_VERSION`` vào cột ``snapshot_version`` của sổ là ghi một con số nói
    về chuyện khác, và mọi phép đối soát sau này đọc sai.

    ``snapshot_hash`` là dấu GỘP nguồn + đích: trạng thái mà lượt chạy trên là
    một CẶP, và lưu riêng hai nửa thì mọi lần đối soát phải tự nhớ ghép lại.
    """
    from app.services.dorm_sync_snapshot import (
        SNAPSHOT_VERSION,
        hash_combined_snapshot,
    )

    token, claims = _phat()

    assert claims.snapshot_version == SNAPSHOT_VERSION
    assert claims.snapshot_hash == hash_combined_snapshot("a" * 64, "b" * 32)
    assert len(claims.snapshot_hash) == 64
    # Và nó KHÁC cả hai nửa — không phải chỉ chép lại một trong hai.
    assert claims.snapshot_hash not in ("a" * 64, "b" * 32)

    doc = doc_token(token, secret=_KHOA, actor_id=7, now_ts=1_000_100)
    assert doc.snapshot_version == claims.snapshot_version
    assert doc.snapshot_hash == claims.snapshot_hash


def test_snapshot_version_KHONG_lay_tu_TOKEN_VERSION(monkeypatch):
    """🔴 Hai hằng số hôm nay ĐỀU bằng 1 — nên ca thường không phân biệt được.

    Kiểm ngược đổi ``snapshot_version=SNAPSHOT_VERSION`` thành ``TOKEN_VERSION``
    cho 48/48 xanh. Chúng chỉ tách nhau vào ngày một trong hai tăng, mà đúng
    ngày đó sổ cái bắt đầu ghi một con số nói về chuyện khác — và không có gì
    báo động.

    Ca này TÁCH chúng ra bằng cách dời ``SNAPSHOT_VERSION`` đi, rồi đòi claim
    đi theo nó chứ không theo ``TOKEN_VERSION``.
    """
    import app.services.dorm_sync_snapshot as m

    monkeypatch.setattr(m, "SNAPSHOT_VERSION", 99)

    _, claims = _phat()

    assert claims.snapshot_version == 99
    assert claims.snapshot_version != m.TOKEN_VERSION


def test_dau_bam_gop_doi_khi_MOT_TRONG_HAI_nua_doi():
    """Vế ĐẢO: đổi riêng nguồn, hoặc riêng đích, dấu gộp đều phải đổi.

    Không có vế này thì một công thức gộp bỏ quên một nửa vẫn xanh.
    """
    from app.services.dorm_sync_snapshot import hash_combined_snapshot

    goc = hash_combined_snapshot("a" * 64, "b" * 32)

    assert hash_combined_snapshot("c" * 64, "b" * 32) != goc
    assert hash_combined_snapshot("a" * 64, "d" * 32) != goc


def test_dau_bam_gop_khong_nhat_quan_thi_TU_CHOI():
    """Chữ ký đúng vẫn chưa đủ: ba trường phải NHẤT QUÁN với nhau.

    Chữ ký bảo đảm không ai sửa được từng trường, nhưng không bảo đảm chúng nói
    cùng một chuyện. Một đường phát hành viết sai — hoặc một phiên bản sau đổi
    công thức gộp mà quên đổi version — sẽ ký ra token hợp lệ mà sổ cái lưu một
    dấu không nói về hai dấu kia.
    """
    import base64
    import json
    import uuid as _uuid

    from app.services.dorm_sync_snapshot import SNAPSHOT_VERSION, _ky

    than = {
        "v": TOKEN_VERSION,
        "op": str(_uuid.uuid4()),
        "actor": 7,
        "year": 2026,
        "iat": 1_000_000,
        "exp": 1_000_000 + TOKEN_TTL_GIAY,
        "src": "a" * 64,
        "tgt": "b" * 32,
        "snap_v": SNAPSHOT_VERSION,
        "snap": "0" * 64,  # không dựng lại được từ src + tgt
    }
    thoi = json.dumps(than, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    token = f"{base64.urlsafe_b64encode(thoi).decode().rstrip('=')}.{_ky(thoi, _KHOA)}"

    with pytest.raises(DormSyncTokenError):
        doc_token(token, secret=_KHOA, actor_id=7, now_ts=1_000_100)


def test_moi_loi_token_ra_ngoai_CUNG_MOT_thong_diep():
    """🔴 Lý do token hỏng KHÔNG được ra HTTP.

    Phân biệt "chữ ký sai" với "hết hạn" hay "sai actor" cho phía ngoài là đưa
    cho người đang dò một tín hiệu để dò tiếp: họ biết chuỗi nào bị chặn vì
    chưa ký đúng, chuỗi nào đã ký đúng mà chỉ quá giờ.

    ⚠️ Đi qua ĐÚNG handler thật — chính nó quyết định cái gì ra tới client.
    """
    import asyncio
    import json

    from app.middleware.exception_handlers import base_app_exception_handler

    token_hop_le, _ = _phat()
    cac_ca = [
        lambda: doc_token(token_hop_le, secret="khoa-khac", actor_id=7, now_ts=1_000_100),
        lambda: doc_token(token_hop_le, secret=_KHOA, actor_id=8, now_ts=1_000_100),
        lambda: doc_token(
            token_hop_le, secret=_KHOA, actor_id=7,
            now_ts=1_000_000 + TOKEN_TTL_GIAY,
        ),
        lambda: doc_token("rac", secret=_KHOA, actor_id=7, now_ts=1_000_100),
    ]

    yeu_cau = SimpleNamespace(
        url=SimpleNamespace(path="/api/v2/admin/dorm-sync/apply"), method="POST"
    )
    vong = asyncio.get_event_loop_policy().new_event_loop()

    than_thay = set()
    for goi in cac_ca:
        with pytest.raises(DormSyncTokenError) as bat:
            goi()
        phan_hoi = vong.run_until_complete(
            base_app_exception_handler(yeu_cau, bat.value)
        )
        du_lieu = json.loads(phan_hoi.body.decode())
        assert phan_hoi.status_code == 409
        assert du_lieu["error_code"] == "DORM_SYNC_TOKEN_INVALID"
        than_thay.add(du_lieu["detail"])
        # Chi tiết vẫn còn cho người vận hành.
        assert bat.value.operator_detail

    assert len(than_thay) == 1, f"bốn ca lộ ra {len(than_thay)} thông điệp khác nhau"


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
    # Chỉ những khoá đã khai, không có gì lọt thêm vào.
    assert set(than) == {
        "v", "op", "actor", "year", "iat", "exp", "src", "tgt", "snap_v", "snap",
    }


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
