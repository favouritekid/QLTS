import Link from "next/link";
import { Settings2, ExternalLink } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export function KpiConfigLinkCard() {
  return (
    <Card>
      <CardContent className="flex items-center justify-between py-4">
        <div className="flex items-center gap-2">
          <Settings2 aria-hidden="true" className="h-5 w-5 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">Cấu hình KPI nâng cao</p>
            <p className="text-xs text-muted-foreground">
              Quản lý KPI codes, scope, thresholds
            </p>
          </div>
        </div>
        <Link
          href="/admin/kpi-config"
          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
        >
          Mở trang cấu hình
          <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
        </Link>
      </CardContent>
    </Card>
  );
}
