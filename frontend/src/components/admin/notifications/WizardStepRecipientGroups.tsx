"use client";

import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import type { RecipientGroup, ExternalResolverOption } from "./wizard-types";
import type { ResolverTypeOption } from "@/types/api.types";
import RecipientGroupCard from "./RecipientGroupCard";
import { createInternalGroup, createExternalGroup } from "./wizard-utils";

interface WizardStepRecipientGroupsProps {
  groups: RecipientGroup[];
  onChange: (groups: RecipientGroup[]) => void;
  resolverOptions: ResolverTypeOption[];
  externalResolverOptions: ExternalResolverOption[];
  availableChannels?: string[];
  validationErrors?: string[];
}

export default function WizardStepRecipientGroups({
  groups,
  onChange,
  resolverOptions,
  externalResolverOptions,
  availableChannels,
  validationErrors,
}: WizardStepRecipientGroupsProps) {
  // Check if browser is used by any group
  const browserUsedGroups = new Set<number>();
  groups.forEach((g, i) => {
    if (g.channels.some((c) => c.channel === "browser")) {
      browserUsedGroups.add(i);
    }
  });

  const updateGroup = (idx: number, updated: RecipientGroup) => {
    const newGroups = [...groups];
    newGroups[idx] = updated;
    onChange(newGroups);
  };

  const removeGroup = (idx: number) => {
    onChange(groups.filter((_, i) => i !== idx));
  };

  const addInternalGroup = () => {
    onChange([...groups, createInternalGroup()]);
  };

  const addExternalGroup = () => {
    onChange([...groups, createExternalGroup()]);
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">Người nhận & Kênh gửi</h3>
        <p className="text-sm text-muted-foreground">
          Chọn ai sẽ nhận thông báo và gửi qua kênh nào. Bạn có thể tạo nhiều nhóm với người nhận khác nhau.
        </p>
        {groups.length > 1 && (
          <p className="text-xs text-muted-foreground mt-1">
            Nếu cùng một người thuộc nhiều nhóm, họ sẽ nhận thông báo từ nhóm có thứ tự thấp nhất cho mỗi kênh.
          </p>
        )}
      </div>

      {validationErrors && validationErrors.length > 0 && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 space-y-1">
          {validationErrors.map((err, i) => (
            <p key={i} className="text-sm text-destructive">{"•"} {err}</p>
          ))}
        </div>
      )}

      {groups.length === 0 && (
        <div className="rounded-lg border-2 border-dashed p-8 text-center text-muted-foreground">
          <p className="text-sm">Chưa có nhóm người nhận nào.</p>
          <p className="text-xs mt-1">Bấm nút bên dưới để thêm nhóm người nhận đầu tiên.</p>
        </div>
      )}

      {groups.map((group, idx) => (
        <RecipientGroupCard
          key={group.group_key}
          group={group}
          index={idx}
          onChange={(updated) => updateGroup(idx, updated)}
          onRemove={() => removeGroup(idx)}
          resolverOptions={resolverOptions}
          externalResolverOptions={externalResolverOptions}
          browserUsedByOtherGroup={
            browserUsedGroups.size > 0 && !browserUsedGroups.has(idx)
          }
          availableChannels={availableChannels}
        />
      ))}

      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={addInternalGroup}>
          <Plus className="h-4 w-4 mr-1" />
          Thêm nhóm nhân viên
        </Button>
        <Button variant="outline" size="sm" onClick={addExternalGroup}>
          <Plus className="h-4 w-4 mr-1" />
          Thêm nhóm khách hàng/đối tác
        </Button>
      </div>
    </div>
  );
}
