#!/bin/bash

###############################################################################
# DEPRECATED ENDPOINTS CLEANUP SCRIPT
# Project: QLTS
# Purpose: Automated cleanup of legacy /api/majors/* endpoints
# Run: bash cleanup-deprecated-endpoints.sh
###############################################################################

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/Backend_FastAPI"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  DEPRECATED ENDPOINTS CLEANUP SCRIPT${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

###############################################################################
# SAFETY CHECKS
###############################################################################

echo -e "${YELLOW}[1/8] Running safety checks...${NC}"

# Check if in correct directory
if [ ! -d "$BACKEND_DIR" ] || [ ! -d "$FRONTEND_DIR" ]; then
    echo -e "${RED}Error: Must run from project root directory${NC}"
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${RED}Warning: You have uncommitted changes${NC}"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create backup branch
BACKUP_BRANCH="backup/pre-deprecated-cleanup-$(date +%Y%m%d-%H%M%S)"
echo -e "${GREEN}Creating backup branch: $BACKUP_BRANCH${NC}"
git checkout -b "$BACKUP_BRANCH"
git checkout -

echo -e "${GREEN}✓ Safety checks passed${NC}"
echo ""

###############################################################################
# PHASE 1: BACKEND CLEANUP
###############################################################################

echo -e "${YELLOW}[2/8] Phase 1: Backend Cleanup${NC}"

# Remove legacy model file
LEGACY_MODEL="$BACKEND_DIR/app/models/major_academic_info.py"
if [ -f "$LEGACY_MODEL" ]; then
    echo -e "  Removing: $LEGACY_MODEL"
    rm "$LEGACY_MODEL"
    echo -e "${GREEN}  ✓ Removed major_academic_info.py${NC}"
else
    echo -e "${YELLOW}  ⚠ File already removed: major_academic_info.py${NC}"
fi

# Clean up commented code in organization.py
ORG_MODEL="$BACKEND_DIR/app/models/organization.py"
if [ -f "$ORG_MODEL" ]; then
    # Create backup
    cp "$ORG_MODEL" "$ORG_MODEL.bak"

    # Remove lines 204-214 (commented Major class)
    # Using sed to remove lines
    sed -i '204,214d' "$ORG_MODEL" 2>/dev/null || \
    sed -i.bak '204,214d' "$ORG_MODEL"  # macOS compatibility

    echo -e "${GREEN}  ✓ Cleaned commented code in organization.py${NC}"
    echo -e "${BLUE}  → Backup saved: organization.py.bak${NC}"
else
    echo -e "${RED}  ✗ File not found: organization.py${NC}"
fi

echo -e "${GREEN}✓ Phase 1 complete${NC}"
echo ""

###############################################################################
# PHASE 2: FRONTEND CLEANUP - COMPONENTS
###############################################################################

echo -e "${YELLOW}[3/8] Phase 2: Frontend Component Cleanup${NC}"

# Remove orphaned components
COMPONENTS_TO_REMOVE=(
    "$FRONTEND_DIR/src/components/admin/organization/MajorDialog.tsx"
    "$FRONTEND_DIR/src/components/admin/organization/AcademicInfoDialog.tsx"
    "$FRONTEND_DIR/src/components/admin/organization/AcademicInfoManagement.tsx"
)

for component in "${COMPONENTS_TO_REMOVE[@]}"; do
    if [ -f "$component" ]; then
        filename=$(basename "$component")
        echo -e "  Removing: $filename"
        rm "$component"
        echo -e "${GREEN}  ✓ Removed $filename${NC}"
    else
        echo -e "${YELLOW}  ⚠ Already removed: $(basename "$component")${NC}"
    fi
done

echo -e "${GREEN}✓ Component cleanup complete${NC}"
echo ""

###############################################################################
# PHASE 3: FRONTEND CLEANUP - HOOKS
###############################################################################

echo -e "${YELLOW}[4/8] Phase 3: Frontend Hook Cleanup${NC}"

USE_ORG_FILE="$FRONTEND_DIR/src/hooks/useOrganization.ts"
if [ -f "$USE_ORG_FILE" ]; then
    # Create backup
    cp "$USE_ORG_FILE" "$USE_ORG_FILE.bak"

    # Remove lines 803-1080 (deprecated hooks)
    sed -i '803,1080d' "$USE_ORG_FILE" 2>/dev/null || \
    sed -i.bak '803,1080d' "$USE_ORG_FILE"  # macOS compatibility

    echo -e "${GREEN}  ✓ Removed 10 deprecated hooks from useOrganization.ts${NC}"
    echo -e "${BLUE}  → Backup saved: useOrganization.ts.bak${NC}"
else
    echo -e "${RED}  ✗ File not found: useOrganization.ts${NC}"
fi

echo -e "${GREEN}✓ Hook cleanup complete${NC}"
echo ""

###############################################################################
# PHASE 4: FRONTEND CLEANUP - ENDPOINTS
###############################################################################

echo -e "${YELLOW}[5/8] Phase 4: Frontend Endpoint Constants Cleanup${NC}"

ENDPOINTS_FILE="$FRONTEND_DIR/src/lib/api/endpoints.ts"
if [ -f "$ENDPOINTS_FILE" ]; then
    # Create backup
    cp "$ENDPOINTS_FILE" "$ENDPOINTS_FILE.bak"

    # Remove legacy endpoint constants (lines 52-56, 106-110)
    # This is a simplified version - manual edit recommended for precision
    sed -i '/LIST_MAJORS:/d' "$ENDPOINTS_FILE" 2>/dev/null || \
    sed -i.bak '/LIST_MAJORS:/d' "$ENDPOINTS_FILE"

    sed -i '/GET_MAJOR:/d' "$ENDPOINTS_FILE" 2>/dev/null || \
    sed -i.bak '/GET_MAJOR:/d' "$ENDPOINTS_FILE"

    sed -i '/ACADEMIC_INFO_HISTORY:/d' "$ENDPOINTS_FILE" 2>/dev/null || \
    sed -i.bak '/ACADEMIC_INFO_HISTORY:/d' "$ENDPOINTS_FILE"

    sed -i '/ACADEMIC_INFO_BY_YEAR:/d' "$ENDPOINTS_FILE" 2>/dev/null || \
    sed -i.bak '/ACADEMIC_INFO_BY_YEAR:/d' "$ENDPOINTS_FILE"

    sed -i '/CREATE_MAJOR:/d' "$ENDPOINTS_FILE" 2>/dev/null || \
    sed -i.bak '/CREATE_MAJOR:/d' "$ENDPOINTS_FILE"

    sed -i '/UPDATE_MAJOR:/d' "$ENDPOINTS_FILE" 2>/dev/null || \
    sed -i.bak '/UPDATE_MAJOR:/d' "$ENDPOINTS_FILE"

    sed -i '/DELETE_MAJOR:/d' "$ENDPOINTS_FILE" 2>/dev/null || \
    sed -i.bak '/DELETE_MAJOR:/d' "$ENDPOINTS_FILE"

    echo -e "${GREEN}  ✓ Removed legacy endpoint constants${NC}"
    echo -e "${BLUE}  → Backup saved: endpoints.ts.bak${NC}"
    echo -e "${YELLOW}  ⚠ Manual review recommended for endpoints.ts${NC}"
else
    echo -e "${RED}  ✗ File not found: endpoints.ts${NC}"
fi

echo -e "${GREEN}✓ Endpoint cleanup complete${NC}"
echo ""

###############################################################################
# PHASE 5: VERIFICATION - SEARCH FOR REMAINING REFERENCES
###############################################################################

echo -e "${YELLOW}[6/8] Phase 5: Verification - Searching for remaining references${NC}"

echo -e "${BLUE}Searching frontend for /api/majors references:${NC}"
cd "$FRONTEND_DIR"
MAJORS_REFS=$(grep -r "/api/majors" src/ 2>/dev/null || echo "")
if [ -z "$MAJORS_REFS" ]; then
    echo -e "${GREEN}  ✓ No /api/majors references found${NC}"
else
    echo -e "${RED}  ✗ Found references:${NC}"
    echo "$MAJORS_REFS"
    echo -e "${YELLOW}  ⚠ Manual cleanup required${NC}"
fi

echo -e "${BLUE}Searching frontend for useMajor (old hook):${NC}"
USE_MAJOR_REFS=$(grep -r "useMajor\(" src/ 2>/dev/null | grep -v "useMajorProgram" || echo "")
if [ -z "$USE_MAJOR_REFS" ]; then
    echo -e "${GREEN}  ✓ No old useMajor() references found${NC}"
else
    echo -e "${RED}  ✗ Found references:${NC}"
    echo "$USE_MAJOR_REFS"
    echo -e "${YELLOW}  ⚠ Manual cleanup required${NC}"
fi

echo -e "${BLUE}Searching for orphaned component imports:${NC}"
for component in "MajorDialog" "AcademicInfoDialog" "AcademicInfoManagement"; do
    REFS=$(grep -r "from.*$component" src/ 2>/dev/null || echo "")
    if [ -z "$REFS" ]; then
        echo -e "${GREEN}  ✓ No $component imports found${NC}"
    else
        echo -e "${RED}  ✗ Found $component imports:${NC}"
        echo "$REFS"
    fi
done

cd "$SCRIPT_DIR"

echo -e "${GREEN}✓ Verification complete${NC}"
echo ""

###############################################################################
# PHASE 6: TESTING
###############################################################################

echo -e "${YELLOW}[7/8] Phase 6: Running Tests${NC}"

# Frontend TypeScript check
echo -e "${BLUE}Running TypeScript compilation check...${NC}"
cd "$FRONTEND_DIR"
if npm run type-check 2>&1 | grep -q "error TS"; then
    echo -e "${RED}  ✗ TypeScript errors found${NC}"
    echo -e "${YELLOW}  → Review errors and fix manually${NC}"
else
    echo -e "${GREEN}  ✓ TypeScript compilation successful${NC}"
fi

# Frontend ESLint
echo -e "${BLUE}Running ESLint...${NC}"
if npm run lint 2>&1 | grep -q "error"; then
    echo -e "${YELLOW}  ⚠ ESLint errors/warnings found${NC}"
    echo -e "${YELLOW}  → Review and fix if necessary${NC}"
else
    echo -e "${GREEN}  ✓ ESLint passed${NC}"
fi

cd "$SCRIPT_DIR"

echo -e "${GREEN}✓ Testing complete${NC}"
echo ""

###############################################################################
# PHASE 7: SUMMARY
###############################################################################

echo -e "${YELLOW}[8/8] Cleanup Summary${NC}"
echo ""
echo -e "${BLUE}=== Files Removed ===${NC}"
echo -e "  Backend:"
echo -e "    - app/models/major_academic_info.py"
echo -e "  Frontend:"
echo -e "    - components/admin/organization/MajorDialog.tsx"
echo -e "    - components/admin/organization/AcademicInfoDialog.tsx"
echo -e "    - components/admin/organization/AcademicInfoManagement.tsx"
echo ""
echo -e "${BLUE}=== Files Modified ===${NC}"
echo -e "  Backend:"
echo -e "    - app/models/organization.py (removed commented code)"
echo -e "  Frontend:"
echo -e "    - hooks/useOrganization.ts (removed 10 deprecated hooks)"
echo -e "    - lib/api/endpoints.ts (removed legacy constants)"
echo ""
echo -e "${BLUE}=== Backups Created ===${NC}"
echo -e "  Git branch: $BACKUP_BRANCH"
echo -e "  File backups:"
echo -e "    - organization.py.bak"
echo -e "    - useOrganization.ts.bak"
echo -e "    - endpoints.ts.bak"
echo ""

###############################################################################
# NEXT STEPS
###############################################################################

echo -e "${BLUE}=== Next Steps ===${NC}"
echo -e "1. ${YELLOW}Review changes:${NC}"
echo -e "   git status"
echo -e "   git diff"
echo ""
echo -e "2. ${YELLOW}Manual cleanup (if needed):${NC}"
echo -e "   - Review endpoints.ts for precision"
echo -e "   - Check organization.types.ts for old types"
echo ""
echo -e "3. ${YELLOW}Test the application:${NC}"
echo -e "   cd frontend && npm run dev"
echo -e "   - Test admin organization management"
echo -e "   - Create/edit major programs"
echo -e "   - Manage program offerings"
echo ""
echo -e "4. ${YELLOW}If everything works:${NC}"
echo -e "   git add ."
echo -e "   git commit -m 'chore: Remove deprecated /api/majors/* endpoints'"
echo -e "   git push"
echo ""
echo -e "5. ${YELLOW}If issues found:${NC}"
echo -e "   git checkout $BACKUP_BRANCH"
echo -e "   # Or restore from .bak files"
echo ""

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  CLEANUP SCRIPT COMPLETE${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "${YELLOW}⚠ Important: Test thoroughly before committing!${NC}"
