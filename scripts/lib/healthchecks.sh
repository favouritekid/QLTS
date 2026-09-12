# scripts/lib/healthchecks.sh
#
# NGUỒN CHUẨN DUY NHẤT cho việc đọc URL ping và gửi ping.
#
# Hai script dùng nó: `celery-heartbeat-monitor.sh` và `backup-with-offsite.sh`.
# Chép đôi phần này ra hai nơi là tự tạo chỗ trôi: một bên siết cách xử lý bí
# mật, bên kia giữ nguyên đường rò — và không ai thấy, vì cả hai vẫn "chạy được".
#
# Tệp này KHÔNG tự chạy gì. Chỉ định nghĩa hàm. Dùng:
#     . "$(dirname "${BASH_SOURCE[0]}")/lib/healthchecks.sh"
#
# ── Luật về bí mật (áp cho MỌI hàm dưới đây) ───────────────────────────────
# URL ping là thông tin xác thực: ai có nó thì ping thay được, tức TẮT được
# cảnh báo. Nên nó chỉ được tồn tại ở hai chỗ:
#   1. biến shell KHÔNG export, trong tiến trình đang chạy;
#   2. stdin của curl, qua `--config -`.
# Tuyệt đối KHÔNG: argv (ai cũng đọc `/proc/<pid>/cmdline` qua `ps`),
# environment (tiến trình con thừa hưởng), stdout/stderr (log cron giữ rất lâu),
# tệp tạm (here-string `<<<` của bash ghi ra tệp tạm — nên không dùng).

# hc_url_an_toan <URL>
#   Trả 0 nếu URL dùng được. In một dòng WARN (KHÔNG kèm URL) rồi trả 1 nếu không.
#
#   Đây không phải phép "kiểm tra URL cho đẹp". Giá trị này được ghim vào một
#   TỆP CẤU HÌNH của curl dưới dạng `url = "…"`, nên:
#     * một dấu `"` đóng chuỗi sớm và phần còn lại thành chỉ thị cấu hình mới;
#     * một `\` là ký tự escape trong giá trị cấu hình của curl;
#     * một ký tự xuống dòng cho phép TIÊM thẳng chỉ thị khác — `proxy = …`,
#       `output = /etc/…`, `trace = …` — tức chuyển hướng hoặc ghi tệp dưới
#       quyền của tiến trình đang chạy.
#   Và bắt buộc `https`: một URL `http` biến ping thành thứ đọc được trên đường
#   truyền, mà chính URL ấy là mật khẩu.
hc_url_an_toan() {
    local url="${1:-}"
    [ -n "$url" ] || { echo "WARN: URL rong"; return 1; }
    case "$url" in
        https://?*) : ;;
        *) echo "WARN: URL khong phai https:// ⇒ tu choi ping"; return 1 ;;
    esac
    case "$url" in
        *'"'*|*'\'*)
            echo "WARN: URL chua dau nhay hoac backslash ⇒ tu choi ping"
            return 1 ;;
        *[[:space:]]*)
            echo "WARN: URL chua khoang trang/xuong dong ⇒ tu choi ping"
            return 1 ;;
    esac
    # Ký tự điều khiển và mọi byte không in được. `LC_ALL=C` để lớp ký tự không
    # đổi nghĩa theo locale của cron.
    if printf '%s' "$url" | LC_ALL=C grep -q '[^[:print:]]'; then
        echo "WARN: URL chua ky tu dieu khien ⇒ tu choi ping"
        return 1
    fi
    return 0
}

# hc_quyen_hop_le <MODE> <OWNER> <GROUP> <NGUOI_CHAY>
#   HÀM THUẦN: nhận giá trị đã đọc, không chạm hệ tệp. Tách ra để test gọi MÃ
#   THẬT với đủ tổ hợp, thay vì chép lại luật — và để luật cho `root` được kiểm
#   ở MỌI môi trường, kể cả runner CI không chạy bằng root.
#
#   Luật:
#     * mode phải là 600 hoặc 400 — mọi quyền của group/other đều bị loại. Đọc
#       được URL là ping success thay được, tức VÔ HIỆU hoá cảnh báo.
#     * tệp phải thuộc chính người đang chạy; nếu không, người khác ghi được nội
#       dung mà tiến trình này tin.
#     * chạy bằng root (đúng ca của cron production) thì group cũng phải là root.
hc_quyen_hop_le() {
    local mode="${1:-}" owner="${2:-}" group="${3:-}" nguoi_chay="${4:-}"
    case "$mode" in
        600|400) : ;;
        *) echo "quyen tep la ${mode:-khong doc duoc}, phai la 600 hoac 400"
           return 1 ;;
    esac
    if [ "$owner" != "$nguoi_chay" ]; then
        echo "tep thuoc '${owner}' nhung tien trinh chay bang '${nguoi_chay}'"
        return 1
    fi
    if [ "$nguoi_chay" = "root" ] && [ "$group" != "root" ]; then
        echo "chay bang root thi group phai la root, dang la '${group}'"
        return 1
    fi
    return 0
}

# hc_kiem_quyen <TEP>
#   In lý do (KHÔNG kèm bí mật) và trả 1 nếu tệp không đủ an toàn để tin.
#   Caller quyết định fail-closed hay chỉ cảnh báo.
hc_kiem_quyen() {
    local tep="${1:-}" mode owner group nguoi_chay
    if [ -L "$tep" ]; then
        # Symlink cho phép người ghi được thư mục cha chuyển hướng chỗ root đọc
        # bí mật, trong khi `stat` trên đích vẫn báo 600 root:root.
        echo "${tep} la symlink"
        return 1
    fi
    [ -f "$tep" ] || { echo "${tep} khong ton tai hoac khong phai tep thuong"; return 1; }
    mode=$(stat -c '%a' "$tep" 2>/dev/null || echo "")
    owner=$(stat -c '%U' "$tep" 2>/dev/null || echo "")
    group=$(stat -c '%G' "$tep" 2>/dev/null || echo "")
    nguoi_chay=$(id -un 2>/dev/null || echo "")
    hc_quyen_hop_le "$mode" "$owner" "$group" "$nguoi_chay"
}

# hc_doc_url <TEN_BIEN> <TEP>
#   In giá trị ra stdout. Trả khác 0 nếu tệp không đọc được, không có biến, biến
#   rỗng, hoặc giá trị KHÔNG an toàn — bốn ca đều có nghĩa "không có URL dùng
#   được", caller phải fail-closed.
#
#   `grep` chứ KHÔNG `source`: tệp bí mật là DỮ LIỆU. `source` biến một tệp cấu
#   hình thành đường thực thi mã dưới quyền root, và `set -a` quanh nó còn export
#   luôn bí mật sang mọi tiến trình con.
hc_doc_url() {
    local ten="$1" tep="$2" dong gt
    [ -r "$tep" ] || return 1
    dong=$(grep -E "^[[:space:]]*${ten}=" "$tep" 2>/dev/null | tail -1) || true
    [ -n "$dong" ] || return 1
    # `printf` là builtin và `tr`/`sed` chỉ thấy giá trị ở STDIN ⇒ không tiến
    # trình nào mang nó trong argv.
    gt=$(printf '%s' "${dong#*=}" | tr -d '\r' \
         | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
               -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/")
    [ -n "$gt" ] || return 1
    hc_url_an_toan "$gt" >/dev/null 2>&1 || return 3
    printf '%s' "$gt"
}

# hc_ping <URL_DAY_DU>
#   URL đi vào curl qua STDIN, không qua argv. Tham số của một HÀM shell không
#   sinh tiến trình nào nên nó không xuất hiện ở đâu ngoài bộ nhớ tiến trình này.
#   stderr bị nuốt có chủ ý: curl có thể nhắc lại địa chỉ trong thông báo lỗi, và
#   đích đến của dòng đó là log cron. Cái cần biết là MÃ THOÁT, caller tự log.
#
#   `-q` PHẢI là đối số ĐẦU TIÊN. `--config -` KHÔNG vô hiệu hoá cấu hình mặc
#   định: thiếu `-q` thì `~/.curlrc` vẫn được nạp trước, và một dòng trong đó đủ
#   để đổi `proxy`, thêm `output`, bật `trace` — tức chuyển hướng ping đi nơi
#   khác hoặc ghi chính URL ra tệp. Chỉ `-q` ở đầu mới bỏ qua tệp ấy.
#
#   `--proto '=https'` và `--proto-redir '=https'`: chốt giao thức ở TẦNG CURL,
#   độc lập với phép kiểm chuỗi bên trên. Một redirect sang `http://` hay `file://`
#   sẽ bị từ chối thay vì được đi theo.
hc_ping() {
    local url="${1:-}"
    hc_url_an_toan "$url" || return 3
    printf 'url = "%s"\n' "$url" \
      | curl -q --config - --proto '=https' --proto-redir '=https' \
             --fail --silent --max-time 10 --retry 3 --output /dev/null 2>/dev/null
}
