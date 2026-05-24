// src/components/leads/InsightsHelperDrawer.tsx
/**
 * InsightsHelperDrawer - Hướng dẫn chi tiết về Lead Insights
 * Drawer slide từ bên phải để officers có thể xem song song với data
 */
"use client";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { HelpCircle, Sparkles, Users, Target, Clock, Star, Lightbulb } from "lucide-react";
import { cn } from "@/lib/utils";

interface InsightsHelperDrawerProps {
  trigger?: React.ReactNode;
}

const INSIGHTS_DOCS = [
  {
    id: "overall",
    label: "Điểm tổng hợp",
    icon: Sparkles,
    color: "text-violet-600",
    bgColor: "bg-violet-100",
    summary: "Chỉ số đánh giá tổng thể tiềm năng chuyển đổi của lead, kết hợp tất cả các yếu tố.",
    interpretation: {
      high: { range: "≥70", meaning: "Lead rất tiềm năng - ưu tiên chăm sóc hàng đầu" },
      medium: { range: "50-69", meaning: "Lead có tiềm năng - cần theo dõi thường xuyên" },
      low: { range: "<50", meaning: "Lead cần được chăm sóc thêm" },
    },
    formula: "= (Tương tác × 30%) + (Phù hợp × 40%) + (Khẩn cấp × 20%) + (Đánh giá × 10%)",
    tips: [
      "Tăng tần suất tư vấn và ghi nhận kết quả đầy đủ",
      "Đánh giá lead dựa trên trải nghiệm tư vấn thực tế",
      "Cập nhật thông tin lead (học vấn, GPA) để điểm Phù hợp chính xác hơn",
    ],
  },
  {
    id: "engagement",
    label: "Mức độ tương tác",
    icon: Users,
    color: "text-info-600",
    bgColor: "bg-info-100",
    summary: "Đo lường mức độ chăm sóc lead thông qua lịch sử tư vấn và kết quả liên hệ.",
    interpretation: {
      high: { range: "≥70", meaning: "Lead được chăm sóc tốt, tương tác đều đặn" },
      medium: { range: "50-69", meaning: "Lead cần được liên hệ thường xuyên hơn" },
      low: { range: "<50", meaning: "Lead chưa được chăm sóc đầy đủ" },
    },
    formula: "Tính từ lịch sử tư vấn",
    details: [
      { label: "Mỗi lần tư vấn", points: "+5" },
      { label: "Kết quả: Thành công", points: "+10" },
      { label: "Kết quả: Cần theo dõi", points: "+5" },
      { label: "Kết quả: Thất bại", points: "-5" },
      { label: "Gặp mặt trực tiếp", points: "+15" },
      { label: "Gọi điện", points: "+5" },
      { label: "Email", points: "+2" },
      { label: "Không liên hệ >3 ngày", points: "-1/ngày" },
    ],
    tips: [
      "Liên hệ lead ít nhất 2-3 lần/tuần để giữ điểm tương tác",
      "Ưu tiên gặp mặt trực tiếp hoặc gọi điện thay vì email",
      "Ghi nhận kết quả tư vấn ngay sau mỗi cuộc gọi",
    ],
  },
  {
    id: "fit",
    label: "Độ phù hợp",
    icon: Target,
    color: "text-success-600",
    bgColor: "bg-success-100",
    summary: "Đánh giá mức độ phù hợp của lead với chương trình, kết hợp dữ liệu hồ sơ và đánh giá chủ quan của bạn.",
    interpretation: {
      high: { range: "≥70", meaning: "Rất phù hợp - khả năng chuyển đổi cao" },
      medium: { range: "50-69", meaning: "Phù hợp một phần - cần tìm hiểu thêm nhu cầu" },
      low: { range: "<50", meaning: "Ít phù hợp hoặc chưa được đánh giá" },
    },
    formula: "= Điểm lead + (Đánh giá của bạn × 4)",
    details: [
      { label: "Điểm lead (tự động)", points: "0-100" },
      { label: "Đánh giá 1 sao ⭐", points: "+4" },
      { label: "Đánh giá 2 sao ⭐⭐", points: "+8" },
      { label: "Đánh giá 3 sao ⭐⭐⭐", points: "+12" },
      { label: "Đánh giá 4 sao ⭐⭐⭐⭐", points: "+16" },
      { label: "Đánh giá 5 sao ⭐⭐⭐⭐⭐", points: "+20" },
    ],
    tips: [
      "Đánh giá sao dựa trên: khả năng tài chính, động lực học tập, thái độ hợp tác",
      "Cập nhật đánh giá sau mỗi buổi tư vấn để phản ánh đúng tiềm năng",
      "Bổ sung thông tin học vấn, GPA để điểm lead tự động tăng",
    ],
  },
  {
    id: "urgency",
    label: "Mức độ khẩn cấp",
    icon: Clock,
    color: "text-warning-600",
    bgColor: "bg-warning-100",
    // Urgency: màu ngược - cao = đỏ cảnh báo, thấp = xanh an toàn
    isReversedColors: true,
    summary: "Cho biết lead này có cần được liên hệ ngay không. Điểm càng cao = càng cần ưu tiên.",
    interpretation: {
      high: { range: "≥70", meaning: "CẦN LIÊN HỆ NGAY! Lead đang \"nóng\"" },
      medium: { range: "50-69", meaning: "Nên liên hệ trong 1-2 ngày tới" },
      low: { range: "<50", meaning: "Có thể theo lịch bình thường" },
    },
    formula: "Tính từ trạng thái lead",
    details: [
      { label: "Chưa liên hệ theo lịch hẹn", points: "+30" },
      { label: "Chưa từng được tư vấn", points: "+25" },
      { label: "Lead nóng (điểm ≥70)", points: "+15" },
      { label: "Có lịch hẹn trong 24h tới", points: "+20" },
      { label: "Mỗi ngày không liên hệ", points: "+3/ngày" },
      { label: "Lead đã chuyển đổi/thất bại", points: "-50" },
    ],
    tips: [
      "Liên hệ ngay các lead có điểm Khẩn cấp ≥70",
      "Đặt lịch hẹn rõ ràng và tuân thủ để tránh bị cộng điểm quá hạn",
      "Lead mới chưa từng tư vấn nên được liên hệ trong 24h đầu tiên",
    ],
  },
  {
    id: "rating",
    label: "Đánh giá của bạn",
    icon: Star,
    color: "text-amber-600",
    bgColor: "bg-amber-100",
    summary: "Đánh giá chủ quan từ trải nghiệm tư vấn thực tế của bạn với lead này.",
    interpretation: {
      high: { range: "4-5 ⭐", meaning: "Lead rất tiềm năng theo kinh nghiệm của bạn" },
      medium: { range: "3 ⭐", meaning: "Lead bình thường, cần theo dõi thêm" },
      low: { range: "1-2 ⭐", meaning: "Lead khó chuyển đổi" },
    },
    formula: "Ảnh hưởng trực tiếp đến Độ phù hợp và Điểm tổng hợp",
    details: [
      { label: "Tác động lên Phù hợp", points: "sao × 4" },
      { label: "Tác động lên Tổng hợp", points: "sao × 2" },
    ],
    tips: [
      "Đánh giá dựa trên: sự quan tâm, khả năng tài chính, thời gian quyết định",
      "Không ngại đánh giá thấp nếu lead thực sự khó - giúp ưu tiên đúng",
      "Cập nhật đánh giá thường xuyên khi có thông tin mới",
    ],
  },
];

export function InsightsHelperDrawer({ trigger }: InsightsHelperDrawerProps) {
  return (
    <Sheet>
      <SheetTrigger asChild>
        {trigger || (
          <Button variant="ghost" size="sm" className="gap-1.5 text-xs text-muted-foreground hover:text-primary">
            <HelpCircle className="h-3.5 w-3.5" />
            Cách tính điểm
          </Button>
        )}
      </SheetTrigger>
      <SheetContent side="right" className="w-[calc(100vw-1rem)] sm:w-[520px] overflow-y-auto">
        <SheetHeader className="mb-6">
          <SheetTitle className="flex items-center gap-2 text-lg">
            <HelpCircle aria-hidden="true" className="h-5 w-5 text-primary" />
            Hướng dẫn Lead Insights
          </SheetTitle>
          <p className="text-sm text-muted-foreground mt-1">
            Hiểu rõ các chỉ số để chăm sóc lead hiệu quả hơn
          </p>
        </SheetHeader>

        <div className="space-y-5">
          {INSIGHTS_DOCS.map((doc) => (
            <div key={doc.id} className="border rounded-lg overflow-hidden">
              {/* Header */}
              <div className={cn("flex items-center gap-2 px-4 py-3", doc.bgColor)}>
                <doc.icon className={cn("h-5 w-5", doc.color)} />
                <h3 className="font-semibold">{doc.label}</h3>
              </div>

              <div className="p-4 space-y-4">
                {/* Mô tả */}
                <p className="text-sm text-muted-foreground">{doc.summary}</p>

                {/* Ý nghĩa điểm số */}
                <div className="bg-muted/40 rounded-lg p-3">
                  <p className="text-xs font-medium text-muted-foreground uppercase mb-2">
                    Ý nghĩa điểm số
                  </p>
                  <div className="space-y-1.5 text-sm">
                    <div className="flex items-start gap-2">
                      <span className={cn(
                        "font-semibold min-w-[50px]",
                        doc.isReversedColors ? "text-error-600" : "text-success-600"
                      )}>{doc.interpretation.high.range}</span>
                      <span className="text-muted-foreground">{doc.interpretation.high.meaning}</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="text-warning-600 font-semibold min-w-[50px]">{doc.interpretation.medium.range}</span>
                      <span className="text-muted-foreground">{doc.interpretation.medium.meaning}</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className={cn(
                        "font-semibold min-w-[50px]",
                        doc.isReversedColors ? "text-success-600" : "text-muted-foreground"
                      )}>{doc.interpretation.low.range}</span>
                      <span className="text-muted-foreground">{doc.interpretation.low.meaning}</span>
                    </div>
                  </div>
                </div>

                {/* Công thức */}
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase mb-1.5">Công thức</p>
                  <code className="block bg-muted px-3 py-2 rounded text-sm font-mono text-primary">
                    {doc.formula}
                  </code>
                </div>

                {/* Chi tiết điểm */}
                {doc.details && (
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase mb-1.5">Chi tiết cộng/trừ điểm</p>
                    <div className="grid grid-cols-2 gap-1.5">
                      {doc.details.map((item, idx) => (
                        <div key={idx} className="flex justify-between bg-muted/30 px-2.5 py-1.5 rounded text-xs">
                          <span className="text-muted-foreground">{item.label}</span>
                          <span className={cn(
                            "font-semibold",
                            item.points.startsWith("-") ? "text-error-500" : "text-primary"
                          )}>{item.points}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Mẹo tăng điểm */}
                {doc.tips && (
                  <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Lightbulb aria-hidden="true" className="h-4 w-4 text-amber-600" />
                      <p className="text-xs font-semibold text-amber-700 uppercase">Mẹo tăng điểm</p>
                    </div>
                    <ul className="space-y-1">
                      {doc.tips.map((tip, idx) => (
                        <li key={idx} className="flex gap-2 text-xs text-amber-800">
                          <span className="text-amber-500">→</span>
                          <span>{tip}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="mt-6 pt-4 border-t text-center">
          <p className="text-xs text-muted-foreground">
            💡 Chăm sóc lead thường xuyên + Đánh giá chính xác = Tăng tỷ lệ chuyển đổi!
          </p>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default InsightsHelperDrawer;
