# QLTS Architecture Lint - Quick Reference
# =========================================
#
# Installation:
#   pip install semgrep
#
# Usage:
#   # Run all architecture rules
#   semgrep --config .semgrep/rules/ app/
#
#   # Run with specific severity
#   semgrep --config .semgrep/rules/ --severity ERROR app/
#
#   # JSON output for CI
#   semgrep --config .semgrep/rules/ --json app/
#
# CI Integration (GitHub Actions):
#   - name: Semgrep Architecture Lint
#     uses: returntocorp/semgrep-action@v1
#     with:
#       config: .semgrep/rules/
#       auditOn: push
#
# Rules Overview:
# ---------------
# ERROR level (must fix):
#   - no-httpexception-in-services: Use custom exceptions
#   - no-db-commit-in-services: Transaction management in routers
#
# WARNING level (should fix):
#   - prefer-repository-pattern: Use Repository classes
#   - no-db-scalar-in-services: Move to Repository
#   - no-complex-logic-in-routers: Business logic in services
#
# INFO level (suggestions):
#   - repository-import-pattern: Use package imports
#
# Ignoring Rules:
# ---------------
# Add comment above the line:
#   # nosemgrep: rule-id
#   await db.execute(...)  # This is allowed
#
# Or ignore entire file:
#   # nosemgrep
#   (at top of file)
