"""Unit tests for the enrollment-letter PDF renderer.

Covers the code-review findings on the render layer:
- A05 injection: candidate data is XML-escaped before entering ReportLab
  Paragraph markup (a raw '&' must not crash; a crafted <img> must not be
  fetched/interpreted).
- Degree level is NOT printed twice (MajorProgram.name already carries it).
- The fee 'Tổng cộng' is floored at 0 (never negative on an official document).
- LAYOUT: the letter must stay on ONE page — on either font stack, and with the
  longest data the system can hold.
"""
import datetime
import io

import pytest

from app.services import admission_pdf_service as pdf

pypdf = pytest.importorskip("pypdf")


@pytest.fixture
def reset_font_state():
    """Cô lập stack font đã bind (biến module ``_active_fonts``).

    Đủ để chỉ khôi phục biến, VÌ mỗi stack đăng ký dưới TÊN RIÊNG
    ('LetterSerif-Liberation' / 'LetterSerif-DejaVu'). Trước đây cả hai dùng
    chung một tên, mà ``pdfmetrics.registerFont`` là first-bind-wins: bind lần
    hai là no-op im lặng, nên teardown KHÔNG thể trả registry về cũ và test
    sau vô tình render bằng font của test trước (đã tái hiện: chạy test fallback
    trước test layout → 2 FAILED).
    """
    saved_stacks = pdf._FONT_STACKS
    saved_active = pdf._active_fonts
    yield
    pdf._FONT_STACKS = saved_stacks
    pdf._active_fonts = saved_active


def _base_data(**overrides):
    d = dict(
        full_name="Nguyễn Văn A",
        dob=datetime.date(2005, 1, 2),
        permanent_address="Số 1, Phường Tân An, Đắk Lắk",
        major_name="Cao đẳng Dược",
        degree_level="Cao đẳng",
        offering_type="Chính quy",
        hk1_fee_amount=6_500_000,
        enrollment_start_date=datetime.date(2026, 7, 28),
        enrollment_end_date=datetime.date(2026, 8, 5),
        phone="0906123456",
    )
    d.update(overrides)
    return d


def _text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "".join((p.extract_text() or "") for p in reader.pages)


def _page_count(pdf_bytes: bytes) -> int:
    """Đếm trang bằng pypdf, KHÔNG bằng pdftotext: pdftotext chèn form-feed giả
    và báo 2 trang cho một PDF một trang."""
    return len(pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


# Bộ dữ liệu dài nhất hệ thống có thể sinh: họ tên ghép, địa chỉ tràn 2 dòng,
# tên ngành đầy đủ, hệ đào tạo mô tả dài.
_LONGEST = dict(
    full_name="Nguyễn Hoàng Thị Trần Lê Phạm Y Bhôk Niê Kdăm",
    permanent_address=(
        "Thôn 12, Buôn Ea Kmar Hoà Thắng Krông Pắc, Xã Ea Hiao, "
        "Huyện Ea H'leo, Tỉnh Đắk Lắk, Việt Nam (gần trạm y tế xã)"
    ),
    major_name="Cao đẳng Công nghệ kỹ thuật điều khiển và tự động hoá",
    offering_type="Chính quy - Liên thông vừa làm vừa học",
    hk1_fee_amount=12_750_000,
)


# --- A05 injection ---------------------------------------------------------


def test_esc_escapes_xml_metacharacters():
    assert pdf._esc("a & b <c>") == "a &amp; b &lt;c&gt;"
    assert pdf._esc(None) == ""
    assert pdf._esc(123) == "123"


def test_render_survives_ampersand_in_address():
    """A raw '&' (routine in addresses) must NOT crash the ReportLab parser —
    otherwise that candidate could never be issued a letter."""
    out = pdf.render_enrollment_letter(
        _base_data(permanent_address="Số 5 & 6 Nguyễn Huệ, Đắk Lắk")
    )
    assert out[:4] == b"%PDF"


def test_render_escapes_malicious_markup_without_fetching():
    """A crafted <img src=...> in the name must be rendered as literal text,
    NOT interpreted. If ReportLab interpreted it, it would try to load the
    (missing) image and raise — so a successful render proves it was escaped."""
    out = pdf.render_enrollment_letter(
        _base_data(full_name='<img src="/nonexistent/evil.png"/>Hà')
    )
    assert out[:4] == b"%PDF"
    # The literal tag text survives (escaped), the candidate name is still there.
    assert "evil.png" in _text(out)


# --- Output correctness ----------------------------------------------------


def test_degree_level_not_duplicated():
    """MajorProgram.name already includes the degree ('Cao đẳng Dược'); the
    renderer must not prepend degree_level again."""
    text = _text(pdf.render_enrollment_letter(_base_data()))
    assert "Cao đẳng Dược" in text
    assert "Cao đẳng Cao đẳng" not in text


def test_bank_transfer_note_is_ascii_sanitized():
    """The bank-transfer memo must be ASCII (diacritics stripped) so it matches
    what a bank's Nội-dung field accepts — while the display name keeps its
    accents."""
    text = _text(
        pdf.render_enrollment_letter(
            _base_data(full_name="Phạm Thái Hà", phone="0906123456")
        )
    )
    assert "nop hoc phi ky I" in text  # ASCII memo tail
    assert "Pham Thai Ha 0906123456" in text  # diacritics stripped in the memo
    assert "Phạm Thái Hà" in text  # display line still has accents


def test_installments_split_first_fixed_second_remainder():
    """HK1 is shown as đợt 1 (fixed FIRST_INSTALLMENT) + đợt 2 (remainder).
    6.500.000 → đợt 1 = 4.000.000, đợt 2 = 2.500.000."""
    assert pdf._installments(6_500_000) == (4_000_000, 2_500_000)
    text = _text(pdf.render_enrollment_letter(_base_data(hk1_fee_amount=6_500_000)))
    assert "Đóng đợt 1" in text and "4.000.000" in text
    assert "Đóng đợt 2" in text and "2.500.000" in text


def test_low_fee_collapses_to_single_installment():
    """A HK1 at/below the first-installment size has no đợt 2 (remainder 0),
    so only đợt 1 (= the full amount) is printed."""
    assert pdf._installments(3_000_000) == (3_000_000, 0)
    text = _text(pdf.render_enrollment_letter(_base_data(hk1_fee_amount=3_000_000)))
    assert "Đóng đợt 1" in text and "3.000.000" in text
    assert "Đóng đợt 2" not in text


# --- Layout: MỘT trang ------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, label",
    [
        ({}, "dữ liệu chuẩn"),
        (_LONGEST, "dữ liệu dài nhất"),
        ({"hk1_fee_amount": 0}, "miễn học phí (không có đợt 2)"),
    ],
)
def test_letter_fits_one_page(overrides, label):
    """Giấy báo phải nằm gọn MỘT trang. Tràn sang trang 2 nghĩa là thí sinh
    cầm về thêm một tờ gần trắng và phần 'Quyền lợi' lạc khỏi tờ có chữ ký."""
    out = pdf.render_enrollment_letter(_base_data(**overrides))
    assert _page_count(out) == 1, f"tràn trang với {label}"


def test_fallback_font_stack_also_fits_one_page(reset_font_state):
    """Image thiếu 'fonts-liberation' sẽ rơi xuống DejaVu Serif — bộ chữ này
    rộng hơn Liberation ~10%. Hệ số ``scale`` của stack phải bù đủ, nếu không
    giấy báo âm thầm thành 2 trang trên chính production image.

    Test này PHẢI tự chứng minh nó thật sự đang dùng DejaVu: bản trước chỉ
    assert ``_font_scale < 1.0`` (một biến module) trong khi ReportLab vẫn
    render bằng Liberation đã bind trước đó, nên bảo chứng hoàn toàn rỗng.
    """
    from reportlab.pdfbase import pdfmetrics

    pdf._FONT_STACKS = [s for s in pdf._FONT_STACKS if s["id"] == "DejaVu"]
    assert pdf._FONT_STACKS, "phải còn stack DejaVu để kiểm chứng fallback"
    pdf._active_fonts = None

    fonts = pdf._resolve_fonts()
    assert fonts["id"] == "DejaVu"
    assert fonts["scale"] < 1.0, "stack fallback phải khai báo hệ số thu nhỏ"
    # Bằng chứng CỨNG: tên font đã bind trỏ đúng file DejaVu trên đĩa.
    face_file = pdfmetrics.getFont(fonts["regular"]).face.filename
    assert "DejaVu" in face_file, f"đang render bằng {face_file}, không phải DejaVu"

    for overrides in ({}, _LONGEST):
        out = pdf.render_enrollment_letter(_base_data(**overrides))
        assert _page_count(out) == 1


def test_font_stacks_register_under_distinct_names():
    """Mỗi stack phải có tên đăng ký RIÊNG. Dùng chung một tên là bẫy ngầm:
    ``registerFont`` là first-bind-wins nên lần bind thứ hai bị bỏ qua im
    lặng — test tưởng đang đổi font mà thực ra không."""
    ids = [s["id"] for s in pdf._FONT_STACKS]
    assert len(ids) == len(set(ids)), f"trùng id stack: {ids}"


# --- Học phí: bám số THẬT của Fee -------------------------------------------


def test_paid_amount_is_deducted_from_what_the_letter_asks_for():
    """Thí sinh đã đóng trước (luồng giữ chỗ) không được nhận giấy đòi lại toàn
    bộ số tiền: giấy in tổng, phần đã nộp, và các đợt chia trên số CÒN LẠI."""
    text = _text(
        pdf.render_enrollment_letter(
            _base_data(hk1_fee_amount=9_200_000, hk1_paid_amount=4_000_000)
        )
    )
    assert "9.200.000" in text  # tổng học phí vẫn hiển thị
    assert "Đã nộp" in text
    assert "Còn phải nộp" in text and "5.200.000" in text
    # đợt 1 kẹp theo số còn lại: 4.000.000, đợt 2 = 1.200.000
    assert "Đóng đợt 1" in text and "1.200.000" in text


def test_fully_paid_letter_asks_for_nothing():
    """Đã đóng đủ → không in đợt nào, chỉ xác nhận đã hoàn thành."""
    text = _text(
        pdf.render_enrollment_letter(
            _base_data(hk1_fee_amount=7_300_000, hk1_paid_amount=7_300_000)
        )
    )
    assert "đã hoàn thành học phí" in text.lower()
    assert "Đóng đợt 1" not in text


def test_waived_fee_is_not_billed():
    """Fee được miễn toàn phần không bị đòi tiền trên giấy chính thức."""
    text = _text(
        pdf.render_enrollment_letter(
            _base_data(hk1_fee_amount=6_500_000, hk1_waived_amount=6_500_000)
        )
    )
    assert "Được miễn giảm" in text
    assert "Đóng đợt 1" not in text


def test_school_year_comes_from_the_data_not_a_constant():
    """Nhãn năm học phải theo Fee đang render; hằng số chỉ là fallback."""
    text = _text(
        pdf.render_enrollment_letter(_base_data(school_year="2026-2027"))
    )
    assert "năm học 2026-2027" in text


# --- A05: nhánh ngày tháng không parse được --------------------------------


def test_unparseable_date_is_escaped_not_injected():
    """``_fmt_date`` trả chuỗi gốc khi không parse được — chuỗi đó đi thẳng vào
    markup Paragraph, nên PHẢI được escape. Không escape thì một dob chứa '<'
    làm vỡ parser (hồ sơ đó vĩnh viễn không phát được giấy) và một thẻ
    <img src=.../> khiến ReportLab MỞ file trên đĩa."""
    assert pdf._fmt_date("01/01/2008 <b>") == "01/01/2008 &lt;b&gt;"
    out = pdf.render_enrollment_letter(
        _base_data(dob="<img src='/etc/passwd'/>")
    )
    assert out[:4] == b"%PDF"
    assert "/etc/passwd" in _text(out)  # in ra dạng chữ, không được nạp file


# --- Gate phát hành ---------------------------------------------------------


def test_dropped_student_is_not_eligible_even_while_enrolled():
    """``drop_profile`` cố ý GIỮ status='enrolled', nên gate dựa trên status
    KHÔNG bắt được sinh viên đã bỏ học. Cờ quyền phía FE chặn riêng ca này,
    nhưng gọi thẳng API thì không — và giấy báo nhập học cho người đã nghỉ là
    văn bản chính thức sai sự thật."""
    from types import SimpleNamespace

    from app.utils.admission_status import is_enrollment_letter_eligible

    dropped = SimpleNamespace(status="enrolled", is_dropped=True)
    assert is_enrollment_letter_eligible(dropped) is False

    still_enrolled = SimpleNamespace(status="enrolled", is_dropped=False)
    assert is_enrollment_letter_eligible(still_enrolled) is True


def test_submitted_is_eligible_but_draft_is_not():
    """User chốt 19-07: phát được giấy ngay từ khi hồ sơ ĐÃ NỘP (nghiệp vụ xét
    học bạ), gồm cả ``resubmitted`` — cùng canonical 'submitted'. ``draft``
    (chưa nộp) thì KHÔNG."""
    from types import SimpleNamespace

    from app.utils.admission_status import is_enrollment_letter_eligible

    for status in ("submitted", "resubmitted", "approved", "confirmed"):
        p = SimpleNamespace(status=status, is_dropped=False)
        assert is_enrollment_letter_eligible(p) is True, status

    for status in ("draft", "rejected", "withdrawn"):
        p = SimpleNamespace(status=status, is_dropped=False)
        assert is_enrollment_letter_eligible(p) is False, status


def test_renders_without_signature_image(monkeypatch, tmp_path):
    """Thiếu file chữ ký thì chừa khoảng trống để ký tay — giấy báo VẪN phát
    hành được, không vỡ."""
    monkeypatch.setattr(pdf, "_SIGNATURE_IMG", tmp_path / "khong-ton-tai.png")
    out = pdf.render_enrollment_letter(_base_data())
    assert out[:4] == b"%PDF"
    assert _page_count(out) == 1
    assert pdf.C.SIGNATORY_NAME in _text(out)
