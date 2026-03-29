"use client";

import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Trash2 } from "lucide-react";
import type { RecipientGroup, ChannelBranch, ExternalResolverOption } from "./wizard-types";
import { DEFAULT_CHANNELS } from "./wizard-types";
import ChannelBranchCard from "./ChannelBranchCard";
import ResolverPicker from "./ResolverPicker";
import AddChannelBar from "./AddChannelBar";
import type { ResolverTypeOption } from "@/types/api.types";

interface RecipientGroupCardProps {
  group: RecipientGroup;
  index: number;
  onChange: (updated: RecipientGroup) => void;
  onRemove: () => void;
  resolverOptions: ResolverTypeOption[];
  externalResolverOptions: ExternalResolverOption[];
  browserUsedByOtherGroup: boolean;
  availableChannels?: string[];
}

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

  const kindLabel = group.recipient_kind === "internal" ? "Nhân viên" : "Khách hàng/Đối tác";
  const resolverValue =
    group.recipient_kind === "internal"
      ? group.recipient_config?.resolver_type ?? ""
      : group.external_resolver ?? "";

  // Duplicate channels: read-only card (created via API)
  if (group._hasDuplicateChannels) {
    return (
      <Card className="border-yellow-300 bg-yellow-50">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            <span>Nhóm nhận #{index + 1} ({kindLabel})</span>
            <Button variant="ghost" size="sm" onClick={onRemove}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-yellow-800">
            Nhóm này có cấu hình phức tạp (tạo qua API). Vui lòng chỉnh sửa qua API hoặc tạo rule mới.
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
            Nhóm nhận #{index + 1} ({kindLabel})
          </span>
          <Button variant="ghost" size="sm" onClick={onRemove} className="text-destructive">
            <Trash2 className="h-4 w-4" />
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Resolver picker */}
        <ResolverPicker
          recipientKind={group.recipient_kind}
          value={resolverValue}
          onChange={handleResolverChange}
          resolverOptions={resolverOptions}
          externalResolverOptions={externalResolverOptions}
        />

        {/* Channel list */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">Gửi qua kênh nào?</label>
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
          <AddChannelBar
            channelList={channelList}
            activeChannels={activeChannels}
            browserUsedByOtherGroup={browserUsedByOtherGroup}
            onAddChannel={addChannel}
          />
        </div>
      </CardContent>
    </Card>
  );
}
