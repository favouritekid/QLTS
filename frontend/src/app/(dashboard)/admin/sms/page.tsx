import { redirect } from "next/navigation"

/**
 * `/admin/sms` không có trang tổng quan riêng (chỉ có contacts/campaigns/reports
 * /opt-out). Redirect về danh sách chiến dịch để breadcrumb/segment "sms" không
 * dẫn tới 404.
 */
export default function SmsIndexPage() {
  redirect("/admin/sms/campaigns")
}
