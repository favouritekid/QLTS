/**
 * useAdmissionPaths Hook Tests
 *
 * BUG-01 regression test: useUpdatePathDocuments must NOT write
 * ResolvedDocumentListResponse into the detail cache (which expects
 * AdmissionPathResponse). The fix replaced setQueryData with
 * invalidateQueries for the detail key.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { createTestQueryClient } from "@/test/utils/test-utils";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  useUpdatePathDocuments,
  useCreateAdmissionPath,
  useUpdateAdmissionPath,
  useUpdateCriteria,
  useActivateAdmissionPath,
  useDeactivateAdmissionPath,
  admissionPathKeys,
} from "./useAdmissionPaths";
import { quotaMatrixKeys } from "./useQuotaMatrix";
import type { AdmissionPathResponse, ResolvedDocumentListResponse } from "@/lib/zod/admission-path";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_PATH_ID = 42;

/** A minimal AdmissionPathResponse to pre-seed the detail cache. */
// Use ``satisfies`` instead of ``: AdmissionPathResponse`` annotation —
// the explicit-annotation form triggered TS2739 "missing properties"
// for the 3 phase1_03 fields (``applicable_to`` / ``method_quota`` /
// ``bonus_rule_override``) even though they are present in the literal.
// Symptom only manifests on CI runner; test-debt fix 2026-05-08 swap
// to ``satisfies`` to widen literal-narrowing while still type-checking
// the shape against ``AdmissionPathResponse``.
const mockAdmissionPathResponse = {
  id: MOCK_PATH_ID,
  academic_info_id: 1,
  admission_method_id: 1,
  status: "draft" as const,
  display_name: "Test Path",
  display_order: 1,
  visibility: "public" as const,
  activated_at: null,
  // Mirror BE Pydantic UserNested shape (admission_path.py:499). FE Zod
  // schema yêu cầu nested object, không phải scalar id.
  activator: null,
  // Phase 2 v8.2 — derived flag từ application_fee > 0.
  requires_application_fee: false,
  created_at: "2025-06-01T00:00:00+00:00",
  updated_at: "2025-06-01T00:00:00+00:00",
  academic_info: null,
  admission_method: null,
  criteria: null,
  available_actions: [] as string[],
  can_edit: true,
  can_activate: false,
  // PR matrix-funnel — governance gate flag (admin-only). Default false
  // mirrors BE for a fresh path created by a non-admin context.
  can_edit_governance: false,
  validation_errors: [] as string[],
  // PR #6: strict submit gate per path; default False in the fixture
  // mirrors the backend default for newly-created paths.
  allow_unverified_submission: false,
  // Minor-correction allowlist — empty by default for fresh paths
  // (admin opts in field-by-field after path creation).
  minor_correction_allowed_fields: [] as string[],
  // phase1_03 (#184 Wave 1 PR-1B') — 3 new fields shipped in BE
  // PR #206 + Zod parse parity. Defaults mirror BE Create behavior:
  // null for all three (= legacy / no audience filter / no method
  // cap / inherit method bonus default). Fixture must include them
  // because Response schema marks them REQUIRED no-default to
  // catch BE-forgot-to-emit drift.
  applicable_to: null,
  method_quota: null,
  bonus_rule_override: null,
  // Phase 2 v8.2 PR-2B/2C — quota fields + admission_round_id (NOT NULL).
  admission_round_id: 1,
  round_quota: null,
  admit_quota: null,
  submission_count: 0,
  application_fee: null,
} satisfies AdmissionPathResponse;

/** The shape that PUT /paths/:id/documents returns. */
const mockDocumentsResponse: ResolvedDocumentListResponse = {
  path_id: MOCK_PATH_ID,
  offering_type_id: 1,
  admission_method_id: 1,
  documents: [
    {
      document_type_id: 10,
      document_type_code: "CMND",
      document_type_name: "CMND/CCCD",
      is_mandatory: true,
      requires_upload: true,
      submission_format: null,
      display_order: 1,
      source: "shared",
      applicable_audience: null,
      layer_kind: "shared_base",
    },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Creates a wrapper that exposes the QueryClient so tests can inspect caches.
 */
function createWrapperWithClient() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return { queryClient, Wrapper };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useAdmissionPaths – BUG-01 regression", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("useUpdatePathDocuments", () => {
    it("should NOT write ResolvedDocumentListResponse into the detail cache", async () => {
      // --- Arrange -----------------------------------------------------------
      // MSW handler: PUT /paths/:id/documents returns the documents shape
      server.use(
        http.put(
          `${API_BASE_URL}/api/admission-config/paths/:pathId/documents`,
          () => {
            return HttpResponse.json(mockDocumentsResponse);
          }
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();

      // Pre-seed the detail cache with a proper AdmissionPathResponse
      const detailKey = admissionPathKeys.detail(MOCK_PATH_ID);
      queryClient.setQueryData(detailKey, mockAdmissionPathResponse);

      // Sanity: the detail cache holds AdmissionPathResponse before mutation
      const cacheBeforeMutation = queryClient.getQueryData(detailKey);
      expect(cacheBeforeMutation).toEqual(mockAdmissionPathResponse);

      // --- Act ---------------------------------------------------------------
      const { result } = renderHook(() => useUpdatePathDocuments(), {
        wrapper: Wrapper,
      });

      act(() => {
        result.current.mutate({
          pathId: MOCK_PATH_ID,
          data: [
            {
              document_type_id: 10,
              is_mandatory: true,
              requires_upload: true,
              display_order: 1,
            },
          ],
        });
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      // --- Assert ------------------------------------------------------------
      const cacheAfterMutation = queryClient.getQueryData(detailKey);

      // The detail cache must NOT contain the documents response shape.
      // If the bug existed, cacheAfterMutation would be mockDocumentsResponse.
      expect(cacheAfterMutation).not.toEqual(mockDocumentsResponse);

      // More specifically: if the cache still has data, it must have `id`
      // (AdmissionPathResponse) and NOT have `documents` array at the top level.
      if (cacheAfterMutation != null) {
        const cached = cacheAfterMutation as Record<string, unknown>;
        // AdmissionPathResponse has `id`, ResolvedDocumentListResponse has `path_id`
        expect(cached).not.toHaveProperty("path_id");
        expect(cached).not.toHaveProperty("documents");
      }
    });

    it("should invalidate the detail cache (not set it directly)", async () => {
      server.use(
        http.put(
          `${API_BASE_URL}/api/admission-config/paths/:pathId/documents`,
          () => {
            return HttpResponse.json(mockDocumentsResponse);
          }
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();

      // Pre-seed the detail cache
      const detailKey = admissionPathKeys.detail(MOCK_PATH_ID);
      queryClient.setQueryData(detailKey, mockAdmissionPathResponse);

      // Spy on invalidateQueries to confirm it is called
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(() => useUpdatePathDocuments(), {
        wrapper: Wrapper,
      });

      act(() => {
        result.current.mutate({
          pathId: MOCK_PATH_ID,
          data: [
            {
              document_type_id: 10,
              is_mandatory: true,
              requires_upload: true,
              display_order: 1,
            },
          ],
        });
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      // invalidateQueries should have been called for the detail key
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: admissionPathKeys.detail(MOCK_PATH_ID),
        })
      );

      invalidateSpy.mockRestore();
    });

    it("should invalidate the documents cache", async () => {
      server.use(
        http.put(
          `${API_BASE_URL}/api/admission-config/paths/:pathId/documents`,
          () => {
            return HttpResponse.json(mockDocumentsResponse);
          }
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();

      // Pre-seed the documents cache
      const documentsKey = admissionPathKeys.documents(MOCK_PATH_ID);
      queryClient.setQueryData(documentsKey, mockDocumentsResponse.documents);

      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(() => useUpdatePathDocuments(), {
        wrapper: Wrapper,
      });

      act(() => {
        result.current.mutate({
          pathId: MOCK_PATH_ID,
          data: [
            {
              document_type_id: 10,
              is_mandatory: true,
              requires_upload: true,
              display_order: 1,
            },
          ],
        });
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      // documents cache should be invalidated
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: admissionPathKeys.documents(MOCK_PATH_ID),
        })
      );

      invalidateSpy.mockRestore();
    });

    it("invalidates admission-paths root and quota-matrix caches", async () => {
      server.use(
        http.put(
          `${API_BASE_URL}/api/admission-config/paths/:pathId/documents`,
          () => HttpResponse.json(mockDocumentsResponse),
        ),
      );

      const { queryClient, Wrapper } = createWrapperWithClient();
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      const { result } = renderHook(() => useUpdatePathDocuments(), {
        wrapper: Wrapper,
      });

      act(() => {
        result.current.mutate({
          pathId: MOCK_PATH_ID,
          data: [
            {
              document_type_id: 10,
              is_mandatory: true,
              requires_upload: true,
              display_order: 1,
            },
          ],
        });
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: admissionPathKeys.all }),
      );
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({ queryKey: quotaMatrixKeys.all }),
      );

      invalidateSpy.mockRestore();
    });

    it("should NOT call setQueryData for the detail key", async () => {
      server.use(
        http.put(
          `${API_BASE_URL}/api/admission-config/paths/:pathId/documents`,
          () => {
            return HttpResponse.json(mockDocumentsResponse);
          }
        )
      );

      const { queryClient, Wrapper } = createWrapperWithClient();

      // Pre-seed the detail cache
      const detailKey = admissionPathKeys.detail(MOCK_PATH_ID);
      queryClient.setQueryData(detailKey, mockAdmissionPathResponse);

      // Spy on setQueryData AFTER pre-seeding
      const setQueryDataSpy = vi.spyOn(queryClient, "setQueryData");

      const { result } = renderHook(() => useUpdatePathDocuments(), {
        wrapper: Wrapper,
      });

      act(() => {
        result.current.mutate({
          pathId: MOCK_PATH_ID,
          data: [
            {
              document_type_id: 10,
              is_mandatory: true,
              requires_upload: true,
              display_order: 1,
            },
          ],
        });
      });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));

      // setQueryData should NOT have been called with the detail key
      // (This is the core BUG-01 assertion: the old code did setQueryData(detail, result))
      const detailSetCalls = setQueryDataSpy.mock.calls.filter(
        ([key]) => JSON.stringify(key) === JSON.stringify(detailKey)
      );
      expect(detailSetCalls).toHaveLength(0);

      setQueryDataSpy.mockRestore();
    });
  });
});

describe("useUpdateAdmissionPath – matrix cache parity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function arrangeUpdateHandler() {
    server.use(
      http.put(`${API_BASE_URL}/api/admission-config/paths/:pathId`, () =>
        HttpResponse.json(mockAdmissionPathResponse),
      ),
    );
  }

  it("keeps detail cache fresh and invalidates admission-paths root", async () => {
    arrangeUpdateHandler();
    const { queryClient, Wrapper } = createWrapperWithClient();
    const setQueryDataSpy = vi.spyOn(queryClient, "setQueryData");
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useUpdateAdmissionPath(), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.mutate({
        pathId: MOCK_PATH_ID,
        data: { display_name: "Updated Path" },
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(setQueryDataSpy).toHaveBeenCalledWith(
      admissionPathKeys.detail(MOCK_PATH_ID),
      mockAdmissionPathResponse,
    );
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: admissionPathKeys.all }),
    );

    setQueryDataSpy.mockRestore();
    invalidateSpy.mockRestore();
  });

  it("invalidates the quota-matrix cache after identity/governance updates", async () => {
    arrangeUpdateHandler();
    const { queryClient, Wrapper } = createWrapperWithClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useUpdateAdmissionPath(), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.mutate({
        pathId: MOCK_PATH_ID,
        data: { visibility: "internal" },
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: quotaMatrixKeys.all }),
    );

    invalidateSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// useCreateAdmissionPath — cache parity (PR-2 follow-up, finding P1 #2)
//
// Sau khi PR-2 gỡ lối cũ, màn Phase 3 sống bằng quotaMatrixKeys (ByMajor/Global)
// + admissionPathKeys.coverageMatrix (readiness). Quick-create path PHẢI
// invalidate cả 2 root, nếu không ô "+Tạo" / readiness vẫn stale tới 30s–5p
// (coverageMatrix dùng global default staleTime 5 phút).
// Đối chiếu useUpdatePathQuota đã invalidate quotaMatrixKeys.all — create bị sót.
// Test này là anchor non-tautological: nếu ai gỡ invalidation → fail.
// ---------------------------------------------------------------------------
describe("useCreateAdmissionPath – matrix cache parity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function arrangeCreateHandler() {
    server.use(
      http.post(`${API_BASE_URL}/api/admission-config/paths`, () =>
        HttpResponse.json(mockAdmissionPathResponse),
      ),
    );
  }

  // AdmissionPathCreate = z.infer OUTPUT type → 2 field có .default() trở thành
  // required trong input type; khớp payload QuickCreatePathModal gửi thật.
  const CREATE_PAYLOAD = {
    academic_info_id: 1,
    admission_method_id: 1,
    admission_round_id: 1,
    allow_unverified_submission: false,
    minor_correction_allowed_fields: [] as string[],
  };

  it("invalidates the quota-matrix cache (by-major + by-year)", async () => {
    arrangeCreateHandler();
    const { queryClient, Wrapper } = createWrapperWithClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useCreateAdmissionPath(), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.mutate(CREATE_PAYLOAD);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Raw ["quota-matrix"] === quotaMatrixKeys.all — prefix invalidation phủ
    // cả byMajor(id) lẫn byYear(year).
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: quotaMatrixKeys.all }),
    );

    invalidateSpy.mockRestore();
  });

  it("invalidates the admission-paths root (covers coverage-matrix)", async () => {
    arrangeCreateHandler();
    const { queryClient, Wrapper } = createWrapperWithClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useCreateAdmissionPath(), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.mutate(CREATE_PAYLOAD);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // admissionPathKeys.all = ["admission-paths"] — prefix phủ detail +
    // coverageMatrix(id) (readiness mode) + documents. (`.lists()` đã gỡ —
    // không còn query nào dưới prefix đó sau PR matrix-funnel cleanup.)
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: admissionPathKeys.all }),
    );

    invalidateSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// Sibling mutations — by-major matrix cache parity (PR matrix-funnel review)
//
// By-major PathMatrixCell (key ["quota-matrix"]) renders `status` (chấm màu)
// + `criteria_code`. Mutations đổi 2 field này PHẢI invalidate ["quota-matrix"]
// ở HOOK (không phụ thuộc call-site bù tay), nếu không ô by-major stale.
// Anchor non-tautological: gỡ invalidation → fail.
// ---------------------------------------------------------------------------
describe("sibling mutations – by-major matrix cache parity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function arrange(path: string, method: "put" | "post") {
    server.use(
      http[method](`${API_BASE_URL}${path}`, () =>
        HttpResponse.json(mockAdmissionPathResponse),
      ),
    );
  }

  it("useUpdateCriteria invalidates the quota-matrix cache (criteria_code)", async () => {
    arrange("/api/admission-config/paths/:pathId/criteria", "put");
    const { queryClient, Wrapper } = createWrapperWithClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useUpdateCriteria(), { wrapper: Wrapper });
    act(() => {
      result.current.mutate({
        pathId: MOCK_PATH_ID,
        // MSW intercepts → payload shape irrelevant; cast minimal.
        data: { code: "C1", name: "Crit", subject_group_ids: [] } as never,
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: quotaMatrixKeys.all }),
    );
    invalidateSpy.mockRestore();
  });

  it("useActivateAdmissionPath invalidates the quota-matrix cache (status dot)", async () => {
    arrange("/api/admission-config/paths/:pathId/activate", "post");
    const { queryClient, Wrapper } = createWrapperWithClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useActivateAdmissionPath(), {
      wrapper: Wrapper,
    });
    act(() => {
      result.current.mutate(MOCK_PATH_ID);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: quotaMatrixKeys.all }),
    );
    invalidateSpy.mockRestore();
  });

  it("useDeactivateAdmissionPath invalidates the quota-matrix cache (status dot)", async () => {
    arrange("/api/admission-config/paths/:pathId/deactivate", "post");
    const { queryClient, Wrapper } = createWrapperWithClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useDeactivateAdmissionPath(), {
      wrapper: Wrapper,
    });
    act(() => {
      result.current.mutate(MOCK_PATH_ID);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: quotaMatrixKeys.all }),
    );
    invalidateSpy.mockRestore();
  });
});
