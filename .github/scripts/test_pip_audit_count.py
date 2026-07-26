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

    # -------- nhánh skip: có khoá là CHƯA đủ, giá trị phải dùng được --------

    def test_skip_reason_null_raises(self):
        # REGRESSION: `"skip_reason" in dep` cho payload này đi qua → đếm 0.
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": [{"name": "a", "skip_reason": None}]})

    def test_skip_reason_empty_string_raises(self):
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": [{"name": "a", "skip_reason": ""}]})

    def test_skip_reason_whitespace_only_raises(self):
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": [{"name": "a", "skip_reason": "   "}]})

    def test_skip_reason_wrong_type_raises(self):
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": [{"name": "a", "skip_reason": 3}]})

    def test_skipped_entry_without_name_raises(self):
        # REGRESSION: entry không có cả tên dependency vẫn được tính 0.
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": [{"skip_reason": "x"}]})

    def test_name_empty_raises(self):
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": [{"name": "  ", "vulns": []}]})

    def test_name_wrong_type_raises(self):
        with self.assertRaises(MalformedAudit):
            count_vulns({"dependencies": [{"name": 42, "vulns": []}]})

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
