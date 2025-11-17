# tests/test_smoke.py
"""
Smoke test - kiểm tra môi trường pytest hoạt động.
Test đơn giản nhất không cần dependencies.
"""


def test_python_basics():
    """Test cơ bản: Python math works."""
    assert 1 + 1 == 2


def test_string_operations():
    """Test cơ bản: String operations work."""
    assert "hello".upper() == "HELLO"


def test_list_operations():
    """Test cơ bản: List operations work."""
    lst = [1, 2, 3]
    assert len(lst) == 3
    assert lst[0] == 1
