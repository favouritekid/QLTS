export interface PublicAdmissionsNavItem {
  label: string
  href: string
}

export interface PublicAdmissionsPillar {
  title: string
  description: string
}

export interface PublicAdmissionsCategory {
  id:
    | "degree-level"
    | "offering-type"
    | "program"
    | "admission-method"
    | "subject-group"
    | "document-flow"
    | "admission-path"
  title: string
  description: string
  backendKey:
    | "ConfigDegreeLevel"
    | "ConfigOfferingType"
    | "MajorProgram"
    | "AdmissionMethod"
    | "SubjectGroup"
    | "ConfigDocumentType"
    | "AdmissionPath"
  examples: readonly string[]
}

export interface PublicAdmissionsJourneyStep {
  id: "discover" | "prepare" | "submit" | "confirm"
  title: string
  description: string
  status: "draft" | "submitted" | "approved" | "confirmed"
}

export interface PublicAdmissionsSupportPanel {
  id: "tuition-aid" | "documents" | "consulting"
  title: string
  description: string
  points: readonly string[]
}

export interface PublicAdmissionsFaqItem {
  question: string
  answer: string
}

export const publicAdmissionsNav: readonly PublicAdmissionsNavItem[] = [
  { label: "Khám phá", href: "#danh-muc" },
  { label: "Lộ trình", href: "#lo-trinh" },
  { label: "Hỗ trợ", href: "#ho-tro" },
  { label: "FAQ", href: "#faq" },
]

export const publicAdmissionsPillars: readonly PublicAdmissionsPillar[] = [
  {
    title: "Chọn chương trình theo bậc học",
    description: "Bắt đầu từ đại học, cao đẳng hoặc liên thông rồi mới đi sâu vào ngành và hệ đào tạo.",
  },
  {
    title: "So sánh phương thức xét tuyển",
    description: "Đặt các điều kiện, tổ hợp và bộ hồ sơ cạnh nhau để thí sinh dễ chọn lộ trình phù hợp.",
  },
  {
    title: "Xem học phí và học bổng",
    description: "Người học cần thấy chi phí, chính sách học bổng và hỗ trợ tài chính ngay trước khi quyết định nộp hồ sơ.",
  },
  {
    title: "Nắm rõ các bước nhập học",
    description: "Sau khi đủ điều kiện, trang phải dẫn tiếp sang giữ chỗ, xác nhận và hoàn tất nhập học.",
  },
]

// Public catalog mirrors the backend admission taxonomy so the page can
// switch from seeded content to public APIs later without a structural rewrite.
export const publicAdmissionsCategories: readonly PublicAdmissionsCategory[] = [
  {
    id: "degree-level",
    title: "Bậc học phù hợp",
    description: "Giúp thí sinh xác định đúng mục tiêu học tập trước khi xem sâu hơn về ngành hoặc phương thức xét tuyển.",
    backendKey: "ConfigDegreeLevel",
    examples: ["Đại học", "Cao đẳng", "Liên thông"],
  },
  {
    id: "offering-type",
    title: "Hệ đào tạo",
    description: "Tách rõ hình thức học để người học chọn lịch học, trải nghiệm và thời lượng phù hợp.",
    backendKey: "ConfigOfferingType",
    examples: ["Chính quy", "Liên thông", "Từ xa"],
  },
  {
    id: "program",
    title: "Nhóm ngành được quan tâm",
    description: "Trang đầu nên cho phép duyệt nhanh những cụm ngành phổ biến thay vì bắt người dùng đi từ menu sâu.",
    backendKey: "MajorProgram",
    examples: ["CNTT & Dữ liệu", "Kinh doanh & Quản trị", "Ngôn ngữ & Truyền thông"],
  },
  {
    id: "admission-method",
    title: "Phương thức xét tuyển",
    description: "Mỗi phương thức cần được mô tả rõ yêu cầu, cách xét và đối tượng phù hợp để thí sinh tự sàng lọc.",
    backendKey: "AdmissionMethod",
    examples: ["Học bạ THPT", "Điểm thi THPT", "Đánh giá năng lực"],
  },
  {
    id: "subject-group",
    title: "Điều kiện và tổ hợp",
    description: "Phần này nên trả lời ngay thắc mắc về GPA, tổ hợp môn, điều kiện tiếng Anh hoặc điểm cộng ưu tiên.",
    backendKey: "SubjectGroup",
    examples: ["A00 - A01 - D01", "GPA tối thiểu", "Điểm cộng ưu tiên"],
  },
  {
    id: "document-flow",
    title: "Hồ sơ cần nộp",
    description: "Checklist hồ sơ nên ngắn gọn, quét nhanh được, nhưng vẫn đủ để người học chuẩn bị đúng từ lần đầu.",
    backendKey: "ConfigDocumentType",
    examples: ["Phiếu đăng ký", "CCCD/CMND", "Học bạ - bằng tốt nghiệp"],
  },
  {
    id: "admission-path",
    title: "Đợt tuyển sinh và xác nhận",
    description: "Sau khi xem chương trình, người học cần biết đang ở đợt nào, nộp khi nào và xác nhận nhập học ra sao.",
    backendKey: "AdmissionPath",
    examples: ["Đợt sớm", "Đợt chính", "Xác nhận nhập học"],
  },
]

export const publicAdmissionsJourney: readonly PublicAdmissionsJourneyStep[] = [
  {
    id: "discover",
    title: "Tìm chương trình phù hợp",
    description: "Bắt đầu bằng bậc học, hệ đào tạo và nhóm ngành để thu hẹp đúng lựa chọn thay vì đọc rời từng bài viết.",
    status: "draft",
  },
  {
    id: "prepare",
    title: "Chọn phương thức phù hợp",
    description: "So sánh học bạ, điểm thi, đánh giá năng lực hoặc xét tuyển kết hợp để chọn lộ trình phù hợp nhất.",
    status: "submitted",
  },
  {
    id: "submit",
    title: "Hoàn thiện hồ sơ và theo dõi kết quả",
    description: "Kiểm tra checklist hồ sơ, nộp minh chứng và theo dõi thông báo bổ sung theo từng đợt tuyển sinh.",
    status: "approved",
  },
  {
    id: "confirm",
    title: "Giữ chỗ và xác nhận nhập học",
    description: "Sau khi đủ điều kiện trúng tuyển, người học cần thấy rõ bước giữ chỗ, đóng phí và xác nhận nhập học.",
    status: "confirmed",
  },
]

export const publicAdmissionsSupportPanels: readonly PublicAdmissionsSupportPanel[] = [
  {
    id: "tuition-aid",
    title: "Học phí, học bổng và hỗ trợ tài chính",
    description: "Các cổng tuyển sinh chuẩn đều đặt chi phí học tập cạnh học bổng và hỗ trợ tài chính để phụ huynh dễ quyết định.",
    points: [
      "Học phí theo học kỳ hoặc theo năm học",
      "Học bổng đầu vào, học bổng thành tích và hỗ trợ tài chính",
      "Phí hồ sơ, phí giữ chỗ và phương thức thanh toán",
    ],
  },
  {
    id: "documents",
    title: "Checklist hồ sơ theo từng phương thức",
    description: "Hồ sơ nên được trình bày theo từng phương thức xét tuyển để giảm nhầm lẫn khi chuẩn bị giấy tờ.",
    points: [
      "Danh sách hồ sơ riêng cho từng phương thức",
      "Phân biệt bản điện tử, bản giấy và minh chứng ưu tiên",
      "Nhắc mốc bổ sung hồ sơ và xác nhận kết quả",
    ],
  },
  {
    id: "consulting",
    title: "FAQ, tư vấn và hỗ trợ tuyển sinh",
    description: "Ngoài thông tin tĩnh, người học thường cần một nơi để hỏi nhanh, đặt lịch tư vấn hoặc xem lại các mốc quan trọng.",
    points: [
      "FAQ tuyển sinh, hotline, email và kênh hỗ trợ",
      "Tư vấn 1-1 cho thí sinh và phụ huynh",
      "Thông báo mốc nộp hồ sơ, phỏng vấn và nhập học",
    ],
  },
]

export const publicAdmissionsFaq: readonly PublicAdmissionsFaqItem[] = [
  {
    question: "Tôi nên bắt đầu từ ngành học hay từ phương thức xét tuyển?",
    answer:
      "Thông thường nên bắt đầu từ bậc học và nhóm ngành trước, sau đó mới so sánh các phương thức xét tuyển phù hợp với hồ sơ hiện có của bạn.",
  },
  {
    question: "Tôi có thể xem học phí và học bổng ở đâu trước khi nộp hồ sơ?",
    answer:
      "Trang tuyển sinh nên cho phép tra cứu học phí, học bổng đầu vào và hỗ trợ tài chính ngay ở tầng thông tin đầu tiên để phụ huynh và thí sinh dễ cân nhắc.",
  },
  {
    question: "Nếu nộp nhiều phương thức xét tuyển thì hồ sơ có thay đổi không?",
    answer:
      "Có thể thay đổi. Một số giấy tờ là hồ sơ chung, nhưng điểm số, minh chứng hoặc tổ hợp xét tuyển sẽ khác theo từng phương thức hoặc từng đợt.",
  },
  {
    question: "Sau khi đủ điều kiện trúng tuyển tôi cần làm gì để giữ chỗ?",
    answer:
      "Người học cần thấy rõ bước xác nhận nhập học, thời hạn giữ chỗ, khoản phí cần hoàn tất và các hồ sơ bổ sung nếu có.",
  },
]
