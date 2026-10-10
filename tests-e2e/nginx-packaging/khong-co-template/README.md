# Thư mục CỐ Ý không có `default.conf.template`.
#
# Mount nó đè lên `/etc/nginx/templates` là mô phỏng đúng thứ xuất hiện khi khai
# bind-mount bằng CÚ PHÁP NGẮN vào một source không tồn tại: một thư mục RỖNG,
# và `up` vẫn exit 0 — nên đây là ca thật, không phải giả định.
#
# ⚠️ Đính chính 21-09-2026: bản trước quy cho `create_host_path: false` "không
# ngăn daemon". SAI trên đường dẫn Linux đã đo — rc≠0 và Docker trả lỗi
# `bind source path does not exist`. Thứ tạo thư mục rỗng là cú pháp NGẮN.
# Xem `CLAUDE.md` → "Nginx & Deploy".
#
# Kỳ vọng: guard `10-qlts-kiem-bien.sh` làm container DỪNG HẲN (exit 1), chứ
# không phải "lên rồi unhealthy". Cấu hình thật nằm trong image nên ca này chỉ
# xảy ra khi có ai mount đè.
