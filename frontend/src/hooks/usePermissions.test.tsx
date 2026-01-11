// src/hooks/usePermissions.test.tsx
/**
 * Unit tests for usePermissions hook
 * 
 * Tests the permission-based rendering pattern (ADR-FE-002)
 */
import { describe, it, expect } from "vitest"
import { renderHook } from "@testing-library/react"
import { usePermissions } from "./usePermissions"

describe("usePermissions Hook", () => {
  describe("can()", () => {
    it("should return true when permission is granted", () => {
      const resource = {
        permissions: {
          edit: true,
          submit: true,
          approve: false,
        }
      }

      const { result } = renderHook(() => usePermissions(resource))

      expect(result.current.can("edit")).toBe(true)
      expect(result.current.can("submit")).toBe(true)
    })

    it("should return false when permission is denied", () => {
      const resource = {
        permissions: {
          edit: true,
          approve: false,
        }
      }

      const { result } = renderHook(() => usePermissions(resource))

      expect(result.current.can("approve")).toBe(false)
    })

    it("should return false for undefined permissions", () => {
      const resource = {
        permissions: {
          edit: true,
        }
      }

      const { result } = renderHook(() => usePermissions(resource))

      expect(result.current.can("delete")).toBe(false)
    })

    it("should handle null resource gracefully", () => {
      const { result } = renderHook(() => usePermissions(null))

      expect(result.current.can("edit")).toBe(false)
      expect(result.current.can("submit")).toBe(false)
    })

    it("should handle undefined resource gracefully", () => {
      const { result } = renderHook(() => usePermissions(undefined))

      expect(result.current.can("edit")).toBe(false)
    })

    it("should handle resource without permissions object", () => {
      // Cast to any to test runtime behavior with missing permissions
      const resource = { id: 1, status: "draft", permissions: {} } as const

      const { result } = renderHook(() => usePermissions(resource as any))

      expect(result.current.can("edit")).toBe(false)
    })
  })

  describe("canAny()", () => {
    it("should return true if any permission is granted", () => {
      const resource = {
        permissions: {
          edit: false,
          submit: false,
          view: true,
        }
      }

      const { result } = renderHook(() => usePermissions(resource))

      expect(result.current.canAny("edit", "submit", "view")).toBe(true)
    })

    it("should return false if no permissions are granted", () => {
      const resource = {
        permissions: {
          edit: false,
          submit: false,
        }
      }

      const { result } = renderHook(() => usePermissions(resource))

      expect(result.current.canAny("edit", "submit")).toBe(false)
    })
  })

  describe("canAll()", () => {
    it("should return true only if all permissions are granted", () => {
      const resource = {
        permissions: {
          edit: true,
          submit: true,
        }
      }

      const { result } = renderHook(() => usePermissions(resource))

      expect(result.current.canAll("edit", "submit")).toBe(true)
    })

    it("should return false if any permission is missing", () => {
      const resource = {
        permissions: {
          edit: true,
          submit: false,
        }
      }

      const { result } = renderHook(() => usePermissions(resource))

      expect(result.current.canAll("edit", "submit")).toBe(false)
    })
  })

  describe("permissions object", () => {
    it("should return the full permissions object", () => {
      const resource = {
        permissions: {
          edit: true,
          submit: true,
          approve: false,
        }
      }

      const { result } = renderHook(() => usePermissions(resource))

      expect(result.current.permissions).toEqual({
        edit: true,
        submit: true,
        approve: false,
      })
    })

    it("should return empty object for null resource", () => {
      const { result } = renderHook(() => usePermissions(null))

      expect(result.current.permissions).toEqual({})
    })
  })

  describe("memoization", () => {
    it("should return same reference for same resource", () => {
      const resource = { permissions: { edit: true } }
      
      const { result, rerender } = renderHook(() => usePermissions(resource))
      const firstResult = result.current

      rerender()
      
      expect(result.current).toBe(firstResult)
    })
  })
})
