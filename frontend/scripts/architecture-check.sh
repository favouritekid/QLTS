#!/usr/bin/env bash
set -e

# ==============================================================================
# QLTS FRONTEND ARCHITECTURE GUARD (V3.1 - ENHANCED)
# 
# Enforces rules from FRONTEND_ARCHITECTURE_V3.md
# ==============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔍 QLTS Architecture Compliance Check (V3.1)${NC}"
echo "=============================================="

VIOLATIONS=0
WARNINGS=0
SRC_DIR="src"
REPORT_FILE="architecture-report.json"

# Initialize Arrays for JSON Report
FAIL_LIST=()
WARN_LIST=()

# Utility functions
log_fail() {
  local rule="$1"
  local msg="$2"
  local evidence="$3"
  
  echo -e "${RED}❌ FAIL [${rule}]: ${msg}${NC}"
  if [ -n "$evidence" ]; then
    echo "$evidence" | head -5 | sed 's/^/   /'
  fi
  VIOLATIONS=$((VIOLATIONS + 1))
  
  # Escape quotes for JSON safety (basic)
  local clean_msg=$(echo "$msg" | sed 's/"/\\"/g')
  FAIL_LIST+=("{\"rule\": \"$rule\", \"message\": \"$clean_msg\"}")
  echo ""
}

log_warn() {
  local rule="$1"
  local msg="$2"
  local evidence="$3"

  echo -e "${YELLOW}⚠️  WARN [${rule}]: ${msg}${NC}"
  if [ -n "$evidence" ]; then
    echo "$evidence" | head -5 | sed 's/^/   /'
  fi
  WARNINGS=$((WARNINGS + 1))

  local clean_msg=$(echo "$msg" | sed 's/"/\\"/g')
  WARN_LIST+=("{\"rule\": \"$rule\", \"message\": \"$clean_msg\"}")
  echo ""
}

# ==============================================================================
# SECTION 1: THIN CLIENT & BUSINESS LOGIC (Rules 0.7, 2.2)
# ==============================================================================
echo "📋 [SECTION 1] Thin Client Principles"

# RULE 2.2: Permission-Based Visibility
# Exclude lines with 'architecture-allow' comment
ROLE_CHECK=$(grep -rn "user\.role" "$SRC_DIR" \
  --include="*.tsx" \
  --exclude-dir="lib" \
  --exclude-dir="utils" \
  | grep -v "architecture-allow" || true)

if [ -n "$ROLE_CHECK" ]; then
  log_fail "Rule 2.2" "Direct 'user.role' usage detected. Use permission flags from API." "$ROLE_CHECK"
else
  echo "✅ Rule 2.2: No direct role checks"
fi

# RULE 0.7: No Computed Business Logic
# Improved Regex: look for calculate/compute at start of word boundaries
LOGIC_KEYWORDS=$(grep -rnE "\b(calculate|compute|process)[A-Z][a-zA-Z]*" "$SRC_DIR" \
  --include="*.tsx" \
  --exclude-dir="lib" \
  --exclude-dir="hooks" \
  | grep -v "Style" \
  | grep -v "Width" \
  | grep -v "Height" || true)

if [ -n "$LOGIC_KEYWORDS" ]; then
  log_warn "Rule 0.7" "Potential business logic naming detected in UI components." "$LOGIC_KEYWORDS"
else
  echo "✅ Rule 0.7: No obvious business logic naming"
fi

# ==============================================================================
# SECTION 2: LAYER VIOLATION (Rule 2.6.2 & 2.6.6)
# ==============================================================================
echo ""
echo "📋 [SECTION 2] Layer Boundaries (View Model Enforcement)"

# Components should NOT import API directly. They should use ViewModels/Hooks.
# Detecting direct API imports in components folder
API_LEAK=$(grep -rn "from.*api/" "$SRC_DIR/components" --include="*.tsx" | grep -v "architecture-allow" || true)

if [ -n "$API_LEAK" ]; then
  log_fail "Rule 2.6.2" "Components accessing API layer directly. MUST use Domain Service/Hooks." "$API_LEAK"
else
  echo "✅ Rule 2.6.2: Components are isolated from API"
fi

# ==============================================================================
# SECTION 3: DOMAIN BOUNDARIES (Rule 2.6.13)
# ==============================================================================
echo ""
echo "📋 [SECTION 3] Domain Boundaries & Type Safety"

# RULE: No unsafe casting 'as unknown as'
CAST_VIOLATIONS=$(grep -rn "as unknown as" "$SRC_DIR" \
  --include="*.ts" --include="*.tsx" \
  --exclude-dir="test" --exclude-dir="__tests__" \
  | grep -v "spec" || true)

if [ -n "$CAST_VIOLATIONS" ]; then
  log_fail "Rule 2.6.13" "Unsafe type casting (as unknown as). STRICTLY FORBIDDEN." "$CAST_VIOLATIONS"
else
  echo "✅ Rule 2.6.13: No unsafe casting"
fi

# RULE: No BaseEntity in mutations
# Checks for patterns like: useMutation<BaseEntity, ...> or useMutation<...>(payload: BaseEntity)
BASE_ENTITY_MUTATION=$(grep -rn "BaseEntity" "$SRC_DIR" \
  --include="*Mutation.ts" \
  --include="*Mutation.tsx" || true)

if [ -n "$BASE_ENTITY_MUTATION" ]; then
  log_warn "Rule 2.6.13" "BaseEntity detected inside Mutation file. Check for 'One Domain = One Payload' rule." "$BASE_ENTITY_MUTATION"
else
  echo "✅ Rule 2.6.13: No BaseEntity in mutations"
fi

# ==============================================================================
# SECTION 4: CODE QUALITY (Rule 0.3)
# ==============================================================================
echo ""
echo "📋 [SECTION 4] Code Quality"

# CHECK: Explicit 'any' types
# Improved Regex: matches ": any" or ":any" but avoids "company", "many" etc.
ANY_USAGE=$(grep -rn ": *any\b" "$SRC_DIR" \
  --include="*.ts" --include="*.tsx" \
  | grep -v "eslint-disable" \
  | grep -v "//" || true)

if [ -n "$ANY_USAGE" ]; then
  log_fail "Rule 2.6.12" "Explicit 'any' type usage detected." "$ANY_USAGE"
else
  echo "✅ Rule 2.6.12: No explicit 'any' types"
fi

# CHECK: BaseFormData (God Object)
BASE_FORM=$(grep -rn "BaseFormData" "$SRC_DIR" --include="*.ts" --include="*.tsx" || true)
if [ -n "$BASE_FORM" ]; then
  log_fail "Rule 2.6.14" "'BaseFormData' usage detected (God Object)." "$BASE_FORM"
else
  echo "✅ Rule 2.6.14: No BaseFormData"
fi

# ==============================================================================
# REPORT GENERATION
# ==============================================================================

# Join array elements with commas
join_json() { local IFS=","; echo "$*"; }

echo "{" > "$REPORT_FILE"
echo "  \"timestamp\": \"$(date -u +"%Y-%m-%dT%H:%M:%SZ")\"," >> "$REPORT_FILE"
echo "  \"violations_count\": $VIOLATIONS," >> "$REPORT_FILE"
echo "  \"warnings_count\": $WARNINGS," >> "$REPORT_FILE"
echo "  \"failures\": [$(join_json "${FAIL_LIST[*]}")]," >> "$REPORT_FILE"
echo "  \"warnings\": [$(join_json "${WARN_LIST[*]}")]" >> "$REPORT_FILE"
echo "}" >> "$REPORT_FILE"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SUMMARY:"
echo -e "❌ Violations: ${RED}$VIOLATIONS${NC}"
echo -e "⚠️  Warnings:   ${YELLOW}$WARNINGS${NC}"
echo "📄 Report saved to: $REPORT_FILE"

if [ $VIOLATIONS -gt 0 ]; then
  echo -e "${RED}❌ ARCHITECTURE CHECK FAILED${NC}"
  exit 1
else
  echo -e "${GREEN}✅ ARCHITECTURE CHECK PASSED${NC}"
  exit 0
fi