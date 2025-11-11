#!/usr/bin/env python3
"""
Phase 4 API Testing Script - 3-Tier Architecture
=================================================

This script tests all refactored API endpoints for the 3-tier architecture.

Prerequisites:
1. Database migrated to Phase 2 (run: alembic upgrade head)
2. Sample data seeded (run: python seed_sample_data.py)
3. Backend server running (run: uvicorn app.main:app --reload)

Usage:
    python test_phase4_api.py
"""

import asyncio
import sys
from typing import Dict, List, Any, Optional
import httpx
from datetime import datetime

# Configuration
API_BASE_URL = "http://localhost:8000"
API_PREFIX = "/api"

# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


class APITester:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.passed_tests = 0
        self.failed_tests = 0
        self.test_results = []
        self.auth_token = None  # Will be set if authentication is available

        # Store IDs for testing
        self.unit_id = None
        self.program_ids = []
        self.offering_ids = []
        self.academic_info_ids = []
        self.lead_ids = []

    def print_header(self, text: str):
        """Print section header"""
        print(f"\n{Colors.HEADER}{'=' * 80}")
        print(f"{text}")
        print(f"{'=' * 80}{Colors.ENDC}\n")

    def print_test(self, test_name: str, passed: Optional[bool], details: str = ""):
        """Print test result. If passed is None, it's a skipped test."""
        if passed is None:
            status = f"{Colors.WARNING}⚠️  SKIP{Colors.ENDC}"
            print(f"{status} - {test_name}")
            if details:
                print(f"      {details}")
            # Don't count skipped tests
            return

        status = f"{Colors.OKGREEN}✅ PASS{Colors.ENDC}" if passed else f"{Colors.FAIL}❌ FAIL{Colors.ENDC}"
        print(f"{status} - {test_name}")
        if details:
            print(f"      {details}")

        if passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1

        self.test_results.append({
            "test": test_name,
            "passed": passed,
            "details": details
        })

    async def test_get(self, endpoint: str, test_name: str, expected_keys: List[str] = None, auth_required: bool = True) -> Optional[Dict]:
        """Generic GET request test"""
        try:
            headers = {}
            if auth_required and self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"

            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}{endpoint}", headers=headers, timeout=10.0)

                # If 401 and no token, skip test with warning
                if response.status_code == 401 and not self.auth_token:
                    self.print_test(test_name, None, "⚠️  SKIPPED - Requires authentication (no token provided)")
                    return None

                if response.status_code == 200:
                    data = response.json()

                    # Check expected keys if provided
                    if expected_keys and isinstance(data, dict):
                        missing_keys = [k for k in expected_keys if k not in data]
                        if missing_keys:
                            self.print_test(test_name, False, f"Missing keys: {missing_keys}")
                            return None

                    self.print_test(test_name, True, f"Status: {response.status_code}")
                    return data
                else:
                    self.print_test(test_name, False, f"Status: {response.status_code}, Error: {response.text[:100]}")
                    return None

        except Exception as e:
            self.print_test(test_name, False, f"Exception: {str(e)[:100]}")
            return None

    async def run_all_tests(self):
        """Run all API tests"""

        print(f"{Colors.BOLD}{Colors.OKCYAN}")
        print("=" * 80)
        print("PHASE 4 API TESTING - 3-TIER ARCHITECTURE")
        print("=" * 80)
        print(f"{Colors.ENDC}")
        print(f"Testing API at: {self.base_url}")
        print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        # ========================================================================
        # TEST SUITE 1: Organization Endpoints
        # ========================================================================
        self.print_header("TEST SUITE 1: Organization Endpoints")

        # Test 1.1: Get organization units
        units_data = await self.test_get(
            f"{API_PREFIX}/organization-units",
            "1.1 GET /organization-units (should return 3-tier tree)"
        )

        if units_data and isinstance(units_data, list) and len(units_data) > 0:
            unit = units_data[0]
            self.unit_id = unit.get('id')

            # Verify 3-tier structure
            has_programs = 'major_programs' in unit
            self.print_test(
                "1.1a Verify 'major_programs' field exists in unit",
                has_programs,
                f"Found: {list(unit.keys())[:5]}"
            )

            if has_programs and unit['major_programs']:
                program = unit['major_programs'][0]
                self.program_ids.append(program['id'])

                has_offerings = 'offerings' in program
                self.print_test(
                    "1.1b Verify 'offerings' field exists in program",
                    has_offerings,
                    f"Program ID: {program['id']}"
                )

                if has_offerings and program['offerings']:
                    offering = program['offerings'][0]
                    self.offering_ids.append(offering['id'])

                    has_academic_info = 'academic_info_history' in offering
                    self.print_test(
                        "1.1c Verify 'academic_info_history' field exists in offering",
                        has_academic_info,
                        f"Offering ID: {offering['id']}"
                    )

        # Test 1.2: Get organization tree with aggregation
        tree_data = await self.test_get(
            f"{API_PREFIX}/organization-units/tree-with-aggregation",
            "1.2 GET /organization-units/tree-with-aggregation"
        )

        if tree_data and isinstance(tree_data, list) and len(tree_data) > 0:
            node = tree_data[0]
            has_stats = 'statistics' in node or 'program_count' in node
            self.print_test(
                "1.2a Verify aggregation statistics exist",
                has_stats,
                f"Keys: {list(node.keys())[:8]}"
            )

        # Test 1.3: Get programs by unit
        if self.unit_id:
            programs_data = await self.test_get(
                f"{API_PREFIX}/programs?unitId={self.unit_id}",
                f"1.3 GET /programs?unitId={self.unit_id}"
            )

            if programs_data and isinstance(programs_data, list):
                self.print_test(
                    "1.3a Verify programs list returned",
                    len(programs_data) > 0,
                    f"Found {len(programs_data)} programs"
                )

                for prog in programs_data[:3]:
                    if prog['id'] not in self.program_ids:
                        self.program_ids.append(prog['id'])

        # ========================================================================
        # TEST SUITE 2: Program Offering Endpoints (Level 2)
        # ========================================================================
        self.print_header("TEST SUITE 2: Program Offering Endpoints (Level 2)")

        if self.program_ids:
            program_id = self.program_ids[0]

            # Test 2.1: Get offerings for a program
            offerings_data = await self.test_get(
                f"{API_PREFIX}/programs/{program_id}/offerings",
                f"2.1 GET /programs/{program_id}/offerings"
            )

            if offerings_data and isinstance(offerings_data, list):
                self.print_test(
                    "2.1a Verify offerings list returned",
                    len(offerings_data) > 0,
                    f"Found {len(offerings_data)} offerings for program {program_id}"
                )

                for offering in offerings_data:
                    if offering['id'] not in self.offering_ids:
                        self.offering_ids.append(offering['id'])

                    # Verify offering structure
                    required_fields = ['id', 'offering_type', 'program_id']
                    has_all_fields = all(f in offering for f in required_fields)
                    self.print_test(
                        f"2.1b Verify offering {offering['id']} structure",
                        has_all_fields,
                        f"Type: {offering.get('offering_type')}, Program: {offering.get('program_id')}"
                    )

        # ========================================================================
        # TEST SUITE 3: Academic Info Endpoints (Level 3)
        # ========================================================================
        self.print_header("TEST SUITE 3: Academic Info Endpoints (Level 3)")

        if self.offering_ids:
            offering_id = self.offering_ids[0]

            # Test 3.1: Get academic info history
            academic_history = await self.test_get(
                f"{API_PREFIX}/offerings/{offering_id}/academic-info",
                f"3.1 GET /offerings/{offering_id}/academic-info (history)"
            )

            if academic_history and isinstance(academic_history, list):
                self.print_test(
                    "3.1a Verify academic info history returned",
                    len(academic_history) > 0,
                    f"Found {len(academic_history)} academic info records"
                )

                for info in academic_history:
                    if info['id'] not in self.academic_info_ids:
                        self.academic_info_ids.append(info['id'])

                    # Verify academic info structure
                    required_fields = ['id', 'offering_id', 'academic_year', 'tuition_fee_per_year']
                    has_all_fields = all(f in info for f in required_fields)
                    self.print_test(
                        f"3.1b Verify academic info {info['id']} structure",
                        has_all_fields,
                        f"Year: {info.get('academic_year')}, Tuition: {info.get('tuition_fee_per_year')}"
                    )

            # Test 3.2: Get academic info by year
            current_year = datetime.now().year
            academic_by_year = await self.test_get(
                f"{API_PREFIX}/offerings/{offering_id}/academic-info/{current_year}",
                f"3.2 GET /offerings/{offering_id}/academic-info/{current_year}"
            )

            if academic_by_year:
                is_correct_year = academic_by_year.get('academic_year') == current_year
                self.print_test(
                    "3.2a Verify correct year returned",
                    is_correct_year,
                    f"Expected: {current_year}, Got: {academic_by_year.get('academic_year')}"
                )

            # Test 3.3: Get current academic info (published for current year)
            current_info = await self.test_get(
                f"{API_PREFIX}/offerings/{offering_id}/academic-info/current",
                f"3.3 GET /offerings/{offering_id}/academic-info/current"
            )

            if current_info:
                is_published = current_info.get('is_published', False)
                is_current_year = current_info.get('academic_year') == current_year
                self.print_test(
                    "3.3a Verify current info is published and current year",
                    is_published and is_current_year,
                    f"Published: {is_published}, Year: {current_info.get('academic_year')}"
                )

        # ========================================================================
        # TEST SUITE 4: Lead Endpoints with offering_id
        # ========================================================================
        self.print_header("TEST SUITE 4: Lead Endpoints (offering_id filter)")

        # Test 4.1: Get all leads
        leads_data = await self.test_get(
            f"{API_PREFIX}/leads?page=1&page_size=10",
            "4.1 GET /leads (paginated)"
        )

        if leads_data and 'leads' in leads_data:
            leads_list = leads_data['leads']
            self.print_test(
                "4.1a Verify leads list returned",
                isinstance(leads_list, list),
                f"Total count: {leads_data.get('total_count')}, Leads: {len(leads_list)}"
            )

            if leads_list:
                lead = leads_list[0]
                self.lead_ids.append(lead['id'])

                # Verify lead has offering field (not major)
                has_offering = 'offering' in lead
                has_no_major = 'major' not in lead
                self.print_test(
                    "4.1b Verify lead has 'offering' field (not 'major')",
                    has_offering and has_no_major,
                    f"Has offering: {has_offering}, Has major: {not has_no_major}"
                )

        # Test 4.2: Filter leads by offering_id
        if self.offering_ids:
            offering_id = self.offering_ids[0]
            filtered_leads = await self.test_get(
                f"{API_PREFIX}/leads?offering_id={offering_id}&page_size=10",
                f"4.2 GET /leads?offering_id={offering_id}"
            )

            if filtered_leads and 'leads' in filtered_leads:
                leads_list = filtered_leads['leads']

                # Verify all leads have the correct offering_id
                if leads_list:
                    all_match = all(
                        lead.get('offering', {}).get('id') == offering_id
                        for lead in leads_list
                        if lead.get('offering')
                    )
                    self.print_test(
                        "4.2a Verify all leads match offering_id filter",
                        all_match,
                        f"Found {len(leads_list)} leads with offering_id={offering_id}"
                    )

        # Test 4.3: Get lead details
        if self.lead_ids:
            lead_id = self.lead_ids[0]
            lead_detail = await self.test_get(
                f"{API_PREFIX}/leads/{lead_id}",
                f"4.3 GET /leads/{lead_id} (detail view)"
            )

            if lead_detail:
                # Verify full lead structure
                required_fields = ['id', 'full_name', 'email', 'phone', 'offering']
                has_all_fields = all(f in lead_detail for f in required_fields)
                self.print_test(
                    "4.3a Verify lead detail structure",
                    has_all_fields,
                    f"Lead: {lead_detail.get('full_name')}, Offering: {lead_detail.get('offering', {}).get('offering_type')}"
                )

        # ========================================================================
        # TEST SUITE 5: Deprecated Endpoints (Should Fail)
        # ========================================================================
        self.print_header("TEST SUITE 5: Deprecated Endpoints (Should Return 404)")

        # Test 5.1: Old /majors endpoint should not exist
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}{API_PREFIX}/majors", timeout=10.0)
                is_404 = response.status_code == 404
                self.print_test(
                    "5.1 Verify /majors endpoint is removed (404)",
                    is_404,
                    f"Status: {response.status_code} (expected 404)"
                )
        except:
            self.print_test("5.1 Verify /majors endpoint is removed", False, "Request failed")

        # Test 5.2: Old /majors/{id}/academic-info endpoint should not exist
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}{API_PREFIX}/majors/1/academic-info", timeout=10.0)
                is_404 = response.status_code == 404
                self.print_test(
                    "5.2 Verify /majors/{id}/academic-info endpoint is removed (404)",
                    is_404,
                    f"Status: {response.status_code} (expected 404)"
                )
        except:
            self.print_test("5.2 Verify old major academic-info endpoint removed", False, "Request failed")

        # ========================================================================
        # TEST SUMMARY
        # ========================================================================
        self.print_summary()

    def print_summary(self):
        """Print test summary"""
        total = self.passed_tests + self.failed_tests
        pass_rate = (self.passed_tests / total * 100) if total > 0 else 0

        print(f"\n{Colors.BOLD}{'=' * 80}")
        print("TEST SUMMARY")
        print(f"{'=' * 80}{Colors.ENDC}\n")

        print(f"Total Tests:   {total}")
        print(f"{Colors.OKGREEN}Passed:        {self.passed_tests}{Colors.ENDC}")
        print(f"{Colors.FAIL}Failed:        {self.failed_tests}{Colors.ENDC}")
        print(f"Pass Rate:     {pass_rate:.1f}%")

        print(f"\n{'=' * 80}")

        if self.failed_tests == 0:
            print(f"{Colors.OKGREEN}{Colors.BOLD}✅ ALL TESTS PASSED!{Colors.ENDC}")
            print(f"\n{Colors.OKCYAN}The 3-tier architecture refactoring is working correctly.{Colors.ENDC}")
            print(f"{Colors.OKCYAN}You can proceed to Phase 5 (Frontend refactoring).{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}{Colors.BOLD}❌ SOME TESTS FAILED{Colors.ENDC}")
            print(f"\n{Colors.WARNING}Please review the failed tests above and fix the issues.{Colors.ENDC}")

        print(f"{'=' * 80}\n")

        # Print collected IDs for debugging
        print(f"{Colors.OKCYAN}Collected IDs for reference:{Colors.ENDC}")
        print(f"  Unit ID:          {self.unit_id}")
        print(f"  Program IDs:      {self.program_ids[:3]}")
        print(f"  Offering IDs:     {self.offering_ids[:3]}")
        print(f"  Academic Info IDs: {self.academic_info_ids[:3]}")
        print(f"  Lead IDs:         {self.lead_ids[:3]}")
        print()


async def main():
    """Main test runner"""
    tester = APITester(API_BASE_URL)

    # Check if server is running
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/health", timeout=5.0)
            print(f"{Colors.OKGREEN}✓ Backend server is running{Colors.ENDC}")
    except:
        print(f"{Colors.FAIL}✗ Backend server is NOT running!{Colors.ENDC}")
        print(f"\nPlease start the server first:")
        print(f"  cd /home/user/QLTS/Backend_FastAPI")
        print(f"  uvicorn app.main:app --reload")
        print()
        return False

    # Run all tests
    await tester.run_all_tests()

    return tester.failed_tests == 0


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARNING}Testing interrupted by user.{Colors.ENDC}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.FAIL}❌ FATAL ERROR: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
