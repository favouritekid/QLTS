// src/components/sms/smsContent.ts
// Nội dung MARKETING cho landing tuyển sinh 2 tầng (editorial — KHÔNG phải dữ
// liệu BE). Chỉ IDENTITY ngành (id/tên/trình độ/mã) là THẬT từ BE để đo lường
// dwell (§16). Nội dung 14 ngành lấy nguyên văn từ mockup "Cao đẳng Bách khoa
// Tây Nguyên"; map theo tên ngành (RegExp) → ngành lạ rơi về DEFAULT generic.
//
// ⚠️ OWNER sửa số liệu tại 1 chỗ này: hotline, Zalo, địa chỉ, hạn, số thống kê.
// CTA gọi/Zalo là đường chốt chính (không form) → hotline/Zalo phải là kênh THẬT.

/** Hotline tuyển sinh (số thật) + link tel:. */
export const SMS_HOTLINE = "0906 513 555"
export const SMS_HOTLINE_TEL = "tel:0906513555"
/** Link Zalo OA (Official Account) của trường — mở thẳng OA để khách chat/theo dõi. */
export const SMS_ZALO_URL = "https://oa.zalo.me/bachkhoataynguyen"
/**
 * Zalo đã cấu hình chưa? Placeholder "#" (chưa có link) → false → ẩn mọi nút Zalo
 * để tránh CTA chết (href="#" chỉ nhảy về đầu trang). Owner điền link https thật
 * ở SMS_ZALO_URL → tự bật lại nút Zalo trên cả 2 tầng.
 */
export const SMS_ZALO_ENABLED = SMS_ZALO_URL.startsWith("http")
/** Địa chỉ trường (footer). */
export const SCHOOL_ADDRESS = "Số 45 Y-Wang, TP. Buôn Ma Thuột, Đắk Lắk"
/** Dòng phụ dưới tên trường ở header. */
export const SMS_SUB_BRAND = "TUYỂN SINH 2026"

/** Hạn nộp hồ sơ (ISO tz-aware) + nhãn hiển thị — OWNER cập nhật mỗi kỳ. */
export const ADMISSION_DEADLINE = "2026-08-31T23:59:59+07:00"
export const ADMISSION_DEADLINE_LABEL = "31/08/2026"
/** Năm footer — suy từ hạn (input cố định, deterministic) để KHÔNG gọi `new
 *  Date()` argless lúc render (dynamicIO cấm khi prerender). */
export const COPYRIGHT_YEAR = new Date(ADMISSION_DEADLINE).getFullYear()

/** Font stack thuần CSS (KHÔNG next/font/google — tránh build fail khi fetch lỗi). */
export const FONT_STACK =
  "'Be Vietnam Pro', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"

// ── Hero (fallback khi campaign không đặt headline/body riêng) ──
export const HERO_BADGE = "🎓 Xét học bạ · Nhập học ngay"
export const HERO_HEADLINE_LEAD = "LÀM CHỦ TAY NGHỀ"
export const HERO_HEADLINE_TAIL = "LÀM CHỦ"
export const HERO_HEADLINE_ACCENT = "TƯƠNG LAI"
// KHÔNG nhồi số ngành cứng vào đây: số ngành hiển thị động (data.programs.length)
// ở heading "Khám phá N ngành học" — chép số cứng sẽ mâu thuẫn khi BE có N khác.
export const HERO_SUBTITLE =
  "Đa dạng ngành nghề, học phí hợp lý, học bổng hấp dẫn và cam kết việc làm sau tốt nghiệp cùng 200+ doanh nghiệp đối tác."

// ── Số liệu / ưu đãi / cảm nhận (editorial) ──
export interface Stat {
  k: string
  v: string
}
export const STATS: readonly Stat[] = [
  { k: "95%", v: "Sinh viên có việc làm sau tốt nghiệp" },
  { k: "200+", v: "Doanh nghiệp đối tác tuyển dụng" },
  // Không dùng số ngành cứng (tránh mâu thuẫn số động BE) — để chung "ngành học".
  { k: "Đa dạng", v: "Ngành đào tạo bậc cao đẳng" },
  { k: "100%", v: "Bằng cấp được công nhận toàn quốc" },
]

export interface Offer {
  n: string
  t: string
  d: string
}
export const OFFERS: readonly Offer[] = [
  {
    n: "01",
    t: "Học bổng đầu vào",
    d: "Học bổng đến 100% học phí học kỳ I cho thí sinh điểm cao và diện hộ nghèo, cận nghèo.",
  },
  {
    n: "02",
    t: "Miễn – giảm học phí",
    d: "Miễn giảm học phí theo chính sách nhà nước cho nhiều đối tượng ưu tiên và dân tộc thiểu số.",
  },
  {
    n: "03",
    t: "Cam kết việc làm",
    d: "Ký cam kết giới thiệu việc làm sau tốt nghiệp với mạng lưới hơn 200 doanh nghiệp đối tác.",
  },
]

export interface Testimonial {
  q: string
  name: string
  role: string
}
export const TESTIMONIALS: readonly Testimonial[] = [
  {
    q: "Em học Điều dưỡng, ngay học kỳ cuối đã được bệnh viện nhận thực tập rồi ký hợp đồng. Thầy cô đồng hành sát sao.",
    name: "Nguyễn Thị Hoa",
    role: "Cựu SV Điều dưỡng – khóa 2022",
  },
  {
    q: "Con tôi học Công nghệ ô tô, trường liên kết gara nên cháu có việc ngay. Học phí lại được miễn giảm.",
    name: "Trần Văn Minh",
    role: "Phụ huynh sinh viên",
  },
  {
    q: "Ngành CNTT được thực hành nhiều, ra trường mình vào được công ty phần mềm ở Buôn Ma Thuột.",
    name: "Lê Quốc Bảo",
    role: "Cựu SV CNTT – khóa 2021",
  },
]

/** Checklist ở khối đăng ký (#reg). */
export const REG_CHECKLIST: readonly string[] = [
  "Xét tuyển bằng học bạ THPT",
  "Học bổng đến 100% học phí kỳ I",
  "Cam kết giới thiệu việc làm",
]

/** Thứ tự nhóm ngành hiển thị ở tier-1 (ngành lạ gom vào "Ngành khác" cuối). */
export const GROUP_ORDER: readonly string[] = [
  "Khối Sức khỏe",
  "Kỹ thuật – Công nghệ",
  "Kinh tế – Dịch vụ",
  "Ngành khác",
]

// ── Kho editorial 14 ngành (nội dung nguyên văn từ mockup) ──
export interface ProgramEditorial {
  group: string
  discount: string // "70%" | "30%"
  hot: boolean // true → badge giảm gradient flame + viền cam
  duration: string // "3 năm" | "2,5 năm"
  tagline: string // hero tier-2
  intro: string // "Giới thiệu ngành"
  subjects: string[] // "Bạn sẽ được học gì?"
  careers: string[] // "Cơ hội nghề nghiệp"
}

/** Generic cho ngành không khớp mockup — vẫn render đủ section. */
const DEFAULT: ProgramEditorial = {
  group: "Ngành khác",
  discount: "30%",
  hot: false,
  duration: "2,5 năm",
  tagline:
    "Chương trình đào tạo gắn thực hành, bám sát nhu cầu tuyển dụng thực tế của doanh nghiệp — học đi đôi với làm.",
  intro:
    "Ngành học trang bị kiến thức nền tảng và kỹ năng nghề nghiệp thực tế, giúp người học sẵn sàng làm việc ngay sau tốt nghiệp và có cơ hội liên thông lên bậc học cao hơn.",
  subjects: [
    "Kiến thức cơ sở ngành",
    "Kỹ năng chuyên môn thực hành",
    "Thực tập tại doanh nghiệp liên kết",
    "Kỹ năng mềm và ngoại ngữ",
    "Đồ án / khóa luận tốt nghiệp",
  ],
  careers: [
    "Làm đúng chuyên ngành sau tốt nghiệp",
    "Thực tập & giới thiệu việc làm tại doanh nghiệp liên kết",
    "Cơ hội thăng tiến theo năng lực",
    "Liên thông lên bậc học cao hơn",
  ],
}

/**
 * Match theo TÊN ngành (khớp đầu tiên thắng → đặt luật hẹp/đặc thù lên trên).
 * Nội dung chép nguyên văn từ object `D` của mockup nganh-detail.
 */
const PROGRAMS_EDITORIAL: ReadonlyArray<{
  match: RegExp
  data: ProgramEditorial
}> = [
  {
    match: /điều dưỡng/i,
    data: {
      group: "Khối Sức khỏe",
      discount: "70%",
      hot: true,
      duration: "3 năm",
      tagline:
        "Nghề điều dưỡng — nhu cầu nhân lực lớn trong và ngoài nước, cơ hội làm việc tại bệnh viện và xuất khẩu lao động.",
      intro:
        "Ngành Điều dưỡng đào tạo cử nhân thực hành có kỹ năng chăm sóc người bệnh toàn diện, thực hiện y lệnh và theo dõi diễn biến sức khỏe. Chương trình chú trọng thực hành tại bệnh viện và hướng đến cơ hội làm việc tại Nhật Bản, Đức.",
      subjects: [
        "Điều dưỡng cơ bản và kỹ thuật",
        "Chăm sóc người bệnh nội – ngoại",
        "Chăm sóc sức khỏe bà mẹ – trẻ em",
        "Kiểm soát nhiễm khuẩn",
        "Thực tập lâm sàng tại bệnh viện",
      ],
      careers: [
        "Điều dưỡng viên bệnh viện, phòng khám",
        "Điều dưỡng chăm sóc tại nhà",
        "Xuất khẩu lao động Nhật, Đức",
        "Nhân viên y tế cơ quan, trường học",
      ],
    },
  },
  {
    match: /y học cổ truyền|cổ truyền|đông y/i,
    data: {
      group: "Khối Sức khỏe",
      discount: "30%",
      hot: false,
      duration: "3 năm",
      tagline:
        "Kết hợp tinh hoa y học cổ truyền với y học hiện đại — chăm sóc sức khỏe bằng châm cứu, xoa bóp, dược liệu.",
      intro:
        "Ngành Y học cổ truyền đào tạo nhân lực nắm vững lý luận Đông y, các phương pháp châm cứu, xoa bóp bấm huyệt, dưỡng sinh và sử dụng dược liệu, kết hợp kiến thức y học hiện đại để chăm sóc và phục hồi sức khỏe.",
      subjects: [
        "Lý luận Y học cổ truyền",
        "Châm cứu – Xoa bóp bấm huyệt",
        "Dược học cổ truyền – Bào chế",
        "Bệnh học và điều trị YHCT",
        "Dưỡng sinh – Phục hồi chức năng",
      ],
      careers: [
        "Kỹ thuật viên YHCT bệnh viện",
        "Nhân viên phòng khám Đông y",
        "Cơ sở xoa bóp – phục hồi chức năng",
        "Kinh doanh dược liệu",
      ],
    },
  },
  {
    match: /y sỹ|y sĩ|đa khoa/i,
    data: {
      group: "Khối Sức khỏe",
      discount: "70%",
      hot: true,
      duration: "3 năm",
      tagline:
        "Đào tạo Y sỹ có năng lực khám, chữa bệnh ban đầu — nền tảng vững chắc để công tác tại y tế cơ sở hoặc học liên thông Bác sỹ.",
      intro:
        "Ngành Y sỹ đa khoa trang bị kiến thức y học cơ sở và lâm sàng, kỹ năng khám, chẩn đoán và xử trí các bệnh thường gặp. Sinh viên thực tập tại bệnh viện, trạm y tế dưới sự hướng dẫn của đội ngũ bác sỹ giàu kinh nghiệm.",
      subjects: [
        "Giải phẫu – Sinh lý",
        "Bệnh học nội – ngoại khoa",
        "Nhi – Sản phụ khoa",
        "Y học cộng đồng – Y tế công cộng",
        "Thực hành lâm sàng tại bệnh viện",
      ],
      careers: [
        "Y sỹ tại trạm y tế xã, phường",
        "Y sỹ phòng khám đa khoa",
        "Nhân viên y tế trường học, cơ quan",
        "Học liên thông lên Bác sỹ",
      ],
    },
  },
  {
    match: /dược/i,
    data: {
      group: "Khối Sức khỏe",
      discount: "70%",
      hot: true,
      duration: "3 năm",
      tagline:
        "Trở thành Dược sỹ cao đẳng — nghề được xã hội trọng vọng, nhu cầu nhân lực luôn cao tại các nhà thuốc, bệnh viện và công ty dược.",
      intro:
        "Ngành Dược đào tạo Dược sỹ trình độ cao đẳng có kiến thức về dược lý, bào chế, quản lý và cung ứng thuốc. Sinh viên được thực hành tại phòng thí nghiệm hiện đại và thực tập tại nhà thuốc, bệnh viện, doanh nghiệp dược liên kết với nhà trường.",
      subjects: [
        "Hóa dược – Dược lý",
        "Bào chế và Công nghiệp dược",
        "Dược liệu – Dược học cổ truyền",
        "Quản lý và Kinh tế dược",
        "Thực hành nhà thuốc – Dược lâm sàng",
      ],
      careers: [
        "Dược sỹ nhà thuốc, quầy thuốc",
        "Trình dược viên công ty dược",
        "Nhân viên kho – cung ứng thuốc",
        "Dược sỹ tại khoa Dược bệnh viện",
      ],
    },
  },
  {
    match: /công nghệ thông tin|cntt|phần mềm/i,
    data: {
      group: "Kỹ thuật – Công nghệ",
      discount: "30%",
      hot: false,
      duration: "2,5 năm",
      tagline:
        "Ngành công nghệ hot nhất — lập trình, quản trị mạng, thiết kế web, cơ hội việc làm rộng mở với thu nhập hấp dẫn.",
      intro:
        "Ngành Công nghệ thông tin đào tạo lập trình viên, kỹ thuật viên có khả năng phát triển phần mềm, thiết kế website, quản trị hệ thống mạng và cơ sở dữ liệu. Sinh viên thực hành trên dự án thực tế và thực tập tại doanh nghiệp phần mềm.",
      subjects: [
        "Lập trình cơ bản và hướng đối tượng",
        "Thiết kế và lập trình web",
        "Cơ sở dữ liệu",
        "Mạng máy tính và quản trị hệ thống",
        "Đồ án phần mềm thực tế",
      ],
      careers: [
        "Lập trình viên web / ứng dụng",
        "Kỹ thuật viên quản trị mạng",
        "Nhân viên IT doanh nghiệp",
        "Thiết kế – bảo trì website",
      ],
    },
  },
  {
    match: /ô ?tô/i,
    data: {
      group: "Kỹ thuật – Công nghệ",
      discount: "70%",
      hot: true,
      duration: "2,5 năm",
      tagline:
        "Làm chủ kỹ thuật sửa chữa, bảo dưỡng ô tô — ngành có nhu cầu tuyển dụng cao tại các gara, hãng xe, showroom.",
      intro:
        "Ngành Công nghệ ô tô đào tạo kỹ thuật viên có tay nghề chẩn đoán, bảo dưỡng và sửa chữa động cơ, hệ thống điện, gầm và điều hòa ô tô. Sinh viên thực hành trên xe thật tại xưởng và thực tập tại gara, hãng xe liên kết.",
      subjects: [
        "Cấu tạo động cơ ô tô",
        "Hệ thống điện – điện tử ô tô",
        "Hệ thống gầm – truyền lực",
        "Chẩn đoán và sửa chữa",
        "Thực hành xưởng ô tô",
      ],
      careers: [
        "Kỹ thuật viên gara, hãng xe",
        "Cố vấn dịch vụ showroom",
        "Nhân viên bảo dưỡng đội xe",
        "Tự mở gara sửa chữa ô tô",
      ],
    },
  },
  {
    match: /thú y|chăn nuôi/i,
    data: {
      group: "Kỹ thuật – Công nghệ",
      discount: "70%",
      hot: true,
      duration: "2,5 năm",
      tagline:
        "Ngành thiết yếu với nông nghiệp Tây Nguyên — chăm sóc, phòng và chữa bệnh cho vật nuôi, cơ hội khởi nghiệp cao.",
      intro:
        "Ngành Chăn nuôi Thú y đào tạo kỹ thuật viên nắm vững kỹ thuật chăn nuôi, phòng và điều trị bệnh cho gia súc, gia cầm. Phù hợp đặc thù nông nghiệp Tây Nguyên, mở ra cơ hội việc làm tại trang trại, công ty thức ăn chăn nuôi và khởi nghiệp.",
      subjects: [
        "Giải phẫu – sinh lý vật nuôi",
        "Kỹ thuật chăn nuôi gia súc, gia cầm",
        "Bệnh học và dược lý thú y",
        "Chẩn đoán và điều trị bệnh",
        "Thực hành tại trang trại",
      ],
      careers: [
        "Kỹ thuật viên trang trại",
        "Nhân viên công ty thức ăn chăn nuôi",
        "Mở cửa hàng thuốc thú y",
        "Khởi nghiệp chăn nuôi",
      ],
    },
  },
  {
    match: /vận tải|logistic/i,
    data: {
      group: "Kỹ thuật – Công nghệ",
      discount: "30%",
      hot: false,
      duration: "2,5 năm",
      tagline:
        "Quản lý và điều hành hoạt động vận tải — ngành gắn với logistics đang phát triển mạnh.",
      intro:
        "Ngành Kinh doanh vận tải đường bộ đào tạo nhân lực tổ chức, quản lý và khai thác dịch vụ vận tải hàng hóa và hành khách, am hiểu logistics, luật giao thông và nghiệp vụ điều hành phương tiện.",
      subjects: [
        "Tổ chức và quản lý vận tải",
        "Logistics và chuỗi cung ứng",
        "Khai thác phương tiện vận tải",
        "Luật và an toàn giao thông",
        "Nghiệp vụ kinh doanh vận tải",
      ],
      careers: [
        "Nhân viên điều hành vận tải",
        "Nhân viên logistics, kho vận",
        "Quản lý đội xe doanh nghiệp",
        "Kinh doanh dịch vụ vận tải",
      ],
    },
  },
  {
    match: /kế toán/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      discount: "30%",
      hot: false,
      duration: "2,5 năm",
      tagline:
        "Nghề ổn định, cần thiết cho mọi doanh nghiệp — thành thạo sổ sách, thuế, phần mềm kế toán.",
      intro:
        "Ngành Kế toán đào tạo nhân viên kế toán nắm vững nghiệp vụ ghi chép, lập báo cáo tài chính, kê khai thuế và sử dụng phần mềm kế toán. Sinh viên thực hành trên chứng từ thực tế và phần mềm chuyên dụng.",
      subjects: [
        "Nguyên lý kế toán",
        "Kế toán doanh nghiệp",
        "Thuế và kê khai thuế",
        "Phần mềm kế toán (MISA, Excel)",
        "Thực hành kế toán tổng hợp",
      ],
      careers: [
        "Kế toán viên doanh nghiệp",
        "Kế toán thuế, kho, bán hàng",
        "Nhân viên hành chính – tài chính",
        "Dịch vụ kế toán",
      ],
    },
  },
  {
    match: /văn phòng/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      discount: "30%",
      hot: false,
      duration: "2,5 năm",
      tagline:
        "Tổ chức, điều hành công việc văn phòng chuyên nghiệp — kỹ năng hành chính, văn thư, lễ tân.",
      intro:
        "Ngành Quản trị văn phòng đào tạo nhân lực có kỹ năng tổ chức, quản lý công việc hành chính, văn thư lưu trữ, tổ chức sự kiện và hỗ trợ điều hành, thành thạo tin học văn phòng và giao tiếp công sở.",
      subjects: [
        "Quản trị hành chính văn phòng",
        "Văn thư – lưu trữ",
        "Tin học văn phòng nâng cao",
        "Kỹ năng giao tiếp và lễ tân",
        "Tổ chức sự kiện, hội họp",
      ],
      careers: [
        "Nhân viên hành chính – văn phòng",
        "Nhân viên văn thư, lưu trữ",
        "Thư ký, trợ lý",
        "Lễ tân doanh nghiệp",
      ],
    },
  },
  {
    match: /tiếng anh|ngôn ngữ anh/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      discount: "30%",
      hot: false,
      duration: "3 năm",
      tagline:
        "Thành thạo tiếng Anh giao tiếp và biên – phiên dịch — chìa khóa cho nhiều cơ hội nghề nghiệp.",
      intro:
        "Ngành Tiếng Anh đào tạo cử nhân thực hành sử dụng thành thạo bốn kỹ năng nghe, nói, đọc, viết; có năng lực biên – phiên dịch cơ bản và giao tiếp trong môi trường công việc quốc tế, du lịch, thương mại.",
      subjects: [
        "Nghe – Nói – Đọc – Viết nâng cao",
        "Ngữ pháp và ngữ âm",
        "Tiếng Anh thương mại",
        "Biên – phiên dịch cơ bản",
        "Tiếng Anh du lịch – khách sạn",
      ],
      careers: [
        "Biên – phiên dịch",
        "Nhân viên công ty nước ngoài",
        "Hướng dẫn viên, lễ tân khách sạn",
        "Giáo viên tiếng Anh trung tâm",
      ],
    },
  },
  {
    match: /hướng dẫn du lịch|hướng dẫn viên/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      discount: "70%",
      hot: true,
      duration: "2,5 năm",
      tagline:
        "Khám phá nghề hướng dẫn viên — đi nhiều, gặp gỡ nhiều, phát huy thế mạnh du lịch Tây Nguyên.",
      intro:
        "Ngành Hướng dẫn du lịch đào tạo hướng dẫn viên có kiến thức văn hóa, lịch sử, địa lý và nghiệp vụ tổ chức, điều hành tour. Sinh viên rèn kỹ năng thuyết minh, xử lý tình huống và thực tập tại các điểm du lịch, công ty lữ hành.",
      subjects: [
        "Tổng quan du lịch và tuyến điểm",
        "Nghiệp vụ hướng dẫn du lịch",
        "Văn hóa – lịch sử Việt Nam",
        "Tổ chức và điều hành tour",
        "Thực tập tour thực tế",
      ],
      careers: [
        "Hướng dẫn viên du lịch",
        "Điều hành tour công ty lữ hành",
        "Nhân viên bán tour",
        "Quản lý điểm du lịch",
      ],
    },
  },
  {
    // Bắt các ngành du lịch còn lại (Quản lý & kinh doanh du lịch) sau HDV.
    match: /du lịch|lữ hành|khách sạn/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      discount: "30%",
      hot: false,
      duration: "2,5 năm",
      tagline:
        "Quản lý dịch vụ lữ hành, khách sạn, nhà hàng — ngành mũi nhọn của kinh tế Tây Nguyên.",
      intro:
        "Ngành Quản lý và kinh doanh du lịch đào tạo nhân lực tổ chức, quản lý và kinh doanh dịch vụ lữ hành, lưu trú, ẩm thực. Sinh viên nắm nghiệp vụ khách sạn – nhà hàng, xây dựng và bán sản phẩm du lịch.",
      subjects: [
        "Quản trị kinh doanh lữ hành",
        "Nghiệp vụ khách sạn – nhà hàng",
        "Marketing du lịch",
        "Thiết kế và điều hành tour",
        "Thực tập tại khách sạn, công ty du lịch",
      ],
      careers: [
        "Nhân viên điều hành lữ hành",
        "Quản lý bộ phận khách sạn",
        "Nhân viên kinh doanh du lịch",
        "Quản lý nhà hàng, khu nghỉ dưỡng",
      ],
    },
  },
  {
    // Catch-all khối kinh doanh (Quản trị kinh doanh) — đặt cuối.
    match: /quản trị kinh doanh|kinh doanh|quản trị|kinh tế|marketing/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      discount: "30%",
      hot: false,
      duration: "2,5 năm",
      tagline:
        "Nền tảng kinh doanh toàn diện — quản lý, marketing, bán hàng, khởi nghiệp trong mọi lĩnh vực.",
      intro:
        "Ngành Quản trị kinh doanh trang bị kiến thức về quản trị, marketing, bán hàng, nhân sự và tài chính. Sinh viên phát triển tư duy kinh doanh, kỹ năng lập kế hoạch và điều hành để làm việc tại doanh nghiệp hoặc tự khởi nghiệp.",
      subjects: [
        "Quản trị học và quản trị doanh nghiệp",
        "Marketing căn bản",
        "Quản trị bán hàng",
        "Quản trị nhân sự",
        "Khởi sự kinh doanh",
      ],
      careers: [
        "Nhân viên kinh doanh, bán hàng",
        "Nhân viên marketing",
        "Quản lý cửa hàng, chi nhánh",
        "Tự khởi nghiệp",
      ],
    },
  },
]

/** Nội dung editorial cho 1 ngành theo tên (khớp đầu tiên; lạ → DEFAULT). */
export function programEditorial(name: string): ProgramEditorial {
  for (const e of PROGRAMS_EDITORIAL) if (e.match.test(name)) return e.data
  return DEFAULT
}
