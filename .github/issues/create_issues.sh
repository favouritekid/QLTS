#!/bin/bash

 

# ============================================================================

# GitHub Issues Creation Script

# ============================================================================

# This script creates all 12 GitHub Issues for code quality refactoring

#

# Prerequisites:

# 1. GitHub CLI installed: https://cli.github.com/

# 2. Authenticated: gh auth login

# 3. Repository access: favouritekid/QLTS

#

# Usage:

#   bash .github/scripts/create_issues.sh

# ============================================================================

 

set -e  # Exit on error

 

# Colors for output

RED='\033[0;31m'

GREEN='\033[0;32m'

YELLOW='\033[1;33m'

BLUE='\033[0;34m'

NC='\033[0m' # No Color

 

# Configuration

REPO="favouritekid/QLTS"

ISSUES_DIR=".github/issues"

 

echo -e "${BLUE}============================================${NC}"

echo -e "${BLUE}GitHub Issues Creation Script${NC}"

echo -e "${BLUE}============================================${NC}"

echo ""

 

# Check if gh CLI is installed

if ! command -v gh &> /dev/null; then

    echo -e "${RED}❌ GitHub CLI (gh) not found!${NC}"

    echo -e "${YELLOW}Please install from: https://cli.github.com/${NC}"

    exit 1

fi

 

# Check if authenticated

if ! gh auth status &> /dev/null; then

    echo -e "${RED}❌ Not authenticated with GitHub!${NC}"

    echo -e "${YELLOW}Please run: gh auth login${NC}"

    exit 1

fi

 

echo -e "${GREEN}✅ GitHub CLI installed and authenticated${NC}"

echo ""

 

# Create milestones

echo -e "${BLUE}Creating milestones...${NC}"

 

gh api repos/$REPO/milestones --method POST \

  -f title="Week 1 - Emergency Fixes" \

  -f description="Priority 0: IDOR + Transaction Management (Top 4)" \

  -f due_on="2025-12-09T23:59:59Z" \

  2>/dev/null || echo "  ⚠️  Milestone 'Week 1' already exists"

 

gh api repos/$REPO/milestones --method POST \

  -f title="Week 2-3 - Critical Fixes" \

  -f description="Priority 1: Remaining Transactions + Rate Limiting" \

  -f due_on="2025-12-23T23:59:59Z" \

  2>/dev/null || echo "  ⚠️  Milestone 'Week 2-3' already exists"

 

gh api repos/$REPO/milestones --method POST \

  -f title="Week 4 - UX Improvements" \

  -f description="Priority 2: Error Boundaries + Loading States" \

  -f due_on="2025-12-30T23:59:59Z" \

  2>/dev/null || echo "  ⚠️  Milestone 'Week 4' already exists"

 

gh api repos/$REPO/milestones --method POST \

  -f title="Month 2 - Final Polish" \

  -f description="Priority 3: Suspense + Remaining IDOR" \

  -f due_on="2026-01-31T23:59:59Z" \

  2>/dev/null || echo "  ⚠️  Milestone 'Month 2' already exists"

 

echo -e "${GREEN}✅ Milestones created${NC}"

echo ""

 

# Create labels

echo -e "${BLUE}Creating labels...${NC}"

 

create_label() {

    local name=$1

    local color=$2

    local description=$3

 

    gh api repos/$REPO/labels --method POST \

      -f name="$name" \

      -f color="$color" \

      -f description="$description" \

      2>/dev/null || echo "  ⚠️  Label '$name' already exists"

}

 

create_label "P0" "b60205" "Priority 0 - Emergency (Week 1)"

create_label "P1" "d93f0b" "Priority 1 - Critical (Week 2-3)"

create_label "P2" "fbca04" "Priority 2 - High (Week 4)"

create_label "P3" "0e8a16" "Priority 3 - Medium (Month 2)"

create_label "security" "d73a4a" "Security vulnerability"

create_label "refactoring" "a2eeef" "Code refactoring"

create_label "database" "1d76db" "Database related"

create_label "frontend" "c5def5" "Frontend (Next.js)"

create_label "UX" "f9d0c4" "User experience"

create_label "enhancement" "84b6eb" "New feature or enhancement"

 

echo -e "${GREEN}✅ Labels created${NC}"

echo ""

 

# Create issues directory

mkdir -p $ISSUES_DIR

 

# Issue #1: IDOR - Applications

echo -e "${BLUE}Creating Issue #1: IDOR Vulnerabilities...${NC}"

cat > $ISSUES_DIR/issue-01.md <<'EOF'

## Description

 

**Severity:** 🔴 CRITICAL - Data Breach Risk

 

Three application endpoints are vulnerable to IDOR (Insecure Direct Object Reference) attacks.

 

**Vulnerable Endpoints:**

- `GET /applications/{application_id}` - Line 97-129

- `PUT /applications/{application_id}` - Line 137-172

- `DELETE /applications/{application_id}` - Line 235-299

 

**Attack Vector:**

```bash

GET /applications/1  → 200 OK (own)

GET /applications/2  → 200 OK (Officer B's) ← VULNERABILITY!

```

 

**Impact:**

- Data Exposure: Any user can read all applications

- Data Modification: Any user can modify any application

- Data Deletion: Any user can delete any application

 

**Files Affected:**

- `Backend_FastAPI/app/routers/applications.py`

- `Backend_FastAPI/app/core/deps.py`

 

## Tasks

 

- [ ] Create `get_application_for_user()` dependency (1h)

- [ ] Update `application_service.py` (30m)

- [ ] Fix GET endpoint (30m)

- [ ] Fix PUT endpoint (30m)

- [ ] Fix DELETE endpoint (30m)

- [ ] Add integration tests (1h)

- [ ] Manual verification (30m)

 

## References

 

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #1)

- **Audit Report:** `COMPREHENSIVE_CODE_AUDIT_REPORT.md` (Section II.C)

 

## Acceptance Criteria

 

- [ ] All 3 endpoints use dependency

- [ ] All IDOR tests pass

- [ ] Manual testing confirms 403 for unauthorized access

EOF

 

gh issue create \

  --repo $REPO \

  --title "[CRITICAL] Fix IDOR Vulnerabilities in Applications Endpoints" \

  --body-file $ISSUES_DIR/issue-01.md \

  --label "security,critical,bug,P0" \

  --milestone "Week 1 - Emergency Fixes" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #1 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #1 may already exist${NC}"

 

# Issue #2: Transaction Management - config_service.py

echo -e "${BLUE}Creating Issue #2: Transaction - config_service.py...${NC}"

cat > $ISSUES_DIR/issue-02.md <<'EOF'

## Description

 

**Severity:** 🔴 CRITICAL - Data Consistency Risk

 

`config_service.py` has **18 violations** where services commit internally.

 

**Violations:** Lines 123, 177, 204, 296, 341, 382, 386, 469, 543, 584, 588, 687, 736, 763, 767, 946, 997, 1062

 

**Risk:**

- Breaks atomicity in multi-service operations

- Cannot rollback on partial failures

 

**Files Affected:**

- `Backend_FastAPI/app/services/config_service.py`

- `Backend_FastAPI/app/routers/admin/config.py`

 

## Tasks

 

**Phase 1:** Audit (1h)

- [ ] Document all 18 functions

- [ ] Create rollback test cases

 

**Phase 2:** Refactor Services (6h)

- [ ] Degree Level functions (1.5h)

- [ ] Tuition Fee functions (1.5h)

- [ ] Consultation Status functions (1.5h)

- [ ] Pipeline Stage functions (1.5h)

 

**Phase 3:** Update Routers (2h)

**Phase 4:** Testing (1h)

 

## References

 

- **Implementation Guide:** `IMPLEMENTATION_PLAN.md` (Issue #2.1)

- **Audit Report:** `TRANSACTION_AUDIT_REPORT.md`

 

## Acceptance Criteria

 

- [ ] Zero `await db.commit()` in service

- [ ] All functions return callbacks

- [ ] Transaction rollback tests pass

EOF

 

gh issue create \

  --repo $REPO \

  --title "[CRITICAL] Fix Transaction Management in config_service.py (18 violations)" \

  --body-file $ISSUES_DIR/issue-02.md \

  --label "critical,refactoring,database,P0" \

  --milestone "Week 1 - Emergency Fixes" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #2 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #2 may already exist${NC}"

 

# Issue #3: Transaction Management - organization_service.py

echo -e "${BLUE}Creating Issue #3: Transaction - organization_service.py...${NC}"

cat > $ISSUES_DIR/issue-03.md <<'EOF'

## Description

 

**Severity:** 🔴 CRITICAL

 

`organization_service.py` has **13 violations** where services commit internally.

 

**Violations:** Lines 359, 477, 548, 628, 669, 721, 797, 850, 883, 1005, 1069, 1129, 1172

 

## Tasks

 

- [ ] Refactor Organization Unit functions (2h)

- [ ] Refactor Program functions (2h)

- [ ] Refactor Offering functions (2h)

- [ ] Refactor Academic Info functions (2h)

 

## Acceptance Criteria

 

- [ ] Zero `await db.commit()` in service

- [ ] Tests pass

EOF

 

gh issue create \

  --repo $REPO \

  --title "[CRITICAL] Fix Transaction Management in organization_service.py (13 violations)" \

  --body-file $ISSUES_DIR/issue-03.md \

  --label "critical,refactoring,database,P0" \

  --milestone "Week 1 - Emergency Fixes" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #3 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #3 may already exist${NC}"

 

# Issue #4: Transaction Management - user_service.py

echo -e "${BLUE}Creating Issue #4: Transaction - user_service.py...${NC}"

cat > $ISSUES_DIR/issue-04.md <<'EOF'

## Description

 

**Severity:** 🔴 CRITICAL

 

`user_service.py` has **10 violations**.

 

**Violations:** Lines 328, 428, 716, 785, 827, 919, 943, 982, 1119, 1285

 

## Tasks

 

- [ ] Refactor User CRUD (2h)

- [ ] Refactor Password functions (1.5h)

- [ ] Refactor Session/Role functions (1.5h)

- [ ] Refactor Bulk operations (1.5h)

EOF

 

gh issue create \

  --repo $REPO \

  --title "[CRITICAL] Fix Transaction Management in user_service.py (10 violations)" \

  --body-file $ISSUES_DIR/issue-04.md \

  --label "critical,refactoring,database,P0" \

  --milestone "Week 1 - Emergency Fixes" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #4 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #4 may already exist${NC}"

 

# Issue #5: Transaction Management - pipeline_service.py

echo -e "${BLUE}Creating Issue #5: Transaction - pipeline_service.py...${NC}"

cat > $ISSUES_DIR/issue-05.md <<'EOF'

## Description

 

**Severity:** 🔴 CRITICAL

 

`pipeline_service.py` has **8 violations**.

 

## Tasks

 

- [ ] Audit functions (30m)

- [ ] Refactor 8 functions (3.5h)

- [ ] Update routers (30m)

- [ ] Testing (30m)

EOF

 

gh issue create \

  --repo $REPO \

  --title "[CRITICAL] Fix Transaction Management in pipeline_service.py (8 violations)" \

  --body-file $ISSUES_DIR/issue-05.md \

  --label "critical,refactoring,database,P0" \

  --milestone "Week 1 - Emergency Fixes" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #5 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #5 may already exist${NC}"

 

# Issue #6: Service Layer Purity

echo -e "${BLUE}Creating Issue #6: Service Layer Purity...${NC}"

cat > $ISSUES_DIR/issue-06.md <<'EOF'

## Description

 

**Severity:** 🟠 MEDIUM

 

Services importing FastAPI classes (UploadFile, status).

 

**Violations:**

- `user_service.py:8` - UploadFile

- `session_service.py:10` - status

 

## Tasks

 

- [ ] Remove UploadFile import (1h)

- [ ] Fix session_service import (30m)

- [ ] Update tests (30m)

EOF

 

gh issue create \

  --repo $REPO \

  --title "[MEDIUM] Remove FastAPI Dependencies from Service Layer" \

  --body-file $ISSUES_DIR/issue-06.md \

  --label "refactoring,architecture,P0" \

  --milestone "Week 1 - Emergency Fixes" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #6 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #6 may already exist${NC}"

 

# Issue #7: Remaining Transactions

echo -e "${BLUE}Creating Issue #7: Remaining Transactions...${NC}"

cat > $ISSUES_DIR/issue-07.md <<'EOF'

## Description

 

**Severity:** 🔴 CRITICAL

 

Complete transaction refactoring for 10 remaining services (20 violations).

 

**Services:**

- notification_service.py (4)

- application_service.py (3)

- notification_preference_service.py (3)

- tuition_discount_service.py (3)

- lead_service.py (2)

- 5 single-violation services (5)

 

## Tasks

 

- [ ] Refactor each service

- [ ] Update routers

- [ ] Final verification

EOF

 

gh issue create \

  --repo $REPO \

  --title "[CRITICAL] Fix Transaction Management in Remaining 10 Services (20 violations)" \

  --body-file $ISSUES_DIR/issue-07.md \

  --label "critical,refactoring,database,P1" \

  --milestone "Week 2-3 - Critical Fixes" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #7 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #7 may already exist${NC}"

 

# Issue #8: Rate Limiting

echo -e "${BLUE}Creating Issue #8: Rate Limiting...${NC}"

cat > $ISSUES_DIR/issue-08.md <<'EOF'

## Description

 

**Severity:** 🟠 HIGH - DoS Vulnerability

 

Only 5/195 endpoints (2.5%) have rate limiting.

 

**Missing:** 190 endpoints (admin, leads, applications, etc.)

 

## Tasks

 

- [ ] Create rate_limits.py (30m)

- [ ] Apply to admin routers (3h)

- [ ] Apply to feature routers (3h)

- [ ] Testing (1h)

- [ ] Monitoring setup (30m)

 

## Acceptance Criteria

 

- [ ] 100% endpoint coverage

- [ ] Rate limit tests pass

- [ ] 429 responses work correctly

EOF

 

gh issue create \

  --repo $REPO \

  --title "[HIGH] Implement Rate Limiting on All Endpoints (190 endpoints)" \

  --body-file $ISSUES_DIR/issue-08.md \

  --label "security,enhancement,P1" \

  --milestone "Week 2-3 - Critical Fixes" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #8 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #8 may already exist${NC}"

 

# Issue #9: Error Boundaries

echo -e "${BLUE}Creating Issue #9: Error Boundaries...${NC}"

cat > $ISSUES_DIR/issue-09.md <<'EOF'

## Description

 

**Severity:** 🟠 HIGH - Poor UX

 

Zero error.tsx files in frontend.

 

**Impact:** White screen on errors, no recovery

 

## Tasks

 

- [ ] Create reusable error components (1h)

- [ ] Add to 10+ routes (2h)

- [ ] Testing (30m)

- [ ] Documentation (30m)

 

## Acceptance Criteria

 

- [ ] 10+ error.tsx files

- [ ] Error recovery works

- [ ] Errors logged

EOF

 

gh issue create \

  --repo $REPO \

  --title "[HIGH] Add Error Boundaries to Frontend Routes" \

  --body-file $ISSUES_DIR/issue-09.md \

  --label "frontend,UX,enhancement,P2" \

  --milestone "Week 4 - UX Improvements" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #9 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #9 may already exist${NC}"

 

# Issue #10: Loading States

echo -e "${BLUE}Creating Issue #10: Loading States...${NC}"

cat > $ISSUES_DIR/issue-10.md <<'EOF'

## Description

 

**Severity:** 🟠 HIGH - Poor UX

 

Zero loading.tsx files in frontend.

 

**Impact:** White screen during loading

 

## Tasks

 

- [ ] Create skeleton components (1h)

- [ ] Add to 10+ routes (2h)

- [ ] Testing (30m)

- [ ] Documentation (30m)

 

## Acceptance Criteria

 

- [ ] 10+ loading.tsx files

- [ ] Smooth transitions

- [ ] No layout shift

EOF

 

gh issue create \

  --repo $REPO \

  --title "[HIGH] Add Loading States to Frontend Routes" \

  --body-file $ISSUES_DIR/issue-10.md \

  --label "frontend,UX,enhancement,P2" \

  --milestone "Week 4 - UX Improvements" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #10 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #10 may already exist${NC}"

 

# Issue #11: Suspense Boundaries

echo -e "${BLUE}Creating Issue #11: Suspense Boundaries...${NC}"

cat > $ISSUES_DIR/issue-11.md <<'EOF'

## Description

 

**Severity:** 🟡 MEDIUM - Performance

 

Only 9 Suspense boundaries. Need 20-30.

 

## Tasks

 

- [ ] Identify async components (1h)

- [ ] Wrap in Suspense (1h)

EOF

 

gh issue create \

  --repo $REPO \

  --title "[MEDIUM] Add Suspense Boundaries to Async Components" \

  --body-file $ISSUES_DIR/issue-11.md \

  --label "frontend,performance,enhancement,P3" \

  --milestone "Month 2 - Final Polish" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #11 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #11 may already exist${NC}"

 

# Issue #12: Admin Config IDOR

echo -e "${BLUE}Creating Issue #12: Admin Config IDOR...${NC}"

cat > $ISSUES_DIR/issue-12.md <<'EOF'

## Description

 

**Severity:** 🟡 MEDIUM

 

Admin config endpoints don't verify manager's unit ownership.

 

## Tasks

 

- [ ] Create dependency (1h)

- [ ] Update endpoints (30m)

- [ ] Tests (30m)

EOF

 

gh issue create \

  --repo $REPO \

  --title "[MEDIUM] Fix IDOR in Admin Config Unit Endpoints" \

  --body-file $ISSUES_DIR/issue-12.md \

  --label "security,enhancement,P3" \

  --milestone "Month 2 - Final Polish" \

  2>/dev/null && echo -e "${GREEN}  ✅ Issue #12 created${NC}" || echo -e "${YELLOW}  ⚠️  Issue #12 may already exist${NC}"

 

echo ""

echo -e "${GREEN}============================================${NC}"

echo -e "${GREEN}✅ All Issues Created Successfully!${NC}"

echo -e "${GREEN}============================================${NC}"

echo ""

echo -e "${YELLOW}Next steps:${NC}"

echo -e "1. View issues: ${BLUE}https://github.com/$REPO/issues${NC}"

echo -e "2. Run project board setup: ${BLUE}bash .github/scripts/setup_project_board.sh${NC}"

echo ""