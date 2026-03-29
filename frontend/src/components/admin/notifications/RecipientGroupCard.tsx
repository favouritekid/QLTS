"use client";

import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Trash2, Plus } from "lucide-react";
import type { RecipientGroup, ChannelBranch, RecipientKind } from "./wizard-types";
import ChannelBranchCard from "./ChannelBranchCard";
import type { ResolverTypeOption } from "@/types/api.types";

interface ExternalResolverOption {
  value: string;
  label: string;
  description: string;
}

interface RecipientGroupCardProps {
  group: RecipientGroup;
  index: number;
  onChange: (updated: RecipientGroup) => void;
  onRemove: () => void;
  resolverOptions: ResolverTypeOption[];
  externalResolverOptions: ExternalResolverOption[];
  browserUsedByOtherGroup: boolean;
  availableChannels?: string[]; // from metadata, defaults to hardcoded
}

const DEFAULT_CHANNELS: Record<RecipientKind, string[]> = {
  internal: ["browser", "email", "zalo", "sms"],
  external: ["zalo", "sms"],
};

export default function RecipientGroupCard({
  group,
  index,
  onChange,
  onRemove,
  resolverOptions,
  externalResolverOptions,
  browserUsedByOtherGroup,
  availableChannels: availableChannelsProp,
}: RecipientGroupCardProps) {
  const activeChannels = new Set(group.channels.map((c) => c.channel));
  const channelList = group.recipient_kind === "external"
    ? (availableChannelsProp ?? DEFAULT_CHANNELS.external).filter((ch) => ch !== "browser")
    : (availableChannelsProp ?? DEFAULT_CHANNELS.internal);

  const handleResolverChange = (value: string) => {
    if (group.recipient_kind === "internal") {
      const label = resolverOptions.find((r) => r.value === value)?.label ?? value;
      onChange({
        ...group,
        recipient_config: { resolver_type: value, params: {} },
        label,
      });
    } else {
      const label = externalResolverOptions.find((r) => r.value === value)?.label ?? value;
      onChange({
        ...group,
        external_resolver: value,
        label,
      });
    }
  };

  const addChannel = (channel: string) => {
    const newBranch: ChannelBranch = {
      channel,
      delay_minutes: 0,
      content_mode: group.recipient_kind === "external" ? "channel_native" : "inherit_default",
      template_code: null,
      content_override: null,
      config: channel === "zalo" ? { zalo_template_id: "", zalo_template_data: {} } : null,
    };
    onChange({ ...group, channels: [...group.channels, newBranch] });
  };

  const updateChannel = (idx: number, updated: ChannelBranch) => {
    const newChannels = [...group.channels];
    newChannels[idx] = updated;
    onChange({ ...group, channels: newChannels });
  };

  const removeChannel = (idx: number) => {
    onChange({ ...group, channels: group.channels.filter((_, i) => i !== idx) });
  };

  const kindLabel = group.recipient_kind === "internal" ? "N\u1ed9i b\u1ed9" : "B\u00ean ngo\u00e0i";

  // Duplicate channels warning
  if (group._hasDuplicateChannels) {
    return (
      <Card className="border-yellow-300 bg-yellow-50">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            <span>Nh\u00f3m nh\u1eadn #{index + 1} ({kindLabel})</span>
            <Button variant="ghost" size="sm" onClick={onRemove}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-yellow-800">
            Nh\u00f3m n\u00e0y c\u00f3 k\u00eanh tr\u00f9ng l\u1eb7p (t\u1ea1o qua API). Kh\u00f4ng th\u1ec3 ch\u1ec9nh s\u1eeda t\u1eeb wizard.
          </p>
          <pre className="text-xs mt-2 p-2 bg-white rounded border overflow-auto max-h-32">
            {JSON.stringify(group.channels, null, 2)}
          </pre>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between">
          <span>
            Nh\u00f3m nh\u1eadn #{index + 1} ({kindLabel})
          </span>
          <Button variant="ghost" size="sm" onClick={onRemove} className="text-destructive">
            <Trash2 className="h-4 w-4" />
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Resolver picker */}
        <div>
          <label className="text-xs font-medium text-muted-foreground">Ng\u01b0\u1eddi nh\u1eadn</label>
          <Select
            value={
              group.recipient_kind === "internal"
                ? group.recipient_config?.resolver_type ?? ""
                : group.external_resolver ?? ""
            }
            onValueChange={handleResolverChange}
          >
            <SelectTrigger className="mt-1">
              <SelectValue placeholder="Ch\u1ecdn ng\u01b0\u1eddi nh\u1eadn..." />
            </SelectTrigger>
            <SelectContent>
              {group.recipient_kind === "internal"
                ? resolverOptions.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))
                : externalResolverOptions.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
            </SelectContent>
          </Select>
        </div>

        {/* Channel list */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">K\u00eanh g\u1eedi</label>
          {group.channels.map((branch, idx) => (
            <ChannelBranchCard
              key={`${branch.channel}-${idx}`}
              branch={branch}
              recipientKind={group.recipient_kind}
              onChange={(updated) => updateChannel(idx, updated)}
              onRemove={() => removeChannel(idx)}
            />
          ))}

          {/* Add channel buttons */}
          <div className="flex flex-wrap gap-2 pt-1">
            {channelList
              .filter((ch) => !activeChannels.has(ch))
              .filter((ch) => !(ch === "browser" && browserUsedByOtherGroup))
              .map((ch) => (
                <Button
                  key={ch}
                  variant="outline"
                  size="sm"
                  onClick={() => addChannel(ch)}
                  className="text-xs"
                >
                  <Plus className="h-3 w-3 mr-1" />
                  {ch}
                </Button>
              ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
