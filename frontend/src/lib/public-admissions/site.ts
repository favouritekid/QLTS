export interface PublicAdmissionsPrimaryLink {
  label: string
  href: string
}

export interface PublicAdmissionsMediaAsset {
  src: string
  alt: string
  width: number
  height: number
  creditLabel: string
  creditHref: string
}

export interface PublicAdmissionsFeaturedPage {
  title: string
  description: string
  href: string
  tag: string
  stats: readonly string[]
  media: keyof typeof publicAdmissionsMedia
}

export interface PublicProgramSelectionStep {
  title: string
  description: string
}

export interface PublicProgramCluster {
  title: string
  summary: string
  degreeLevel: string
  offeringTypes: readonly string[]
  tuitionRange: string
  examples: readonly string[]
  outcomes: readonly string[]
}

export interface PublicProgramFormat {
  title: string
  schedule: string
  bestFor: string
  description: string
}

export interface PublicAdmissionMethodDetail {
  title: string
  audience: string
  summary: string
  requirements: readonly string[]
  documents: readonly string[]
}

export interface PublicSubjectGroupHighlight {
  code: string
  focus: string
  subjects: readonly string[]
  fit: string
}

export interface PublicDocumentBucket {
  title: string
  description: string
  items: readonly string[]
}

export interface PublicTuitionBand {
  title: string
  range: string
  note: string
  includes: readonly string[]
}

export interface PublicScholarshipPolicy {
  title: string
  value: string
  criteria: string
  notes: readonly string[]
}

export interface PublicPaymentStep {
  title: string
  timing: string
  description: string
}

export interface PublicCostFaq {
  question: string
  answer: string
}

export const publicAdmissionsPrimaryLinks: readonly PublicAdmissionsPrimaryLink[] = [
  { label: "Trang chủ", href: "/" },
  { label: "Ngành học", href: "/tuyen-sinh/nganh-hoc" },
  { label: "Phương thức", href: "/tuyen-sinh/phuong-thuc" },
  { label: "Hồ sơ", href: "/tuyen-sinh/ho-so" },
  { label: "Học phí & học bổng", href: "/tuyen-sinh/hoc-phi-hoc-bong" },
]

export const publicAdmissionsMedia = {
  heroCampus: {
    src: "https://images.pexels.com/photos/31085764/pexels-photo-31085764.jpeg?auto=compress&cs=tinysrgb&w=1400",
    alt: "Khuôn viên đại học hiện đại với sinh viên sinh hoạt ngoài trời.",
    width: 1400,
    height: 875,
    creditLabel: "DΛVΞ GΛRCIΛ / Pexels",
    creditHref: "https://www.pexels.com/photo/modern-university-campus-with-students-outdoors-31085764/",
  },
  studentsWalk: {
    src: "https://images.pexels.com/photos/7973039/pexels-photo-7973039.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Nhóm sinh viên đi bộ cùng nhau trong khuôn viên trường.",
    width: 1200,
    height: 800,
    creditLabel: "George Pak / Pexels",
    creditHref: "https://www.pexels.com/photo/university-students-walking-together-7973039/",
  },
  libraryStudy: {
    src: "https://images.pexels.com/photos/6549913/pexels-photo-6549913.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Sinh viên học tập trong thư viện với laptop và sách.",
    width: 1200,
    height: 800,
    creditLabel: "Tima Miroshnichenko / Pexels",
    creditHref: "https://www.pexels.com/photo/college-students-studying-and-researching-6549913/",
  },
  classroomStudy: {
    src: "https://images.pexels.com/photos/8199165/pexels-photo-8199165.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Sinh viên học tập trong giảng đường với máy tính và tài liệu.",
    width: 1200,
    height: 800,
    creditLabel: "Yan Krukau / Pexels",
    creditHref: "https://www.pexels.com/photo/college-students-studying-inside-a-classroom-8199165/",
  },
  documentsDesk: {
    src: "https://images.pexels.com/photos/7681333/pexels-photo-7681333.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Người đang xem và sắp xếp hồ sơ giấy tờ trên bàn làm việc.",
    width: 1200,
    height: 800,
    creditLabel: "Karolina Grabowska / Pexels",
    creditHref: "https://www.pexels.com/photo/woman-sitting-beside-the-documents-7681333/",
  },
  scholarshipAward: {
    src: "https://images.pexels.com/photos/31772913/pexels-photo-31772913.jpeg?auto=compress&cs=tinysrgb&w=1200",
    alt: "Hình ảnh trao thưởng và chứng nhận cho học sinh trong buổi lễ.",
    width: 1200,
    height: 800,
    creditLabel: "Legacy of Fire / Pexels",
    creditHref: "https://www.pexels.com/photo/students-receiving-awards-at-school-ceremony-31772913/",
  },
} satisfies Record<string, PublicAdmissionsMediaAsset>

export const publicAdmissionsFeaturedPages: readonly PublicAdmissionsFeaturedPage[] = [
  {
    title: "Ngành học và hệ đào tạo",
    description:
      "Duyệt theo nhóm ngành, bậc học và hình thức đào tạo để chọn đúng chương trình trước khi so sánh điều kiện xét tuyển.",
    href: "/tuyen-sinh/nganh-hoc",
    tag: "Programs",
    stats: ["4 nhóm ngành", "3 hệ đào tạo", "Lộ trình chọn ngành"],
    media: "libraryStudy",
  },
  {
    title: "Phương thức xét tuyển",
    description:
      "Xem nhanh từng phương thức, tổ hợp và checklist hồ sơ để biết hồ sơ hiện tại của bạn phù hợp với hướng nào.",
    href: "/tuyen-sinh/phuong-thuc",
    tag: "Admissions",
    stats: ["4 phương thức chính", "Tổ hợp tham chiếu", "Checklist hồ sơ"],
    media: "documentsDesk",
  },
  {
    title: "Hồ sơ tuyển sinh",
    description:
      "Xem checklist hồ sơ theo hệ đào tạo và phương thức để biết mình cần chuẩn bị gì trước khi nộp hoặc xác nhận nhập học.",
    href: "/tuyen-sinh/ho-so",
    tag: "Documents",
    stats: ["Checklist theo hệ", "Override theo phương thức", "Giấy tờ cần upload"],
    media: "classroomStudy",
  },
  {
    title: "Học phí và học bổng",
    description:
      "Đặt mức học phí, học bổng đầu vào và lộ trình thanh toán trên cùng một trang để phụ huynh dễ ra quyết định.",
    href: "/tuyen-sinh/hoc-phi-hoc-bong",
    tag: "Fees & Aid",
    stats: ["Khung học phí", "Ưu đãi đầu vào", "Mốc thanh toán"],
    media: "scholarshipAward",
  },
]

export const publicProgramSelectionSteps: readonly PublicProgramSelectionStep[] = [
  {
    title: "Xác định bậc học và mục tiêu đầu ra",
    description:
      "Bắt đầu từ đại học, cao đẳng hoặc liên thông để giới hạn đúng nhóm chương trình thay vì xem toàn bộ danh mục.",
  },
  {
    title: "Chọn hệ đào tạo và cách học phù hợp",
    description:
      "So sánh chính quy, liên thông hay từ xa để cân bằng thời gian học, cường độ và trải nghiệm sinh viên.",
  },
  {
    title: "Đối chiếu học phí và phương thức xét tuyển",
    description:
      "Khi đã có 2-3 lựa chọn ngành gần đúng, hãy xem tiếp khung học phí và phương thức phù hợp với hồ sơ hiện có.",
  },
]

export const publicProgramClusters: readonly PublicProgramCluster[] = [
  {
    title: "CNTT, dữ liệu và công nghệ ứng dụng",
    summary:
      "Nhóm phù hợp với thí sinh muốn học theo hướng phát triển phần mềm, phân tích dữ liệu, AI ứng dụng hoặc vận hành hệ thống số.",
    degreeLevel: "Đại học, cao đẳng, liên thông",
    offeringTypes: ["Chính quy", "Liên thông", "Từ xa"],
    tuitionRange: "32 - 45 triệu/năm",
    examples: ["Kỹ thuật phần mềm", "Khoa học dữ liệu", "Mạng máy tính", "Thiết kế sản phẩm số"],
    outcomes: ["Lập trình viên", "Phân tích dữ liệu", "Vận hành hệ thống", "Product support"],
  },
  {
    title: "Kinh doanh, tài chính và quản trị",
    summary:
      "Phù hợp với người học muốn làm việc trong vận hành doanh nghiệp, marketing, bán hàng, tài chính doanh nghiệp hoặc thương mại số.",
    degreeLevel: "Đại học, cao đẳng",
    offeringTypes: ["Chính quy", "Từ xa"],
    tuitionRange: "28 - 38 triệu/năm",
    examples: ["Quản trị kinh doanh", "Marketing", "Tài chính - ngân hàng", "Kinh doanh số"],
    outcomes: ["Sales & marketing", "Phân tích vận hành", "Dịch vụ khách hàng", "Điều phối kinh doanh"],
  },
  {
    title: "Ngôn ngữ, truyền thông và dịch vụ",
    summary:
      "Nhóm phù hợp với thí sinh có thế mạnh giao tiếp, ngoại ngữ, sáng tạo nội dung hoặc định hướng làm việc trong môi trường dịch vụ.",
    degreeLevel: "Đại học, cao đẳng",
    offeringTypes: ["Chính quy", "Từ xa"],
    tuitionRange: "26 - 34 triệu/năm",
    examples: ["Ngôn ngữ Anh", "Truyền thông đa phương tiện", "Quan hệ công chúng", "Quản trị dịch vụ"],
    outcomes: ["Biên - phiên dịch", "Truyền thông nội dung", "Điều phối sự kiện", "Dịch vụ khách hàng quốc tế"],
  },
  {
    title: "Sức khỏe, giáo dục và khoa học ứng dụng",
    summary:
      "Nhóm dành cho người học muốn theo đuổi các ngành có yêu cầu chuẩn bị hồ sơ kỹ, chú trọng thực hành và chuẩn đầu ra rõ ràng.",
    degreeLevel: "Đại học, liên thông",
    offeringTypes: ["Chính quy", "Liên thông"],
    tuitionRange: "35 - 52 triệu/năm",
    examples: ["Điều dưỡng", "Công nghệ xét nghiệm", "Giáo dục học", "Tâm lý ứng dụng"],
    outcomes: ["Nhân sự chuyên môn", "Điều phối học vụ", "Công tác hỗ trợ", "Vận hành phòng lab"],
  },
]

export const publicProgramFormats: readonly PublicProgramFormat[] = [
  {
    title: "Chính quy tập trung",
    schedule: "Lịch học chính khóa trong tuần",
    bestFor: "Thí sinh tốt nghiệp THPT hoặc muốn trải nghiệm đầy đủ campus life",
    description:
      "Phù hợp với người học muốn tham gia đầy đủ hoạt động lớp, thực hành, cố vấn học tập và các dịch vụ hỗ trợ sinh viên.",
  },
  {
    title: "Liên thông",
    schedule: "Theo lộ trình rút gọn và công nhận học phần",
    bestFor: "Người đã có nền tảng học tập hoặc bằng cấp liên quan",
    description:
      "Tập trung vào việc nối tiếp chương trình học hiện có để rút ngắn thời gian và tối ưu lộ trình hoàn tất bằng cấp.",
  },
  {
    title: "Từ xa hoặc kết hợp",
    schedule: "Linh hoạt theo học phần và lịch hỗ trợ trực tuyến",
    bestFor: "Người đi làm, cần học song song với công việc hoặc ở xa campus",
    description:
      "Ưu tiên sự linh hoạt về thời gian, phù hợp khi người học cần theo học dài hạn nhưng không thể tham gia toàn thời gian.",
  },
]

export const publicAdmissionMethodsDetailed: readonly PublicAdmissionMethodDetail[] = [
  {
    title: "Xét học bạ THPT",
    audience: "Phù hợp khi bạn có quá trình học ổn định và muốn chủ động nộp hồ sơ sớm.",
    summary:
      "Phương thức này thường dựa trên điểm trung bình các môn theo tổ hợp hoặc điểm trung bình theo học kỳ, theo năm học.",
    requirements: ["GPA đáp ứng ngưỡng của chương trình", "Đúng tổ hợp hoặc nhóm môn tham chiếu", "Đủ điều kiện tốt nghiệp theo quy định"],
    documents: ["Học bạ photo hoặc bản scan", "Phiếu đăng ký xét tuyển", "CCCD/CMND", "Minh chứng ưu tiên nếu có"],
  },
  {
    title: "Xét điểm thi tốt nghiệp THPT",
    audience: "Phù hợp khi bạn muốn dùng kết quả kỳ thi quốc gia làm căn cứ xét tuyển chính.",
    summary:
      "Đây là phương thức quen thuộc, phù hợp với thí sinh muốn đối chiếu theo tổ hợp rõ ràng và so sánh trên diện rộng.",
    requirements: ["Điểm thi đạt ngưỡng nhận hồ sơ", "Tổ hợp đúng với chương trình đăng ký", "Các điều kiện phụ nếu chương trình có quy định"],
    documents: ["Phiếu đăng ký xét tuyển", "Kết quả thi THPT", "CCCD/CMND", "Thông tin ưu tiên khu vực hoặc đối tượng"],
  },
  {
    title: "Đánh giá năng lực hoặc tư duy",
    audience: "Phù hợp với thí sinh muốn mở rộng cơ hội ngoài điểm thi THPT truyền thống.",
    summary:
      "Thường áp dụng cho chương trình cần sàng lọc thêm về tư duy tổng hợp, khả năng xử lý tình huống hoặc nền tảng học thuật.",
    requirements: ["Điểm bài thi riêng đạt ngưỡng quy định", "Đăng ký đúng đợt và đúng mã chương trình", "Hoàn tất hồ sơ trong thời hạn"],
    documents: ["Phiếu điểm bài thi", "Phiếu đăng ký xét tuyển", "CCCD/CMND", "Học bạ hoặc bảng điểm bổ trợ nếu được yêu cầu"],
  },
  {
    title: "Xét tuyển kết hợp",
    audience: "Phù hợp khi bạn có thêm chứng chỉ ngoại ngữ, giải thưởng hoặc hồ sơ thành tích nổi bật.",
    summary:
      "Phương thức này cho phép kết hợp nhiều nguồn minh chứng để phản ánh tốt hơn năng lực thật của người học.",
    requirements: ["Có chứng chỉ hoặc thành tích hợp lệ", "Đạt điều kiện nền tối thiểu về học lực", "Hồ sơ minh chứng rõ ràng, còn hiệu lực"],
    documents: ["Minh chứng chứng chỉ hoặc giải thưởng", "Học bạ hoặc kết quả thi", "Phiếu đăng ký xét tuyển", "CCCD/CMND"],
  },
]

export const publicSubjectGroupHighlights: readonly PublicSubjectGroupHighlight[] = [
  {
    code: "A00 - A01",
    focus: "Toán, Lý, Hóa hoặc Toán, Lý, Anh",
    subjects: ["Kỹ thuật", "CNTT", "Công nghệ", "Một số ngành kinh tế định lượng"],
    fit: "Thường gặp ở các chương trình thiên về tư duy logic, tính toán và nền tảng khoa học tự nhiên.",
  },
  {
    code: "D01 - D07",
    focus: "Toán, Ngữ văn, Anh hoặc các biến thể ngoại ngữ",
    subjects: ["Ngôn ngữ", "Truyền thông", "Kinh doanh", "Dịch vụ quốc tế"],
    fit: "Phù hợp với nhóm ngành chú trọng giao tiếp, ngoại ngữ, phân tích xã hội và kỹ năng ứng dụng.",
  },
  {
    code: "Kết hợp GPA và chứng chỉ",
    focus: "Điểm học tập cùng ngoại ngữ, thành tích hoặc bài thi riêng",
    subjects: ["Chương trình chọn lọc", "Ngành có tiêu chí bổ sung", "Xét tuyển sớm"],
    fit: "Giúp nổi bật hồ sơ nếu bạn có chứng chỉ hoặc thành tích học thuật, hoạt động phù hợp với chương trình đăng ký.",
  },
]

export const publicDocumentBuckets: readonly PublicDocumentBucket[] = [
  {
    title: "Hồ sơ chung",
    description: "Những giấy tờ gần như thí sinh nào cũng cần chuẩn bị trước.",
    items: ["Phiếu đăng ký xét tuyển", "CCCD/CMND", "Ảnh chân dung theo yêu cầu", "Thông tin liên hệ chính xác"],
  },
  {
    title: "Minh chứng theo phương thức",
    description: "Mỗi phương thức xét tuyển sẽ cần bộ giấy tờ bổ sung riêng.",
    items: ["Học bạ hoặc bảng điểm", "Kết quả thi THPT hoặc bài thi riêng", "Chứng chỉ ngoại ngữ", "Giải thưởng hoặc hồ sơ thành tích"],
  },
  {
    title: "Sau khi đủ điều kiện trúng tuyển",
    description: "Bộ hồ sơ để hoàn tất xác nhận nhập học và giữ chỗ.",
    items: ["Bản sao bằng tốt nghiệp hoặc giấy chứng nhận", "Hồ sơ học sinh - sinh viên", "Biên nhận giữ chỗ", "Các giấy tờ bổ sung theo thông báo"],
  },
]

export const publicTuitionBands: readonly PublicTuitionBand[] = [
  {
    title: "Nhóm kinh doanh và dịch vụ",
    range: "26 - 34 triệu/năm",
    note: "Mức phù hợp với chương trình chuẩn, học theo tín chỉ hoặc theo năm học.",
    includes: ["Học phí học phần cốt lõi", "Hỗ trợ cố vấn học tập", "Sử dụng hạ tầng học tập chung"],
  },
  {
    title: "Nhóm công nghệ và dữ liệu",
    range: "32 - 45 triệu/năm",
    note: "Thường cao hơn do cường độ thực hành, phần mềm, lab hoặc workshop chuyên môn.",
    includes: ["Học phần thực hành", "Phòng lab hoặc tài nguyên số", "Hoạt động dự án theo môn học"],
  },
  {
    title: "Nhóm ngôn ngữ và truyền thông",
    range: "27 - 36 triệu/năm",
    note: "Tùy định hướng chương trình chuẩn hay tăng cường thực hành, ngoại ngữ hoặc studio.",
    includes: ["Học phần chuyên ngành", "Một số hoạt động thực hành", "Hỗ trợ kỹ năng nghề nghiệp"],
  },
  {
    title: "Nhóm sức khỏe và khoa học ứng dụng",
    range: "35 - 52 triệu/năm",
    note: "Có thể thay đổi theo thời lượng thực tập, thực hành chuyên môn và yêu cầu chương trình.",
    includes: ["Học phần cơ sở và chuyên ngành", "Thực hành bắt buộc", "Hỗ trợ điều phối thực tập"],
  },
]

export const publicScholarshipPolicies: readonly PublicScholarshipPolicy[] = [
  {
    title: "Học bổng đầu vào",
    value: "25% - 100% học phí kỳ đầu hoặc năm đầu",
    criteria: "Dành cho thí sinh có kết quả học tập cao, điểm thi tốt hoặc hồ sơ nổi bật theo tiêu chí từng đợt.",
    notes: ["Có thể xét theo từng đợt tuyển sinh", "Thường cần nộp đúng hạn để được ưu tiên", "Một số suất giới hạn theo ngành"],
  },
  {
    title: "Ưu đãi theo thành tích hoặc chứng chỉ",
    value: "Miễn giảm theo mức quy đổi",
    criteria: "Áp dụng cho hồ sơ có chứng chỉ ngoại ngữ, giải thưởng, hoạt động nổi bật hoặc thành tích học thuật liên quan.",
    notes: ["Cần minh chứng còn hiệu lực", "Có thể cộng với ưu đãi khác nếu chính sách cho phép", "Nên kiểm tra điều kiện áp dụng theo từng ngành"],
  },
  {
    title: "Hỗ trợ tài chính và giãn tiến độ",
    value: "Theo chính sách hỗ trợ từng thời điểm",
    criteria: "Dành cho trường hợp cần hỗ trợ tiến độ thanh toán hoặc phương án nộp phí theo mốc.",
    notes: ["Thường cần tư vấn riêng", "Có thể đi kèm giấy tờ xác minh", "Nên hỏi trước khi xác nhận nhập học"],
  },
]

export const publicPaymentSteps: readonly PublicPaymentStep[] = [
  {
    title: "Xem khung học phí theo chương trình",
    timing: "Trước khi nộp hồ sơ",
    description: "Đối chiếu mức học phí theo ngành, hệ đào tạo và năm học để ước lượng tổng chi phí ban đầu.",
  },
  {
    title: "Kiểm tra học bổng hoặc ưu đãi đầu vào",
    timing: "Khi nộp hồ sơ hoặc sau khi đủ điều kiện sơ bộ",
    description: "Chuẩn bị thêm minh chứng thành tích để không bỏ lỡ các chính sách giảm học phí hoặc hỗ trợ đầu vào.",
  },
  {
    title: "Hoàn tất phí giữ chỗ",
    timing: "Sau khi có thông báo đủ điều kiện trúng tuyển",
    description: "Đây thường là mốc quan trọng để xác nhận bạn tiếp tục theo học và giữ vị trí trong đợt tuyển sinh.",
  },
  {
    title: "Chọn phương án thanh toán học phí",
    timing: "Trước hoặc khi nhập học",
    description: "Tùy chính sách thực tế, người học có thể thanh toán theo học kỳ, theo năm hoặc theo kế hoạch hỗ trợ riêng.",
  },
]

export const publicCostFaq: readonly PublicCostFaq[] = [
  {
    question: "Học phí có cố định trong toàn khóa không?",
    answer:
      "Không nên mặc định như vậy. Trang public nên ghi rõ đây là khung tham chiếu theo năm tuyển sinh, còn mức chính thức sẽ theo thông báo của từng khóa và từng chương trình.",
  },
  {
    question: "Học bổng có tự động áp dụng khi đủ điều kiện không?",
    answer:
      "Tùy chính sách. Một số học bổng được xét tự động theo điểm số, nhưng cũng có loại yêu cầu thí sinh nộp thêm minh chứng hoặc hoàn tất hồ sơ đúng thời hạn.",
  },
  {
    question: "Ngoài học phí còn khoản nào cần chuẩn bị?",
    answer:
      "Thí sinh thường cần lưu ý thêm phí hồ sơ, phí giữ chỗ, các khoản phục vụ nhập học hoặc các chi phí phát sinh theo đặc thù chương trình.",
  },
]
