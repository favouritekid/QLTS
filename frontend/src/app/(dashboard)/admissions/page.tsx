// src/app/(dashboard)/admissions/page.tsx
/**
 * Admissions List Page
 * 
 * Placeholder page for viewing all admission profiles.
 * TODO: Implement full list with filtering/sorting
 */
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ClipboardCheck } from "lucide-react"

export const metadata = {
  title: "Hồ sơ tuyển sinh",
  description: "Quản lý hồ sơ tuyển sinh",
}

export default function AdmissionsPage() {
  return (
    <div className="container mx-auto py-6">
      <div className="flex items-center gap-3 mb-6">
        <ClipboardCheck className="h-8 w-8 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Hồ sơ tuyển sinh</h1>
          <p className="text-muted-foreground">Quản lý và theo dõi hồ sơ tuyển sinh</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Danh sách hồ sơ</CardTitle>
          <CardDescription>
            Tính năng đang được phát triển. Để tạo hồ sơ mới, vui lòng vào trang chi tiết Lead và nhấn "Tạo hồ sơ tuyển sinh".
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-center py-12 text-muted-foreground">
            <ClipboardCheck className="h-16 w-16 mx-auto mb-4 opacity-20" />
            <p>Chưa có hồ sơ nào</p>
            <p className="text-sm mt-2">Danh sách hồ sơ tuyển sinh sẽ hiển thị ở đây</p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
