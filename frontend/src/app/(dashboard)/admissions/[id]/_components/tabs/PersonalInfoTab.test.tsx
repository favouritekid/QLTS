/**
 * PersonalInfoTab UI Contract Tests
 *
 * Validates the version-resync pattern for addressMode:
 *   profile.version changes → addressMode re-derives from profile.permanent_district
 *
 * Does NOT test address selection behavior (covered by AdaptiveAddressSelect.test.tsx).
 */

import { useState } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { useForm, FormProvider, type UseFormReturn } from "react-hook-form";
import { act } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createTestQueryClient } from "@/test/utils/test-utils";
import type { AdmissionProfileResponse, AdmissionProfileUpdateInput } from "@/lib/zod/admissions";

// Mock useConfigData — all category lists return empty
vi.mock("@/lib/hooks/useConfigData", () => ({
  useConfigData: () => ({ data: [], isLoading: false }),
}));

// Mock useAdministrative — place_of_birth combobox uses useProvinces("legacy");
// no network calls allowed in test (would emit MSW-style XHR errors).
vi.mock("@/lib/hooks/useAdministrative", () => ({
  useProvinces: () => ({ data: [], isLoading: false }),
  useDistricts: () => ({ data: [], isLoading: false }),
  useWards: () => ({ data: [], isLoading: false }),
  useResolveWard: () => ({ data: undefined, isLoading: false }),
}));

// Mock AdaptiveAddressSelect — lightweight spy that exposes key props
let capturedAddressProps: Record<string, unknown> = {};
vi.mock("@/components/forms/AdaptiveAddressSelect", () => ({
  AdaptiveAddressSelect: (props: Record<string, unknown>) => {
    capturedAddressProps = props;
    return (
      <div data-testid="address-select">
        <span data-testid="address-mode">{String(props.mode)}</span>
        <span data-testid="address-disabled">{String(props.disabled)}</span>
        <span data-testid="address-label">{String(props.label)}</span>
      </div>
    );
  },
}));

// Mock heavy UI components to avoid import chain issues
vi.mock("@/components/ui/combobox", () => ({
  Combobox: (props: { value?: string; placeholder?: string; disabled?: boolean }) => (
    <select data-testid="combobox" disabled={props.disabled} defaultValue={props.value || ""}>
      <option>{props.placeholder || ""}</option>
    </select>
  ),
}));

// Import after mocks
import { PersonalInfoTab } from "../tabs/PersonalInfoTab";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildProfile(overrides: Partial<AdmissionProfileResponse> = {}): AdmissionProfileResponse {
  return {
    id: 1,
    lead_id: 1,
    status: "draft",
    version: 1,
    academic_year: 2026,
    permanent_province: null,
    permanent_district: null,
    permanent_ward: null,
    full_name: "Test User",
    gender: null,
    dob: null,
    citizen_id: null,
    social_insurance_number: null,
    phone: null,
    email: null,
    place_of_birth: null,
    native_place: null,
    nationality: null,
    ethnicity: null,
    religion: null,
    disability_type: null,
    union_entry_date: null,
    party_entry_date: null,
    party_official_entry_date: null,
    permissions: {},
    eligibility_status: "pending",
    validation_errors: [],
    available_actions: [],
    completion_percent: 50,
    applied_rules: {},
    family_info: [],
    academic_history: [],
    documents_checklist: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as unknown as AdmissionProfileResponse;
}

const DEFAULT_VALUES: Partial<AdmissionProfileUpdateInput> = {
  full_name: "Test User",
  gender: "",
  dob: "",
  citizen_id: "",
  social_insurance_number: "",
  phone: "",
  email: "",
  place_of_birth: "",
  native_place: "",
  nationality: "",
  ethnicity: "",
  religion: "",
  disability_type: "",
  union_entry_date: "",
  party_entry_date: "",
  party_official_entry_date: "",
  permanent_province: "",
  permanent_district: "",
  permanent_ward: "",
};

// Module-level form spy lets tests reach into form state after rendering.
// Cleared in beforeEach via capturedFormRef reassign.
let capturedFormRef: UseFormReturn<AdmissionProfileUpdateInput> | null = null;

/** Wrapper that provides FormProvider + renders PersonalInfoTab */
function TestFormHost({
  profile,
  isEditable = true,
}: {
  profile: AdmissionProfileResponse;
  isEditable?: boolean;
}) {
  const [queryClient] = useState(() => createTestQueryClient());
  const form = useForm<AdmissionProfileUpdateInput>({
    defaultValues: {
      ...DEFAULT_VALUES,
      permanent_province: profile.permanent_province || "",
      permanent_district: profile.permanent_district || "",
      permanent_ward: profile.permanent_ward || "",
      permanent_commune_code:
        (profile as unknown as { permanent_commune_code?: string | null })
          .permanent_commune_code ?? null,
    } as AdmissionProfileUpdateInput,
  });
  capturedFormRef = form;

  return (
    <QueryClientProvider client={queryClient}>
      <FormProvider {...form}>
        <PersonalInfoTab profile={profile} form={form} isEditable={isEditable} />
      </FormProvider>
    </QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PersonalInfoTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedAddressProps = {};
    capturedFormRef = null;
  });

  describe("addressMode derivation", () => {
    it("current mode when permanent_district is null", () => {
      const profile = buildProfile({ permanent_district: null, version: 1 });
      render(<TestFormHost profile={profile} />);

      expect(screen.getByTestId("address-mode").textContent).toBe("current");
    });

    it("legacy mode when permanent_district has value", () => {
      const profile = buildProfile({
        permanent_district: "Huyện Cư M'gar",
        version: 1,
      });
      render(<TestFormHost profile={profile} />);

      expect(screen.getByTestId("address-mode").textContent).toBe("legacy");
    });

    it("re-derives to legacy when version changes and district set", () => {
      const profile1 = buildProfile({ permanent_district: null, version: 1 });
      const { rerender } = render(<TestFormHost profile={profile1} />);

      expect(screen.getByTestId("address-mode").textContent).toBe("current");

      // Simulate profile update: version changes, district now has value
      const profile2 = buildProfile({
        permanent_district: "Huyện Krông Búk",
        version: 2,
      });
      rerender(<TestFormHost profile={profile2} />);

      expect(screen.getByTestId("address-mode").textContent).toBe("legacy");
    });

    it("re-derives to current when version changes and district cleared", () => {
      const profile1 = buildProfile({
        permanent_district: "Huyện Cư M'gar",
        version: 1,
      });
      const { rerender } = render(<TestFormHost profile={profile1} />);

      expect(screen.getByTestId("address-mode").textContent).toBe("legacy");

      // Simulate profile update: version changes, district cleared
      const profile2 = buildProfile({
        permanent_district: null,
        version: 2,
      });
      rerender(<TestFormHost profile={profile2} />);

      expect(screen.getByTestId("address-mode").textContent).toBe("current");
    });
  });

  describe("isEditable → disabled", () => {
    it("isEditable=false passes disabled=true to address select", () => {
      const profile = buildProfile({ version: 1 });
      render(<TestFormHost profile={profile} isEditable={false} />);

      expect(screen.getByTestId("address-disabled").textContent).toBe("true");
    });

    it("isEditable=true passes disabled=false to address select", () => {
      const profile = buildProfile({ version: 1 });
      render(<TestFormHost profile={profile} isEditable={true} />);

      expect(screen.getByTestId("address-disabled").textContent).toBe("false");
    });
  });

  describe("Phase E.4 KV bridge — permanent_commune_code wiring", () => {
    it("wires onWardCodeChange handler into AdaptiveAddressSelect", () => {
      const profile = buildProfile({ version: 1 });
      render(<TestFormHost profile={profile} />);

      expect(typeof capturedAddressProps.onWardCodeChange).toBe("function");
    });

    it("onWardCodeChange sets permanent_commune_code form field", () => {
      const profile = buildProfile({ version: 1 });
      render(<TestFormHost profile={profile} />);

      const onWardCodeChange =
        capturedAddressProps.onWardCodeChange as (code: string | null) => void;
      act(() => {
        onWardCodeChange("66_002");
      });

      expect(capturedFormRef?.getValues("permanent_commune_code")).toBe("66_002");
    });

    it("onWardCodeChange(null) clears permanent_commune_code", () => {
      const profile = buildProfile({
        version: 1,
      });
      // Seed the form với code có sẵn để verify it gets cleared
      render(<TestFormHost profile={profile} />);

      const onWardCodeChange =
        capturedAddressProps.onWardCodeChange as (code: string | null) => void;
      act(() => {
        onWardCodeChange("66_002");
      });
      expect(capturedFormRef?.getValues("permanent_commune_code")).toBe("66_002");

      act(() => {
        onWardCodeChange(null);
      });
      expect(capturedFormRef?.getValues("permanent_commune_code")).toBeNull();
    });

    it("changing province clears permanent_commune_code", () => {
      const profile = buildProfile({ version: 1 });
      render(<TestFormHost profile={profile} />);

      // Seed code first
      const onWardCodeChange =
        capturedAddressProps.onWardCodeChange as (code: string | null) => void;
      act(() => {
        onWardCodeChange("66_002");
      });

      const onProvinceChange =
        capturedAddressProps.onProvinceChange as (v: string) => void;
      act(() => {
        onProvinceChange("Hà Nội");
      });

      expect(capturedFormRef?.getValues("permanent_commune_code")).toBeNull();
    });

    it("changing district clears permanent_commune_code", () => {
      const profile = buildProfile({
        permanent_district: "Quận 1",
        version: 1,
      });
      render(<TestFormHost profile={profile} />);

      const onWardCodeChange =
        capturedAddressProps.onWardCodeChange as (code: string | null) => void;
      act(() => {
        onWardCodeChange("01_001");
      });

      const onDistrictChange =
        capturedAddressProps.onDistrictChange as (v: string | null) => void;
      act(() => {
        onDistrictChange("Quận 2");
      });

      expect(capturedFormRef?.getValues("permanent_commune_code")).toBeNull();
    });

    it("changing address mode clears permanent_commune_code", () => {
      const profile = buildProfile({ version: 1 });
      render(<TestFormHost profile={profile} />);

      const onWardCodeChange =
        capturedAddressProps.onWardCodeChange as (code: string | null) => void;
      act(() => {
        onWardCodeChange("66_002");
      });

      const onModeChange =
        capturedAddressProps.onModeChange as (m: "current" | "legacy") => void;
      act(() => {
        onModeChange("legacy");
      });

      expect(capturedFormRef?.getValues("permanent_commune_code")).toBeNull();
    });
  });
});
