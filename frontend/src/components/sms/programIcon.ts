// src/components/sms/programIcon.ts
// Ánh xạ tên ngành → emoji minh hoạ cho card landing SMS. CHỈ là trình bày
// (không phải suy luận nghiệp vụ): fallback 🎓 khi không khớp luật nào.
// Thứ tự có ý nghĩa — luật khớp trước thắng (đặt luật hẹp/đặc thù lên trên).
const ICON_RULES: ReadonlyArray<[RegExp, string]> = [
  [/công nghệ thông tin|cntt|phần mềm|lập trình|dữ liệu|mạng máy tính|\bit\b/i, "💻"],
  [/cơ khí|hàn|chế tạo|\bcnc\b|tiện|phay/i, "🔧"],
  [/ô ?tô|động cơ|gầm/i, "🚗"],
  [/điện|tự động ho[áa]|điện tử|cơ điện/i, "⚡"],
  [/y\b|dược|điều dưỡng|hộ sinh|xét nghiệm|răng|khám/i, "🏥"],
  [/nhà hàng|khách sạn|nấu ăn|ẩm thực|bếp|pha chế/i, "🍳"],
  [/du lịch|lữ hành|hướng dẫn viên/i, "🧳"],
  [/kế toán|kinh tế|tài chính|ngân hàng|quản trị|kinh doanh|marketing|logistic/i, "💼"],
  [/thiết kế|đồ ho[aạ]|mỹ thuật|thời trang|nội thất/i, "🎨"],
  [/ngôn ngữ|tiếng|biên phiên dịch|phiên dịch/i, "🗣️"],
  [/xây dựng|kiến trúc|trắc địa|cầu đường/i, "🏗️"],
  [/nông|thú y|chăn nuôi|trồng trọt|lâm nghiệp|thuỷ sản|thủy sản/i, "🌾"],
  [/sư phạm|giáo dục|mầm non/i, "📚"],
  [/luật|pháp lý/i, "⚖️"],
]

/** Emoji đại diện cho ngành theo tên (chỉ để hiển thị). */
export function programIcon(name: string): string {
  for (const [re, icon] of ICON_RULES) if (re.test(name)) return icon
  return "🎓"
}
