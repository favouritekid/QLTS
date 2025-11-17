#!/bin/bash
# run_phase2a_tests.sh
# Script to run PHASE 2A automated tests
#
# Usage:
#   ./run_phase2a_tests.sh              # Run all PHASE 2A tests
#   ./run_phase2a_tests.sh --verbose    # Run with verbose output
#   ./run_phase2a_tests.sh --coverage   # Run with coverage report

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}PHASE 2A: Running Automated Tests${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "app/main.py" ]; then
    echo -e "${RED}Error: Must run from Backend_FastAPI directory${NC}"
    exit 1
fi

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}Warning: No virtual environment detected${NC}"
    echo "Recommended: activate your virtual environment first"
    echo ""
fi

# Install dependencies if needed
echo -e "${YELLOW}Checking dependencies...${NC}"
if ! python -c "import httpx" 2>/dev/null; then
    echo -e "${YELLOW}Installing test dependencies...${NC}"
    pip install -r requirements.txt
fi

# Set test environment
export APP_ENV=test
export TESTING=1

# Parse command line arguments
VERBOSE=""
COVERAGE=""
MARKER=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose|-v)
            VERBOSE="-vv"
            shift
            ;;
        --coverage|-c)
            COVERAGE="--cov=app/routers/admin --cov-report=term-missing --cov-report=html"
            shift
            ;;
        --users)
            MARKER="tests/routers/admin/test_users.py"
            shift
            ;;
        --roles)
            MARKER="tests/routers/admin/test_roles.py"
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Default to running all admin tests
if [ -z "$MARKER" ]; then
    MARKER="tests/routers/admin/"
fi

# Run tests
echo -e "${GREEN}Running tests: $MARKER${NC}"
echo ""

pytest $MARKER $VERBOSE $COVERAGE --tb=short

# Check result
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✅ All PHASE 2A tests passed!${NC}"
    echo -e "${GREEN}========================================${NC}"

    if [ -n "$COVERAGE" ]; then
        echo ""
        echo -e "${YELLOW}Coverage report saved to: htmlcov/index.html${NC}"
        echo "Open in browser: file://$(pwd)/htmlcov/index.html"
    fi
else
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}❌ Some tests failed${NC}"
    echo -e "${RED}========================================${NC}"
    exit 1
fi
