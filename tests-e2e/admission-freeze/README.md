# E2E chạy tay — cần gạt đóng băng tuyển sinh (hai tầng)

Hai script ở đây đo **hành vi thật** của cần gạt đóng băng, không đọc lại hằng
số. Chúng chạy tay; guard tự động là
`Backend_FastAPI/tests/middleware/test_admission_freeze.py` (lát **Tier 4**).

## Vì sao có thư mục này

Trước bản vá, `FROZEN_PREFIXES` (middleware) và khối `location ~` (nginx) mỗi
bên giữ một bản sao riêng, cùng ghim ba tiền tố `/api/…` v1 và cùng được chú
thích *"verified against `feat/admission-full-cutover`"* — đúng ở thời điểm ấy.
Các router `/api/v2/` ra đời sau, không ai rà lại, nên **cả hai tầng** đều
không phủ đường ghi v2. `nginx -t` sạch, reload rc=0, test cũ vẫn xanh.

Đo được trên `main@0c3031d7`, `ADMISSION_FROZEN=true`:

| | backend trực tiếp | qua nginx |
|---|---|---|
| **trước** bản vá | 9/17 lệch — đường ghi v2 trả **403** (cổng auth), tầng freeze không chạm | 10/20 lệch — trả **200**, đi thẳng tới upstream |
| **sau** bản vá, freeze BẬT | 0/21 | 0/20 |
| **sau** bản vá, freeze TẮT | 0/21 | 0/20 |

(Cột "trước" đo bằng bản harness **chưa** cô lập — nó chạy alembic + sync +
lifespan lên CSDL dev. Không tái hiện được bằng bản hiện tại; giữ làm ghi chép
lịch sử, không phải quy trình.)

Cột "trước" là lý do thư mục này tồn tại: `403` và `200` đều **không phải** 503,
nghĩa là cần gạt không đóng — nhưng không lệnh nào báo lỗi.

## Chạy

Từ gốc kho. Cần Docker. Cả hai script **chứng minh** mình không chạm stack
dev/prod (xem `_bat_buoc_co_lap()` bên dưới) thay vì chỉ tuyên bố.

### A — backend trực tiếp (qua middleware thật, không stub)

```bash
bash tests-e2e/admission-freeze/run-smoke-backend.sh          # cả hai trạng thái
bash tests-e2e/admission-freeze/run-smoke-backend.sh true     # chỉ BẬT
```

Dùng wrapper, đừng gõ tay `docker run`: các cờ an toàn quá dễ sót và sót cái
nào cũng im lặng.

| Cờ | Thiếu nó thì |
|---|---|
| `--network none` | container còn interface ngoài loopback, tức vẫn có đường ra mạng. Qua `docker compose run` thì đó là mạng compose và chạm thẳng được postgres/redis (`--no-deps` chỉ không KHỞI ĐỘNG dependency, không ngăn kết nối); qua `docker run` trần thì là **bridge mặc định** — tên dịch vụ không phân giải nhưng egress vẫn mở |
| `--entrypoint python` | `docker compose run`/`docker run` chỉ thay CMD, **không** thay `ENTRYPOINT`, nên `docker-entrypoint.sh` vẫn chạy `alembic upgrade head` (DDL) và `sync_notification_rules` (ghi) |
| DSN sentinel | trỏ vào CSDL thật |
| (trong script) `uvicorn --lifespan off` | lifespan `create_all` bảng Casbin — lại là ghi |

Wrapper chỉ là lớp tiện lợi. `_bat_buoc_co_lap()` trong `smoke-backend.py` mới
là lớp bảo đảm, và nó **chứng minh** chứ không tin cờ:

- `DATABASE_URL`/`REDIS_URL` phải khớp **nguyên văn** hai sentinel. Bản trước
  parse host/port rồi thử kết nối, nên URL rỗng hoặc không parse được cho
  `host=None` ⇒ "không nghe" ⇒ bị coi là đã cô lập; một CSDL production đang
  tạm dừng cũng cho ra đúng kết luận ấy.
- `ADMISSION_FROZEN` phải là `"true"` hoặc `"false"`. Bản trước để thiếu thành
  `"?"` rồi xử như TẮT, nên smoke xanh mà không đo gì về trạng thái đóng băng.
- Container phải **không có interface nào ngoài loopback** — đây mới là phép
  đo trực tiếp của `--network none`. Bản trước hỏi "tên dịch vụ compose có
  phân giải được không", và đó là một false-green: trên **bridge mặc định** của
  Docker không có DNS nội bộ cho tên dịch vụ, nên chúng không phân giải trong
  khi container vẫn có `eth0`. Đo được:

  | lệnh | interface | DNS `postgres` |
  |---|---|---|
  | `docker run --network none …` | `['lo']` | không phân giải |
  | `docker run …` (bridge mặc định) | `['lo', 'eth0']` | không phân giải |

  Hai trạng thái khác hẳn nhau mà phép cũ cho cùng một kết luận.

Sai bất kỳ điều nào ⇒ thoát `3`, không đo gì cả.

Env truyền vào đều là giá trị giả, nên tiến trình đo không mang theo secret
thật nào. Vì CSDL cố ý không tới được, các đường không bị đóng băng có thể trả
5xx thay vì 401/403 — bất biến duy nhất được đo ở đây là *có phải 503 kèm
`code=ADMISSION_FROZEN`* hay không.

`ADMISSION_FROZEN` đọc lúc import `app.config`, nên phải đặt **khi TẠO** tiến
trình — cũng là lý do runbook cấm `docker compose restart`.

### B — qua nginx (dùng nguyên văn khối `location` trong template)

```bash
for v in true false; do
  docker run --rm -i -e NGINX_ADMISSION_FROZEN=$v \
    -v "$PWD/nginx:/nginx:ro" \
    -v "$PWD/tests-e2e/admission-freeze/smoke-nginx.sh:/tmp/smoke.sh:ro" \
    nginx:1.27-alpine sh -c 'apk add --no-cache curl gettext >/dev/null && sh /tmp/smoke.sh'
done
```

Phạm vi B là **khối freeze + upstream giả**, không gồm TLS/domain/rate-limit
thật của production — chỗ đó thuộc `scripts/nginx-apply.sh` +
`scripts/nginx-verify.sh`, và phải đo bằng **SNI thật** (`curl --resolve`).

## Cả hai script fail-closed ở đâu

- B thoát `3` nếu không thấy template, nếu trích khối ra **rỗng**, hoặc nếu
  trích ra **quá 40 dòng** (dấu hiệu awk nuốt tới cuối tệp vì CRLF).
- B thoát `3` nếu `envsubst` nuốt mất `$request_method` — bản trần sẽ thay cả
  biến của nginx, cho ra config vô nghĩa mà `nginx -t` vẫn sạch.
- A thoát `3` nếu uvicorn không lên trong 90s, thay vì báo "không có ca nào lệch".
- A thoát `3` nếu DSN không khớp nguyên văn sentinel, nếu `ADMISSION_FROZEN`
  không thuộc {`true`,`false`}, nếu còn interface ngoài loopback, hoặc nếu
  **danh sách interface rỗng**. Vế cuối quan trọng: mọi container thật luôn có
  ít nhất `lo`, nên rỗng LUÔN nghĩa là không liệt kê được — không được suy ra
  "chỉ có loopback". Phép kiểm rỗng đặt SAU cả hai đường `try`/`except`; đặt
  bên trong `except` thì một `if_nameindex()` trả `[]` mà không ném sẽ đi thẳng
  qua cổng.

  Kiểm ngược bốn trạng thái:

  | tiêm | mạng | rc | vì sao |
  |---|---|---|---|
  | — | `--network none` | 0 | `['lo']`, chạy 0/21 |
  | — | bridge | 3 | thấy `['eth0']` |
  | `if_nameindex()` → `[]` | `--network none` | 3 | danh sách rỗng ⇒ không liệt kê được |
  | `if_nameindex()` ném | bridge | 3 | fallback `/proc/net/dev` thấy `['eth0']` |

  Cả bốn đều dừng TRƯỚC khi dựng uvicorn.

## Khi thêm route tuyển sinh mới

Sửa **bốn** khai báo trong `Backend_FastAPI/app/middleware/admission_freeze.py`
(`ADMISSION_ROUTER_MODULES`, `NON_ADMISSION_ROUTER_MODULES`, `FROZEN_PREFIXES`,
`ADMISSION_WRITE_ROUTES`) và khối `location ~` trong
`nginx/templates/default.conf.template`.

Phân loại module là **thế giới đóng**: mọi module có route ghi phải thuộc đúng
một trong hai tập đầu. Nên nếu chỉ thêm router mà quên mọi thứ còn lại, CI vẫn
ĐỎ ngay ở ca `test_MOI_module_co_route_ghi_deu_da_duoc_phan_loai` — thay vì im
lặng bỏ qua như bản trước, vốn chỉ soi những gì đã nằm dưới tiền tố hoặc đã
nằm trong tập tuyển sinh.
