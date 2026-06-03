# QLTS — Bộ chuẩn tương tác Mobile (Mobile Interaction Design System)

> **Trạng thái:** Đề xuất / Kim chỉ nam (v1, 2026-05-27)
> **Phạm vi:** Drawer · Navigation · Sheet · Dialog · Action sheet · Popover · Toast · Form trên frontend (Next.js + React + Tailwind + Radix UI).
> **Mục tiêu:** Thống nhất hành vi overlay + trải nghiệm vuốt-chạm (gesture) cho QLTS theo chuẩn iOS HIG / Material 3 và cách các hệ thống lớn (Linear, Vercel, Family) vận hành — để các lỗi kiểu "bottom nav che nội dung" không tái diễn và mọi surface có cảm giác native.
>
> Tài liệu này là **chuẩn để tham chiếu khi build/refactor**, không phải nhật ký triển khai. Khi thực thi, mỗi PR phải link về mục tương ứng ở đây.

---

## 0. TL;DR cho người vội

1. **Mobile bottom overlay = Vaul drawer** (drag-handle thật + swipe-to-dismiss + snap-points), KHÔNG phải Radix `Sheet side="bottom"` trang trí như hiện tại.
2. **Một thang elevation duy nhất** qua token `--z-*`; cấm rải `z-[40/50/60]` thủ công.
3. **Bottom nav ẩn khi có overlay** (đã ship ở branch `fix/mobile-bottom-nav-overlap`) — overlay phủ/thay nav, không bao giờ ngược lại.
4. **Form mobile**: CTA `sticky` (KHÔNG `fixed`), input ≥16px (đã có), padding safe-area, keyboard-aware.
5. **Confirm dialog KHÔNG swipe-dismiss** (tránh xác nhận nhầm). Snap-points KHÔNG dùng cho form nhiều bước chưa guard mất dữ liệu.

---

## 1. Hiện trạng (baseline — từ audit codebase 2026-05-27)

### Đã có (khai thác được ngay)
- Radix `Dialog` / `AlertDialog` / `Sheet` (4 side), `Popover`, `DropdownMenu`, `Tooltip`, `Select`, `cmdk` CommandPalette.
- `ResponsiveDialog` — tự đổi **Dialog (desktop) ↔ Sheet side=bottom (mobile)** qua `useIsMobile()`.
- `sonner` (toast) — **cùng tác giả với Vaul (Emil Kowalski)** → triết lý đồng nhất.
- `react-swipeable` + `useSwipeNavigation` + `SwipeableContainer`/`SwipeableTabs`/`DismissibleContainer` — nhưng **chỉ dùng cho tab/card nav**, không cho overlay.
- `framer-motion` v12 (dùng tối thiểu), `@dnd-kit` (kanban).
- Token nền: `--touch-target-*`, `--safe-area-*`, `--bottom-nav-height(-safe)`, `--input-height-mobile`, `--input-font-mobile`, `--dialog-max-height-mobile`, `--sheet-width-mobile`.

### Thiếu / nợ kỹ thuật
- ❌ **Không có swipe-to-dismiss / drag-handle chức năng / snap-points** trên bất kỳ sheet nào. Drag-handle hiện tại (`w-10 h-1` bar) **chỉ trang trí**, không gắn event. Sheet đóng chỉ bằng nút X / nút action.
- ❌ Chưa cài `vaul`. Chưa có `components/ui/drawer.tsx`.
- ⚠️ **Thang z-index `--z-*` đã định nghĩa trong `foundation.css` nhưng KHÔNG component nào dùng** — code rải `z-10/30/40/50/60` thủ công. Đây là nguồn gốc lớp lỗi "nav che overlay/chrome".
- ⚠️ Mobile sidebar (menu chính) là custom `fixed aside + translate + scrim` thủ công, không phải Radix/Vaul → không có swipe-close.
- ⚠️ Form: chưa có pattern sticky-CTA / keyboard-aware chuẩn; nút submit nằm trong footer cuộn theo content.

---

## 2. Nguyên tắc (5 trụ)

| # | Nguyên tắc | Diễn giải |
|---|-----------|-----------|
| P1 | **Touch-first, gesture-native** | Overlay trượt từ đáy PHẢI có drag-handle chức năng + swipe-to-dismiss; cái cần đa độ cao thì có snap-points (detents). Theo kỳ vọng iOS/Android. |
| P2 | **Một thang elevation** | Mọi layer dùng token `--z-*`. Cấm số z tùy biến. Overlay luôn > app-chrome. |
| P3 | **Surface đúng ngữ cảnh** | Sheet = tác vụ phụ giữ ngữ cảnh; Full-screen = workflow nhiều bước cần tập trung; Dialog = xác nhận ngắn hủy được. |
| P4 | **Motion có chủ đích** | Spring cho drawer, ease-out cho dialog, duration ngắn; LUÔN tôn trọng `prefers-reduced-motion`. |
| P5 | **An toàn bàn phím & safe-area** | CTA `sticky` (không `fixed`); input ≥16px; padding `env(safe-area-inset-*)`; không để bàn phím che CTA. |

---

## 3. Ma trận surface (chuẩn quyết định)

| Surface | Mobile (<lg) | Desktop (≥lg) | Gesture | Khi dùng | Khi KHÔNG dùng |
|---------|--------------|---------------|---------|----------|----------------|
| **Nav drawer** (menu chính) | trượt trái + scrim | sidebar cố định | swipe-close, scrim-tap, Esc | điều hướng cấp app | tác vụ/nội dung |
| **Bottom Sheet** (filter, action, detail nhẹ, issue) | **Vaul drawer** đáy: drag-handle + swipe-dismiss + (tùy) snap | Dialog giữa HOẶC side-panel | drag-to-dismiss + snap-points | tác vụ phụ giữ ngữ cảnh, danh sách lựa chọn | workflow dài, nhập liệu phức tạp dễ mất data |
| **Full-screen sheet** (sửa hồ sơ tuyển sinh nhiều bước) | full-screen + header back | inline panel/page | swipe-back (dùng `useSwipeNavigation`) | nhiều bước cần tập trung | tác vụ ngắn |
| **Dialog / Alert** | centered, edge-pad 16px | centered | tap-scrim / Esc — **KHÔNG swipe** | xác nhận, cảnh báo, lỗi hủy được | nội dung dài/cuộn nhiều |
| **Action sheet** | Vaul đáy list | DropdownMenu | drag-close | menu ngữ cảnh (3 chấm) | >7 mục (chuyển full sheet) |
| **Popover / Tooltip / Select** | giữ Radix nguyên | giữ Radix | — | overlay nhỏ neo trigger | nội dung lớn |
| **Toast** | Sonner | Sonner | swipe-dismiss (Sonner sẵn) | phản hồi tạm thời | thông tin cần hành động |
| **Bottom nav** | hiện; **ẩn khi có overlay** | `lg:hidden` | — | điều hướng chính 4–5 mục | — |

> **Quy tắc vàng (đã enforce):** Khi BẤT KỲ overlay nào mở (nav drawer hoặc Radix sheet/dialog) → **bottom nav ẩn**. Phát hiện qua `document.body[data-scroll-locked]` (Radix tự set) + cờ `isSidebarCollapsed`. Overlay > nav, không bao giờ ngược lại (Material 3).

---

## 4. Thang elevation / z-index (chuẩn hóa)

**Bỏ** mọi `z-[n]` thủ công; dùng token. Thang canonical (giá trị giữ tương thích Radix `z-50` mặc định bằng cách dùng bội số rõ ràng):

| Lớp | Token đề xuất | Ví dụ thành phần |
|-----|---------------|------------------|
| Base content | (auto) | nội dung trang |
| Sticky trong trang | `--z-sticky` (10) | table header dính, sticky section |
| Bottom nav (app chrome) | `--z-nav` (20) | `MobileBottomNav` |
| Header / page action bar | `--z-header` (30) | `Header`, `AdmissionActions` |
| Scrim overlay | `--z-scrim` (40) | nền tối drawer |
| Drawer / Sheet | `--z-drawer` (50) | Vaul drawer, Radix Sheet, sidebar |
| Dialog / Alert | `--z-dialog` (60) | confirm, form modal |
| Popover/Dropdown/Tooltip/Select | `--z-popover` (70) | overlay neo trigger (nổi trên dialog) |
| Toast | `--z-toast` (80) | Sonner (cao nhất) |

**Ghi chú quan trọng:**
- Token `--z-*` cũ trong `foundation.css` (dropdown:50…toast:700) **đang không dùng** và lệch magnitude với code (`z-40/50/60`). PR elevation phải **thống nhất về 1 thang** (giữ tên rõ nghĩa như trên) và refactor toàn bộ raw z hiện có.
- Vì nav (`--z-nav` 20) thấp hơn overlay, đáng lẽ overlay tự phủ nav. NHƯNG cơ chế hiện tại là **ẩn nav khi overlay mở** (an toàn hơn, tránh nav "ló" mép). Giữ cả hai: thang z đúng + ẩn nav. (Đây là lý do `z-[60]` cũ gây bug — nav cao hơn cả overlay.)

---

## 5. Quy tắc gesture (vuốt-chạm)

| Gesture | Áp dụng cho | Spec | Nguồn |
|---------|-------------|------|-------|
| **Swipe-to-dismiss (xuống)** | Bottom sheet, action sheet | drag-handle kéo xuống quá ngưỡng velocity/khoảng cách → đóng; dưới ngưỡng → bật về | Vaul mặc định |
| **Drag-to-resize / snap-points** | Sheet cần nhiều độ cao (vd lead detail: preview → nửa → full) | `snapPoints` mảng; preview ~peek, half, full | Vaul `snapPoints` |
| **Swipe-close (trái)** | Nav drawer | kéo về phía cạnh xuất phát → đóng | Vaul side / custom |
| **Swipe-back** | Full-screen detail | vuốt từ mép trái → quay lại | `useSwipeNavigation` (đã có) |
| **Swipe-dismiss toast** | Sonner | sẵn có | Sonner |
| **Tap-scrim / Esc** | Mọi overlay | luôn có như fallback của gesture | Radix/Vaul |

**Ngưỡng & cảm giác:** dùng default của Vaul (physics-based) trừ khi đo trên iPhone SE thấy cần tinh chỉnh. Mọi gesture phải có **fallback không-gesture** (nút X / Esc / scrim) cho accessibility.

---

## 6. Quy tắc Motion

- **Durations**: micro (~120ms), standard (~200–250ms), drawer spring (Vaul default). Thêm token `--duration-fast/base/slow` + `--ease-standard/emphasized`.
- **Drawer/sheet**: spring (đã có trong Vaul). **Dialog**: scale+fade ease-out. **Toast**: slide+fade.
- **`prefers-reduced-motion`**: tắt transform-heavy animation, chỉ giữ opacity tối giản. `useSwipeNavigation` đã tôn trọng điều này — áp cùng nguyên tắc cho overlay.
- Tham chiếu: [Emil Kowalski — Great animations](https://emilkowal.ski/ui/great-animations).

---

## 7. Quy tắc Form trên mobile

| Quy tắc | Chi tiết | Trạng thái QLTS |
|---------|----------|-----------------|
| Input ≥16px | chống iOS auto-zoom | ✅ `--input-font-mobile: 1rem` + `input.tsx text-[16px]` |
| Touch height ≥44px | dễ chạm | ✅ `--input-height-mobile: 2.75rem` |
| CTA submit **sticky** (KHÔNG `fixed`) | `fixed` vỡ với bàn phím iOS | ❌ cần chuẩn hóa |
| Padding safe-area đáy | tránh home indicator | ⚠️ rải rác |
| Keyboard-aware | input focus không bị bàn phím che; ưu tiên field + CTA ở trên | ❌ cần pattern |
| `inputMode`/`type` đúng | hiện bàn phím phù hợp (tel/email/number) | ⚠️ kiểm tra từng field |
| Lỗi hiển thị inline gần field | không chỉ toast | ✅ react-hook-form |

Nguồn: [web.dev sign-in form](https://web.dev/articles/sign-in-form-best-practices) · [Zuko mobile form UX](https://www.zuko.io/blog/8-tips-to-optimize-your-mobile-form-ux).

---

## 8. Quyết định thư viện

**Thêm `vaul`** (shadcn `Drawer`) làm primitive cho mọi mobile bottom overlay.

Lý do:
- Cùng tác giả & triết lý với `sonner` (đã dùng) → nhất quán.
- **Dựa trên Radix Dialog** → tương thích ngược: focus-trap, scroll-lock, `data-scroll-locked` (cơ chế ẩn nav đang dùng), portal, a11y giữ nguyên.
- Cung cấp sẵn drag-handle chức năng + swipe-dismiss + snap-points + nested drawers + background-scaling — thứ đang phải tự code.
- Là pattern các hệ thống lớn (Linear, Vercel, Family) dùng.

Tham chiếu: [shadcn Drawer (vaul)](https://ui.shadcn.com/docs/components/radix/drawer) · [Drawer + snap points](https://www.shadcn.io/patterns/drawer-bottom-4).

**Giữ nguyên:** Radix Dialog/AlertDialog (desktop modal + confirm), Popover/Tooltip/Select/Dropdown, cmdk, Sonner, `@dnd-kit` (kanban), `react-swipeable` (swipe-back/tabs).

---

## 9. Kế hoạch migration (phân tầng — blast radius tăng dần)

> Mỗi tầng = 1 PR riêng. KHÔNG gộp với branch `fix/mobile-bottom-nav-overlap` (đang gần ship).

- **P0 — Prototype 1 surface (đo cảm giác trước khi cam kết)**
  Cài `vaul` + tạo `components/ui/drawer.tsx`. Migrate **đúng MỘT** surface rủi ro thấp — **`MobileFilterSheet` hoặc `MobileActionSheet`** — sang Vaul. Browser-smoke iPhone SE: drag/swipe/snap thật. Mục tiêu: validate thư viện + cảm giác, CHƯA đụng `ResponsiveDialog`.

- **P1 — Elevation chuẩn hóa (PR riêng)**
  Định nghĩa thang `--z-*` (mục 4), refactor raw z toàn dashboard. Cross-route smoke. (Có thể đi kèm P0 nếu phạm vi đủ hẹp; mặc định tách riêng vì blast radius lớn.)

- **P2 — Nâng `ResponsiveDialog` → Vaul** (sau khi P0 xanh)
  Đổi nhánh mobile của `ResponsiveDialog` từ `Sheet` sang Drawer → **mọi** consumer kế thừa gesture mà không sửa từng cái. Audit lại từng consumer.

- **P3 — Migrate phần còn lại có guard**
  `MobileIssueDrawer`, lead-detail sheet (+ snap-points preview→full), nav drawer (swipe-close). Form chuẩn (sticky CTA, keyboard-aware). Motion tokens. Swipe-back full-screen.

- **P4 — Polish & a11y**
  Reduced-motion sweep, fallback không-gesture cho mọi overlay, (tùy) pull-to-refresh.

---

## 10. Acceptance criteria (kiểm thử được)

Mỗi PR áp dụng chuẩn này phải pass các tiêu chí liên quan, verify trên **iPhone SE (375×667) + iPhone 13 (390×844)** bằng device emulation thật:

1. **Không occlusion**: ở 375px, không phần tử nội dung/CTA nào bị bottom nav hay overlay khác che (đo `getBoundingClientRect`).
2. **Gesture**: mọi bottom sheet đóng được bằng **vuốt xuống**; snap-point (nếu có) chuyển mượt; luôn còn fallback X/Esc/scrim.
3. **Nav behavior**: mở bất kỳ overlay → bottom nav ẩn; đóng → hiện lại (round-trip).
4. **Z-index**: không còn `z-[n]` thủ công trong file đã refactor; toast > popover > dialog > drawer > scrim > header > nav.
5. **Form/keyboard**: với bàn phím mở, CTA submit vẫn chạm tới; CTA dùng `sticky` không `fixed`; input không trigger auto-zoom (≥16px).
6. **Safe-area**: padding đáy tôn trọng `env(safe-area-inset-bottom)` (notch/home indicator).
7. **Reduced-motion**: bật `prefers-reduced-motion` → không transform giật, chỉ opacity.
8. **A11y**: focus-trap trong overlay; trả focus về trigger khi đóng; overlay có `aria-label`/`Description`.
9. **Desktop regression**: ≥lg không đổi hành vi (drawer→dialog/panel, nav ẩn).
10. **Gate**: type-check + lint + vitest xanh (chạy với host `src` mount, KHÔNG dùng image stale).

---

## 11. KHÔNG LÀM (Non-goals — ràng buộc bắt buộc)

> Phần này quan trọng ngang phần "làm". Vi phạm = reject PR.

1. **KHÔNG migrate toàn bộ sheet một lượt.** Đi từng tầng (P0→P4), mỗi tầng smoke + gate riêng. Một "big-bang refactor" mọi overlay là chống chỉ định.
2. **KHÔNG đổi confirm/alert dialog sang swipe-dismiss.** Xác nhận (xóa, hủy, ghi đè) phải cần hành động chủ đích (nút/Esc/scrim-tap) — swipe dễ gây xác nhận nhầm, mất an toàn.
3. **KHÔNG dùng snap-points cho form nhiều bước nếu chưa guard mất dữ liệu.** Sheet nhập liệu phức tạp mà cho kéo-đóng tự do sẽ làm mất nhập liệu chưa lưu. Phải có unsaved-guard (dialog "Ở lại/Rời đi") TRƯỚC khi cho gesture-dismiss, hoặc dùng full-screen sheet thay vì bottom sheet.
4. **KHÔNG tự ý đổi thang z-index lẻ tẻ trong feature PR.** Elevation chỉ refactor trong PR P1 chuyên trách (blast radius lớn).
5. **KHÔNG bỏ fallback không-gesture.** Mọi overlay vẫn phải đóng được bằng nút X / Esc / scrim cho người không dùng/không thể dùng gesture (a11y).
6. **KHÔNG gộp công việc design-system này vào branch `fix/mobile-bottom-nav-overlap`.** Branch đó chỉ giữ fix occlusion (đã gate xanh), ship như PR độc lập.

---

## 12. Liên hệ với fix đang chờ ship

Branch `fix/mobile-bottom-nav-overlap` (PR riêng, gate xanh) đã hiện thực sẵn 2 nguyên tắc của chuẩn này:
- **Quy tắc vàng mục 3** (nav ẩn khi overlay mở) — qua `body[data-scroll-locked]` observer.
- Tinh thần **P2 motion/elevation** (page chrome offset trên nav qua `--bottom-nav-height-safe`).

Doc này mở rộng thành chuẩn đầy đủ; fix đó là điểm khởi đầu hợp lệ, không mâu thuẫn.

---

## Nguồn tham khảo
- [Material 3 — Navigation bar guidelines](https://m3.material.io/components/navigation-bar/guidelines)
- [Apple HIG — Sheets](https://developer.apple.com/design/human-interface-guidelines/components/presentation/sheets/)
- [Bottom sheets vs full screens](https://medium.com/@sammi121313/when-to-use-bottom-sheets-vs-full-screens-a5a2393878c5)
- [shadcn Drawer (vaul)](https://ui.shadcn.com/docs/components/radix/drawer) · [Drawer snap points](https://www.shadcn.io/patterns/drawer-bottom-4)
- [Emil Kowalski — Great animations](https://emilkowal.ski/ui/great-animations) · [emilkowal.ski](https://emilkowal.ski/)
- [web.dev — Sign-in form best practices](https://web.dev/articles/sign-in-form-best-practices) · [Zuko — Mobile form UX](https://www.zuko.io/blog/8-tips-to-optimize-your-mobile-form-ux)
