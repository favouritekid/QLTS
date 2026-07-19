# app/constants/enrollment_letter.py
"""
Static (literal) content for the "Giấy báo nhập học" PDF.

MVP note: the fields the system does NOT yet own are hard-coded here verbatim
from the reference letter (2025 mẫu "Ksơr Y Lực") so the letter renders
correctly today. They are gathered in ONE place (not scattered in the render
code) so the user can adjust wording / amounts later without touching layout
logic. When these graduate to a runtime store, move them to system_config
``school_profile`` (v2) and keep this module as the fallback default.

⚠️ The HK1 tuition AMOUNT itself is NOT here — it is bound to the profile's real
active HK1 tuition Fee at render time. Only the FIRST-installment split policy
(``FIRST_INSTALLMENT``) is literal; the second installment is the remainder.
"""

# --- School identity (letterhead / body) ---
MINISTRY_NAME = "BỘ GIÁO DỤC VÀ ĐÀO TẠO"
SCHOOL_NAME = "TRƯỜNG CAO ĐẲNG BÁCH KHOA TÂY NGUYÊN"
# Title-case form used inside body prose ("Trường ... trân trọng thông báo:").
SCHOOL_NAME_TITLE = "Trường Cao đẳng Bách khoa Tây Nguyên"
SCHOOL_CODE = "TPC"
SCHOOL_ADDRESS = "02 Lý Nhân Tông, Khối 8, Phường Tân An, Tỉnh Đắk Lắk"
SCHOOL_PHONE = "(0262) 8551 558 - 0906 513 555"
# Header shows the bare domain; the footer bar shows the full URL.
SCHOOL_WEBSITE = "tnpc.edu.vn"
FOOTER_WEBSITE = "https://tnpc.edu.vn"

# Enrollment location + support line shown in the body ("Địa điểm" / "Điện
# thoại hỗ trợ").
LOCATION_ADDRESS = "Số 02 Lý Nhân Tông, Khối 8, Phường Tân An, Tỉnh Đắk Lắk."
SUPPORT_PHONE = "0906 513 555"

# School year label for the fee heading ("Học phí học kỳ I năm học ...").
SCHOOL_YEAR = "2025-2026"
# First installment (đợt 1); the remainder becomes đợt 2. Literal until a
# per-term collection policy row exists in the system.
FIRST_INSTALLMENT = 4000000

# --- Signatory ---
SIGNATORY_TITLE = "HIỆU TRƯỞNG"
SIGNATORY_NAME = "Ths.Nguyễn Thái Bình"

# --- Documents the candidate must bring (static checklist, item "2" sub-list) ---
REQUIRED_DOCUMENTS = [
    "Học bạ Trung học Phổ thông hoặc bảng điểm xác nhận kết quả học tập THPT;",
    (
        "Bằng tốt nghiệp THPT hoặc Giấy chứng nhận tốt nghiệp THPT tạm thời "
        "(đối với thí sinh tốt nghiệp năm 2025);"
    ),
    (
        "Giấy khai sinh; Căn cước công dân; Giấy xác nhận ưu tiên "
        "(nếu có); 04 ảnh thẻ 3x4."
    ),
]

# --- Bank transfer block (literal until system_config bank_collection_account
#     is populated for this purpose). ---
BANK_ACCOUNT_NUMBER = "118 000 130 705"
BANK_ACCOUNT_NAME = "Trường Cao đẳng Bách Khoa Tây Nguyên"
BANK_NAME = "TMCP Công thương Việt Nam (Vietinbank) chi nhánh Đắk Lắk"

# --- Candidate benefits footer (static) ---
BENEFITS_TITLE = "QUYỀN LỢI CỦA THÍ SINH KHI NHẬP HỌC TẠI TRƯỜNG"
BENEFITS = [
    (
        "Sau khi sinh viên hoàn tất thủ tục nhập học và đóng học phí theo quy "
        "định, Nhà trường sẽ hướng dẫn chi tiết, nhanh chóng để sinh viên hoàn "
        "thiện hồ sơ và nhận lại khoản tiền được Nhà nước cấp bù theo quy định."
    ),
    (
        "Sinh viên ở xa được bố trí chỗ ở tại trường. Được hỗ trợ giới thiệu "
        "việc làm và học liên thông lên trình độ Cao đẳng, Đại học sau khi tốt "
        "nghiệp;"
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
