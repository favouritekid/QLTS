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
export const SCHOOL_ADDRESS = "Số 02 Lý Nhân Tông, phường Tân An, tỉnh Đắk Lắk"
/** Ảnh hero chung (sinh viên trường) — tier-1 panel phải. Ảnh THẬT tải từ
 *  tnpc.edu.vn về public/lp/. Owner thay ảnh khác bằng cách ghi đè file này. */
export const SCHOOL_HERO_IMAGE = "/lp/campus-students.jpg"
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
  "Đa dạng ngành nghề, học phí hợp lý, học bổng hấp dẫn và cam kết việc làm sau tốt nghiệp cùng 100+ doanh nghiệp đối tác."

// ── Số liệu / ưu đãi / cảm nhận (editorial) ──
export interface Stat {
  k: string
  v: string
}
export const STATS: readonly Stat[] = [
  { k: "95%", v: "Sinh viên có việc làm sau tốt nghiệp" },
  { k: "100+", v: "Doanh nghiệp đối tác tuyển dụng" },
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
    d: "Ký cam kết giới thiệu việc làm đúng chuyên môn nghề sau tốt nghiệp, với mạng lưới hơn 100 doanh nghiệp đối tác.",
  },
]

export interface Testimonial {
  q: string
  name: string
  role: string
  img?: string // avatar THẬT (public/lp/testimonials/…); thiếu → placeholder gradient
}
// Cảm nghĩ THẬT của sinh viên (nguyên văn + ảnh từ tnpc.edu.vn "Cảm nghĩ TNPC").
export const TESTIMONIALS: readonly Testimonial[] = [
  {
    q: "Được trở thành sinh viên cao đẳng chuyên ngành Công nghệ Ô tô tại trường là cơ hội để em vừa phát triển cả về kiến thức chuyên môn vừa trau dồi kỹ năng tay nghề lẫn kỹ năng mềm. Điều này làm nền tảng để bản thân em có thể ứng dụng vào công việc thực tế sau khi tốt nghiệp.",
    name: "Phạm Thế Hùng",
    role: "Lớp Công nghệ Ô tô – CCO2331",
    img: "/lp/testimonials/sv-o-to.jpg",
  },
  {
    q: "Mình rất vui khi được trở thành tân sinh viên của Cao đẳng Bách khoa Tây Nguyên. Mình đã lựa chọn trường vì chương trình học thực tế từ đó nhanh chóng tiếp cận với công việc sau khi ra trường. Mình tin rằng 2 năm rưỡi học tại trường sẽ là quãng thời gian đáng nhớ nhất.",
    name: "Thái Văn Quang",
    role: "Lớp Chăn nuôi-Thú y – CTY2331",
    img: "/lp/testimonials/sv-chan-nuoi.jpg",
  },
  {
    q: "Môi trường học tập năng động và cơ sở vật chất tốt là hai yếu tố chính em yêu thích nhất tại Cao đẳng Bách khoa Tây Nguyên. Là sinh viên ngành công nghệ thông tin, em tin rằng nhà trường sẽ giúp em phát triển điểm mạnh CNTT của mình, từng bước đạt được ước mơ.",
    name: "Lê Minh Chương",
    role: "Lớp Công nghệ Thông tin – CIT2331",
    img: "/lp/testimonials/sv-cntt.jpg",
  },
  {
    q: "Bản thân em có niềm yêu thích với ngành y, từ đó em đã tìm hiểu trường Cao đẳng Bách khoa Tây Nguyên. Không chỉ lựa chọn môi trường học tập mà đây còn là nơi để em phát triển bản thân. Bên cạnh đào tạo chuyên môn, trường còn có nhiều hoạt động văn nghệ, thể thao, giao lưu.",
    name: "H Sana Niê",
    role: "Lớp Điều dưỡng – CDD2131",
    img: "/lp/testimonials/sv-dieu-duong.jpg",
  },
  {
    q: "Sau khi tìm hiểu biết được Cao đẳng Bách khoa Tây Nguyên có đào tạo ngành Y sỹ đa khoa. Đây là ngôi trường phù hợp với nhu cầu và tiêu chí của em nên em quyết định theo học. Với mục tiêu đề ra, em sẽ học hỏi và rèn luyện để có nghề nghiệp và tương lai tốt hơn.",
    name: "Lê Minh Nhân",
    role: "Lớp Y sỹ đa khoa – TYS2121",
    img: "/lp/testimonials/sv-y-sy.jpg",
  },
  {
    q: "Để được cơ hội công tác trong ngành Dược em đã tham khảo chương trình học của nhiều trường. Với lộ trình học xen kẽ thực hành chiếm 75% thời lượng, kết hợp đi thực tập tại các đơn vị, cơ sở y tế tại trường Cao đẳng Bách khoa Tây Nguyên đã giúp em tự tin hơn khi sắp tốt nghiệp.",
    name: "H Thu Huyền Niê",
    role: "Lớp Dược – CDU2231",
    img: "/lp/testimonials/sv-duoc.jpg",
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

/** 1 câu hỏi–đáp trong khối FAQ ngành. */
export interface Faq {
  q: string
  a: string
}

// ── Kho editorial ngành (nội dung marketing — KHÔNG phải dữ liệu BE) ──
// 4 trường mới (goodIf/considerIf/trends/faq) là OPTIONAL: ngành chưa biên tập
// riêng dùng fallback GENERIC_* để vẫn render đủ khối. Badge miễn giảm học phí
// KHÔNG còn ở đây — suy từ cờ THẬT `is_heavy` của BE (NĐ 238/NĐ-CP).
export interface ProgramEditorial {
  group: string
  duration: string // "3 năm" | "2,5 năm"
  tagline: string // hero tier-2
  intro: string // "Giới thiệu ngành"
  subjects: string[] // "Bạn sẽ được học gì?"
  careers: string[] // "Cơ hội nghề nghiệp"
  image?: string // ảnh THẬT theo ngành (public/lp/programs/…); thiếu → gradient+icon
  goodIf?: string[] // "Ngành này hợp với bạn nếu…"
  considerIf?: string[] // "Cân nhắc nếu bạn…" (anti-fit trung thực)
  trends?: string[] // "Xu hướng việc làm"
  faq?: Faq[] // Hỏi – Đáp ngành
}

// ── Fallback generic cho các ngành CHƯA biên tập riêng 4 khối mới ──
// Mọi ngành vẫn trả lời đủ "có hợp không / xu hướng / FAQ" (không rỗng section).
export const GENERIC_GOOD_IF: readonly string[] = [
  "Yêu thích và muốn theo đuổi nghề một cách nghiêm túc",
  "Thích học đi đôi với thực hành, làm nghề thực tế",
  "Muốn ra trường có việc làm sớm, thu nhập ổn định",
]
export const GENERIC_CONSIDER_IF: readonly string[] = [
  "Chưa chắc về sở thích — nên gọi hotline để được tư vấn hướng nghiệp",
  "Muốn học nặng về nghiên cứu, lý thuyết hàn lâm dài hạn",
]
export const GENERIC_TRENDS: readonly string[] = [
  "Doanh nghiệp ưu tiên nhân lực có tay nghề, làm được việc ngay",
  "Nhu cầu tuyển dụng ổn định tại Tây Nguyên và các tỉnh lân cận",
  "Cơ hội liên thông lên bậc cao hơn trong khi vẫn đi làm",
]
export const GENERIC_FAQ: readonly Faq[] = [
  {
    q: "Xét tuyển bằng cách nào?",
    a: "Xét học bạ THPT — thủ tục đơn giản, không thi tuyển. Gọi hotline để được hướng dẫn hồ sơ chi tiết.",
  },
  {
    q: "Ra trường có được hỗ trợ việc làm không?",
    a: "Trường cam kết giới thiệu việc làm qua mạng lưới doanh nghiệp đối tác; nhiều sinh viên có việc ngay trong kỳ thực tập.",
  },
  {
    q: "Học xong có liên thông lên cao hơn được không?",
    a: "Có. Người học có thể liên thông lên bậc cao hơn (Trung cấp → Cao đẳng → Đại học) theo quy định.",
  },
]

/** Generic cho ngành không khớp mockup — vẫn render đủ section. */
const DEFAULT: ProgramEditorial = {
  group: "Ngành khác",
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
// CNTT: 2 mã dùng CHUNG nội dung, chỉ khác ẢNH — CĐ "Công nghệ thông tin"
// (cntt.jpg) + TC "Công nghệ thông tin (ứng dụng phần mềm)" (cntt-phan-mem.jpg).
// Tách entry /phần mềm/ đặt TRƯỚC entry CNTT chung bên dưới (khớp đầu tiên thắng).
const CNTT_EDITORIAL: ProgramEditorial = {
  group: "Kỹ thuật – Công nghệ",
  image: "/lp/programs/cntt.jpg",
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
  goodIf: [
    "Thích máy tính, công nghệ, giải quyết vấn đề bằng logic",
    "Kiên nhẫn tìm lỗi và tự học cái mới liên tục",
    "Muốn nghề thu nhập tốt, có thể làm từ xa / freelance",
  ],
  considerIf: [
    "Không thích ngồi lâu với máy tính, ngại tư duy logic",
    "Mong muốn công việc ít phải cập nhật kiến thức mới",
  ],
  trends: [
    "Chuyển đổi số khiến hầu hết doanh nghiệp đều cần nhân lực IT",
    "Nhu cầu lập trình, quản trị mạng tăng đều, lương hấp dẫn",
    "Có thể làm từ xa, freelance hoặc cho công ty nước ngoài",
  ],
  faq: [
    {
      q: "Học IT có cần giỏi Toán không?",
      a: "Cần tư duy logic hơn là Toán cao siêu. Chương trình dạy từ lập trình cơ bản; quan trọng nhất là chăm thực hành trên dự án thật.",
    },
    {
      q: "Ra trường có làm được ngay không?",
      a: "Chương trình thực hành trên dự án thực tế và thực tập tại doanh nghiệp phần mềm, giúp sinh viên sớm làm được việc.",
    },
  ],
}

const PROGRAMS_EDITORIAL: ReadonlyArray<{
  match: RegExp
  data: ProgramEditorial
}> = [
  {
    match: /điều dưỡng/i,
    data: {
      group: "Khối Sức khỏe",
      image: "/lp/programs/dieu-duong.jpg",
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
      goodIf: [
        "Thích chăm sóc, giúp đỡ người khác",
        "Bình tĩnh, tỉ mỉ, cẩn thận, có trách nhiệm",
        "Sức khỏe tốt, không ngại làm việc theo ca",
      ],
      considerIf: [
        "Sợ máu hoặc môi trường bệnh viện",
        "Không muốn làm việc ca kíp, cuối tuần, lễ tết",
      ],
      trends: [
        "Dân số già hóa → nhu cầu điều dưỡng tăng mạnh trên cả nước",
        "Tây Nguyên còn thiếu nhân lực y tế tuyến cơ sở",
        "Nhật Bản, Đức tuyển điều dưỡng đều đặn với thu nhập cao",
        "Ngành sức khỏe thuộc nhóm có tỷ lệ việc làm cao nhất",
      ],
      faq: [
        {
          q: "Không giỏi các môn tự nhiên có học được không?",
          a: "Được. Chương trình chú trọng thực hành và kỹ năng chăm sóc; nhà trường đồng hành từ nền tảng. Quan trọng nhất là sự chăm chỉ và yêu nghề.",
        },
        {
          q: "Học Điều dưỡng có phải trực đêm không?",
          a: "Khi thực tập và đi làm tại bệnh viện sẽ có ca trực (kể cả ban đêm) theo lịch — đây là đặc thù của nghề chăm sóc người bệnh 24/7.",
        },
        {
          q: "Muốn đi Nhật/Đức làm điều dưỡng cần gì?",
          a: "Cần bằng Điều dưỡng và trình độ ngoại ngữ theo chương trình tiếp nhận. Gọi hotline để được tư vấn lộ trình học ngoại ngữ và kết nối đơn hàng.",
        },
      ],
    },
  },
  {
    match: /y học cổ truyền|cổ truyền|đông y/i,
    data: {
      group: "Khối Sức khỏe",
      image: "/lp/programs/y-hoc-co-truyen.jpg",
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
      goodIf: [
        "Yêu thích y học cổ truyền, dược liệu, dưỡng sinh",
        "Đôi tay khéo léo, kiên nhẫn, tỉ mỉ",
        "Muốn nghề vừa chăm sóc sức khỏe vừa có thể tự kinh doanh",
      ],
      considerIf: [
        "Muốn theo hướng bác sỹ điều trị chuyên sâu ở bệnh viện lớn",
        "Không thích công việc cần sự nhẹ nhàng, kiên trì lâu dài",
      ],
      trends: [
        "Xu hướng chăm sóc sức khỏe tự nhiên, phục hồi chức năng lên ngôi",
        "Nhu cầu spa – dưỡng sinh – phục hồi chức năng tăng nhanh",
        "Có thể tự mở cơ sở xoa bóp, kinh doanh dược liệu",
      ],
      faq: [
        {
          q: "Ra trường làm ở đâu?",
          a: "Khoa/tổ YHCT bệnh viện, phòng khám Đông y, cơ sở xoa bóp – phục hồi chức năng, hoặc tự kinh doanh dược liệu.",
        },
        {
          q: "Có được châm cứu cho bệnh nhân không?",
          a: "Phạm vi hành nghề theo chứng chỉ và quy định. Chương trình trang bị kỹ thuật châm cứu, xoa bóp bấm huyệt bài bản để làm nghề đúng quy định.",
        },
      ],
    },
  },
  {
    match: /y sỹ|y sĩ|đa khoa/i,
    data: {
      group: "Khối Sức khỏe",
      image: "/lp/programs/y-sy.jpg",
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
      goodIf: [
        "Mơ ước theo nghề y, muốn khám chữa bệnh ban đầu",
        "Chăm chỉ, chịu khó, có trách nhiệm với sức khỏe người khác",
        "Định hướng học liên thông lên Bác sỹ về sau",
      ],
      considerIf: [
        "Sợ máu, sợ môi trường lâm sàng",
        "Không sẵn sàng học lâu và trực ca tại cơ sở y tế",
      ],
      trends: [
        "Y tế cơ sở (trạm y tế xã/phường) luôn cần nhân lực ổn định",
        "Là bước đệm vững chắc để liên thông lên Bác sỹ",
        "Nhu cầu chăm sóc sức khỏe ban đầu ở vùng Tây Nguyên còn lớn",
      ],
      faq: [
        {
          q: "Y sỹ khác Bác sỹ thế nào?",
          a: "Y sỹ khám, chữa các bệnh thường gặp và làm việc ở tuyến cơ sở; là nền tảng để học liên thông lên Bác sỹ theo quy định.",
        },
        {
          q: "Học xong có được mở phòng khám không?",
          a: "Việc hành nghề, mở cơ sở phải theo chứng chỉ hành nghề và quy định pháp luật. Gọi hotline để được tư vấn lộ trình cụ thể.",
        },
      ],
    },
  },
  {
    match: /dược/i,
    data: {
      group: "Khối Sức khỏe",
      image: "/lp/programs/duoc.jpg",
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
      goodIf: [
        "Cẩn thận, tỉ mỉ, trí nhớ tốt (nhớ thuốc, liều dùng)",
        "Thích công việc ổn định, sạch sẽ, giao tiếp với khách",
        "Muốn nghề có thể tự mở nhà thuốc, quầy thuốc",
      ],
      considerIf: [
        "Cẩu thả, ngại ghi nhớ chi tiết (rủi ro cao với thuốc)",
        "Không thích công việc cần tuân thủ quy trình nghiêm ngặt",
      ],
      trends: [
        "Hệ thống nhà thuốc mở rộng nhanh → nhu cầu Dược sỹ luôn cao",
        "Chuỗi nhà thuốc hiện đại tuyển dụng nhiều, đãi ngộ tốt",
        "Có thể tự khởi nghiệp mở nhà thuốc sau khi đủ điều kiện",
      ],
      faq: [
        {
          q: "Học Dược cao đẳng có mở được nhà thuốc không?",
          a: "Việc đứng tên/mở nhà thuốc phải theo chứng chỉ hành nghề và quy định. Bằng Dược cao đẳng là điều kiện nền tảng — gọi hotline để được tư vấn cụ thể.",
        },
        {
          q: "Ra trường dễ xin việc không?",
          a: "Nhu cầu Dược sỹ tại nhà thuốc, công ty dược, bệnh viện rất lớn; nhiều sinh viên có việc ngay sau thực tập.",
        },
      ],
    },
  },
  {
    match: /chế biến món ăn|nấu ăn|ẩm thực|đầu bếp/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      image: "/lp/programs/che-bien-mon-an.jpg",
      duration: "2 năm",
      tagline:
        "Trở thành đầu bếp chuyên nghiệp — nghề mũi nhọn của nhà hàng – khách sạn, cơ hội việc làm rộng và có thể tự kinh doanh ẩm thực.",
      intro:
        "Ngành Kỹ thuật chế biến món ăn đào tạo đầu bếp nắm vững kỹ thuật sơ chế, chế biến món Á – Âu, làm bánh và trang trí món ăn, bảo đảm an toàn vệ sinh thực phẩm. Sinh viên thực hành nhiều tại bếp thực nghiệm và thực tập tại nhà hàng, khách sạn liên kết.",
      subjects: [
        "Kỹ thuật sơ chế và cắt thái",
        "Chế biến món ăn Á – Âu",
        "Kỹ thuật làm bánh và món tráng miệng",
        "An toàn vệ sinh thực phẩm – dinh dưỡng",
        "Thực hành bếp nhà hàng, khách sạn",
      ],
      careers: [
        "Đầu bếp nhà hàng, khách sạn, khu nghỉ dưỡng",
        "Phụ bếp → tổ trưởng bếp → bếp trưởng (theo kinh nghiệm)",
        "Bếp bánh, chế biến suất ăn công nghiệp",
        "Tự mở quán ăn, kinh doanh ẩm thực",
      ],
      goodIf: [
        "Yêu thích nấu ăn, sáng tạo với món ăn",
        "Nhanh tay, chịu được môi trường bếp nóng, đứng nhiều",
        "Muốn nghề có thể tự khởi nghiệp quán ăn",
      ],
      considerIf: [
        "Không chịu được áp lực giờ cao điểm, môi trường bếp nóng bức",
        "Ngại làm buổi tối, cuối tuần, lễ tết (giờ vàng của nhà hàng)",
      ],
      trends: [
        "Du lịch – nhà hàng – khách sạn phục hồi mạnh → cần nhiều đầu bếp",
        "Đầu bếp giỏi luôn khan hiếm, thu nhập tăng nhanh theo tay nghề",
        "Dễ khởi nghiệp quán ăn, kinh doanh ẩm thực với vốn vừa phải",
      ],
      faq: [
        {
          q: "Chưa biết nấu ăn có học được không?",
          a: "Được. Chương trình dạy từ kỹ thuật cơ bản (sơ chế, cắt thái) đến nâng cao, thực hành rất nhiều tại bếp — quan trọng là chăm chỉ luyện tay nghề.",
        },
        {
          q: "Ra trường có dễ xin việc không?",
          a: "Nhà hàng, khách sạn, khu nghỉ dưỡng luôn cần đầu bếp; nhiều sinh viên có việc ngay trong kỳ thực tập.",
        },
      ],
    },
  },
  {
    // Mã TC hẹp hơn — đặt TRƯỚC entry CNTT chung để khớp đầu tiên (ảnh riêng).
    match: /phần mềm/i,
    data: { ...CNTT_EDITORIAL, image: "/lp/programs/cntt-phan-mem.jpg" },
  },
  {
    match: /công nghệ thông tin|cntt/i,
    data: CNTT_EDITORIAL,
  },
  {
    match: /ô ?tô/i,
    data: {
      group: "Kỹ thuật – Công nghệ",
      image: "/lp/programs/o-to.jpg",
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
      goodIf: [
        "Thích máy móc, động cơ, thích tự tay tháo lắp sửa chữa",
        "Khỏe khoắn, chịu khó, không ngại dầu mỡ",
        "Muốn nghề dễ xin việc và có thể tự mở gara",
      ],
      considerIf: [
        "Không thích môi trường xưởng, tiếng ồn, dầu mỡ",
        "Ngại công việc chân tay, đứng và vận động nhiều",
      ],
      trends: [
        "Ô tô ngày càng phổ biến → gara, hãng xe luôn thiếu thợ lành nghề",
        "Xe điện, hybrid lên ngôi → thợ biết công nghệ mới rất được săn đón",
        "Tay nghề cứng có thể tự mở gara, thu nhập cao",
      ],
      faq: [
        {
          q: "Con gái học Công nghệ ô tô được không?",
          a: "Được. Ngoài sửa chữa còn nhiều vị trí như cố vấn dịch vụ, quản lý phụ tùng, kinh doanh — phù hợp cả nam và nữ.",
        },
        {
          q: "Ra trường làm ở đâu?",
          a: "Gara, hãng xe, showroom, trạm bảo dưỡng, hoặc tự mở gara. Trường liên kết gara nên nhiều em có việc ngay khi thực tập.",
        },
      ],
    },
  },
  {
    match: /thú y|chăn nuôi/i,
    data: {
      group: "Kỹ thuật – Công nghệ",
      image: "/lp/programs/chan-nuoi-thu-y.jpg",
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
      goodIf: [
        "Yêu động vật, thích công việc gắn với nông nghiệp, trang trại",
        "Chịu khó, không ngại môi trường chuồng trại",
        "Muốn nghề dễ khởi nghiệp ở quê, hợp vùng Tây Nguyên",
      ],
      considerIf: [
        "Sợ hoặc dị ứng với động vật, ngại mùi chuồng trại",
        "Không thích công việc ngoài trời, tay chân",
      ],
      trends: [
        "Chăn nuôi Tây Nguyên phát triển mạnh → cần kỹ thuật viên thú y",
        "Trang trại, công ty thức ăn chăn nuôi tuyển dụng đều đặn",
        "Dễ khởi nghiệp: mở cửa hàng thuốc thú y, trại chăn nuôi",
      ],
      faq: [
        {
          q: "Học xong có làm bác sỹ thú y được không?",
          a: "Tốt nghiệp là kỹ thuật viên chăn nuôi – thú y, làm tại trang trại, cửa hàng thuốc thú y; có thể liên thông lên bậc cao hơn theo quy định.",
        },
        {
          q: "Có phải chỉ làm ở quê không?",
          a: "Không. Ngoài trang trại còn có công ty thức ăn chăn nuôi, thuốc thú y, cơ quan quản lý — ở cả thành phố và nông thôn.",
        },
      ],
    },
  },
  {
    match: /vận tải|logistic/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      image: "/lp/programs/van-tai.jpg",
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
      goodIf: [
        "Thích công việc tổ chức, điều phối, quản lý",
        "Cẩn thận, có tư duy sắp xếp, chịu được nhịp độ nhanh",
        "Quan tâm lĩnh vực logistics đang phát triển mạnh",
      ],
      considerIf: [
        "Không thích công việc giấy tờ, điều phối, theo dõi lịch trình",
        "Ngại áp lực thời gian giao – nhận hàng",
      ],
      trends: [
        "Thương mại điện tử bùng nổ → logistics và vận tải tăng nhanh",
        "Doanh nghiệp vận tải, kho vận liên tục cần nhân lực điều hành",
        "Cơ hội tự kinh doanh dịch vụ vận tải, nhà xe",
      ],
      faq: [
        {
          q: "Ngành này ra làm nghề gì?",
          a: "Điều hành vận tải, nhân viên logistics – kho vận, quản lý đội xe, hoặc kinh doanh dịch vụ vận tải.",
        },
        {
          q: "Có cần bằng lái xe không?",
          a: "Không bắt buộc để học. Ngành thiên về tổ chức, quản lý và kinh doanh vận tải hơn là trực tiếp lái xe.",
        },
      ],
    },
  },
  {
    match: /kế toán/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      image: "/lp/programs/ke-toan.jpg",
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
      goodIf: [
        "Cẩn thận, tỉ mỉ, thích làm việc với con số",
        "Ngăn nắp, trung thực, có trách nhiệm cao",
        "Muốn nghề ổn định, doanh nghiệp nào cũng cần",
      ],
      considerIf: [
        "Cẩu thả với con số, ngại công việc lặp lại đều đặn",
        "Không thích làm việc với sổ sách, phần mềm, quy định",
      ],
      trends: [
        "Mọi doanh nghiệp đều cần kế toán → nhu cầu ổn định lâu dài",
        "Thành thạo phần mềm kế toán (MISA…) là lợi thế lớn",
        "Có thể nhận làm dịch vụ kế toán cho nhiều đơn vị nhỏ",
      ],
      faq: [
        {
          q: "Không giỏi Toán có học kế toán được không?",
          a: "Kế toán chủ yếu cộng trừ nhân chia và sự cẩn thận, không cần Toán cao. Quan trọng nhất là tỉ mỉ và trung thực.",
        },
        {
          q: "Ra trường dễ xin việc không?",
          a: "Doanh nghiệp nào cũng cần kế toán nên cơ hội rộng; nhiều em làm kế toán kho, bán hàng, thuế ngay sau tốt nghiệp.",
        },
      ],
    },
  },
  {
    match: /văn phòng/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      image: "/lp/programs/van-phong.jpg",
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
      goodIf: [
        "Ngăn nắp, cẩn thận, giao tiếp tốt",
        "Thành thạo (hoặc muốn học) tin học văn phòng",
        "Thích môi trường công sở, công việc ổn định",
      ],
      considerIf: [
        "Không thích công việc bàn giấy, giao tiếp, tiếp khách",
        "Mong muốn công việc năng động, ngoài trời",
      ],
      trends: [
        "Cơ quan, doanh nghiệp nào cũng cần nhân sự hành chính – văn phòng",
        "Kỹ năng văn thư, lưu trữ, tổ chức sự kiện ngày càng được coi trọng",
        "Bước đệm tốt để lên thư ký, trợ lý, quản lý hành chính",
      ],
      faq: [
        {
          q: "Ngành này làm những việc gì?",
          a: "Hành chính – văn phòng, văn thư – lưu trữ, thư ký/trợ lý, lễ tân, tổ chức hội họp – sự kiện cho cơ quan, doanh nghiệp.",
        },
        {
          q: "Có cần ngoại hình không?",
          a: "Không bắt buộc. Quan trọng là sự cẩn thận, kỹ năng tin học và giao tiếp chuyên nghiệp.",
        },
      ],
    },
  },
  {
    match: /tiếng anh|ngôn ngữ anh/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      image: "/lp/programs/tieng-anh.jpg",
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
      goodIf: [
        "Yêu thích ngoại ngữ, thích giao tiếp",
        "Kiên trì luyện nghe – nói – đọc – viết đều đặn",
        "Muốn cơ hội làm việc với công ty nước ngoài, du lịch",
      ],
      considerIf: [
        "Ngại giao tiếp, không thích học thuộc – luyện tập thường xuyên",
        "Mong muốn một nghề kỹ thuật / tay chân cụ thể",
      ],
      trends: [
        "Hội nhập quốc tế → tiếng Anh là lợi thế cho hầu hết ngành nghề",
        "Du lịch, thương mại, công ty nước ngoài cần nhân lực tiếng Anh",
        "Có thể làm biên – phiên dịch, dạy học hoặc kết hợp với ngành khác",
      ],
      faq: [
        {
          q: "Mất gốc tiếng Anh có học được không?",
          a: "Được. Chương trình xây lại từ nền tảng nghe – nói – đọc – viết; quan trọng là luyện tập đều đặn.",
        },
        {
          q: "Ra trường làm gì?",
          a: "Biên – phiên dịch, nhân viên công ty nước ngoài, lễ tân – hướng dẫn khách sạn, giáo viên trung tâm tiếng Anh.",
        },
      ],
    },
  },
  {
    match: /hướng dẫn du lịch|hướng dẫn viên/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      image: "/lp/programs/huong-dan-du-lich.jpg",
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
      goodIf: [
        "Thích đi đây đó, năng động, giao tiếp tốt",
        "Ưa khám phá văn hóa, lịch sử, thích kể chuyện",
        "Không ngại di chuyển nhiều, làm cuối tuần / lễ",
      ],
      considerIf: [
        "Thích công việc ổn định một chỗ, ít di chuyển",
        "Ngại giao tiếp đám đông, xử lý tình huống bất ngờ",
      ],
      trends: [
        "Du lịch Tây Nguyên và cả nước phục hồi, phát triển mạnh",
        "Hướng dẫn viên giỏi, biết ngoại ngữ luôn được săn đón",
        "Có thể làm điều hành tour, kinh doanh du lịch, dẫn tour tự do",
      ],
      faq: [
        {
          q: "Nghề này có phải đi suốt không?",
          a: "Khi dẫn tour sẽ đi nhiều, làm cả cuối tuần và lễ. Bù lại được đi đây đó, gặp gỡ nhiều người và thu nhập theo tour thường tốt.",
        },
        {
          q: "Không giỏi ngoại ngữ làm được không?",
          a: "Vẫn làm được với khách nội địa; biết thêm ngoại ngữ sẽ mở rộng cơ hội với khách quốc tế và thu nhập cao hơn.",
        },
      ],
    },
  },
  {
    // Bắt các ngành du lịch còn lại (Quản lý & kinh doanh du lịch) sau HDV.
    match: /du lịch|lữ hành|khách sạn/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      image: "/lp/programs/du-lich.jpg",
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
      goodIf: [
        "Thích lĩnh vực du lịch, nhà hàng – khách sạn",
        "Giao tiếp tốt, nhanh nhẹn, thích tổ chức – kinh doanh",
        "Muốn nghề năng động, nhiều cơ hội thăng tiến",
      ],
      considerIf: [
        "Không thích môi trường dịch vụ, làm theo ca, cuối tuần",
        "Ngại giao tiếp, chăm sóc khách hàng",
      ],
      trends: [
        "Du lịch – khách sạn – nhà hàng là ngành mũi nhọn, phục hồi mạnh",
        "Nhu cầu quản lý dịch vụ lữ hành, lưu trú tăng nhanh",
        "Cơ hội thăng tiến lên quản lý bộ phận, quản lý cơ sở",
      ],
      faq: [
        {
          q: "Khác gì với Hướng dẫn du lịch?",
          a: "Ngành này thiên về tổ chức, quản lý và kinh doanh dịch vụ (lữ hành, khách sạn, nhà hàng); Hướng dẫn du lịch thiên về trực tiếp dẫn tour.",
        },
        {
          q: "Ra trường làm ở đâu?",
          a: "Công ty lữ hành, khách sạn, resort, nhà hàng — ở bộ phận điều hành, kinh doanh, quản lý dịch vụ.",
        },
      ],
    },
  },
  {
    // Catch-all khối kinh doanh (Quản trị kinh doanh) — đặt cuối.
    match: /quản trị kinh doanh|kinh doanh|quản trị|kinh tế|marketing/i,
    data: {
      group: "Kinh tế – Dịch vụ",
      image: "/lp/programs/quan-tri-kinh-doanh.jpg",
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
      goodIf: [
        "Thích kinh doanh, bán hàng, marketing",
        "Năng động, giao tiếp tốt, có đầu óc tổ chức",
        "Mơ ước tự khởi nghiệp hoặc làm quản lý",
      ],
      considerIf: [
        "Ngại giao tiếp, thuyết phục, làm việc với con người",
        "Muốn một nghề kỹ thuật chuyên sâu, cụ thể",
      ],
      trends: [
        "Kỹ năng kinh doanh – marketing cần cho mọi lĩnh vực",
        "Thương mại điện tử, bán hàng online mở nhiều cơ hội mới",
        "Nền tảng tốt để tự khởi nghiệp hoặc thăng tiến lên quản lý",
      ],
      faq: [
        {
          q: "Học Quản trị kinh doanh ra làm gì?",
          a: "Nhân viên kinh doanh – bán hàng, marketing, quản lý cửa hàng/chi nhánh, hoặc tự khởi nghiệp.",
        },
        {
          q: "Ngành rộng quá, có khó xin việc không?",
          a: "Kiến thức rộng là lợi thế để làm nhiều vị trí; quan trọng là chọn hướng (bán hàng, marketing, quản lý) và rèn kỹ năng thực tế qua thực tập.",
        },
      ],
    },
  },
]

/** Nội dung editorial cho 1 ngành theo tên (khớp đầu tiên; lạ → DEFAULT). */
export function programEditorial(name: string): ProgramEditorial {
  for (const e of PROGRAMS_EDITORIAL) if (e.match.test(name)) return e.data
  return DEFAULT
}

// ── Học phí THẬT theo MÃ ngành (trường cung cấp 08-07) ──
// Key theo `code` vì CĐ và TC cùng tên có mức KHÁC nhau. Hệ TC tách 2 diện
// đầu vào (tốt nghiệp THCS / THPT). `pay` = thực đóng toàn khóa sau hỗ trợ.
// ⚠️ Số hiệu "NĐ 238/NĐ-CP" theo owner cung cấp — cần owner xác nhận lại số+năm.
/** 1 mức đóng theo diện đầu vào. `kind` là NGUỒN SỰ THẬT của mức ưu đãi (badge +
 *  màu số tiền suy từ đây, KHÔNG dò câu chữ `note` hiển thị). */
export interface TuitionTier {
  label: string // "Thực tế phải đóng" (CĐ) | "Tốt nghiệp THCS/THPT" (TC)
  kind: "free" | "70" | "30" | "none" // free=miễn 100%; none=chưa hỗ trợ
  note: string // căn cứ hỗ trợ (CHỈ để hiển thị)
  pay: string // thực đóng toàn khóa
}
/** Học phí 1 ngành (theo code). `total` = tổng học phí toàn khóa trước hỗ trợ. */
export interface Tuition {
  total: string
  tiers: TuitionTier[]
}

const T70 = "Hỗ trợ 70% theo NĐ 238/NĐ-CP"
const T30 = "Ưu đãi 30% học phí kỳ 1"
const T100_THCS = "Miễn 100% theo NĐ 238/NĐ-CP (diện tốt nghiệp THCS)"
const T70_THPT = "Hỗ trợ 70% theo NĐ 238/NĐ-CP (diện tốt nghiệp THPT)"
const T_NONE = "Chưa áp dụng hỗ trợ học phí"

// Builders 1 mức đóng — gắn `kind` (cấu trúc) với `note` (hiển thị), tránh lặp.
const cd70 = (pay: string): TuitionTier => ({ label: "Thực tế phải đóng", kind: "70", note: T70, pay })
const cd30 = (pay: string): TuitionTier => ({ label: "Thực tế phải đóng", kind: "30", note: T30, pay })
const thcsFree: TuitionTier = { label: "Tốt nghiệp THCS", kind: "free", note: T100_THCS, pay: "0 đ" }
const thcsNone = (pay: string): TuitionTier => ({ label: "Tốt nghiệp THCS", kind: "none", note: T_NONE, pay })
const thpt70 = (pay: string): TuitionTier => ({ label: "Tốt nghiệp THPT", kind: "70", note: T70_THPT, pay })
const thptNone = (pay: string): TuitionTier => ({ label: "Tốt nghiệp THPT", kind: "none", note: T_NONE, pay })

export const PROGRAM_TUITION: Record<string, Tuition> = {
  // ── Cao đẳng ──
  "6720301": { total: "49.800.000 đ", tiers: [cd70("14.900.000 đ")] }, // Điều dưỡng
  "6720201": { total: "48.000.000 đ", tiers: [cd70("14.400.000 đ")] }, // Dược
  "6720101": { total: "54.300.000 đ", tiers: [cd70("16.300.000 đ")] }, // Y sỹ CĐ
  "6720102": { total: "48.000.000 đ", tiers: [cd30("45.900.000 đ")] }, // YHCT
  "6620120": { total: "44.100.000 đ", tiers: [cd70("13.200.000 đ")] }, // Chăn nuôi–Thú y CĐ
  "6510216": { total: "40.000.000 đ", tiers: [cd70("12.000.000 đ")] }, // Ô tô CĐ
  "6810103": { total: "35.800.000 đ", tiers: [cd70("8.750.000 đ")] }, // Hướng dẫn du lịch CĐ
  "6480201": { total: "39.000.000 đ", tiers: [cd30("36.900.000 đ")] }, // CNTT CĐ
  "6340101": { total: "35.800.000 đ", tiers: [cd30("33.850.000 đ")] }, // QTKD CĐ
  "6340404": { total: "35.800.000 đ", tiers: [cd30("33.850.000 đ")] }, // QTKD CĐ (bản 2)
  "6340403": { total: "35.800.000 đ", tiers: [cd30("33.850.000 đ")] }, // QT văn phòng
  "6340301": { total: "35.800.000 đ", tiers: [cd30("33.850.000 đ")] }, // Kế toán CĐ
  "6220206": { total: "35.800.000 đ", tiers: [cd30("33.850.000 đ")] }, // Tiếng Anh
  // ── Trung cấp (2 diện đầu vào) ──
  "5510216": { total: "37.800.000 đ", tiers: [thcsFree, thpt70("11.340.000 đ")] }, // Ô tô TC
  "5480202": { total: "37.800.000 đ", tiers: [thcsFree, thptNone("37.800.000 đ")] }, // CNTT TC
  "5810207": { total: "37.800.000 đ", tiers: [thcsFree, thpt70("11.340.000 đ")] }, // Chế biến món ăn TC
  "5620120": { total: "28.800.000 đ", tiers: [thcsFree, thpt70("8.640.000 đ")] }, // Chăn nuôi–Thú y TC
  "5340421": { total: "27.800.000 đ", tiers: [thcsFree, thptNone("27.800.000 đ")] }, // QL&KD du lịch TC
  "5340301": { total: "27.800.000 đ", tiers: [thcsFree, thptNone("27.800.000 đ")] }, // Kế toán TC
  "5340407": { total: "27.800.000 đ", tiers: [thcsFree, thptNone("27.800.000 đ")] }, // KD vận tải đường bộ TC
  "5720101": { total: "28.300.000 đ", tiers: [thcsNone("28.300.000 đ"), thpt70("8.490.000 đ")] }, // Y sỹ TC
}

/** Học phí theo mã ngành (null nếu chưa có dữ liệu → FE hiện khối generic). */
export function programTuition(code: string): Tuition | null {
  return PROGRAM_TUITION[code] ?? null
}

/** Mức ưu đãi học phí NỔI BẬT (để hiện badge/TL;DR) — suy TỪ học phí thật, KHÔNG
 *  từ is_heavy (dữ liệu học phí owner chuẩn hơn: Điều dưỡng/Dược cũng 70%). */
export type TuitionLevel = "free" | "70" | "30" | null
export function tuitionTier(code: string): TuitionLevel {
  const t = PROGRAM_TUITION[code]
  if (!t) return null
  if (t.tiers.some((x) => x.kind === "free")) return "free"
  if (t.tiers.some((x) => x.kind === "70")) return "70"
  if (t.tiers.some((x) => x.kind === "30")) return "30"
  return null
}
/** Mức ưu đãi "mạnh" (miễn 100% / giảm 70%) → badge flame + viền cam. Nguồn DUY
 *  NHẤT của quyết định flame, dùng chung tier-1 card / tier-2 hero / TL;DR. */
export function isStrongTuition(level: TuitionLevel): boolean {
  return level === "free" || level === "70"
}
/** Nhãn ưu đãi ngắn theo mức (card tier-1 gọn / hero tier-2 dài). */
export function tuitionLevelLabel(
  level: TuitionLevel,
  size: "card" | "hero",
): string {
  switch (level) {
    case "free":
      return size === "card" ? "Miễn 100%" : "Miễn 100% học phí"
    case "70":
      return size === "card" ? "Giảm 70%" : "Giảm 70% học phí"
    case "30":
      return size === "card" ? "Ưu đãi 30%" : "Ưu đãi 30% kỳ 1"
    default:
      return size === "card" ? "Học bổng" : "Học bổng đầu vào"
  }
}
