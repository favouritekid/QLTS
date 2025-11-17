#!/bin/bash
# run_tests_simple.sh
# Simplified test runner for PHASE 2A (no dependency management)
#
# IMPORTANT: Activate your virtual environment FIRST!
#   source venv/bin/activate
#
# Then run:
#   bash run_tests_simple.sh

set -e  # Exit on error

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}PHASE 2A: Running Tests (Simple)${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "app/main.py" ]; then
    echo -e "${RED}Error: Must run from Backend_FastAPI directory${NC}"
    exit 1
fi

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${RED}Error: Virtual environment not activated!${NC}"
    echo ""
    echo -e "${YELLOW}Please activate your virtual environment first:${NC}"
    echo "  source venv/bin/activate"
    echo ""
    echo "Then run this script again."
    exit 1
fi

echo -e "${GREEN}Virtual environment: ${VIRTUAL_ENV}${NC}"
echo ""

# Check if httpx is installed
if ! python -c "import httpx" 2>/dev/null; then
    echo -e "${YELLOW}Warning: httpx not found. Installing test dependencies...${NC}"
    pip install httpx pytest pytest-asyncio fakeredis redis
fi

# Set test environment
export APP_ENV=test
export TESTING=1

echo -e "${GREEN}Running PHASE 2A tests...${NC}"
echo ""

# Parse command line arguments
VERBOSE=""
COVERAGE=""
MARKER="tests/routers/admin/"

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

# Run tests
python -m pytest $MARKER $VERBOSE $COVERAGE --tb=short

# Check result
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✅ All tests passed!${NC}"
    echo -e "${GREEN}========================================${NC}"

    if [ -n "$COVERAGE" ]; then
        echo ""
        echo -e "${YELLOW}Coverage report saved to: htmlcov/index.html${NC}"
    fi
else
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}❌ Some tests failed${NC}"
    echo -e "${RED}========================================${NC}"
    exit 1
fi
