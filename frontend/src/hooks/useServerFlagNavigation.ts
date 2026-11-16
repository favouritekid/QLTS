// src/hooks/useServerFlagNavigation.ts
/**
 * Lọc thanh bên theo CỜ QUYỀN của máy chủ (F238, Codex lần 8): mục mang `serverFlag` chỉ hiện khi
 * máy chủ trả ít nhất một cờ bật cho người gọi. Đang tải / lỗi / 403 ⇒ ẨN (fail-closed — trang
 * vẫn tự kiểm cờ, máy chủ vẫn là chốt). Chỉ hỏi máy chủ khi còn mục mang cờ sau bộ lọc vai thô
 * của `useAppNavigation` (không gọi `/quyen` cho vai chắc chắn không có dòng Casbin nào).
 */
import { useMemo } from "react";

import { useCouncilDocumentPermissions } from "@/hooks/admin/useCouncilDocuments";
import type { NavGroup, NavItem } from "@/types/navigation";

function hasServerFlagItem(items: NavItem[]): boolean {
  return items.some(
    (i) => i.serverFlag !== undefined || (i.children ? hasServerFlagItem(i.children) : false),
  );
}

export function useServerFlagNavigation(navigation: NavGroup[]): NavGroup[] {
  const needsQuery = navigation.some((g) => hasServerFlagItem(g.items));
  const document = useCouncilDocumentPermissions({ enabled: needsQuery });
  const openDocument =
    document.state === "ready" && Object.values(document.permissions).some((v) => v === true);

  return useMemo(() => {
    const hold = (items: NavItem[]): NavItem[] =>
      items
        .filter((i) => i.serverFlag === undefined || (i.serverFlag === "council-documents" && openDocument))
        .map((i) => (i.children ? { ...i, children: hold(i.children) } : i));
    return navigation
      .map((g) => ({ ...g, items: hold(g.items) }))
      .filter((g) => g.items.length > 0);
  }, [navigation, openDocument]);
}
