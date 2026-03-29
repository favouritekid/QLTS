"use client";

import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import { CHANNEL_LABELS } from "./wizard-types";

interface AddChannelBarProps {
  channelList: string[];
  activeChannels: Set<string>;
  browserUsedByOtherGroup: boolean;
  onAddChannel: (channel: string) => void;
}

export default function AddChannelBar({
  channelList,
  activeChannels,
  browserUsedByOtherGroup,
  onAddChannel,
}: AddChannelBarProps) {
  const available = channelList
    .filter((ch) => !activeChannels.has(ch))
    .filter((ch) => !(ch === "browser" && browserUsedByOtherGroup));

  if (available.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 pt-1">
      {available.map((ch) => (
        <Button
          key={ch}
          variant="outline"
          size="sm"
          onClick={() => onAddChannel(ch)}
          className="text-xs"
        >
          <Plus className="h-3 w-3 mr-1" />
          {CHANNEL_LABELS[ch] ?? ch}
        </Button>
      ))}
    </div>
  );
}
