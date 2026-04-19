"""Pseudo-code formatters for domain entity IDs.

Pre-enrollment the system does not carry a real ``student_code``; these helpers
produce stable human-readable references that fit external template constraints
(e.g., Zalo ZNS STRING params capped at 30 chars).
"""


def format_lead_code(lead_id: int) -> str:
    """``LEAD-000123`` (11 chars). Pseudo-code used before enrollment."""
    return f"LEAD-{lead_id:06d}"


def format_profile_code(profile_id: int) -> str:
    """``HS-000123`` (9 chars). Admission profile reference."""
    return f"HS-{profile_id:06d}"


def format_booking_code(consultation_id: int) -> str:
    """``CONS-000123`` (11 chars). Consultation booking reference."""
    return f"CONS-{consultation_id:06d}"
