"use client";

import { useParams } from "next/navigation";
import { NotificationRuleWizard } from "@/components/admin/notifications/NotificationRuleWizard";

export default function EditNotificationRulePage() {
  const params = useParams();
  const ruleId = Number(params.id);

  if (isNaN(ruleId)) {
    return <div className="p-8 text-center text-destructive">Rule ID không hợp lệ</div>;
  }

  return <NotificationRuleWizard ruleId={ruleId} />;
}
