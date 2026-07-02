// src/components/sms/smsContent.ts
// Nội dung MARKETING cho landing chốt (editorial — KHÔNG phải dữ liệu BE, chủ
// động thêm/bớt/tinh chỉnh). Chỉ IDENTITY ngành (id/tên/trình độ/mã) là thật từ
// BE để đo lường dwell. Mỗi ngành lấy DEFAULT rồi merge override theo từ khoá tên
// → mọi ngành đều hiển thị đủ section đúng thiết kế. Owner sửa số liệu tại đây.
import { programIcon } from "./programIcon"

/** Hotline hiển thị ở nút "Gọi ngay" — chỉnh 1 chỗ. */
export const SMS_HOTLINE = "1900 1234"
export const SMS_HOTLINE_TEL = "tel:19001234"

export interface ProgramEditorial {
  icon: string
  badge: "hot" | "open" | null
  tuitionTeaser: string // dòng nhỏ trên card tier-1
  careers: string[] // "Học xong làm gì?"
  tuitionPerTerm: string // "Học phí & học bổng"
  scholarship: string
  methods: string[] // "Phương thức xét tuyển"
  documents: string[] // "Hồ sơ cần chuẩn bị"
  roundLabel: string // "Đợt & hạn nộp"
  roundDeadline: string
}

const DEFAULT: Omit<ProgramEditorial, "icon"> = {
  badge: "open",
  tuitionTeaser: "Học phí ưu đãi",
  careers: [
    "Làm đúng chuyên ngành ngay sau tốt nghiệp",
    "Thực tập & giới thiệu việc làm tại doanh nghiệp liên kết",
    "Liên thông lên bậc học cao hơn",
  ],
  tuitionPerTerm: "Liên hệ nhận báo phí",
  scholarship: "Nhiều suất học bổng cho thí sinh nộp hồ sơ sớm.",
  methods: ["Xét học bạ THPT", "Xét điểm thi tốt nghiệp", "Xét tuyển thẳng"],
  documents: [
    "Học bạ THPT (bản sao công chứng)",
    "Bằng/giấy chứng nhận tốt nghiệp",
    "CCCD + 4 ảnh 3×4",
  ],
  roundLabel: "Đợt 1 năm 2026",
  roundDeadline: "Hạn cuối 31/07",
}

// Override theo từ khoá tên ngành (khớp đầu tiên thắng). Số liệu = editorial.
const OVERRIDES: ReadonlyArray<[RegExp, Partial<ProgramEditorial>]> = [
  [
    /công nghệ thông tin|cntt|phần mềm/i,
    {
      badge: "hot",
      tuitionTeaser: "Học phí từ 5tr/kỳ",
      careers: [
        "Lập trình viên phần mềm, web, ứng dụng di động",
        "Kỹ thuật viên hệ thống mạng, quản trị dữ liệu",
        "Nhu cầu tuyển cao — lương khởi điểm 8–15 triệu",
      ],
      tuitionPerTerm: "5.000.000đ / kỳ",
      scholarship: "Học bổng đến 20% học phí kỳ 1 cho hồ sơ nộp trước 30/6.",
    },
  ],
  [
    /dược|điều dưỡng|y\b|y học|y sỹ|xét nghiệm/i,
    {
      badge: "hot",
      tuitionTeaser: "Học phí từ 9tr/kỳ",
      careers: [
        "Làm tại bệnh viện, phòng khám, nhà thuốc, cơ sở y tế",
        "Điều dưỡng viên, dược tá, kỹ thuật viên xét nghiệm",
        "Ngành nhân lực thiếu — cơ hội việc làm rộng",
      ],
      tuitionPerTerm: "9.000.000đ / kỳ",
      scholarship: "Ưu đãi học phí & học bổng cho hồ sơ nộp sớm.",
    },
  ],
  [
    /ô ?tô|cơ khí|hàn/i,
    {
      tuitionTeaser: "Học phí từ 6tr/kỳ",
      careers: [
        "Kỹ thuật viên sửa chữa, bảo dưỡng ô tô/cơ khí",
        "Thợ hàn, vận hành máy CNC tại nhà máy",
        "Thực hành trên thiết bị thực tế tại xưởng trường",
      ],
      tuitionPerTerm: "6.000.000đ / kỳ",
    },
  ],
  [
    /kế toán|kinh tế|tài chính|quản trị|kinh doanh/i,
    {
      tuitionTeaser: "Học phí từ 5.5tr/kỳ",
      careers: [
        "Kế toán, nhân viên tài chính, hành chính doanh nghiệp",
        "Nhân viên kinh doanh, quản trị bán hàng",
        "Kỹ năng thực chiến trên phần mềm kế toán phổ biến",
      ],
      tuitionPerTerm: "5.500.000đ / kỳ",
    },
  ],
  [
    /du lịch|nhà hàng|khách sạn|lữ hành/i,
    {
      badge: "hot",
      tuitionTeaser: "Học phí từ 6tr/kỳ",
      careers: [
        "Hướng dẫn viên, điều hành tour, lễ tân khách sạn",
        "Nhân viên nhà hàng — khách sạn 3–5 sao",
        "Thực tập tại doanh nghiệp du lịch liên kết",
      ],
      tuitionPerTerm: "6.000.000đ / kỳ",
    },
  ],
  [
    /thiết kế|đồ ho[aạ]|mỹ thuật/i,
    {
      tuitionTeaser: "Học phí từ 5.5tr/kỳ",
      careers: [
        "Thiết kế đồ hoạ, dựng phim, làm nội dung số",
        "Chuyên viên thiết kế tại agency/doanh nghiệp",
        "Xây dựng portfolio thực tế trong quá trình học",
      ],
      tuitionPerTerm: "5.500.000đ / kỳ",
    },
  ],
]

/** Nội dung editorial cho 1 ngành (default + override theo tên). */
export function programEditorial(name: string): ProgramEditorial {
  const base: ProgramEditorial = { icon: programIcon(name), ...DEFAULT }
  for (const [re, ov] of OVERRIDES) if (re.test(name)) return { ...base, ...ov }
  return base
}
