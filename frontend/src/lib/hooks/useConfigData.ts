import { useQuery } from "@tanstack/react-query";
import { configApi } from "@/lib/api/config";

export const useConfigData = (type: string | null) => {
    return useQuery({
        queryKey: ["config", "categories", type],
        queryFn: () => type ? configApi.getCategories(type) : Promise.resolve([]),
        enabled: !!type,
        staleTime: 60 * 60 * 1000, // 1 hour
    });
};
