# =============================================================================
# QLTS Nginx — cấu hình ĐI THEO IMAGE, không đi theo thư mục trên host
# =============================================================================
# Vì sao có tệp này (sự cố 12-08-2026 và bài học vòng hai của nó):
#
#   Vòng một: template nằm ở `nginx/conf.d/` — nơi entrypoint KHÔNG quét — nên
#   nó không bao giờ được render và nginx chạy với không một server block nào.
#
#   Vòng hai: chuyển template sang `nginx/templates/` rồi bind-mount thư mục đó
#   vào container. Nhưng bind-mount một thư mục KHÔNG tồn tại thì Docker daemon
#   TỰ TẠO nó rỗng — đo thật trên Docker 29.7.2: `create_host_path: false` chỉ
#   ngăn Compose tạo, daemon vẫn tạo, `up` vẫn exit 0. Kết quả y hệt vòng một,
#   cộng thêm việc vhost mặc định của image (`Welcome to nginx!`) lộ ra vì
#   không còn gì che nó ⇒ cổng 80 trả 200 OK trong lúc site chết.
#
# Nên cấu hình được COPY VÀO IMAGE:
#   * thiếu template ⇒ `docker build` ĐỎ, deploy dừng TRƯỚC khi mở traffic;
#   * không có thư mục host nào để daemon tạo rỗng;
#   * đổi nội dung template ⇒ đổi image ID ⇒ `up -d` tự recreate nginx, không
#     cần `--force-recreate` vô điều kiện (xem `scripts/deploy.sh` Step 8b).
#
# Muốn thử một template khác (các ca hồi quy E2E) thì mount đè
# `/etc/nginx/templates` — mount vẫn thắng nội dung image.
# =============================================================================
FROM nginx:1.27-alpine

# Vhost mặc định của image chính là trang "Welcome to nginx!" đã biến ca "không
# có config" từ một ECONNREFUSED ầm ĩ thành một 200 OK im lặng. Xoá hẳn: từ đây
# `include /etc/nginx/conf.d/*.conf` chỉ khớp đúng bản render của ta.
RUN rm -f /etc/nginx/conf.d/*.conf

COPY nginx.conf /etc/nginx/nginx.conf
COPY templates/ /etc/nginx/templates/
# Cấu hình cho container bootstrap của `scripts/setup-ssl.sh` (profile
# `bootstrap`). Nằm ở đường RIÊNG để không đụng cấu hình production, và cũng đi
# theo image chứ không bind-mount — cùng lý do với phần trên.
COPY bootstrap/nginx.conf /etc/nginx/nginx-bootstrap.conf
COPY bootstrap/default.conf.template /etc/nginx/templates-bootstrap/

COPY docker-entrypoint.d/ /docker-entrypoint.d/

# COPY không giữ bit thực thi khi build từ Windows; entrypoint chính thức bỏ qua
# (chỉ log "Ignoring") mọi tệp `.sh` không `-x` — tức guard sẽ im lặng không chạy.
RUN chmod +x /docker-entrypoint.d/*.sh
