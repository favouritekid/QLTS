import { redirect } from "next/navigation";

/**
 * Màn "Báo cáo tuyển sinh" đã GỘP vào "Tổng quan tuyển sinh"
 * (`/reports/admission-overview`, tab "Bảng chi tiết"). Route cũ giữ lại chỉ để
 * redirect — bookmark/link cũ không gãy. Các `_components` (WeeklyReportTable,
 * SummaryBand, cockpit-rank) vẫn dùng, được màn gộp import.
 */
export default function AdmissionsWeeklyReportPage() {
  redirect("/reports/admission-overview");
}
