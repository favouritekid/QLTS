// src/components/officer/dashboard/KPICardsGrid.tsx
/**
 * KPI Cards Grid for Officer Dashboard
 * Clean 4-column layout with consistent white cards
 */

"use client";

import { useRouter } from "next/navigation";
import { Phone, Users, TrendingUp, Clock } from "lucide-react";
import { KPICard } from "./KPICard";

interface TrendInfo {
  value: number;
  direction: "up" | "down" | "neutral";
  comparison: string;
}

interface KPIStats {
  consultations_today: number;
  consultations_target: number;
  consultations_trend: TrendInfo;
  active_leads: number;
  active_leads_trend: TrendInfo;
  conversion_rate: number;
  conversion_rate_trend: TrendInfo;
  avg_response_time: number;
  avg_response_time_trend: TrendInfo;
}

interface KPICardsGridProps {
  kpis: KPIStats;
}

export function KPICardsGrid({ kpis }: KPICardsGridProps) {
  const router = useRouter();

  // Navigate to leads page
  const goToLeads = () => router.push("/leads");

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {/* Consultations Today */}
      <KPICard
        title="Tư vấn hôm nay"
        value={`${kpis.consultations_today}/${kpis.consultations_target}`}
        subtitle="Mục tiêu hàng ngày"
        trend={kpis.consultations_trend}
        icon={Phone}
        onClick={goToLeads}
      />

      {/* Active Leads */}
      <KPICard
        title="Leads đang xử lý"
        value={kpis.active_leads}
        subtitle="Chưa hoàn thành"
        trend={kpis.active_leads_trend}
        icon={Users}
        onClick={goToLeads}
      />

      {/* Conversion Rate */}
      <KPICard
        title="Tỉ lệ chuyển đổi"
        value={`${kpis.conversion_rate}%`}
        subtitle="Tháng này"
        trend={kpis.conversion_rate_trend}
        icon={TrendingUp}
        onClick={goToLeads}
      />

      {/* Average Response Time */}
      <KPICard
        title="Thời gian phản hồi"
        value={`${kpis.avg_response_time}h`}
        subtitle="Trung bình"
        trend={kpis.avg_response_time_trend}
        icon={Clock}
        onClick={goToLeads}
        inverseTrend={true}
      />
    </div>
  );
}
