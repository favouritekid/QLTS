/**
 * useOverviewUrlState — URL là NGUỒN TRẠNG THÁI cho trang Tổng quan tuyển sinh.
 *
 * Bộ điều khiển của trang (tab · năm · đợt · đơn vị · nhóm · kỳ · tuần · heatmap)
 * được lưu trên query-string, KHÔNG mirror vào useState → deep-link, reload và
 * Back/Forward khôi phục cùng một lát dữ liệu, không có vòng lặp state ↔ URL.
 *
 *   - Đọc: derive thẳng từ `useSearchParams()` (parse theo allowlist, sai → fallback).
 *   - Ghi: `window.history.pushState` cho điều hướng CHỦ ĐÍCH (Back/Forward bước qua
 *     từng thay đổi), `replaceState` cho canonicalize/dọn mặc định. Next.js patch hai
 *     hàm này nên `useSearchParams`/`usePathname` tự đồng bộ (không refetch RSC).
 *
 * Ba helper thuần (parse · canonicalize · resolveApiUnitId) tách riêng để unit-test
 * đúng các guardrail rủi ro nhất (round-theo-năm, khóa unit manager, bootstrap scope).
 */
"use client";

import { usePathname, useSearchParams } from "next/navigation";
import * as React from "react";

import type { Period } from "@/app/(dashboard)/reports/admissions-weekly/_components/WeeklyReportTable";
import type { ReportGroupBy } from "@/lib/zod/reports";

export const CURRENT_YEAR = new Date().getFullYear();
export const ALL_ROUNDS = "__all__";
export const ALL_UNITS = "__all__";

export type OverviewTab = "exec" | "analysis";
export type HeatmapTab = "profiles" | "fee" | "enrolled";

const TABS = ["exec", "analysis"] as const;
const GROUP_BYS = ["major", "officer"] as const;
const PERIODS = ["week", "ytd"] as const;
const HEATMAPS = ["profiles", "fee", "enrolled"] as const;

export interface OverviewUrlState {
  tab: OverviewTab;
  year: number;
  /** ALL_ROUNDS hoặc mã đợt thô — tính hợp lệ theo NĂM kiểm ở canonicalize. */
  round: string;
  /** ALL_UNITS hoặc chuỗi id đơn vị dương. */
  unit: string;
  groupBy: ReportGroupBy;
  period: Period;
  /** YYYY-MM-DD đã validate, hoặc undefined (mốc điều hướng tuần). */
  weekStart: string | undefined;
  heatmap: HeatmapTab;
}

// ---------------------------------------------------------------------------
// PARSE (allowlist + coerce + fallback) — thuần, test được
// ---------------------------------------------------------------------------

function pick<T extends string>(
  raw: string | null,
  allow: readonly T[],
  fallback: T,
): T {
  return raw != null && (allow as readonly string[]).includes(raw)
    ? (raw as T)
    : fallback;
}

function parseYear(raw: string | null, currentYear: number): number {
  if (!raw) return currentYear;
  const n = Number(raw);
  return Number.isInteger(n) && n >= 2000 && n <= 2100 ? n : currentYear;
}

function parseUnit(raw: string | null): string {
  if (!raw) return ALL_UNITS;
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? String(n) : ALL_UNITS;
}

function parseRound(raw: string | null): string {
  const v = raw?.trim();
  return v ? v : ALL_ROUNDS;
}

/** YYYY-MM-DD ĐÚNG lịch (loại 2026-02-31, 2026-13-01…). TZ-độc lập. */
function isValidYmd(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(`${s}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return false;
  return d.toISOString().slice(0, 10) === s;
}

function parseWeekStart(raw: string | null): string | undefined {
  if (!raw) return undefined;
  return isValidYmd(raw) ? raw : undefined;
}

export function parseOverviewParams(
  sp: URLSearchParams,
  currentYear: number = CURRENT_YEAR,
): OverviewUrlState {
  return {
    tab: pick(sp.get("tab"), TABS, "exec"),
    year: parseYear(sp.get("year"), currentYear),
    round: parseRound(sp.get("round")),
    unit: parseUnit(sp.get("unit")),
    groupBy: pick(sp.get("group_by"), GROUP_BYS, "major"),
    period: pick(sp.get("period"), PERIODS, "ytd"),
    weekStart: parseWeekStart(sp.get("week_start")),
    heatmap: pick(sp.get("heatmap"), HEATMAPS, "profiles"),
  };
}

// ---------------------------------------------------------------------------
// SERIALIZE — canonical: bỏ mặc định, LUÔN ghi year (share-link không đổi nghĩa
// khi sang năm mới)
// ---------------------------------------------------------------------------

export function serializeOverviewParams(s: OverviewUrlState): string {
  const p = new URLSearchParams();
  p.set("year", String(s.year)); // luôn ghi
  if (s.tab !== "exec") p.set("tab", s.tab);
  if (s.round !== ALL_ROUNDS) p.set("round", s.round);
  if (s.unit !== ALL_UNITS) p.set("unit", s.unit);
  if (s.groupBy !== "major") p.set("group_by", s.groupBy);
  if (s.period !== "ytd") p.set("period", s.period);
  if (s.weekStart) p.set("week_start", s.weekStart);
  if (s.heatmap !== "profiles") p.set("heatmap", s.heatmap);
  return p.toString();
}

// ---------------------------------------------------------------------------
// CANONICALIZE — sửa URL sai về hợp lệ (chỉ dùng cho replaceState, không request lỗi)
// ---------------------------------------------------------------------------

export interface CanonicalizeInputs {
  /** Catalog đợt đã đúng theo năm hiện tại (không phải placeholder năm cũ). */
  roundReady: boolean;
  roundCodes: readonly string[];
  /** Đã nhận response đầu (biết được scope người dùng). */
  scopeResolved: boolean;
  /** scope_unit_id của người dùng bị giới hạn (manager) — null nếu toàn quyền. */
  enforcedUnit: number | null;
}

/**
 * Trả về state đã chuẩn hoá (round hợp lệ theo năm; đơn vị của người dùng bị giới
 * hạn khóa về scope_unit_id). Giữ NGUYÊN tham chiếu nếu không có gì đổi để effect
 * so sánh rẻ và không ghi URL thừa.
 */
export function canonicalizeOverviewState(
  s: OverviewUrlState,
  i: CanonicalizeInputs,
): OverviewUrlState {
  let round = s.round;
  if (
    round !== ALL_ROUNDS &&
    i.roundReady &&
    !i.roundCodes.includes(round)
  ) {
    round = ALL_ROUNDS; // đợt không thuộc năm đã chọn → bỏ
  }

  let unit = s.unit;
  if (i.scopeResolved && i.enforcedUnit != null) {
    unit = String(i.enforcedUnit); // khóa manager về đơn vị của họ (bỏ unit lạ)
  }

  return round === s.round && unit === s.unit ? s : { ...s, round, unit };
}

// ---------------------------------------------------------------------------
// RESOLVE API UNIT — cái gì THỰC SỰ gửi cho backend (khác giá trị hiển thị)
// ---------------------------------------------------------------------------

/**
 * Đơn vị gửi vào query báo cáo. KHÔNG bao giờ gửi unit từ URL trước khi biết scope,
 * và không bao giờ gửi unit của URL cho người dùng bị giới hạn (backend đã scope
 * server-side khi bỏ trống) → tránh tái phát 404 với unit lạ.
 */
export function resolveApiUnitId(i: {
  scopeResolved: boolean;
  enforcedUnit: number | null;
  urlUnitId: number | undefined;
}): number | undefined {
  if (!i.scopeResolved) return undefined; // bootstrap: chưa biết scope
  if (i.enforcedUnit != null) return undefined; // bị giới hạn: BE tự scope
  return i.urlUnitId; // toàn quyền: tôn trọng URL
}

// ---------------------------------------------------------------------------
// SLICE-CURRENT — có được coi response (giữ bởi placeholderData:prev) là lát cắt
// HIỆN TẠI không. Phải khớp năm·đợt·đơn-vị VÀ scope + catalog đợt đã sẵn sàng
// (nếu không, deep-link có đơn-vị/đợt lúc bootstrap sẽ hiện báo cáo toàn-trường /
// toàn-năm như dữ liệu thật). Thuần — test được.
// ---------------------------------------------------------------------------

export interface SliceEcho {
  academic_year: number;
  round_code: string | null;
  scope_unit_id: number | null;
}

export function isSliceCurrent(
  d: SliceEcho | undefined,
  expected: {
    year: number;
    round: string | null; // giá trị round_code KỲ VỌNG (null = mọi đợt)
    unit: number | null; // scope_unit_id KỲ VỌNG (gồm manager bị ép)
    scopeResolved: boolean; // đã học được scope người dùng chưa
    roundResolved: boolean; // đợt = ALL, hoặc mã đợt đã có trong catalog năm
  },
): boolean {
  return (
    !!d &&
    expected.scopeResolved &&
    expected.roundResolved &&
    d.academic_year === expected.year &&
    (d.round_code ?? null) === expected.round &&
    (d.scope_unit_id ?? null) === expected.unit
  );
}

/** Nhãn scope cho nút Xuất Excel — derive từ BỘ LỌC (scope) hiện tại, KHÔNG từ
 *  response (response có thể trễ/toàn-trường lúc bootstrap → nhãn nhảy sai). */
export function describeExportScope(
  unitId: number | null,
  units: readonly { id: number; name: string }[],
): string {
  if (unitId == null) return "toàn trường";
  return units.find((u) => u.id === unitId)?.name ?? `đơn vị #${unitId}`;
}

// ---------------------------------------------------------------------------
// HOOK
// ---------------------------------------------------------------------------

export interface UseOverviewUrlState {
  state: OverviewUrlState;
  /** Ghi 1 phần state — pushState (điều hướng chủ đích) mặc định. */
  patch: (p: Partial<OverviewUrlState>, opts?: { replace?: boolean }) => void;
  /** Ghi toàn bộ state — dùng cho canonicalize (replace). */
  commit: (next: OverviewUrlState, opts?: { replace?: boolean }) => void;
  /** Query-string thô hiện tại (để so với dạng canonical mà làm sạch URL). */
  search: string;
}

export function useOverviewUrlState(): UseOverviewUrlState {
  const searchParams = useSearchParams();
  const pathname = usePathname();

  const state = React.useMemo(
    () => parseOverviewParams(searchParams, CURRENT_YEAR),
    [searchParams],
  );

  const commit = React.useCallback(
    (next: OverviewUrlState, opts?: { replace?: boolean }) => {
      const qs = serializeOverviewParams(next);
      const url = qs ? `${pathname}?${qs}` : pathname;
      if (opts?.replace) window.history.replaceState(null, "", url);
      else window.history.pushState(null, "", url);
    },
    [pathname],
  );

  const patch = React.useCallback(
    (p: Partial<OverviewUrlState>, opts?: { replace?: boolean }) => {
      commit({ ...state, ...p }, opts);
    },
    [state, commit],
  );

  return { state, patch, commit, search: searchParams.toString() };
}
