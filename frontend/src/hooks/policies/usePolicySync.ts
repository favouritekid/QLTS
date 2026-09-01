import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { policiesApi, type SyncStatus } from "@/lib/api/policies";
import { toast } from "sonner";
export type { SyncStatus } from "@/lib/api/policies"; // Re-export for UI


export const syncKeys = {
  status: ["policies", "sync-status"] as const,
};

export function usePolicySyncStatus() {
  return useQuery<SyncStatus>({
    queryKey: syncKeys.status,
    queryFn: async () => {
      return policiesApi.getSyncStatus();
    },
  });
}

export function useSyncPolicies() {
  const queryClient = useQueryClient();

  return useMutation({
    // `userIds === null` ⇒ đồng bộ TẤT CẢ; mảng `user_id` ⇒ đồng bộ từng phần.
    // Cả hai đi qua cùng một endpoint `POST /api/admin/sync` (sync.py:53 là
    // `@router.post("")` trên prefix `/sync`). `/api/admin/sync/users` là
    // đường CHẾT — không router nào phục vụ chuỗi đó.
    mutationFn: async (userIds: number[] | null) => {
      return policiesApi.syncUsers(userIds);
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: syncKeys.status });

      // HTTP 200 KHÔNG có nghĩa là mọi user đã đồng bộ: backend trả
      // `{synced_count, failed_count}` và `failed_count > 0` là hỏng một phần.
      // Bản cũ toast "Sync operation completed" cho mọi phản hồi 2xx ⇒ báo
      // thành công cho việc chưa xảy ra.
      const synced = result?.synced_count;
      const failed = result?.failed_count;

      if (typeof synced !== "number" || typeof failed !== "number") {
        toast.error(
          "Sync đã chạy nhưng backend không trả về số liệu — bấm 'Làm mới' và " +
          "kiểm tra lại danh sách lệch trước khi coi là xong."
        );
        return;
      }

      if (failed > 0) {
        toast.error(
          `Đồng bộ MỘT PHẦN: ${synced} user thành công, ${failed} user THẤT BẠI. ` +
          "Danh sách lệch bên dưới vẫn còn — xem log backend rồi chạy lại.",
          { duration: 12000 }
        );
        return;
      }

      toast.success(`Đã đồng bộ ${synced} user`);
    },
    onError: () => {
      toast.error("Failed to synchronize");
    },
  });
}
