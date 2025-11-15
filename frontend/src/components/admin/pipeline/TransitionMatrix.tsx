// src/components/admin/pipeline/TransitionMatrix.tsx
"use client";

import { useMemo } from "react";
import { Loader2, Info } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ScrollArea } from "@/components/ui/scroll-area"; // ❌ Đã xóa ScrollBar
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useConsultationStatuses,
  useAllowedTransitions,
  useCreateAllowedTransition,
  useDeleteAllowedTransition,
} from "@/hooks/usePipeline";
import { toast } from "sonner";

export function TransitionMatrix() {
  // 1. Fetch Data
  const { data: statuses = [], isLoading: isLoadingStatuses } = useConsultationStatuses();
  const { data: transitions = [], isLoading: isLoadingTransitions } = useAllowedTransitions();

  // 2. Mutations
  const createMutation = useCreateAllowedTransition();
  const deleteMutation = useDeleteAllowedTransition();

  const isMutating = createMutation.isPending || deleteMutation.isPending;

  // 3. Optimize Lookup
  const allowedSet = useMemo(() => {
    const set = new Set<string>();
    if (Array.isArray(transitions)) {
      transitions.forEach((t) => set.add(`${t.from_status_id}|${t.to_status_id}`));
    }
    return set;
  }, [transitions]);

  // 4. Handle Toggle
  const handleToggle = (fromId: string, toId: string, currentState: boolean) => {
    if (fromId === toId) return;

    if (currentState) {
      deleteMutation.mutate(
        { from_status_id: fromId, to_status_id: toId },
        {
          onSuccess: () => toast.success("Đã chặn luồng chuyển đổi"),
          onError: (err) => toast.error("Lỗi: " + err.message),
        }
      );
    } else {
      createMutation.mutate(
        { from_status_id: fromId, to_status_id: toId },
        {
          onSuccess: () => toast.success("Đã cho phép luồng chuyển đổi"),
          onError: (err) => toast.error("Lỗi: " + err.message),
        }
      );
    }
  };

  if (isLoadingStatuses || isLoadingTransitions) {
    return (
      <div className="text-muted-foreground flex h-64 flex-col items-center justify-center gap-4">
        <Loader2 className="text-primary h-8 w-8 animate-spin" />
        <p>Đang tải dữ liệu quy trình...</p>
      </div>
    );
  }

  if (statuses.length === 0) {
    return (
      <div className="bg-muted/10 flex h-64 flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed">
        <Info className="text-muted-foreground/50 h-10 w-10" />
        <p className="text-muted-foreground font-medium">Chưa có trạng thái tư vấn nào.</p>
        <p className="text-muted-foreground text-xs">
          Vui lòng tạo Status trong tab "Consultation Statuses" trước.
        </p>
      </div>
    );
  }

  return (
    <Card className="border shadow-sm">
      <CardHeader className="pb-4">
        <CardTitle className="flex items-center gap-2 text-lg">
          Ma trận chuyển đổi (Workflow Rules)
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger>
                <Info className="text-muted-foreground h-4 w-4 cursor-help" />
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-xs">
                <p className="mb-1 font-semibold">Hướng dẫn:</p>
                <p>
                  • <strong>Hàng dọc:</strong> Trạng thái hiện tại (From)
                </p>
                <p>
                  • <strong>Hàng ngang:</strong> Trạng thái tiếp theo (To)
                </p>
                <p className="mt-1 text-xs italic">Tích chọn để cho phép chuyển đổi.</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </CardTitle>
        <CardDescription>
          Cấu hình quy trình bằng cách quy định trạng thái A có thể chuyển sang trạng thái B hay
          không.
        </CardDescription>
      </CardHeader>

      <CardContent className="p-0">
        <ScrollArea className="h-[600px] w-full">
          <div className="min-w-max p-6 pt-2">
            <table className="w-full border-collapse text-sm">
              {/* HEADER ROW (TO) */}
              <thead>
                <tr>
                  <th className="bg-muted/40 sticky top-0 left-0 z-20 min-w-[200px] border p-3 text-left font-bold shadow-sm">
                    <div className="flex flex-col">
                      <span className="text-muted-foreground text-xs font-normal">Từ (From) ↓</span>
                      <span className="text-muted-foreground text-right text-xs font-normal">
                        Đến (To) →
                      </span>
                    </div>
                  </th>
                  {statuses.map((status) => (
                    <th
                      key={status.id}
                      className="bg-background sticky top-0 z-10 min-w-[100px] border p-2 align-top"
                    >
                      <div className="flex h-full flex-col items-center justify-end gap-1 pb-1">
                        <div
                          className="mb-1 h-1 w-full rounded-full"
                          style={{ backgroundColor: status.color_code }}
                        />
                        <span
                          className="max-w-[100px] text-center text-xs font-semibold break-words"
                          title={status.name}
                        >
                          {status.name}
                        </span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>

              {/* BODY ROWS (FROM) */}
              <tbody>
                {statuses.map((fromStatus) => (
                  <tr key={fromStatus.id} className="group hover:bg-muted/5 transition-colors">
                    {/* ROW HEADER */}
                    <td className="bg-background group-hover:bg-muted/5 sticky left-0 z-10 border p-3 shadow-sm">
                      <div className="flex items-center gap-3">
                        <div
                          className="h-3 w-3 flex-shrink-0 rounded-full ring-1 ring-black/10 ring-offset-1"
                          style={{ backgroundColor: fromStatus.color_code }}
                        />
                        <span
                          className="max-w-[180px] truncate text-sm font-medium"
                          title={fromStatus.name}
                        >
                          {fromStatus.name}
                        </span>
                      </div>
                    </td>

                    {/* CELLS */}
                    {statuses.map((toStatus) => {
                      const isSelf = fromStatus.id === toStatus.id;
                      const isAllowed = allowedSet.has(`${fromStatus.id}|${toStatus.id}`);

                      return (
                        <td
                          key={`${fromStatus.id}-${toStatus.id}`}
                          className={`relative border p-2 text-center transition-colors ${
                            isAllowed ? "bg-primary/5" : ""
                          }`}
                        >
                          {isSelf ? (
                            <div className="bg-muted/30 flex h-full w-full items-center justify-center opacity-20 select-none">
                              —
                            </div>
                          ) : (
                            <div className="flex h-full items-center justify-center">
                              <Checkbox
                                checked={isAllowed}
                                onCheckedChange={() =>
                                  handleToggle(fromStatus.id, toStatus.id, isAllowed)
                                }
                                disabled={isMutating}
                                className="data-[state=checked]:bg-primary data-[state=checked]:border-primary h-5 w-5 transition-all active:scale-95"
                              />
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* ❌ Đã xóa ScrollBar components */}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
