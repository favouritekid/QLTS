"use client"

import Link from "next/link"
import { CheckCircle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

export default function RegisterCTVSuccessPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md text-center">
        <CardHeader>
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/20">
            <CheckCircle className="h-8 w-8 text-green-600" />
          </div>
          <CardTitle className="text-2xl">Đăng ký thành công!</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground">
            Đơn đăng ký của bạn đã được gửi thành công.
            Quản trị viên sẽ xem xét và kích hoạt tài khoản trong thời gian sớm nhất.
          </p>
          <p className="text-muted-foreground text-sm">
            Bạn sẽ nhận được thông báo khi tài khoản được kích hoạt.
          </p>
          <div className="pt-2">
            <Button variant="outline" asChild>
              <Link href="/login">Quay về trang đăng nhập</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
