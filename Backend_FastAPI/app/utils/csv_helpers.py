# app/utils/csv_helpers.py
"""
CSV Security Helpers

This module provides utilities to prevent CSV Injection attacks.

CSV Injection (also known as Formula Injection) occurs when user-controlled data
is exported to CSV files without proper sanitization. When opened in spreadsheet
applications like Excel, LibreOffice, or Google Sheets, cells starting with
special characters (=, +, -, @, etc.) are interpreted as formulas and executed.

Attack Example:
    username = "=cmd|'/c calc'!A1"
    When admin exports users to CSV and opens in Excel → Calculator executes

OWASP Recommendation:
    Prepend single quote (') to cells starting with dangerous characters.
    This forces the spreadsheet application to treat the cell as text.

References:
    - OWASP: https://owasp.org/www-community/attacks/CSV_Injection
    - CWE-1236: https://cwe.mitre.org/data/definitions/1236.html
"""

from typing import Any, List
import structlog

log = structlog.get_logger(__name__)

# Characters that can trigger formula execution in spreadsheet applications
# Based on OWASP recommendations
DANGEROUS_PREFIXES = (
    '=',   # Formula start (Excel, LibreOffice, Google Sheets)
    '+',   # Formula start (Excel)
    '-',   # Formula start (Excel)
    '@',   # Formula start (Excel)
    '\t',  # Tab character (can be used in exploits)
    '\r',  # Carriage return (can be used in exploits)
    '\n',  # Line feed (can be used in exploits)
    '|',   # Pipe character (used in DDE attacks)
)

# Additional dangerous patterns (for logging/monitoring)
DANGEROUS_PATTERNS = [
    'cmd',      # Windows command execution
    'powershell',  # PowerShell execution
    'DDE',      # Dynamic Data Exchange
    'DDEAUTO',  # Auto DDE
    'http://',  # External URL fetch
    'https://', # External URL fetch
    'file://',  # Local file access
]


def sanitize_csv_cell(value: Any) -> str:
    """
    Sanitize a single CSV cell value to prevent formula injection.
    
    This function prepends a single quote (') to any cell value that starts
    with a dangerous character. The single quote forces spreadsheet applications
    to treat the cell as text rather than a formula.
    
    Args:
        value: Any value to sanitize (will be converted to string)
        
    Returns:
        Sanitized string safe for CSV export
        
    Examples:
        >>> sanitize_csv_cell("=1+1")
        "'=1+1"
        >>> sanitize_csv_cell("@SUM(A1:A10)")
        "'@SUM(A1:A10)"
        >>> sanitize_csv_cell("John Doe")
        "John Doe"
        >>> sanitize_csv_cell(123)
        "123"
        >>> sanitize_csv_cell(None)
        ""
    """
    # Handle None/empty values
    if value is None:
        return ""
    
    # Convert to string
    str_value = str(value).strip()
    
    # Empty string after strip
    if not str_value:
        return ""
    
    # Check if starts with dangerous character
    if str_value[0] in DANGEROUS_PREFIXES:
        # Log potential injection attempt for monitoring
        log.warning(
            "CSV injection attempt detected and sanitized",
            original_value=str_value[:50],  # Limit log size
            first_char=str_value[0],
        )
        
        # Prepend single quote to force text interpretation
        return f"'{str_value}"
    
    # Check for dangerous patterns (for monitoring only)
    str_value_lower = str_value.lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in str_value_lower:
            log.info(
                "Potentially dangerous pattern in CSV cell",
                value=str_value[:50],
                pattern=pattern,
            )
            break
    
    return str_value


def sanitize_csv_row(row: List[Any]) -> List[str]:
    """
    Sanitize all cells in a CSV row.
    
    Args:
        row: List of cell values to sanitize
        
    Returns:
        List of sanitized string values
        
    Examples:
        >>> sanitize_csv_row(["=1+1", "John", "@SUM(A1)", "safe", 123])
        ["'=1+1", "John", "'@SUM(A1)", "safe", "123"]
    """
    return [sanitize_csv_cell(cell) for cell in row]


def is_potentially_malicious(value: Any) -> bool:
    """
    Check if a value is potentially malicious (for validation/monitoring).
    
    This is a stricter check than sanitize_csv_cell() and can be used
    to reject user input entirely rather than just sanitizing it.
    
    Args:
        value: Value to check
        
    Returns:
        True if value is potentially malicious, False otherwise
        
    Examples:
        >>> is_potentially_malicious("=cmd|'/c calc'!A1")
        True
        >>> is_potentially_malicious("John Doe")
        False
    """
    if value is None:
        return False
    
    str_value = str(value).strip()
    
    if not str_value:
        return False
    
    # Check for dangerous prefix
    if str_value[0] in DANGEROUS_PREFIXES:
        return True
    
    # Check for dangerous patterns
    str_value_lower = str_value.lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in str_value_lower:
            return True
    
    return False

