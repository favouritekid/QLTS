# Thư mục CỐ Ý không có `default.conf.template`.
#
# Mount nó đè lên `/etc/nginx/templates` là mô phỏng đúng thứ Docker daemon tự
# tạo khi bind source không tồn tại trên host: một thư mục RỖNG. Đo trên Docker
# 29.7.2, `create_host_path: false` chỉ ngăn Compose tạo chứ không ngăn daemon,
# và `up` vẫn exit 0 — nên đây là ca thật, không phải giả định.
#
# Kỳ vọng: guard `10-qlts-kiem-bien.sh` làm container DỪNG HẲN (exit 1), chứ
# không phải "lên rồi unhealthy". Cấu hình thật nằm trong image nên ca này chỉ
# xảy ra khi có ai mount đè.
