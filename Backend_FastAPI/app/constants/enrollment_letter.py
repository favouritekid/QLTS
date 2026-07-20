# app/constants/enrollment_letter.py
"""
Static (literal) content for the "Giấy báo nhập học" PDF.

MVP note: the fields the system does NOT yet own are hard-coded here verbatim
from the reference letter (2025 mẫu "Ksơr Y Lực") so the letter renders
correctly today. They are gathered in ONE place (not scattered in the render
code) so the user can adjust wording / amounts later without touching layout
logic. When these graduate to a runtime store, move them to system_config
``school_profile`` (v2) and keep this module as the fallback default.

⚠️ Khối HỌC PHÍ trên giấy đọc từ ``TUITION_SCHEDULE`` bên dưới — bảng thu do
Nhà trường ban hành, tra theo MÃ NGÀNH. Fee của hồ sơ vẫn là hàng rào bắt buộc
(xác định ngành/trình độ + đối chiếu tổng học phí), nhưng CÁC MỨC ĐỢT in trên
giấy là mức chuẩn của bảng thu, KHÔNG trừ phần thí sinh đã nộp trước.
"""

from datetime import date

# --- School identity (letterhead / body) ---
MINISTRY_NAME = "BỘ GIÁO DỤC VÀ ĐÀO TẠO"
SCHOOL_NAME = "TRƯỜNG CAO ĐẲNG BÁCH KHOA TÂY NGUYÊN"
# Title-case form used inside body prose ("Trường ... trân trọng thông báo:").
SCHOOL_NAME_TITLE = "Trường Cao đẳng Bách khoa Tây Nguyên"
SCHOOL_CODE = "TPC"
SCHOOL_ADDRESS = "02 Lý Nhân Tông, Phường Tân An, Tỉnh Đắk Lắk"
SCHOOL_PHONE = "(0262) 8551 558 - 0906 513 555"
# Header shows the bare domain; the footer bar shows the full URL.
SCHOOL_WEBSITE = "tnpc.edu.vn"
FOOTER_WEBSITE = "https://tnpc.edu.vn"

# Enrollment location + support line shown in the body ("Địa điểm" / "Điện
# thoại hỗ trợ").
LOCATION_ADDRESS = "Số 02 Lý Nhân Tông, Phường Tân An, Tỉnh Đắk Lắk."
SUPPORT_PHONE = "0906 513 555"

# School year label for the fee heading ("Học phí học kỳ I năm học ...").
SCHOOL_YEAR = "2025-2026"

# --- BẢNG THU HỌC PHÍ KỲ I (mùa tuyển sinh 2026) ---------------------------
# Nguồn: bảng thu Nhà trường ban hành, tra theo MÃ NGÀNH (``major_program.code``
# — khoá tự nhiên, không đổi khi ngành được đổi tên; mã 6xxxxxx = Cao đẳng,
# 5xxxxxx = Trung cấp nên không cần ghép thêm trình độ vào khoá).
#
# Mỗi dòng:
#   hk1               tổng học phí kỳ I — PHẢI khớp ``Fee.final_amount``, lệch
#                     thì KHÔNG phát giấy (xem ``build_letter_data``)
#   discount_percent  0 = thu 2 đợt; >0 = ưu đãi nộp-một-lần, chỉ có "first"
#   first / second    mức đóng từng đợt. Ngành thu 2 đợt: first+second == hk1.
#                     Ngành ưu đãi: first == hk1 × (100−discount_percent)%,
#                     second == 0.
# Hai bất biến trên được khoá bằng test (``test_tuition_schedule_is_consistent``)
# nên một dòng gõ sai số không thể lọt ra giấy chính thức.
#
# ⚠️ MÙA SAU phải sửa Ở ĐÂY rồi deploy lại (bảng là hằng số Python theo quyết
# định 19-07). Đổi mức thu / hạn nộp mà quên file này thì giấy in số của mùa cũ.
TUITION_SCHEDULE_ACADEMIC_YEAR = 2026
INSTALLMENT_1_DUE = date(2026, 7, 31)
INSTALLMENT_2_DUE = date(2026, 9, 30)

TUITION_SCHEDULE: dict[str, dict] = {
    # --- Cao đẳng ---
    "6720301": {  # Điều dưỡng
        "hk1": 7_300_000, "discount_percent": 0,
        "first": 5_100_000, "second": 2_200_000,
    },
    "6720201": {  # Dược
        "hk1": 7_000_000, "discount_percent": 0,
        "first": 4_900_000, "second": 2_100_000,
    },
    "6720101": {  # Y sỹ đa khoa
        "hk1": 8_000_000, "discount_percent": 0,
        "first": 5_600_000, "second": 2_400_000,
    },
    "6720102": {  # Y học cổ truyền
        "hk1": 7_000_000, "discount_percent": 30,
        "first": 4_900_000, "second": 0,
    },
    "6620120": {  # Chăn nuôi - Thú y
        "hk1": 8_000_000, "discount_percent": 0,
        "first": 5_600_000, "second": 2_400_000,
    },
    "6510216": {  # Công nghệ ô tô
        "hk1": 7_200_000, "discount_percent": 0,
        "first": 5_000_000, "second": 2_200_000,
    },
    "6810103": {  # Hướng dẫn du lịch
        "hk1": 6_500_000, "discount_percent": 0,
        "first": 4_600_000, "second": 1_900_000,
    },
    "6480201": {  # Công nghệ thông tin
        "hk1": 7_000_000, "discount_percent": 30,
        "first": 4_900_000, "second": 0,
    },
    "6340404": {  # Quản trị kinh doanh
        "hk1": 6_500_000, "discount_percent": 30,
        "first": 4_550_000, "second": 0,
    },
    "6340403": {  # Quản trị văn phòng
        "hk1": 6_500_000, "discount_percent": 30,
        "first": 4_550_000, "second": 0,
    },
    "6340301": {  # Kế toán
        "hk1": 6_500_000, "discount_percent": 30,
        "first": 4_550_000, "second": 0,
    },
    "6220206": {  # Tiếng Anh
        "hk1": 6_500_000, "discount_percent": 30,
        "first": 4_550_000, "second": 0,
    },
    # --- Trung cấp (đợt 1 cố định 4.500.000, đợt 2 = phần còn lại) ---
    "5510216": {  # Công nghệ ô tô
        "hk1": 9_200_000, "discount_percent": 0,
        "first": 4_500_000, "second": 4_700_000,
    },
    # ⚠️ ĐỪNG "sửa lại cho khớp bảng thu bản giấy". Bảng giấy ghi 5480201,
    # nhưng production KHÔNG CÓ mã đó: ngành CNTT Trung cấp trên hệ thống là
    # 5480202 ("Công nghệ thông tin (ứng dụng phần mềm)") — đã đối chiếu
    # major_program trên prod 19-07, và user chốt "mã theo production" 20-07.
    # Đổi về 5480201 thì không tra được dòng nào ⇒ CHẶN SẠCH mọi hồ sơ CNTT-TC
    # (16 hồ sơ tại thời điểm đối chiếu).
    # (Ghi chú: 6480201 mới là mã CNTT CAO ĐẲNG — xem dòng "6480201" ở trên.
    # Bản comment trước ở đây nói 5480201 là mã Cao đẳng: SAI.)
    "5480202": {  # Công nghệ thông tin (ứng dụng phần mềm)
        "hk1": 9_200_000, "discount_percent": 0,
        "first": 4_500_000, "second": 4_700_000,
    },
    "5810207": {  # Kỹ thuật chế biến món ăn
        "hk1": 9_200_000, "discount_percent": 0,
        "first": 4_500_000, "second": 4_700_000,
    },
    "5620120": {  # Chăn nuôi - Thú y
        "hk1": 7_000_000, "discount_percent": 0,
        "first": 4_500_000, "second": 2_500_000,
    },
    "5340421": {  # Quản lý và kinh doanh du lịch
        "hk1": 6_800_000, "discount_percent": 0,
        "first": 4_500_000, "second": 2_300_000,
    },
    "5340301": {  # Kế toán
        "hk1": 6_800_000, "discount_percent": 0,
        "first": 4_500_000, "second": 2_300_000,
    },
    "5340407": {  # Quản trị kinh doanh vận tải đường bộ
        "hk1": 6_800_000, "discount_percent": 0,
        "first": 4_500_000, "second": 2_300_000,
    },
    "5720101": {  # Y sỹ đa khoa
        "hk1": 6_600_000, "discount_percent": 0,
        "first": 4_500_000, "second": 2_100_000,
    },
}

# --- Signatory ---
SIGNATORY_TITLE = "HIỆU TRƯỞNG"
SIGNATORY_NAME = "Ths.Nguyễn Thái Bình"

# --- Hồ sơ thí sinh mang theo (mục "2") -------------------------------------
# Danh mục KHÁC NHAU theo trình độ: Trung cấp nhận cả thí sinh mới hoàn thành
# THCS, nên đòi bằng tốt nghiệp THPT như bên Cao đẳng là đòi thứ họ không thể
# có. Giấy chỉ in danh mục CỦA CHÍNH trình độ thí sinh trúng tuyển — in cả hai
# nhánh kèm tiêu đề "Đối với trình độ ..." bắt người đọc tự lọc, và tờ giấy này
# vốn đã cá nhân hoá tới từng hồ sơ.
_DOCUMENTS_CAO_DANG = [
    "Học bạ Trung học Phổ thông hoặc bảng điểm xác nhận kết quả học tập THPT;",
    (
        "Bằng tốt nghiệp THPT hoặc Giấy chứng nhận kết quả thi tốt nghiệp THPT "
        "(đối với thí sinh tốt nghiệp năm 2026);"
    ),
]
_DOCUMENTS_TRUNG_CAP = [
    (
        "Học bạ THCS/THPT xác nhận trình độ văn hóa đã hoàn thành; nếu đã tốt "
        "nghiệp THPT thì nộp kèm Bằng tốt nghiệp THPT hoặc Giấy chứng nhận kết "
        "quả thi tốt nghiệp THPT (đối với thí sinh tốt nghiệp năm 2026);"
    ),
]

# Giấy tờ tuỳ thân — chung cho mọi trình độ, luôn đứng cuối danh mục.
REQUIRED_DOCUMENTS_COMMON = [
    (
        "Giấy khai sinh; Căn cước công dân; Giấy xác nhận ưu tiên "
        "(nếu có); 04 ảnh thẻ 3x4."
    ),
]

REQUIRED_DOCUMENTS_BY_DEGREE = {
    "cao đẳng": _DOCUMENTS_CAO_DANG,
    "trung cấp": _DOCUMENTS_TRUNG_CAP,
}


def documents_for_degree(degree_level) -> list[str] | None:
    """Danh mục hồ sơ ứng với trình độ, đã nối phần giấy tờ tuỳ thân.

    Trả ``None`` khi KHÔNG nhận ra trình độ — người gọi phải fail-closed. In một
    danh mục hồ sơ sai khiến thí sinh vượt cả trăm cây số tới trường rồi phải
    quay về lấy giấy tờ; thà chặn phát giấy và báo lỗi.

    Thực tế nhánh ``None`` không chạm được: ``TUITION_SCHEDULE`` chỉ chứa mã
    ngành Cao đẳng/Trung cấp và đã chặn mọi ngành lạ từ trước. Nó là lưới an
    toàn cho ngày ai đó thêm ngành Sơ cấp vào bảng thu mà quên danh mục này.
    """
    key = (degree_level or "").strip().casefold()
    docs = REQUIRED_DOCUMENTS_BY_DEGREE.get(key)
    if docs is None:
        return None
    return [*docs, *REQUIRED_DOCUMENTS_COMMON]


# --- Bank transfer block (literal until system_config bank_collection_account
#     is populated for this purpose). ---
BANK_ACCOUNT_NUMBER = "118 000 130 705"
BANK_ACCOUNT_NAME = "Trường Cao đẳng Bách Khoa Tây Nguyên"
BANK_NAME = "TMCP Công thương Việt Nam (Vietinbank) chi nhánh Đắk Lắk"

# --- Ưu đãi khuyến khích nhập học sớm -------------------------------------
# In ngay dưới các đợt đóng học phí (mục 3): quyền lợi này gắn với chính MỐC
# THỜI GIAN của đợt 1, nên đặt cạnh con số phải nộp thì người đọc thấy ngay
# "đóng sớm thì được gì" — tách xuống mục Quyền lợi cuối trang là mất liên hệ.
#
# ⚠️ Mốc thời gian KHÔNG viết cứng ở đây: nó LUÔN bằng hạn đợt 1
# (``INSTALLMENT_1_DUE``) và được truyền vào lúc render. Viết cứng thì đổi hạn
# thu mà quên sửa câu này sẽ cho ra tờ giấy tự mâu thuẫn về ngày — chính tờ
# giấy đó lại là căn cứ để thí sinh đòi quyền lợi.
EARLY_ENROLLMENT_BONUS_LABEL = "Ưu đãi nhập học sớm"
EARLY_ENROLLMENT_BONUS = (
    "Thí sinh nhập học và đóng đủ học phí đến ngày {due} được tặng 01 ba lô, "
    "01 áo thun, hỗ trợ học lái xe máy hạng A1 và miễn 03 tháng ở ký túc xá."
)

# --- Candidate benefits footer (static) ---
BENEFITS_TITLE = "QUYỀN LỢI CỦA THÍ SINH KHI NHẬP HỌC TẠI TRƯỜNG"
BENEFITS = [
    (
        "Sau khi hoàn tất thủ tục nhập học và đóng học phí theo quy định, Nhà "
        "trường sẽ hướng dẫn chi tiết để sinh viên hoàn thiện hồ sơ và nhận lại "
        "khoản tiền được Nhà nước cấp bù theo quy định."
    ),
    (
        "Sinh viên ở xa được bố trí chỗ ở tại trường; được hỗ trợ giới thiệu "
        "việc làm và học liên thông lên trình độ Cao đẳng, Đại học sau khi tốt "
        "nghiệp."
    ),
]

# Closing note ("Lưu ý: ...") rendered after the benefits section.
CLOSING_NOTE = (
    "Đối với thí sinh nhận được giấy báo nhưng không thể làm thủ tục hoàn "
    "thiện hồ sơ đăng ký xét tuyển đầu vào trong khoảng thời gian trên có thể "
    "liên hệ với Nhà trường để được tư vấn, hỗ trợ nhập học sau."
)

FOOTER_SLOGAN = "THỰC HỌC - THỰC HÀNH - THỰC NGHIỆP"

# Default training system when the profile's offering does not resolve one.
DEFAULT_OFFERING_TYPE = "Chính quy"
