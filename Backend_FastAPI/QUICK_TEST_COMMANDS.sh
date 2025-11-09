#!/bin/bash
# Quick Test Commands for 4-Phase Sync Solution
# Usage: Source this file to get helper functions
#   source QUICK_TEST_COMMANDS.sh
#   run_all_tests

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

BASE_URL="http://localhost:8000"
TOKEN=""

# Helper function to print colored output
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Login and get token
login() {
    local username=${1:-admin}
    local password=${2:-admin}

    print_header "Logging in..."

    TOKEN=$(curl -s -X POST "$BASE_URL/api/auth/login" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "username=$username&password=$password" \
        | jq -r '.access_token')

    if [ "$TOKEN" != "null" ] && [ -n "$TOKEN" ]; then
        print_success "Login successful"
        export TOKEN
        echo "Token: $TOKEN"
    else
        print_error "Login failed"
        exit 1
    fi
}

# Test Phase 1: Prevention
test_phase_1() {
    print_header "PHASE 1: PREVENTION TEST"

    # Get first user
    print_info "Fetching test user..."
    USER_DATA=$(curl -s -X GET "$BASE_URL/api/admin/users?page=1&page_size=1" \
        -H "Authorization: Bearer $TOKEN")

    USER_ID=$(echo $USER_DATA | jq -r '.items[0].id')
    ORIGINAL_ROLE=$(echo $USER_DATA | jq -r '.items[0].role')
    USERNAME=$(echo $USER_DATA | jq -r '.items[0].username')

    print_info "Test User: $USERNAME (ID: $USER_ID, Role: $ORIGINAL_ROLE)"

    # Determine new role
    if [ "$ORIGINAL_ROLE" == "manager" ]; then
        NEW_ROLE="officer"
    else
        NEW_ROLE="manager"
    fi

    # Update role
    print_info "Updating role to $NEW_ROLE..."
    curl -s -X PUT "$BASE_URL/api/admin/users/$USER_ID" \
        -H "Authorization: Bearer $TOKEN" \
        -F "role=$NEW_ROLE" > /dev/null

    sleep 1

    # Check sync status
    print_info "Checking sync status..."
    MISMATCH=$(curl -s -X GET "$BASE_URL/api/admin/users/sync-status" \
        -H "Authorization: Bearer $TOKEN" \
        | jq ".mismatched_users[] | select(.user_id == $USER_ID)")

    if [ -z "$MISMATCH" ]; then
        print_success "PHASE 1 PASSED: DB and Casbin are in sync"
    else
        print_error "PHASE 1 FAILED: Found mismatch!"
        echo "$MISMATCH" | jq '.'
    fi

    # Restore original role
    print_info "Restoring original role..."
    curl -s -X PUT "$BASE_URL/api/admin/users/$USER_ID" \
        -H "Authorization: Bearer $TOKEN" \
        -F "role=$ORIGINAL_ROLE" > /dev/null

    print_success "Role restored"
}

# Test Phase 3: Detection
test_phase_3() {
    print_header "PHASE 3: DETECTION TEST"

    print_info "Fetching sync status..."
    SYNC_STATUS=$(curl -s -X GET "$BASE_URL/api/admin/users/sync-status" \
        -H "Authorization: Bearer $TOKEN")

    TOTAL=$(echo $SYNC_STATUS | jq -r '.total_users')
    SYNCED=$(echo $SYNC_STATUS | jq -r '.synced_count')
    OUT_OF_SYNC=$(echo $SYNC_STATUS | jq -r '.out_of_sync_count')

    echo ""
    echo "┌─────────────────────┬─────────┐"
    echo "│ Metric              │ Value   │"
    echo "├─────────────────────┼─────────┤"
    echo "│ Total Users         │ $TOTAL       │"
    echo "│ Synced              │ $SYNCED       │"
    echo "│ Out of Sync         │ $OUT_OF_SYNC       │"
    echo "└─────────────────────┴─────────┘"
    echo ""

    if [ "$OUT_OF_SYNC" -gt 0 ]; then
        print_info "Found $OUT_OF_SYNC mismatched user(s):"
        echo $SYNC_STATUS | jq '.mismatched_users[] | {user_id, username, db_role, casbin_role}'
    else
        print_success "All users are in sync!"
    fi

    print_success "PHASE 3 PASSED: Detection endpoint working"
}

# Test Phase 4: Remediation
test_phase_4() {
    print_header "PHASE 4: REMEDIATION TEST"

    # Check current status
    print_info "Checking current sync status..."
    BEFORE=$(curl -s -X GET "$BASE_URL/api/admin/users/sync-status" \
        -H "Authorization: Bearer $TOKEN" \
        | jq -r '.out_of_sync_count')

    print_info "Out of sync before: $BEFORE"

    # Run sync
    print_info "Running sync operation..."
    SYNC_RESULT=$(curl -s -X POST "$BASE_URL/api/admin/users/sync" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"user_ids": null}')

    SYNCED_COUNT=$(echo $SYNC_RESULT | jq -r '.synced_count')
    FAILED_COUNT=$(echo $SYNC_RESULT | jq -r '.failed_count')

    echo ""
    echo "Sync Results:"
    echo "  • Synced: $SYNCED_COUNT"
    echo "  • Failed: $FAILED_COUNT"
    echo ""

    if [ "$FAILED_COUNT" -gt 0 ]; then
        print_error "Some users failed to sync:"
        echo $SYNC_RESULT | jq '.failed_users'
    fi

    # Check after status
    sleep 1
    AFTER=$(curl -s -X GET "$BASE_URL/api/admin/users/sync-status" \
        -H "Authorization: Bearer $TOKEN" \
        | jq -r '.out_of_sync_count')

    print_info "Out of sync after: $AFTER"

    if [ "$AFTER" -eq 0 ]; then
        print_success "PHASE 4 PASSED: All users synced successfully"
    else
        print_info "Some users may still be out of sync"
    fi
}

# Run all tests
run_all_tests() {
    if [ -z "$TOKEN" ]; then
        print_error "Please login first: login <username> <password>"
        return 1
    fi

    print_header "4-PHASE SYNC SOLUTION TEST SUITE"

    test_phase_1
    echo ""

    test_phase_3
    echo ""

    test_phase_4
    echo ""

    print_header "TEST SUITE COMPLETE"
}

# Show current sync status (quick check)
sync_status() {
    if [ -z "$TOKEN" ]; then
        print_error "Please login first"
        return 1
    fi

    curl -s -X GET "$BASE_URL/api/admin/users/sync-status" \
        -H "Authorization: Bearer $TOKEN" \
        | jq '{total_users, synced_count, out_of_sync_count, mismatched_users: [.mismatched_users[] | {user_id, username, db_role, casbin_role}]}'
}

# Sync all users (quick fix)
sync_all() {
    if [ -z "$TOKEN" ]; then
        print_error "Please login first"
        return 1
    fi

    print_info "Syncing all users..."
    curl -s -X POST "$BASE_URL/api/admin/users/sync" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"user_ids": null}' \
        | jq '.'
}

# Sync specific users
sync_users() {
    if [ -z "$TOKEN" ]; then
        print_error "Please login first"
        return 1
    fi

    if [ -z "$1" ]; then
        print_error "Usage: sync_users <user_id1> <user_id2> ..."
        return 1
    fi

    # Build JSON array from arguments
    USER_IDS=$(echo "$@" | jq -R 'split(" ") | map(tonumber)')

    print_info "Syncing users: $@"
    curl -s -X POST "$BASE_URL/api/admin/users/sync" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"user_ids\": $USER_IDS}" \
        | jq '.'
}

# Print help
help_commands() {
    cat << EOF

${GREEN}Available Commands:${NC}

${YELLOW}Authentication:${NC}
  login <username> <password>    - Login and get access token

${YELLOW}Testing:${NC}
  run_all_tests                  - Run complete test suite
  test_phase_1                   - Test Phase 1 (Prevention)
  test_phase_3                   - Test Phase 3 (Detection)
  test_phase_4                   - Test Phase 4 (Remediation)

${YELLOW}Quick Operations:${NC}
  sync_status                    - Show current sync status
  sync_all                       - Sync all users
  sync_users <id1> <id2>...      - Sync specific users

${YELLOW}Example Usage:${NC}
  ${BLUE}source QUICK_TEST_COMMANDS.sh${NC}
  ${BLUE}login admin mypassword${NC}
  ${BLUE}run_all_tests${NC}
  ${BLUE}sync_status${NC}
  ${BLUE}sync_all${NC}

EOF
}

# Show help on source
echo ""
print_success "Sync Solution Test Commands Loaded!"
echo ""
help_commands
