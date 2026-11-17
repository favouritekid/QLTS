// src/hooks/useServerFlagNavigation.ts
/**
 * Lọc thanh bên theo CỜ QUYỀN của máy chủ (F238, Codex lần 8; GĐ1b đặc tả §7 + bản 6 C2.1): mục mang `serverFlag` chỉ
 * hiện khi máy chủ trả cờ bật cho CHÍNH người gọi. Đang tải / lỗi mạng / 4xx / 5xx ⇒ ẨN (fail-closed — trang vẫn tự kiểm
 * cờ, máy chủ vẫn là chốt). Không suy theo vai.
 *
 * Mỗi cờ một endpoint, chỉ hỏi khi còn mục mang ĐÚNG cờ đó sau bộ lọc vai thô của `useAppNavigation`:
 *  - `council-documents` — `/quyen` (ít nhất một cờ bật);
 *  - `cross-review`      — `cross-review/eligibility` → `eligible`;
 *  - `document-batches`  — `bulk-verify/eligibility` → `eligible`.
 */
import { useMemo } from "react";

import { useCouncilDocumentPermissions } from "@/hooks/admin/useCouncilDocuments";
import { useBulkVerifyEligibility } from "@/hooks/document-review/useBulkVerify";
import { useCrossReviewEligibility } from "@/hooks/document-review/useCrossReview";
import type { NavGroup, NavItem, ServerNavFlag } from "@/types/navigation";

function hasFlag(items: NavItem[], flag: ServerNavFlag): boolean {
  return items.some((i) => i.serverFlag === flag || (i.children ? hasFlag(i.children, flag) : false));
}

export function useServerFlagNavigation(navigation: NavGroup[]): NavGroup[] {
  const needs = (flag: ServerNavFlag) => navigation.some((g) => hasFlag(g.items, flag));

  const document = useCouncilDocumentPermissions({ enabled: needs("council-documents") });
  const cross = useCrossReviewEligibility({ enabled: needs("cross-review") });
  const bulk = useBulkVerifyEligibility({ enabled: needs("document-batches") });

  const openDocument =
    document.state === "ready" && Object.values(document.permissions).some((v) => v === true);
  // `isSuccess` false khi đang tải HOẶC lỗi (kể cả lỗi khi làm mới sau một lần thành công) ⇒ ẩn.
  const openCross = cross.isSuccess && cross.data.eligible === true;
  const openBulk = bulk.isSuccess && bulk.data.eligible === true;

  return useMemo(() => {
    const open: Record<ServerNavFlag, boolean> = {
      "council-documents": openDocument,
      "cross-review": openCross,
      "document-batches": openBulk,
    };
    const hold = (items: NavItem[]): NavItem[] =>
      items
        .filter((i) => i.serverFlag === undefined || open[i.serverFlag])
        .map((i) => (i.children ? { ...i, children: hold(i.children) } : i));
    return navigation
      .map((g) => ({ ...g, items: hold(g.items) }))
      .filter((g) => g.items.length > 0);
  }, [navigation, openDocument, openCross, openBulk]);
}
