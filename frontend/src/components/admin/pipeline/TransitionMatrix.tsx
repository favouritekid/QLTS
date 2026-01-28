"use client";

import { useState, useMemo } from "react";
import { Loader2, ArrowRight, Search, MousePointerClick } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { ColorDot } from "@/components/ui/dynamic-color-badge";
import {
  usePipelineStages,
  useConsultationStatuses,
  useAllowedTransitions,
  useCreateAllowedTransition,
  useDeleteAllowedTransition,
} from "@/hooks/usePipeline";
import { toast } from "sonner";

export function TransitionMatrix() {
  // 1. Fetch Data
  const { data: stages = [], isLoading: isLoadingStages } = usePipelineStages();
  const { data: statuses = [], isLoading: isLoadingStatuses } = useConsultationStatuses();
  const { data: transitions = [], isLoading: isLoadingTransitions } = useAllowedTransitions();

  // 2. State
  const [selectedFromId, setSelectedFromId] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");

  // 3. Mutations
  const createMutation = useCreateAllowedTransition();
  const deleteMutation = useDeleteAllowedTransition();
  const isMutating = createMutation.isPending || deleteMutation.isPending;

  // 4. Memoized Data Processing
  const sortedStages = useMemo(() => {
    return [...stages].sort((a, b) => a.order - b.order);
  }, [stages]);

  const allowedSet = useMemo(() => {
    const set = new Set<string>();
    if (Array.isArray(transitions)) {
      transitions.forEach((t) => set.add(`${t.from_status_id}|${t.to_status_id}`));
    }
    return set;
  }, [transitions]);

  // Tìm status object đang được chọn
  const selectedFromStatus = useMemo(() => {
    return statuses.find((s) => s.id === selectedFromId);
  }, [statuses, selectedFromId]);

  // 5. Handlers
  const handleToggle = (toId: string, currentState: boolean) => {
    if (!selectedFromId || selectedFromId === toId) return;

    if (currentState) {
      const transition = transitions.find(
        (t) => t.from_status_id === selectedFromId && t.to_status_id === toId
      );
      if (transition) {
        deleteMutation.mutate(transition.id, {
          onError: (err) => toast.error("Lỗi: " + err.message),
        });
      }
    } else {
      createMutation.mutate(
        { from_status_id: selectedFromId, to_status_id: toId },
        {
          onError: (err) => toast.error("Lỗi: " + err.message),
        }
      );
    }
  };

  // Loading State
  if (isLoadingStages || isLoadingStatuses || isLoadingTransitions) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="text-primary h-8 w-8 animate-spin" />
      </div>
    );
  }

  return (
    <div className="grid h-[calc(100vh-280px)] min-h-[500px] grid-cols-12 gap-6">
      {/* --- LEFT COLUMN: SOURCE SELECTION --- */}
      <Card className="col-span-4 flex h-full flex-col rounded-none border-y-0 border-r border-l-0 shadow-none">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-base">1. Chọn Trạng thái Nguồn</CardTitle>
          <CardDescription>Trạng thái bắt đầu (From)</CardDescription>
          <div className="relative mt-2">
            <Search className="text-muted-foreground absolute top-2.5 left-2 h-4 w-4" />
            <Input
              placeholder="Tìm kiếm..."
              className="pl-8"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </CardHeader>
        <CardContent className="flex-1 overflow-hidden p-0">
          <ScrollArea className="h-full">
            <div className="space-y-6 p-4 pt-0">
              {sortedStages.map((stage) => {
                const stageStatuses = statuses.filter((s) => s.stage_id === stage.id);
                const filteredStatuses = stageStatuses.filter((s) =>
                  s.name.toLowerCase().includes(searchTerm.toLowerCase())
                );

                if (filteredStatuses.length === 0) return null;

                return (
                  <div key={stage.id} className="space-y-2">
                    <div className="text-muted-foreground flex items-center gap-2 text-xs font-semibold tracking-wider uppercase">
                      <div className="bg-border h-px flex-1" />
                      {stage.name}
                      <div className="bg-border h-px flex-1" />
                    </div>

                    <div className="grid gap-1">
                      {filteredStatuses.map((status) => (
                        <button
                          key={status.id}
                          onClick={() => setSelectedFromId(status.id)}
                          className={cn(
                            "flex w-full items-center justify-between rounded-md p-2 text-sm transition-all",
                            selectedFromId === status.id
                              ? "bg-primary text-primary-foreground shadow-md"
                              : "hover:bg-muted text-foreground"
                          )}
                        >
                          <div className="flex items-center gap-3">
                            <ColorDot
                              color={status.color_code}
                              size="md"
                              className={cn(
                                "ring-2 ring-offset-1",
                                selectedFromId === status.id
                                  ? "ring-primary-foreground"
                                  : "ring-transparent"
                              )}
                            />
                            <span className="font-medium">{status.name}</span>
                          </div>
                          {selectedFromId === status.id && <ArrowRight className="h-4 w-4" />}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>

      {/* --- RIGHT COLUMN: TARGET SELECTION --- */}
      <Card className="col-span-8 flex h-full flex-col border-0 shadow-none">
        <CardHeader className="p-4 pb-2">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base">2. Cấu hình Chuyển đổi (Transitions)</CardTitle>
              <CardDescription>
                {selectedFromId ? (
                  <span>
                    Được phép chuyển từ <strong>{selectedFromStatus?.name}</strong> sang các trạng
                    thái dưới đây:
                  </span>
                ) : (
                  "Vui lòng chọn một trạng thái bên trái để bắt đầu cấu hình."
                )}
              </CardDescription>
            </div>
            {selectedFromId && (
              <Badge variant="outline" className="gap-2 px-3 py-1 text-sm">
                <ColorDot color={selectedFromStatus?.color_code} size="sm" />
                {selectedFromStatus?.name}
              </Badge>
            )}
          </div>
        </CardHeader>

        <CardContent className="bg-muted/5 m-4 mt-0 flex-1 overflow-hidden rounded-lg border p-0">
          {!selectedFromId ? (
            <div className="text-muted-foreground flex h-full flex-col items-center justify-center">
              <MousePointerClick className="mb-4 h-12 w-12 opacity-20" />
              <p>Chọn trạng thái nguồn ở cột bên trái</p>
            </div>
          ) : (
            <ScrollArea className="h-full p-6">
              <div className="space-y-8 pb-10">
                {sortedStages.map((stage) => {
                  const stageStatuses = statuses.filter((s) => s.stage_id === stage.id);
                  if (stageStatuses.length === 0) return null;

                  return (
                    <div key={stage.id} className="space-y-3">
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary" className="rounded-sm">
                          Stage {stage.order}
                        </Badge>
                        <h4 className="text-sm font-semibold">{stage.name}</h4>
                        <Separator className="flex-1" />
                      </div>

                      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                        {stageStatuses.map((toStatus) => {
                          const isSelf = selectedFromId === toStatus.id;
                          const isAllowed = allowedSet.has(`${selectedFromId}|${toStatus.id}`);

                          return (
                            <div
                              key={toStatus.id}
                              className={cn(
                                "flex items-center space-x-3 rounded-md border p-3 transition-all",
                                isAllowed
                                  ? "border-success-200 bg-success-50 dark:border-success-900 dark:bg-success-900/20"
                                  : "bg-background hover:bg-accent",
                                isSelf && "bg-muted cursor-not-allowed opacity-50"
                              )}
                            >
                              <Checkbox
                                id={`to-${toStatus.id}`}
                                checked={isAllowed}
                                onCheckedChange={() => handleToggle(toStatus.id, isAllowed)}
                                disabled={isSelf || isMutating}
                                className={cn(
                                  isAllowed &&
                                    "data-[state=checked]:border-success-600 data-[state=checked]:bg-success-600"
                                )}
                              />
                              <label
                                htmlFor={`to-${toStatus.id}`}
                                className="flex flex-1 cursor-pointer items-center gap-2 text-sm leading-none font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                              >
                                <ColorDot color={toStatus.color_code} size="sm" />
                                {toStatus.name}
                              </label>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
