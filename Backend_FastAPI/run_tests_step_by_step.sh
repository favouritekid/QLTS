#!/bin/bash
# Script test từng bước để debug test environment
# Chạy: bash run_tests_step_by_step.sh

set -e  # Stop on first error

echo "=========================================="
echo "BƯỚC 1: Kiểm tra môi trường"
echo "=========================================="
echo "Python version:"
python --version
echo ""
echo "Current directory:"
pwd
echo ""
echo "Virtual environment:"
which python
echo ""

echo "=========================================="
echo "BƯỚC 2: Kiểm tra pytest installed"
echo "=========================================="
pytest --version
echo ""

echo "=========================================="
echo "BƯỚC 3: Test đơn giản nhất (smoke test)"
echo "=========================================="
echo "Running: pytest tests/test_smoke.py -v"
pytest tests/test_smoke.py -v
echo ""

echo "=========================================="
echo "BƯỚC 4: Test exceptions (no dependencies)"
echo "=========================================="
echo "Running: pytest tests/unit/utils/test_exceptions.py -v"
pytest tests/unit/utils/test_exceptions.py -v
echo ""

echo "=========================================="
echo "BƯỚC 5: Collect all tests (don't run)"
echo "=========================================="
echo "Running: pytest --collect-only"
pytest --collect-only | head -50
echo ""

echo "=========================================="
echo "✅ TẤT CẢ TESTS CHẠY THÀNH CÔNG!"
echo "=========================================="
echo "Môi trường test hoạt động tốt."
echo ""
echo "Để chạy tất cả unit tests:"
echo "  pytest tests/unit/ -v"
echo ""
echo "Để chạy một test cụ thể:"
echo "  pytest tests/unit/utils/test_exceptions.py::TestBaseAppException::test_default_values -v"
