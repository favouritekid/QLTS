// src/components/sms/programIcon.ts
// Ánh xạ tên ngành → icon lucide minh hoạ cho landing SMS. CHỈ là trình bày
// (không phải suy luận nghiệp vụ). Thứ tự có ý nghĩa — luật khớp trước thắng
// (đặt luật hẹp/đặc thù lên trên). Icon lucide mờ ở góc card (không CDN, tree-shake).
import {
  Briefcase,
  Building2,
  Calculator,
  Car,
  GraduationCap,
  HeartPulse,
  Languages,
  Leaf,
  Monitor,
  PawPrint,
  Pill,
  Plane,
  Stethoscope,
  Truck,
  type LucideIcon,
} from "lucide-react"

const LUCIDE_RULES: ReadonlyArray<[RegExp, LucideIcon]> = [
  [/dược|thuốc/i, Pill],
  [/điều dưỡng/i, HeartPulse],
  [/y học cổ truyền|cổ truyền|đông y/i, Leaf],
  [/y sỹ|y sĩ|đa khoa|bác sỹ|khám/i, Stethoscope],
  [/công nghệ thông tin|cntt|phần mềm|lập trình|\bit\b/i, Monitor],
  [/ô ?tô|động cơ|gầm/i, Car],
  [/thú y|chăn nuôi|trồng trọt|nông/i, PawPrint],
  [/vận tải|logistic|kho vận/i, Truck],
  [/kế toán|tài chính|thuế/i, Calculator],
  [/văn phòng|hành chính|lưu trữ/i, Building2],
  [/tiếng anh|ngôn ngữ|biên phiên dịch|phiên dịch/i, Languages],
  [/du lịch|lữ hành|hướng dẫn|khách sạn/i, Plane],
  [/quản trị|kinh doanh|kinh tế|marketing/i, Briefcase],
]

/** Component icon lucide đại diện cho ngành theo tên (chỉ để hiển thị). */
export function programLucideIcon(name: string): LucideIcon {
  for (const [re, Icon] of LUCIDE_RULES) if (re.test(name)) return Icon
  return GraduationCap
}

/** Gói icon ngành trong object → nơi dùng chỉ member-access (`glyph.Icon`),
 *  thoả react-compiler: cấm dùng trực tiếp call-trả-component làm JSX-type.
 *  Idiom DUY NHẤT cho cả 2 tầng (tier-1 lưu vào VM, tier-2 gọi trực tiếp). */
export function programGlyph(name: string): { Icon: LucideIcon } {
  return { Icon: programLucideIcon(name) }
}
