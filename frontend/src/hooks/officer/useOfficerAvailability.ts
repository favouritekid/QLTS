import { useMutation, useQueryClient } from "@tanstack/react-query";
import { officerApi, type AvailabilityPayload } from "@/lib/api/officer";
import { toast } from "sonner";
import { officerKeys } from "./useWeeklyLeaderboard";

export function useOfficerAvailability() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (status: "available" | "busy" | "offline") => {
      return officerApi.updateAvailability({ availability_status: status });
    },
    onSuccess: (data) => {
      // Invalidate relevant queries needed to refresh the dashboard or header status
      queryClient.invalidateQueries({ queryKey: officerKeys.all }); // Broad invalidation for now or specific keys
      toast.success(`Đã cập nhật: ${data.availability_status === "available" ? "Sẵn sàng" : "Bận"}`);
    },
    onError: () => {
      toast.error("Không thể cập nhật trạng thái");
    },
  });
}
