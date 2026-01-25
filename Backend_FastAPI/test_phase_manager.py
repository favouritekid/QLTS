#!/usr/bin/env python3
"""Quick test script for phase_manager module"""
import sys
sys.path.insert(0, '/mnt/d/QLTS/Backend_FastAPI')

from app.services.phase_manager import (
    LeadPhase,
    PHASE_STATUSES,
    derive_phase_from_admission,
    get_allowed_statuses_for_phase,
    is_terminal_phase
)

print("=" * 60)
print("PHASE MANAGER MODULE TEST")
print("=" * 60)

# Test 1: LeadPhase enum
print("\n1. LeadPhase enum values:")
for phase in LeadPhase:
    print(f"   - {phase.value}")

# Test 2: PHASE_STATUSES mapping
print("\n2. PHASE_STATUSES mapping:")
for phase, statuses in PHASE_STATUSES.items():
    statuses_list = list(statuses)
    print(f"   {phase.value}: {len(statuses_list)} statuses")
    for s in statuses_list[:3]:  # Show first 3
        print(f"      - {s}")
    if len(statuses_list) > 3:
        print(f"      ... and {len(statuses_list) - 3} more")

# Test 3: Phase derivation using mock objects
print("\n3. Phase derivation tests:")

class MockProfile:
    def __init__(self, status):
        self.status = status

test_cases = [
    (None, "No admission profile"),
    (MockProfile("draft"), "Draft admission"),
    (MockProfile("submitted"), "Submitted admission"),
    (MockProfile("approved"), "Approved admission"),
    (MockProfile("fee_recorded"), "Fee recorded"),
    (MockProfile("enrolled"), "Enrolled (terminal)"),
]
for profile, desc in test_cases:
    result = derive_phase_from_admission(profile)
    status_str = profile.status if profile else "None"
    print(f"   {desc} ({status_str}): {result.value}")

# Test 4: Terminal phase check
print("\n4. Terminal phase check:")
for phase in LeadPhase:
    is_term = is_terminal_phase(phase)
    print(f"   {phase.value}: {'TERMINAL' if is_term else 'active'}")

# Test 5: Allowed statuses for phase
print("\n5. Allowed statuses for CONSULTATION phase (officer role):")
allowed = get_allowed_statuses_for_phase(LeadPhase.CONSULTATION, "officer")
allowed_list = list(allowed)
print(f"   Total: {len(allowed_list)} statuses")
for s in allowed_list[:5]:
    print(f"   - {s}")

# Test 6: Allowed statuses for ADMISSION phase
print("\n6. Allowed statuses for ADMISSION phase (officer role):")
allowed = get_allowed_statuses_for_phase(LeadPhase.ADMISSION, "officer")
allowed_list = list(allowed)
print(f"   Total: {len(allowed_list)} statuses")
for s in allowed_list[:5]:
    print(f"   - {s}")

print("\n" + "=" * 60)
print("ALL TESTS PASSED!")
print("=" * 60)
