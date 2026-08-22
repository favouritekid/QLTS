# E2E chạy tay — phiên pytest phải kết thúc bình thường

`kiem-phien.py` đo ba điều theo **từng node**, không đọc cú pháp và không phụ
thuộc việc ai vá bằng cách nào:

1. không `INTERNALERROR`;
2. mã thoát là **1** (có test đỏ, phiên bình thường) chứ không phải **3**;
3. số node **thực thi** bằng số node **thu thập**, và node sentinel chỉ định
   phải có kết quả `passed`.

Vế 3 lấp đúng chỗ cổng độ phủ của nightly còn thiếu: cổng ấy chứng minh node đã
được **phân lát**, không chứng minh đã **thực thi**. shard-06 của run
`32513696715` phân lát 744 node, thực thi 737 — bảy test không bao giờ chạy mà
cổng vẫn xanh.

## Vì sao là JOB RIÊNG, không phải một node trong Tier 5

Nó dựng một tiến trình pytest con nạp cả ứng dụng. Khi bản đầu nằm **trong**
bộ test, tiến trình cha cũng là pytest đang giữ cả app, và cha + con vượt trần
1 GB của service `backend` trong `docker-compose.yml`. Đo được **1/5 lượt** đổ:

```
OSError: [Errno 12] Cannot allocate memory: '/app/app'
```

kể cả sau khi thêm `--noconftest` và dừng các dịch vụ dev. Một ca đỏ 1/5 lượt
trong PR gate còn hại hơn không có — nó dạy người ta bấm "re-run".

Tách ra thành script độc lập thì tiến trình cha chỉ là Python trần: **3/3 lượt
ổn định**.

CI gọi nó qua job `session-survival` trong `.github/workflows/backend-test.yml`,
và job gom `pytest` (required check) đòi job ấy phải `success`. Không gom vào
đó thì nó không thuộc cổng nào và PR gate vẫn xanh khi bất biến bị phá.

Các cổng **rẻ và tất định** vẫn nằm trong Tier 5:

- `tests/utils/test_file_helpers.py::test_khong_ro_ri_stdlib` — identity lúc chạy
- `tests/utils/test_file_helpers_guard.py` — quét tĩnh + bảng ca kiểm cho chính
  bộ quét + cặp đối chứng nhân quả (tệp bài tổng hợp, nhẹ)

## Chạy

Từ gốc kho:

```bash
docker compose run --rm -T --no-deps \
  -v "$PWD/Backend_FastAPI:/app" \
  -v "$PWD/tests-e2e:/e2e:ro" \
  backend bash -c 'pip install -r requirements-dev.txt -q && cd /app && \
    python /e2e/session-survival/kiem-phien.py \
      tests/utils/test_file_helpers.py test_khong_ro_ri_stdlib'
```

Tham số: `<đường-dẫn-tệp-test> [tên-node-sentinel]`.

## Mã thoát

| | |
|---|---|
| `0` | đạt |
| `1` | lệch — phiên chết, mã thoát ngoài {0,1}, thiếu node, hoặc sentinel không passed |
| `3` | **không đo được** — tiến trình con bị giết, **treo quá trần**, không thu thập được node, không ghi được JUnit XML |

Mã `3` tách riêng có chủ đích: không đo được thì **báo**, không suy ra là đạt.
Script nhận diện cả `rc=137`/`-9` và chuỗi `Cannot allocate memory`.

## Trần thời gian — ba lớp

Đây là cổng **required**, nên một lượt treo phải đỏ chứ không được đứng im tới
trần mặc định của Actions (6 giờ):

| lớp | giá trị |
|---|---|
| `timeout-minutes` của job `session-survival` | **15 phút** (900s) |
| `subprocess.run(timeout=…)` trong script | **120s** thu thập · **300s** chạy |
| `--timeout=60` cho lượt pytest được đo | 60s mỗi test |

Lớp thứ ba khác hai lớp trên về bản chất: nó để **chính pytest** cắt một test
treo, nhờ đó phiên vẫn kết thúc bình thường — đúng thứ cổng này đo.

**Ngân sách phải có biên**, nếu không ba lớp mất thứ tự:

```
setup (checkout + python + pip, có cache)   ~<= 180s
collect  (TRAN_THU_THAP)                      120s
chạy     (TRAN_CHAY)                          300s
--------------------------------------------------
xấu nhất                                      600s   <   900s
```

Bản đầu đặt job 600s trong khi hai subprocess tuần tự đã là 180 + 420 = 600s:
nếu collect gần chạm trần rồi lượt chạy treo, Actions giết job **trước** khi
script kịp bắt `TimeoutExpired` và trả mã `3` — mất đúng phần phân biệt "không
đo được" với "lệch". Đổi một trong ba số thì phải đổi cả ba chỗ: hằng số trong
script, `timeout-minutes` trong workflow, và bảng này.

## Đã đo

| trạng thái | kết quả |
|---|---|
| `main@de1f74d4` + bản vá | `rc=0` · thu thập 10 = thực thi 10 · sentinel `passed` · **3/3 lượt** |
| tiêm lại một `mocker.patch("os.path.commonpath", …)` vào fixture | `rc=1` · `DO: phiên pytest CHẾT giữa chừng` |

Ca thứ hai là phép kiểm ngược: nếu nó không đỏ thì ca thứ nhất không chứng minh
được gì.

**Không** khoá số ca đỏ. Tệp mục tiêu hiện có 9 ca đỏ vì test double lỗi thời
(ngoài phạm vi bản vá này); khi chúng được sửa thì con số ấy phải giảm bình
thường, không được biến thành hồi quy giả.
