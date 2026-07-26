"""Đếm lỗ hổng từ output ``pip-audit --format json``. FAIL CLOSED.

Parser cũ nằm inline trong workflow và mặc định hoá dữ liệu thiếu thành 0::

    vulns = data.get('dependencies', [])
    count = sum(len(d.get('vulns', [])) for d in vulns)

Payload ``{}`` hoặc ``{"dependencies": [{}]}`` đều cho ra 0, nên một lần
pip-audit hỏng (đổi schema, ghi ra file rỗng, lỗi mạng) sẽ khiến required
check ``Python Dependencies`` XANH mà chưa audit được gì.

Ở đây mọi hình dạng lạ đều nổ, vì "không đọc được kết quả" khác hẳn
"không có lỗ hổng".

CLI: python pip_audit_count.py <audit-results.json>  → stdout: số nguyên
"""

import json
import sys


class MalformedAudit(Exception):
    """Output pip-audit không đúng hình dạng kỳ vọng."""


def count_vulns(data):
    """Đếm tổng số vuln, ném MalformedAudit nếu payload không tin được."""
    if not isinstance(data, dict):
        raise MalformedAudit(
            f"payload gốc phải là object, nhận {type(data).__name__}"
        )

    if "dependencies" not in data:
        raise MalformedAudit(
            "thiếu khoá 'dependencies' — pip-audit nhiều khả năng không chạy "
            "tới nơi; KHÔNG coi đây là 0 lỗ hổng"
        )

    deps = data["dependencies"]
    if not isinstance(deps, list):
        raise MalformedAudit(
            f"'dependencies' phải là list, nhận {type(deps).__name__}"
        )

    total = 0
    for index, dep in enumerate(deps):
        if not isinstance(dep, dict):
            raise MalformedAudit(
                f"dependencies[{index}] phải là object, nhận "
                f"{type(dep).__name__}"
            )

        # Formatter JSON chính thức của pip-audit phát MỌI entry kèm 'name',
        # kể cả entry bị bỏ qua. Thiếu name = payload không phải của
        # pip-audit → không đáng tin.
        name = dep.get("name")
        if not isinstance(name, str) or not name.strip():
            raise MalformedAudit(
                f"dependencies[{index}] phải có 'name' là chuỗi không rỗng, "
                f"nhận {name!r}"
            )

        if "vulns" in dep:
            vulns = dep["vulns"]
            if not isinstance(vulns, list):
                raise MalformedAudit(
                    f"dependencies[{index}] ({name}).vulns phải là list, "
                    f"nhận {type(vulns).__name__}"
                )
            total += len(vulns)
            continue

        # Không có 'vulns' thì CHỈ chấp nhận khi pip-audit nói rõ vì sao bỏ
        # qua. Kiểm sự TỒN TẠI của khoá là chưa đủ: {"skip_reason": null},
        # {"skip_reason": ""} hay skip_reason sai kiểu đều sẽ khiến cả entry
        # bị đếm là 0 và required check xanh.
        skip_reason = dep.get("skip_reason")
        if not isinstance(skip_reason, str) or not skip_reason.strip():
            raise MalformedAudit(
                f"dependencies[{index}] ({name}) không có 'vulns', và "
                f"'skip_reason' không phải chuỗi không rỗng (nhận "
                f"{skip_reason!r})"
            )

    return total


def main(argv):
    if len(argv) != 2:
        print("Usage: python pip_audit_count.py <audit-results.json>",
              file=sys.stderr)
        return 2

    try:
        with open(argv[1], encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as err:
        print(f"❌ không đọc/parse được {argv[1]}: {err}", file=sys.stderr)
        return 1

    try:
        print(count_vulns(data))
    except MalformedAudit as err:
        print(f"❌ {err}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
