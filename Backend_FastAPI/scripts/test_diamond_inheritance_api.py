#!/usr/bin/env python3
"""
Script test Diamond Inheritance qua API calls.

Chạy:
    cd /mnt/d/QLTS/Backend_FastAPI
    source venv/bin/activate
    python scripts/test_diamond_inheritance_api.py

Yêu cầu:
    - Server đang chạy: uvicorn app.main:app --reload
    - Đã chạy create_test_users.py trước
"""

import asyncio
import sys
from dataclasses import dataclass
from typing import Optional

import httpx

# Configuration
BASE_URL = "http://localhost:8000"
DEFAULT_PASSWORD = "Test@123456"

# Test users (username is email prefix)
TEST_USERS = {
    "officer": "test_officer",
    "accountant": "test_accountant",
    "manager": "test_manager",
    "admin": "test_admin",
}


@dataclass
class TestResult:
    """Result of a single API test."""
    endpoint: str
    method: str
    role: str
    expected_status: int
    actual_status: int
    passed: bool
    message: str = ""


class DiamondInheritanceAPITester:
    """Test Diamond Inheritance via API calls."""

    def __init__(self):
        # Store cookies for each role (httpOnly cookies from login)
        self.cookies: dict[str, httpx.Cookies] = {}
        # Store CSRF tokens for each role (needed for POST/PUT/DELETE)
        self.csrf_tokens: dict[str, str] = {}
        self.results: list[TestResult] = []
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def login(self, role: str, username: str) -> bool:
        """Login and store cookies for a role."""
        try:
            # OAuth2PasswordRequestForm uses form data, not JSON
            response = await self.client.post(
                "/api/auth/login",
                data={"username": username, "password": DEFAULT_PASSWORD}
            )

            if response.status_code == 200:
                # Token is in httpOnly cookies, not response body
                # Store cookies for this role
                self.cookies[role] = response.cookies

                # Extract CSRF token from cookies (needed for POST/PUT/DELETE)
                csrf_token = response.cookies.get("csrf_token")
                if csrf_token:
                    self.csrf_tokens[role] = csrf_token

                print(f"  ✅ {role}: logged in successfully (user: {username})")
                return True
            else:
                detail = response.json().get("detail", "unknown error")
                print(f"  ❌ {role}: login failed - {response.status_code} - {detail}")
                return False
        except Exception as e:
            print(f"  ❌ {role}: login error - {e}")
            return False

    async def test_endpoint(
        self,
        role: str,
        method: str,
        endpoint: str,
        expected_status: int,
        json_data: dict = None,
        description: str = ""
    ) -> TestResult:
        """Test an endpoint with a specific role."""

        cookies = self.cookies.get(role)
        if not cookies:
            return TestResult(
                endpoint=endpoint,
                method=method,
                role=role,
                expected_status=expected_status,
                actual_status=0,
                passed=False,
                message="No cookies available"
            )

        # Build headers with CSRF token for state-changing methods
        headers = {}
        if method in ["POST", "PUT", "DELETE", "PATCH"]:
            csrf_token = self.csrf_tokens.get(role)
            if csrf_token:
                headers["X-CSRF-Token"] = csrf_token

        try:
            if method == "GET":
                response = await self.client.get(endpoint, cookies=cookies)
            elif method == "POST":
                response = await self.client.post(endpoint, cookies=cookies, headers=headers, json=json_data or {})
            elif method == "PUT":
                response = await self.client.put(endpoint, cookies=cookies, headers=headers, json=json_data or {})
            elif method == "DELETE":
                response = await self.client.delete(endpoint, cookies=cookies, headers=headers)
            else:
                raise ValueError(f"Unknown method: {method}")

            # Check if status matches expected
            # For permission tests, we accept both exact match and 4xx range
            passed = response.status_code == expected_status

            # Special case: if we expect 400, also accept 422 (both are validation errors)
            # 400 = Business validation, 422 = Pydantic/Schema validation
            if expected_status == 400 and response.status_code == 422:
                passed = True

            # Special case: if we expect 403/401, also accept 404 (IDOR protection returns 404)
            if expected_status in [401, 403] and response.status_code == 404:
                passed = True

            # Debug: Print response body if unexpected 403
            msg = description
            if response.status_code == 403 and expected_status != 403:
                try:
                    detail = response.json().get("detail", "no detail")
                    msg = f"{description} [403 detail: {detail}]"
                except:
                    pass

            return TestResult(
                endpoint=endpoint,
                method=method,
                role=role,
                expected_status=expected_status,
                actual_status=response.status_code,
                passed=passed,
                message=msg
            )

        except Exception as e:
            return TestResult(
                endpoint=endpoint,
                method=method,
                role=role,
                expected_status=expected_status,
                actual_status=0,
                passed=False,
                message=f"Error: {e}"
            )

    async def run_all_tests(self):
        """Run all diamond inheritance tests."""

        print("=" * 70)
        print("🧪 DIAMOND INHERITANCE API TEST")
        print("=" * 70)

        # Step 1: Login all users
        print("\n📝 Step 1: Login all test users")
        print("-" * 50)

        for role, username in TEST_USERS.items():
            await self.login(role, username)

        if not all(role in self.cookies for role in TEST_USERS.keys()):
            print("\n❌ Cannot proceed - some logins failed")
            return

        # Step 2: Test Finance Operations (Accountant-specific)
        print("\n📝 Step 2: Test Finance Operations (Separation of Duties)")
        print("-" * 50)

        finance_tests = [
            # Accountant CAN record payment
            ("accountant", "POST", "/api/payments", 400, "Accountant records payment (expect 400 - validation error, not 403)"),
            # Manager CANNOT record payment
            ("manager", "POST", "/api/payments", 403, "Manager CANNOT record payment"),
            # Officer CANNOT record payment
            ("officer", "POST", "/api/payments", 403, "Officer CANNOT record payment"),
            # Admin CAN record payment
            ("admin", "POST", "/api/payments", 400, "Admin records payment (expect 400 - validation error, not 403)"),

            # Accountant CAN calculate fee
            ("accountant", "POST", "/api/fees/calculate", 400, "Accountant calculates fee"),
            # Manager CANNOT calculate fee
            ("manager", "POST", "/api/fees/calculate", 403, "Manager CANNOT calculate fee"),
            # Officer CANNOT calculate fee
            ("officer", "POST", "/api/fees/calculate", 403, "Officer CANNOT calculate fee"),
        ]

        for role, method, endpoint, expected, desc in finance_tests:
            result = await self.test_endpoint(role, method, endpoint, expected, description=desc)
            self.results.append(result)
            status_icon = "✅" if result.passed else "❌"
            print(f"  {status_icon} [{role}] {method} {endpoint} → {result.actual_status} (expected {expected})")

        # Step 3: Test User Management (Manager-specific)
        print("\n📝 Step 3: Test User Management (Separation of Duties)")
        print("-" * 50)

        user_mgmt_tests = [
            # Manager CAN list users
            ("manager", "GET", "/api/admin/users", 200, "Manager lists users"),
            # Accountant CANNOT list users
            ("accountant", "GET", "/api/admin/users", 403, "Accountant CANNOT list users"),
            # Officer CANNOT list users
            ("officer", "GET", "/api/admin/users", 403, "Officer CANNOT list users"),
            # Admin CAN list users
            ("admin", "GET", "/api/admin/users", 200, "Admin lists users"),
        ]

        for role, method, endpoint, expected, desc in user_mgmt_tests:
            result = await self.test_endpoint(role, method, endpoint, expected, description=desc)
            self.results.append(result)
            status_icon = "✅" if result.passed else "❌"
            print(f"  {status_icon} [{role}] {method} {endpoint} → {result.actual_status} (expected {expected})")

        # Step 4: Test Common Officer Permissions (inherited by both branches)
        print("\n📝 Step 4: Test Common Officer Permissions (inherited)")
        print("-" * 50)

        common_tests = [
            # All roles can view leads (inherited from officer)
            ("officer", "GET", "/api/leads", 200, "Officer views leads"),
            ("accountant", "GET", "/api/leads", 200, "Accountant views leads (inherited)"),
            ("manager", "GET", "/api/leads", 200, "Manager views leads (inherited)"),
            ("admin", "GET", "/api/leads", 200, "Admin views leads (inherited)"),

            # All roles can view own profile (inherited from user)
            ("officer", "GET", "/api/profile", 200, "Officer views profile"),
            ("accountant", "GET", "/api/profile", 200, "Accountant views profile"),
            ("manager", "GET", "/api/profile", 200, "Manager views profile"),
            ("admin", "GET", "/api/profile", 200, "Admin views profile"),
        ]

        for role, method, endpoint, expected, desc in common_tests:
            result = await self.test_endpoint(role, method, endpoint, expected, description=desc)
            self.results.append(result)
            status_icon = "✅" if result.passed else "❌"
            print(f"  {status_icon} [{role}] {method} {endpoint} → {result.actual_status} (expected {expected})")

        # Step 5: Test Admin-only Operations
        print("\n📝 Step 5: Test Admin-only Operations")
        print("-" * 50)

        admin_only_tests = [
            # Only Admin can create accounting period
            ("admin", "GET", "/api/accounting/periods", 200, "Admin views periods"),
            ("manager", "GET", "/api/accounting/periods", 403, "Manager CANNOT view periods"),
            ("accountant", "GET", "/api/accounting/periods", 200, "Accountant views periods"),
            ("officer", "GET", "/api/accounting/periods", 403, "Officer CANNOT view periods"),
        ]

        for role, method, endpoint, expected, desc in admin_only_tests:
            result = await self.test_endpoint(role, method, endpoint, expected, description=desc)
            self.results.append(result)
            status_icon = "✅" if result.passed else "❌"
            print(f"  {status_icon} [{role}] {method} {endpoint} → {result.actual_status} (expected {expected})")

        # Summary
        self.print_summary()

    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 70)
        print("📊 TEST SUMMARY")
        print("=" * 70)

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        print(f"\n  Total Tests: {total}")
        print(f"  ✅ Passed: {passed}")
        print(f"  ❌ Failed: {failed}")
        print(f"  Success Rate: {passed/total*100:.1f}%")

        if failed > 0:
            print("\n  Failed Tests:")
            for r in self.results:
                if not r.passed:
                    print(f"    - [{r.role}] {r.method} {r.endpoint}")
                    print(f"      Expected: {r.expected_status}, Got: {r.actual_status}")
                    if r.message:
                        print(f"      Note: {r.message}")

        # Diamond Inheritance specific checks
        print("\n" + "-" * 70)
        print("🔷 DIAMOND INHERITANCE VERIFICATION")
        print("-" * 70)

        # Check: Manager cannot do finance
        manager_finance = [r for r in self.results
                         if r.role == "manager" and "/api/payments" in r.endpoint]
        if all(r.passed for r in manager_finance):
            print("  ✅ Manager cannot access finance operations (separation of duties)")
        else:
            print("  ❌ Manager can access finance operations (VIOLATION!)")

        # Check: Accountant cannot do user management
        accountant_users = [r for r in self.results
                          if r.role == "accountant" and "/api/admin/users" in r.endpoint]
        if all(r.passed for r in accountant_users):
            print("  ✅ Accountant cannot access user management (separation of duties)")
        else:
            print("  ❌ Accountant can access user management (VIOLATION!)")

        # Check: Admin can do both
        # For finance, we expect 400/422 (validation error = has permission)
        # For users, we expect 200 (success)
        admin_finance = [r for r in self.results
                        if r.role == "admin" and "/api/payments" in r.endpoint]
        admin_users = [r for r in self.results
                      if r.role == "admin" and "/api/admin/users" in r.endpoint]

        admin_has_finance = all(r.actual_status in [200, 400, 422] for r in admin_finance)
        admin_has_users = all(r.actual_status == 200 for r in admin_users)

        if admin_has_finance and admin_has_users:
            print("  ✅ Admin can access BOTH finance AND user management (diamond inheritance)")
        else:
            print("  ❌ Admin cannot access both (MISSING inheritance!)")

        # Check: Both branches inherit from Officer
        accountant_leads = [r for r in self.results
                          if r.role == "accountant" and "/api/leads" in r.endpoint]
        manager_leads = [r for r in self.results
                        if r.role == "manager" and "/api/leads" in r.endpoint]
        if all(r.passed for r in accountant_leads + manager_leads):
            print("  ✅ Both Manager and Accountant inherit Officer permissions")
        else:
            print("  ❌ Inheritance from Officer not working")

        print("\n" + "=" * 70)
        if failed == 0:
            print("🎉 ALL TESTS PASSED - DIAMOND INHERITANCE WORKING CORRECTLY!")
        else:
            print(f"⚠️  {failed} TESTS FAILED - Please investigate")
        print("=" * 70)


async def main():
    """Main function."""
    print("\n🚀 Starting Diamond Inheritance API Tests...")
    print("   Make sure the server is running: uvicorn app.main:app --reload\n")

    try:
        async with DiamondInheritanceAPITester() as tester:
            await tester.run_all_tests()
    except httpx.ConnectError:
        print("\n❌ ERROR: Cannot connect to server!")
        print("   Please make sure the server is running:")
        print("   cd /mnt/d/QLTS/Backend_FastAPI")
        print("   source venv/bin/activate")
        print("   uvicorn app.main:app --reload")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
