// src/lib/status-config.test.ts
/**
 * Unit tests for getStatusConfig function
 * 
 * Tests the status-driven UI pattern (ADR-FE-003)
 */
import { describe, it, expect } from "vitest"
import { 
  getStatusConfig, 
  ADMISSION_STATUS_CONFIG, 
  DEFAULT_STATUS_CONFIG,
} from "./status-config"

describe("getStatusConfig", () => {
  describe("Admission statuses", () => {
    it("should return draft config", () => {
      const config = getStatusConfig("draft")

      expect(config.label).toBe("Nháp")
      expect(config.badgeVariant).toBe("secondary")
      expect(config.showBanner).toBe(false)
      expect(config.allowedActions).toContain("save")
      expect(config.allowedActions).toContain("submit")
    })

    it("should return submitted config with banner", () => {
      const config = getStatusConfig("submitted")

      expect(config.label).toBe("Chờ duyệt")
      expect(config.showBanner).toBe(true)
      expect(config.bannerType).toBe("info")
      expect(config.bannerMessage).toContain("chờ xét duyệt")
      expect(config.allowedActions).toEqual([])
    })

    it("should return resubmitted config with banner", () => {
      const config = getStatusConfig("resubmitted")

      expect(config.label).toBe("Đã nộp lại")
      expect(config.showBanner).toBe(true)
      expect(config.bannerType).toBe("info")
    })

    it("should return approved config", () => {
      const config = getStatusConfig("approved")

      expect(config.label).toBe("Đã duyệt")
      expect(config.badgeColor).toContain("green")
      expect(config.showBanner).toBe(true)
      expect(config.bannerType).toBe("success")
      expect(config.allowedActions).toContain("enroll")
    })

    it("should return rejected config", () => {
      const config = getStatusConfig("rejected")

      expect(config.label).toBe("Từ chối")
      expect(config.badgeVariant).toBe("destructive")
      expect(config.showBanner).toBe(true)
      expect(config.bannerType).toBe("warning")
      expect(config.allowedActions).toContain("edit")
      expect(config.allowedActions).toContain("resubmit")
    })

    it("should return enrolled config", () => {
      const config = getStatusConfig("enrolled")

      expect(config.label).toBe("Đã nhập học")
      expect(config.badgeColor).toContain("purple")
      expect(config.showBanner).toBe(false)
      expect(config.allowedActions).toEqual([])
    })
  })

  describe("Unknown/future statuses", () => {
    it("should return fallback config for unknown status", () => {
      const config = getStatusConfig("some_new_status")

      expect(config.label).toBe("some_new_status") // Uses status as label
      expect(config.badgeVariant).toBe("outline")
      expect(config.showBanner).toBe(false)
      expect(config.allowedActions).toEqual([])
    })

    it("should handle empty string status", () => {
      const config = getStatusConfig("")

      expect(config.badgeVariant).toBe("outline")
      expect(config.allowedActions).toEqual([])
    })
  })

  describe("Module parameter", () => {
    it("should use admission config by default", () => {
      const config = getStatusConfig("draft")
      const explicitConfig = getStatusConfig("draft", "admission")

      expect(config).toEqual(explicitConfig)
    })

    it("should use lead config for lead module", () => {
      // Lead module has its own statuses
      const config = getStatusConfig("new", "lead")

      expect(config.label).toBe("Mới")
    })
  })

  describe("Status config properties", () => {
    it("should have all required properties for each status", () => {
      const statuses = ["draft", "submitted", "resubmitted", "approved", "rejected", "enrolled"]
      
      statuses.forEach(status => {
        const config = getStatusConfig(status)

        expect(config).toHaveProperty("label")
        expect(config).toHaveProperty("badgeVariant")
        expect(config).toHaveProperty("badgeColor")
        expect(config).toHaveProperty("showBanner")
        expect(config).toHaveProperty("allowedActions")
        expect(Array.isArray(config.allowedActions)).toBe(true)
      })
    })

    it("should have banner properties when showBanner is true", () => {
      const statusesWithBanner = ["submitted", "resubmitted", "approved", "rejected"]
      
      statusesWithBanner.forEach(status => {
        const config = getStatusConfig(status)

        expect(config.showBanner).toBe(true)
        expect(config.bannerType).toBeDefined()
        expect(config.bannerMessage).toBeDefined()
        expect(config.bannerMessage!.length).toBeGreaterThan(0)
      })
    })
  })

  describe("ADMISSION_STATUS_CONFIG constant", () => {
    it("should have all expected statuses defined", () => {
      expect(ADMISSION_STATUS_CONFIG).toHaveProperty("draft")
      expect(ADMISSION_STATUS_CONFIG).toHaveProperty("submitted")
      expect(ADMISSION_STATUS_CONFIG).toHaveProperty("resubmitted")
      expect(ADMISSION_STATUS_CONFIG).toHaveProperty("approved")
      expect(ADMISSION_STATUS_CONFIG).toHaveProperty("rejected")
      expect(ADMISSION_STATUS_CONFIG).toHaveProperty("enrolled")
    })
  })

  describe("DEFAULT_STATUS_CONFIG constant", () => {
    it("should have safe default values", () => {
      expect(DEFAULT_STATUS_CONFIG.label).toBe("Không xác định")
      expect(DEFAULT_STATUS_CONFIG.badgeVariant).toBe("outline")
      expect(DEFAULT_STATUS_CONFIG.showBanner).toBe(false)
      expect(DEFAULT_STATUS_CONFIG.allowedActions).toEqual([])
    })
  })
})
