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
  admissionPathKeys,
} from "./useAdmissionPaths";
import type { AdmissionPathResponse, ResolvedDocumentListResponse } from "@/lib/zod/admission-path";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_PATH_ID = 42;

/** A minimal AdmissionPathResponse to pre-seed the detail cache. */
const mockAdmissionPathResponse: AdmissionPathResponse = {
  id: MOCK_PATH_ID,
  academic_info_id: 1,
  admission_method_id: 1,
  status: "draft",
  display_name: "Test Path",
  display_order: 1,
  visibility: "public",
  activated_at: null,
  activated_by: null,
  created_at: "2025-06-01T00:00:00+00:00",
  updated_at: "2025-06-01T00:00:00+00:00",
  academic_info: null,
  admission_method: null,
  criteria: null,
  available_actions: [],
  can_edit: true,
  can_activate: false,
  validation_errors: [],
  // PR #6: strict submit gate per path; default False in the fixture
  // mirrors the backend default for newly-created paths.
  allow_unverified_submission: false,
  // Minor-correction allowlist — empty by default for fresh paths
  // (admin opts in field-by-field after path creation).
  minor_correction_allowed_fields: [],
};

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

    it("should invalidate the lists cache", async () => {
      server.use(
        http.put(
          `${API_BASE_URL}/api/admission-config/paths/:pathId/documents`,
          () => {
            return HttpResponse.json(mockDocumentsResponse);
          }
        )
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

      // lists cache should be invalidated
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: admissionPathKeys.lists(),
        })
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
