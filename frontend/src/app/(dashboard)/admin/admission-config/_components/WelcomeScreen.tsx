/**
 * WelcomeScreen Component
 *
 * First-time setup guide for Admission Configuration
 * Displays when no Phase 1 data exists
 */

"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { GraduationCap, Rocket, CheckCircle2 } from "lucide-react";

// ============================================
// TYPES
// ============================================

interface WelcomeScreenProps {
  onStart: () => void;
}

// ============================================
// COMPONENT
// ============================================

export function WelcomeScreen({ onStart }: WelcomeScreenProps) {
  return (
    <div className="flex items-center justify-center min-h-[80vh] p-6">
      <Card className="max-w-3xl w-full">
        <CardHeader className="text-center pb-4">
          <div className="flex justify-center mb-4">
            <div className="p-4 bg-primary/10 rounded-full">
              <GraduationCap className="h-12 w-12 text-primary" />
            </div>
          </div>
          <CardTitle className="text-3xl">Chào mừng đến với Cấu hình Tuyển sinh</CardTitle>
          <CardDescription className="text-base mt-2">
            Thiết lập hệ thống tuyển sinh của bạn qua 3 giai đoạn
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-8">
          {/* Phase Overview */}
          <div className="space-y-6">
            <div className="flex gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-info-100 text-info-600 flex items-center justify-center font-bold">
                  1
                </div>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Giai đoạn 1: Dữ liệu Danh mục</h3>
                <p className="text-muted-foreground mb-3">
                  Thiết lập nền tảng cho hệ thống. Thực hiện một lần và ít khi thay đổi.
                </p>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Đơn vị tổ chức (Khoa, Phòng ban)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Hệ đào tạo (Chính quy, Vừa làm vừa học)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Phương thức xét tuyển (Học bạ, Điểm thi...)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Loại giấy tờ (Học bạ, CCCD...)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Tổ hợp môn (A00, A01...)
                  </li>
                </ul>
              </div>
            </div>

            <div className="flex gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-purple-100 text-purple-600 flex items-center justify-center font-bold">
                  2
                </div>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Giai đoạn 2: Chương trình Đào tạo</h3>
                <p className="text-muted-foreground mb-3">
                  Thiết lập ngành và chương trình tuyển sinh. Cập nhật khi có ngành mới.
                </p>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Ngành đào tạo (CNTT, Kinh tế...)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Chương trình tuyển sinh (CNTT Chính quy...)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Thông tin năm học (Chỉ tiêu, Học phí)
                  </li>
                </ul>
              </div>
            </div>

            <div className="flex gap-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 rounded-full bg-success-100 text-success-600 flex items-center justify-center font-bold">
                  3
                </div>
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-lg mb-2">Giai đoạn 3: Cấu hình Tuyển sinh</h3>
                <p className="text-muted-foreground mb-3">
                  Cấu hình các đợt tuyển sinh cho năm học. Kết hợp tất cả các thành phần trên.
                </p>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Thiết lập tiêu chí xét tuyển cho từng phương thức
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Cấu hình yêu cầu hồ sơ giấy tờ
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Tạo đợt tuyển sinh (Phương thức + Tiêu chí + Hồ sơ)
                  </li>
                  <li className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success-600" />
                    Kích hoạt đợt tuyển sinh cho thí sinh đăng ký
                  </li>
                </ul>
              </div>
            </div>
          </div>

          {/* CTA */}
          <div className="pt-6 border-t">
            <div className="flex flex-col items-center gap-4">
              <p className="text-sm text-muted-foreground text-center max-w-md">
                Hệ thống chưa có dữ liệu danh mục. Hãy bắt đầu với Giai đoạn 1.
              </p>
              <Button size="lg" onClick={onStart} className="gap-2">
                <Rocket className="h-5 w-5" />
                Bắt đầu Thiết lập Giai đoạn 1
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
