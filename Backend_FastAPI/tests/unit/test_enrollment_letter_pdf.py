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
        # Khối tiền đã được build_letter_data tra sẵn từ bảng thu (renderer chỉ
        # trình bày) — ở đây dựng thẳng như một dòng bảng thu thu 2 đợt.
        tuition_discount_percent=0,
        first_installment=4_600_000,
        second_installment=1_900_000,
        first_installment_due="2026-07-31",
        second_installment_due="2026-09-30",
        enrollment_start_date=datetime.date(2026, 7, 28),
        enrollment_end_date=datetime.date(2026, 8, 5),
        phone="0906123456",
    )
    d.update(overrides)
    return d


def _text(pdf_bytes: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "".join((p.extract_text() or "") for p in reader.pages)


def _flat(pdf_bytes: bytes) -> str:
    """Text đã gộp mọi khoảng trắng về một dấu cách.

    Bắt buộc khi assert một CÂU: ReportLab ngắt dòng theo bề rộng khung, nên
    một cụm từ bình thường ('ba lô') có thể rơi vào hai dòng và
    ``extract_text`` trả về 'ba\\nlô'. Assert thẳng trên text thô làm test đỏ
    vì lý do trình bày, trong khi nội dung giấy hoàn toàn đúng.
    """
    return " ".join(_text(pdf_bytes).split())


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
    first_installment=8_925_000,
    second_installment=3_825_000,
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


def test_two_installments_print_their_own_due_dates():
    """Thu 2 đợt: mỗi đợt in kèm HẠN RIÊNG của nó (31/07 và 30/09), không phải
    ngày kết thúc nhập học của hồ sơ."""
    text = _text(pdf.render_enrollment_letter(_base_data()))
    assert "Đóng đợt 1" in text and "31/07/2026" in text and "4.600.000" in text
    assert "Đóng đợt 2" in text and "30/09/2026" in text and "1.900.000" in text


def test_discounted_major_prints_one_conditional_line():
    """Ngành ưu đãi: MỘT dòng nộp duy nhất, và ưu đãi phải in thành ĐIỀU KIỆN
    ('nếu nộp đủ đến ngày ...') — chỉ in số cuối thì thí sinh không biết vì sao
    lệch với dòng tổng phía trên."""
    text = _flat(
        pdf.render_enrollment_letter(
            _base_data(
                hk1_fee_amount=7_000_000,
                tuition_discount_percent=30,
                first_installment=4_900_000,
                second_installment=0,
            )
        )
    )
    assert "giảm 30%" in text and "nếu nộp đủ" in text and "31/07/2026" in text
    assert "4.900.000" in text
    assert "Đóng đợt 2" not in text


def test_required_documents_follow_the_degree_level():
    """Danh mục hồ sơ phải theo TRÌNH ĐỘ.

    Trung cấp tuyển cả thí sinh mới hoàn thành THCS, nên in yêu cầu 'Bằng tốt
    nghiệp THPT' như bên Cao đẳng là đòi thứ họ không thể có — và thí sinh sẽ
    tin tờ giấy có chữ ký Hiệu trưởng hơn là tin lời tư vấn qua điện thoại.
    """
    cd = _flat(pdf.render_enrollment_letter(_base_data(degree_level="Cao đẳng")))
    assert "Học bạ Trung học Phổ thông" in cd
    assert "THCS" not in cd

    tc = _flat(pdf.render_enrollment_letter(_base_data(degree_level="Trung cấp")))
    assert "THCS/THPT" in tc
    assert "Học bạ Trung học Phổ thông hoặc bảng điểm" not in tc

    # Giấy tờ tuỳ thân là phần CHUNG — phải còn ở cả hai trình độ.
    for text in (cd, tc):
        assert "Căn cước công dân" in text and "04 ảnh thẻ 3x4" in text


def test_unknown_degree_level_has_no_document_list():
    """Trình độ lạ ⇒ helper trả None để người gọi fail-closed, KHÔNG lặng lẽ rơi
    về danh mục của một trình độ khác."""
    from app.constants import enrollment_letter as consts

    assert consts.documents_for_degree("Sơ cấp") is None
    assert consts.documents_for_degree("") is None
    assert consts.documents_for_degree(None) is None
    # Chuẩn hoá hoa/thường + khoảng trắng thừa vẫn phải nhận ra.
    assert consts.documents_for_degree("  CAO ĐẲNG ") == consts.documents_for_degree(
        "Cao đẳng"
    )


def test_early_enrollment_bonus_uses_the_first_installment_due_date():
    """Quà tặng nhập học sớm phải in đúng MỐC của đợt 1, dẫn từ dữ liệu.

    Nếu câu này viết cứng một ngày riêng thì đổi hạn thu (constants) sẽ cho ra
    tờ giấy nói hai ngày khác nhau — mà chính tờ giấy đó là căn cứ thí sinh cầm
    đến đòi quyền lợi.
    """
    text = _flat(
        pdf.render_enrollment_letter(
            _base_data(first_installment_due="2026-08-15")
        )
    )
    assert "Ưu đãi nhập học sớm" in text
    assert "ba lô" in text and "A1" in text and "ký túc xá" in text
    assert "15/08/2026" in text
    assert "31/07/2026" not in text, "mốc quà tặng đang bị viết cứng"


def test_early_enrollment_bonus_also_shown_for_discounted_majors():
    """Ngành ưu đãi 30% chỉ có MỘT dòng nộp; quà tặng vẫn phải xuất hiện — cùng
    mốc thời gian, nên không có lý do để nhóm này mất quyền lợi."""
    text = _flat(
        pdf.render_enrollment_letter(
            _base_data(
                hk1_fee_amount=7_000_000,
                tuition_discount_percent=30,
                first_installment=4_900_000,
                second_installment=0,
            )
        )
    )
    assert "Ưu đãi nhập học sớm" in text and "ba lô" in text


def test_letter_never_shows_what_the_candidate_already_paid():
    """Giấy in MỨC CHUẨN của bảng thu, không đối trừ tiền giữ chỗ (quyết định
    19-07) — việc đối trừ diễn ra tại quầy. Một dòng 'Đã nộp'/'Còn phải nộp' lọt
    lên giấy nghĩa là hai tờ giấy cùng ngành in hai số khác nhau."""
    text = _flat(pdf.render_enrollment_letter(_base_data()))
    for banned in ("Đã nộp", "Còn phải nộp", "Được miễn giảm"):
        assert banned not in text, f"giấy còn in '{banned}'"


# --- Layout: MỘT trang ------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, label",
    [
        ({}, "dữ liệu chuẩn"),
        (_LONGEST, "dữ liệu dài nhất"),
        # Dòng ưu đãi là dòng nhãn DÀI NHẤT bảng thu sinh ra ("Ưu đãi giảm 30%
        # học phí kỳ I nếu nộp đủ đến ngày ...") → wrap 2 dòng, phải kiểm riêng.
        (
            {
                "hk1_fee_amount": 7_000_000,
                "tuition_discount_percent": 30,
                "first_installment": 4_900_000,
                "second_installment": 0,
            },
            "ngành ưu đãi (nhãn dài nhất)",
        ),
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


def test_tuition_schedule_is_internally_consistent():
    """Bảng thu là dữ liệu gõ tay 20 dòng — một con số lệch sẽ in thẳng lên văn
    bản có chữ ký Hiệu trưởng mà không ai phát hiện. Khoá hai bất biến:
    thu 2 đợt ⇒ đợt1 + đợt2 == tổng; ưu đãi ⇒ đợt1 == tổng × (100−giảm)%.
    """
    from app.constants import enrollment_letter as consts

    assert consts.TUITION_SCHEDULE, "bảng thu rỗng"
    for code, row in consts.TUITION_SCHEDULE.items():
        total, first = row["hk1"], row["first"]
        second, disc = row["second"], row["discount_percent"]
        if disc:
            assert second == 0, f"{code}: ngành ưu đãi không được có đợt 2"
            assert first == round(total * (100 - disc) / 100), (
                f"{code}: đợt 1 ({first:,}) không bằng {100 - disc}% của "
                f"{total:,}"
            )
        else:
            assert first + second == total, (
                f"{code}: {first:,} + {second:,} != {total:,}"
            )


def test_every_active_major_code_is_in_the_schedule():
    """Mã ngành trong bảng thu phải đúng dạng mã ngành thật (7 chữ số, 6=Cao
    đẳng / 5=Trung cấp). Bắt lỗi gõ mã — mã sai không tra được thì hồ sơ ngành
    đó bị CHẶN phát giấy, và lỗi chỉ lộ ra khi officer bấm nút."""
    from app.constants import enrollment_letter as consts

    for code in consts.TUITION_SCHEDULE:
        assert code.isdigit() and len(code) == 7, f"mã ngành lạ: {code}"
        assert code[0] in ("5", "6"), f"mã ngành không phải CĐ/TC: {code}"


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
