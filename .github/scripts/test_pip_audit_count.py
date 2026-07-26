"""Chạy: python .github/scripts/test_pip_audit_count.py

Dùng unittest của thư viện chuẩn — job python-audit chỉ cài pip-audit, không
có pytest, và test này phải chạy được TRƯỚC khi tin vào số nó đếm.
"""

import unittest

from pip_audit_count import MalformedAudit, count_vulns


class CountVulnsTest(unittest.TestCase):
    def test_counts_across_dependencies(self):
        data = {
            "dependencies": [
                {"name": "a", "vulns": [{"id": "X"}, {"id": "Y"}]},
                {"name": "b", "vulns": []},
                {"name": "c", "vulns": [{"id": "Z"}]},
            ]
        }
        self.assertEqual(count_vulns(data), 3)

    def test_clean_report_is_zero(self):
        data = {"dependencies": [{"name": "a", "vulns": []}]}
        self.assertEqual(count_vulns(data), 0)

    def test_skipped_dependency_without_vulns_is_allowed(self):
        # pip-audit bỏ qua dep không resolve được và kèm skip_reason.
        data = {
            "dependencies": [
                {"name": "a", "skip_reason": "không tìm thấy trên PyPI"},
                {"name": "b", "vulns": [{"id": "X"}]},
            ]
        }
        self.assertEqual(count_vulns(data), 1)

    # ------------------------------------------------------------ fail closed

    def test_empty_object_raises(self):
        # REGRESSION: parser cũ trả 0 cho payload này → gate xanh mù.
        with self.assertRaises(MalformedAudit):
            count_vulns({})

    def test_dependency_without_vulns_key_raises(self):
        # REGRESSION: parser cũ trả 0 cho payload này.
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": [{}]})

    def test_dependencies_not_a_list_raises(self):
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": "oops"})

    def test_vulns_not_a_list_raises(self):
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": [{"name": "a", "vulns": 3}]})

    def test_dependency_not_an_object_raises(self):
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": ["a"]})

    def test_top_level_not_an_object_raises(self):
        with self.assertRaises(MalformedAudit):
            count_vulns([])


if __name__ == "__main__":
    unittest.main(verbosity=2)
