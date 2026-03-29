"use client";

import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import type { RecipientGroup } from "./wizard-types";
import type { ResolverTypeOption } from "@/types/api.types";
import RecipientGroupCard from "./RecipientGroupCard";
import { createInternalGroup, createExternalGroup } from "./wizard-utils";

interface ExternalResolverOption {
  value: string;
  label: string;
  description: string;
}

interface WizardStepRecipientGroupsProps {
  groups: RecipientGroup[];
  onChange: (groups: RecipientGroup[]) => void;
  resolverOptions: ResolverTypeOption[];
  externalResolverOptions: ExternalResolverOption[];
  availableChannels?: string[]; // from metadata
}

export default function WizardStepRecipientGroups({
  groups,
  onChange,
  resolverOptions,
  externalResolverOptions,
  availableChannels,
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
        <h3 className="text-lg font-semibold">Nh\u00f3m nh\u1eadn</h3>
        <p className="text-sm text-muted-foreground">
          C\u1ea5u h\u00ecnh ai s\u1ebd nh\u1eadn th\u00f4ng b\u00e1o v\u00e0 qua k\u00eanh n\u00e0o. M\u1ed7i nh\u00f3m c\u00f3 th\u1ec3 c\u00f3 ng\u01b0\u1eddi nh\u1eadn v\u00e0 n\u1ed9i dung kh\u00e1c nhau.
        </p>
      </div>

      {groups.length === 0 && (
        <div className="rounded-lg border-2 border-dashed p-8 text-center text-muted-foreground">
          <p className="text-sm">Ch\u01b0a c\u00f3 nh\u00f3m nh\u1eadn n\u00e0o.</p>
          <p className="text-xs mt-1">Th\u00eam nh\u00f3m nh\u1eadn \u0111\u1ec3 b\u1eaft \u0111\u1ea7u c\u1ea5u h\u00ecnh.</p>
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
          Th\u00eam nh\u00f3m n\u1ed9i b\u1ed9
        </Button>
        <Button variant="outline" size="sm" onClick={addExternalGroup}>
          <Plus className="h-4 w-4 mr-1" />
          Th\u00eam nh\u00f3m b\u00ean ngo\u00e0i
        </Button>
      </div>
    </div>
  );
}
