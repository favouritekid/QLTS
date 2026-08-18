# Kịch bản Chrome smoke đầy đủ cho Finance

> Trạng thái tài liệu: runbook kiểm thử trên môi trường dev, không phải bằng chứng rằng hệ thống đã hết lỗi.
>
> Phạm vi đối chiếu gần nhất: `origin/main` tại **`2ca5d1a57520699a8acd9d531e72c96a80f5d1ac`** (14-08-2026) — đã bao gồm #541/#548/#550 (duplicate review), #552 (overpayment producer), #553 (nginx packaging), #554 (deploy gates).
>
> ⚠️ Checkpoint `SMK20260810` neo vào HEAD cũ `1b4c1854` và một runtime khác. Việc commit đó nay đã nằm trong `main` **không** biến checkpoint thành bằng chứng cho `2ca5d1a5`: lượt mới phải mở **RUN_ID mới** và attest lại runtime.
>
> Không được dùng tài liệu này để kiểm thử phá huỷ trên production hoặc trên dữ liệu thật.

## 0. Đọc các SHA trong tài liệu này thế nào

Tài liệu trộn hai loại câu, và nhầm chúng là cách dễ nhất để báo một lượt smoke là đạt
trong khi nó chưa hề chạy:

* **Bằng chứng lịch sử** — mọi con số neo vào `9950abe9` (và checkpoint `SMK20260810`
  neo `1b4c1854`). Chúng **mô tả quá khứ**: đã đo được gì, tại SHA nào, trên runtime nào.
  Chúng **KHÔNG** là bằng chứng cho `2ca5d1a5`, kể cả khi commit ấy nay đã nằm trong `main`.
* **Cổng phải chạy lại** — mọi phép kiểm muốn dùng cho lượt này. Chúng phải chạy **tại
  SHA đang smoke**, với **RUN_ID mới** và runtime đã attest lại.

Quy ước: câu nào mở đầu bằng "Tại `<sha>`" là **bằng chứng lịch sử tại sha đó**.
Muốn dùng lại kết luận ấy cho SHA hiện tại thì phải đo lại, không được chép sang.

⚠️ Hai *finding mở* ở §1 (return page · kỳ kế toán) đã được **kiểm lại tại
`2ca5d1a5` ngày 14-08-2026 và VẪN CÒN**: `can_record_transaction` grep toàn repo ra
đúng một dòng — chính dòng định nghĩa; `parseStatus` vẫn ghi `// Priority: query param >
intent status`. Hai ca FIN-17/D06 và FIN-19 vì vậy vẫn là **expected FAIL**.

## 1. Kết luận và mục tiêu

Không được kết luận “Finance đã hết lỗi”. Trạng thái đã xác minh tại HEAD nêu trên:

1. **P1 deadlock nhập lô đối đầu ghi tay đã đóng.** Thứ tự mới là toàn bộ Invoice liên quan → toàn bộ Fee; sau khi chạm Fee, import không xin thêm khóa Invoice. Ca hai session/barrier nằm ở `test_import_vs_manual_deadlock.py`, mốc đỏ tái hiện được là `0739946a`, bản sửa là `5f65309f`.
2. **Cổng backend cuối đã đạt:** Tier 1 + Tier 2b nguyên từ workflow trên container sạch: `944 passed, 2 skipped`, exit 0 tại `9950abe9`. Hai tệp khóa deadlock và `committed <=> payment_ids` đều xuất hiện trong log lượt chạy.
3. **Finding mở — return page:** `PaymentReturnClient` vẫn ưu tiên `status` trong query string hơn trạng thái intent backend. `?status=success&intent_id=<pending-or-failed>` có thể vẽ thành công giả. FIN-19 phải FAIL cho tới khi backend/callback đã xác minh trở thành nguồn có thẩm quyền.
4. **Finding mở — kỳ kế toán:** `AccountingPeriodService.can_record_transaction()` hiện không được đường ghi payment/import/refund gọi. Đóng kỳ vì vậy chưa chứng minh được rằng giao dịch có ngày trong kỳ đóng bị chặn. FIN-17.5 là expected FAIL hiện tại, không phải dependency bị thiếu.
5. **~~Giới hạn kiến trúc — nguồn overpayment~~ — ĐÃ HẾT HIỆU LỰC từ #552.** Câu cũ ("source không có đường production tạo `OverpaymentRecord`") đúng tại `9950abe9` nhưng **sai tại `2ca5d1a5`**: `payment_service.check_overpayment` sinh record qua `overpayment_amount=excess` + event `overpayment_recorded` ở MỌI đường settlement. ⇒ FIN-12..14 nay **phải** smoke E2E nguồn→xử lý: sinh khoản dư bằng đường thật (thu vượt số còn nợ), không seed thẳng bản ghi.
6. **Cổng frontend vẫn phải chạy lại trước Chrome:** số `944/2 skipped` chỉ là backend. FE đã đổi sau baseline `222 file / 2316 test` trước đó (các finding cache/disabled/response ở `24f046ab`), nên cần type-check + toàn Vitest + lint + attestation tại đúng source hiện tại; không được suy xanh từ việc các commit cuối chỉ chạm BE.

Runbook này nhằm phát hiện lỗi nghiệp vụ nhìn thấy được từ giao diện và đối soát các hậu điều kiện tiền bạc. Nó chỉ cho phép kết luận **GO smoke Finance tại đúng SHA đã chạy** khi đồng thời đạt cả bốn cổng:

- Cổng A — test tự động và migration tại đúng SHA;
- Cổng B — Chrome smoke qua giao diện thật;
- Cổng C — đối soát API/CSDL và audit sau mỗi hành trình;
- Cổng D — các test concurrency không thể chứng minh bằng Chrome.

Một toast “Thành công”, HTTP 2xx, trang không trắng hoặc test chỉ dùng `page.request` không đủ để coi nghiệp vụ đúng.

### 1.1. Gói thực thi

Không chạy 28 hành trình như một khối không checkpoint. Chia thành các gói độc lập; mỗi gói có fixture riêng và cleanup riêng:

| Gói | Mục tiêu | Ca | Điều kiện dừng |
|---|---|---|---|
| `P0 — preflight` | Source, migration, health, actor, seed và baseline | A01..A05 | Sai SHA/DB/migration/fixture → BLOCK toàn lượt |
| `P1 — core collection` | Tính phí, hóa đơn, thu tay, verify/reject, duplicate, cache, FIFO, import | FIN-00..09 | Sai tiền/payment IDs/deadlock → dừng mutation, đối soát ngay |
| `P2 — money out` | Refund, overpayment resolution, rút hồ sơ | FIN-10..14, FIN-24 | Sai balance hoặc state machine → không chạy accounting/export |
| `P3 — controls` | Fee/invoice, accounting, report/export, RBAC, target guard, biên ngày | FIN-15..18, FIN-20, FIN-25..26 | Quyền hoặc kỳ kế toán fail → verdict FAIL |
| `P4 — online/config` | Intent/return, responsive, discount/installment, commission, realtime | FIN-19, FIN-21..23, FIN-27 | Sandbox thiếu → chỉ FIN-19 gateway BLOCKED; finding code vẫn FAIL |
| `P5 — reconciliation` | Đối soát toàn cục, concurrency anchors và cleanup | Cổng C, D01..D06, §12 | Chênh một đồng hoặc còn rác → FAIL |

Mỗi gói phải có `checkpoint.json` ghi ca cuối đã hoàn tất, ID mới phát sinh và baseline delta. Khi tiếp tục sau gián đoạn, reload dữ liệu từ backend/DB; không tiếp tục từ state React đang mở dở.

### 1.2. Quyết định trước khi chạy

Tại `9950abe9` đã có thể chạy ngay `P1 — core collection`, `P2 — money out` và các phần không liên quan của `P3/P4` để tìm thêm lỗi. Tuy nhiên verdict cuối chắc chắn là `FAIL` cho tới khi:

1. return page không còn tin query `status` hơn intent backend và có ca UI chống success giả;
2. guard kỳ đóng được nối vào mọi đường ghi tiền, D06 xanh và kiểm ngược đạt;
3. ~~owner quyết định nguồn sinh OverpaymentRecord~~ — **ĐÃ GIẢI QUYẾT bởi #552**: nguồn là nghiệp vụ trong repo (`check_overpayment`). Không còn lý do ghi `SEEDED_RESOLUTION_ONLY` mặc định.

Không chờ sửa ba điểm mới bắt đầu các pack độc lập khác; nhưng không được dùng số ca xanh của chúng để che expected FAIL đã biết.

⚠️ **Trạng thái pack, cập nhật sau run `BL20260817A`**: `P1` nay có **đủ** seed, validator,
sổ hành động (`--action-begin`/`--action-end`) **và `--cleanup`** — lượt cleanup của
`BL20260817A` đã chạy thật, `rc=0`, vân tay khớp baseline. Câu cũ *"tại `2ca5d1a5` P1 chưa
có `--cleanup`"* đã hết hiệu lực.

`P2–P4` **vẫn chưa có fixture nào**. Chưa được chạy các ca refund/overpayment/withdrawal
bằng thao tác tay: mọi id phải được ghi atomically trước mutation (§A05), và không có đường
dọn fail-closed thì mỗi lượt thử là một đống rác không ai gỡ được.

## 2. Nguyên tắc bắt buộc

### 2.1. An toàn môi trường

- Chỉ chạy trên dev cục bộ với dữ liệu thử riêng.
- Ghi lại chính xác `branch`, `HEAD`, dirty/clean state, migration head và thời gian chạy.
- Bắt buộc có cờ chủ động `SMOKE_ALLOW_DESTRUCTIVE=1` trước mọi seed/cleanup có thay đổi dữ liệu.
- Bắt buộc truyền rõ `SMOKE_WEB_BASE=http://127.0.0.1:3100` và `SMOKE_API_BASE=http://127.0.0.1:8100`; không tự suy từ biến môi trường production.
  Đây là cổng của stack `qltssmoke` (`docker-compose.smoke.yml`), KHÔNG phải `3000`/`8000` của stack dev — trỏ nhầm là chạy smoke trên `qlts_dev`.
- Seed/cleanup phải từ chối chạy nếu `APP_ENV`, hostname, database name hoặc URL có dấu hiệu production.
- Không ghi mật khẩu, access token, review token, cookie hoặc thông tin cá nhân thật vào ảnh, log hay tệp bằng chứng.
- Không dùng `docker compose down`. Các container `qlts-g2-*` của worktree khác dùng chung compose project; chỉ `start/stop` từng service được phép động tới.
- Nếu cần xóa runner sau cùng, chỉ xóa đúng tên: `docker rm -f qlts-test-runner`.
- Không `TRUNCATE`, không xóa theo khoảng ID và không cleanup bằng điều kiện tên mơ hồ. Mọi bản ghi thử phải được lưu ID ngay lúc tạo.

### 2.2. Kỷ luật Chrome

- Hành động đang được smoke phải thực hiện bằng UI thật trong Chrome: mở trang, nhập form, chọn combobox, bấm nút và đọc kết quả hiển thị.
- API hoặc SQL chỉ được dùng để:
  - dựng fixture trước hành trình;
  - chụp baseline trước hành động;
  - đối soát hậu điều kiện sau hành động;
  - cleanup đúng các ID đã ghi.
- Không thay thao tác UI bằng `page.request`, `fetch` trong DevTools hoặc gọi endpoint rồi vẫn đánh dấu bước UI là đạt.
- Trước mỗi thao tác tự động, lấy snapshot DOM mới, chọn locator duy nhất và xác minh đúng đối tượng. Không đoán locator từ lượt render trước.
- Chờ tín hiệu nghiệp vụ có thẩm quyền: trạng thái, số tiền, mã phiếu, badge hoặc dữ liệu tải lại; không chỉ chờ animation/toast.
- Sau mutation, reload cứng hoặc đóng/mở lại màn hình ít nhất tại các điểm được chỉ định để bắt cache cũ.
- Ghi console error và request 4xx/5xx bất ngờ. Cảnh báo muốn bỏ qua phải có allowlist, lý do và owner.
- Chụp ảnh ở các mốc được yêu cầu, nhưng che token, tài khoản và dữ liệu nhạy cảm.
- Không dùng locator theo vị trí (`first/nth`) khi chưa đếm và chứng minh vị trí. Sau navigation, mở/đóng dialog, đổi tab, filter hoặc mutation phải lấy snapshot DOM mới.
- Trước click/fill/press: locator phải xuất phát từ snapshot hiện tại và resolve đúng một phần tử. Locator 0 hoặc >1 là lỗi kịch bản, không click cưỡng bức để “đi tiếp”.
- Với download, đăng ký chờ download trước khi click; lưu file vào thư mục evidence rồi mở và kiểm nội dung. Chỉ thấy nút hoặc sự kiện download không phải PASS.

### 2.3. Quy ước dữ liệu thử

Mỗi lượt chạy có một `RUN_ID` duy nhất:

```text
FIN-SMOKE-YYYYMMDD-HHMM-<sha8>
```

Mọi mã tham chiếu, ghi chú, tên fixture và file import phải chứa `RUN_ID`. Lưu registry cục bộ, không commit:

```text
.smoke-evidence/<RUN_ID>/registry.json
.smoke-evidence/dumps/<RUN_ID>.dump
```

`registry.json` (quản bởi `smoke_lib/registry.py`) tối thiểu phải ghi:

```json
{
  "run_id": "FIN-SMOKE-...",
  "git_sha": "9950abe9e91740166e31f6c525bad1a719befae2",
  "unit_ids": [],
  "user_ids": [],
  "lead_ids": [],
  "profile_ids": [],
  "fee_ids": [],
  "invoice_ids": [],
  "payment_ids": [],
  "payment_transaction_ids": [],
  "payment_import_batch_ids": [],
  "refund_request_ids": [],
  "overpayment_ids": [],
  "accounting_period_ids": [],
  "discount_policy_ids": [],
  "installment_plan_ids": [],
  "commission_policy_ids": [],
  "commission_record_ids": [],
  "download_files": []
}
```

Nếu đường dẫn `.smoke` chưa được ignore thì phải bổ sung ignore trước khi chạy, không được commit token hoặc evidence có dữ liệu nhạy cảm.

## 3. Cổng A — preflight trước khi mở Chrome

### A01. Chụp danh tính source

Chạy tại `D:\QLTS`:

```powershell
git status --short --branch
git rev-parse HEAD
git log -1 --oneline
```

Ghi kết quả vào manifest. Không dùng kết quả test của commit cũ cho HEAD mới.

### A02. Kiểm môi trường và migration

Xác nhận:

- URL trình duyệt là `http://127.0.0.1:3100`;
- API là `http://127.0.0.1:8100`;
- database là DB dev/test đã chỉ định, không phải production;
- Alembic đang ở head mà source yêu cầu;
- `fee.duplicate_guard_version` tồn tại;
- đủ bốn trigger bảo vệ `payment` và `refund_request`;
- constraint hai trục trạng thái import đang ở bản `CASE`, không phải bản `AND` cũ;
- không còn migration pending.

Nếu một mục sai: **BLOCK**, không tự “sửa DB cho khớp” rồi tiếp tục mà không ghi lại migration đã chạy.

### A03. Cổng tự động tại đúng SHA

Bắt buộc trước GO cuối:

- backend Tier 1 + Tier 2b nguyên văn từ workflow trên container sạch;
- frontend `type-check`, toàn bộ Vitest và lint qua `scripts/fe-check.sh`/`.cmd`, attestation source phải khớp;
- các test roundtrip HTTP cho xác nhận nghi trùng ghi tay và nhập lô;
- test migration/DDL chạy `create_all()` hai lượt;
- test concurrency ở mục 11.

Runner sống lâu có thể dùng để phát triển nhanh, nhưng không được dùng làm bằng chứng cổng cuối.

Baseline tại `9950abe9`: `944 passed, 2 skipped`, exit 0. Nếu HEAD, migration, workflow hoặc bất kỳ file BE liên quan thay đổi, baseline này hết hiệu lực và phải chạy lại. Không trích số cũ cho commit mới.

#### A03.1. Lượt test harness smoke tại máy — hình dạng lệnh là bắt buộc

Luật "runner sống lâu không được dùng làm bằng chứng" ở trên có một biến thể tinh vi
hơn: **container one-off cũng không sạch**. Mặc định `docker-compose.override.yml`
mount `./Backend_FastAPI:/app`, tức checkout dev, còn `smoke_finance_seed.py` thì
`sys.path.insert(0, "/app")` ngay ở module level. `scripts` không có `__init__.py` nên
là *namespace package*, portion lấy theo thứ tự `sys.path`. Hệ quả: tệp test nào import
script seed sẽ kéo `/app` lên đầu, và mọi `import scripts.*` sau đó đọc **cây nguồn
khác** với SHA đang xét. Lượt chạy khi ấy không nói gì về mã đang kiểm.

Ba hình dạng của `/app`, đo ngày 15-08 trên cùng một checkout:

| `/app` là gì | Kết quả |
|---|---|
| checkout dev (mount mặc định của override) | dừng ở collect: `no attribute 'BoCompose'` |
| bản sao **cùng nội dung** của chính worktree đang kiểm | 34 failed / 266 passed / 5 skipped |
| **thư mục rỗng** — hình dạng CI | `300 passed, 5 skipped` |

Cùng nội dung vẫn đỏ vì khi ấy tồn tại **hai định danh module cho một mã** (`smoke_lib.*`
do seed chèn, và `scripts.smoke_lib.*`). Vì vậy "bind checkout hiện tại vào `/app`"
không phải cách vá — nó còn phá thêm giả định `_GOC.parent == gốc kho` (các test tính
gốc kho bằng cha của thư mục chứa `scripts/`+`tests/`; đặt `Backend_FastAPI` thẳng vào
`/app` thì cha là `/`, sinh 44 ca đỏ dạng `thiếu /.env.smoke.app.example`).

Lệnh chạy, nguyên văn — chạy **từ gốc kho chính**, không từ worktree (cwd sai thì
Compose nạp nhầm bộ cấu hình và đổ ở `NEXT_PUBLIC_API_URL is required`):

```bash
MASK=/d/QLTS-smoke/.smoke-evidence/empty-app     # theo từng worktree; đã bị .gitignore che

kiem_che() {                                      # guard fail-closed, chạy TRƯỚC và SAU
  mkdir -p "$MASK" || return 2                    # mkdir hỏng ⇒ DỪNG, không đo tiếp
  found=$(find "$MASK" -mindepth 1 \( -type f -o -type l \) -print) || return 2
  [ -z "$found" ] || { echo "[CHẶN] thư mục che có tệp/symlink"; return 2; }
}

kiem_che || exit 2
rc=0
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T --entrypoint bash \
  -v "D:\QLTS-smoke:/repo" \
  -v "D:\QLTS-smoke\.smoke-evidence\empty-app:/app" \
  -w /repo/Backend_FastAPI -e QLTS_REPO_ROOT=/repo backend -c \
  "pip install -r requirements-dev.txt -q >/dev/null 2>&1 && \
   python -m pytest tests/unit/test_smoke_*.py -q --tb=line" || rc=$?
kiem_che || exit 2
exit "$rc"
```

Ba chi tiết của khối trên đều là hàng rào, không phải văn phong:

- **`&&` chứ không phải `;`** giữa `pip install` và `pytest`: cài đặt hỏng mà vẫn chạy
  pytest thì được một lượt "xanh" của bộ test chạy thiếu phụ thuộc.
- **`|| rc=$?` rồi `exit "$rc"`**: hậu-guard là lệnh CUỐI của khối, nên nếu không giữ
  lại mã thoát thì `docker`/`pytest` đỏ sẽ bị hậu-guard xanh **ghi đè**. Đo được: khối
  không giữ `rc`, lệnh trong container trả 7, mà cả khối trả **0**.
- **`find … -print || return 2`, không phải `find … | wc -l`**: mã thoát của một pipeline
  là mã của lệnh CUỐI, tức của `wc`. `find` hỏng vẫn cho `n=0` và guard kết luận "sạch".
  Đo được: `find` trên một đường dẫn không tồn tại vẫn cho `n=0`. `mkdir -p` cũng phải
  `|| return 2` — không dựng được thư mục che thì không có gì để đo.

`--entrypoint bash` thay hẳn ba cờ `RUN_*_ON_STARTUP=false`. Bỏ entrypoint thì không
alembic, không sync notification rule, không nạp Casbin — quên một cờ là chạy alembic
trên `qlts_dev`, đã vấp.

**Guard chạy hai đầu, và bắt cả symlink.** Bind không phải read-only (xem dưới), nên
container ghi được vào thư mục che; một symlink tên `scripts` trỏ ra ngoài là đủ dựng
lại đúng cây cạnh tranh mà cả mục này đang loại bỏ. Đã đo hai chiều: container
`ln -s /etc/passwd /app/…` trả rc=0 và symlink hiện sang host; guard đếm được và chặn.

**Thư mục che sẽ luôn có 7 thư mục rỗng — đó là bình thường, không phải ô nhiễm.**
`docker-compose.yml` khai năm named volume nằm **dưới** `/app` (`uploads`,
`app/static/uploads`, `private_exports`, `geoip`, `logs`); daemon phải tạo điểm mount
và `/app` là bind từ host nên chúng hiện lên host. Chúng rỗng, lượt chạy thứ hai vẫn
cho đúng số. Vì thế guard hỏi **"có TỆP hay SYMLINK không"**, không hỏi "có rỗng
không" — guard rỗng-tuyệt-đối sẽ chặn nhầm từ lượt thứ hai.

**Ba đường KHÔNG dùng:**

- `PYTHONPATH` — vô nghĩa: hai script chủ động `sys.path.insert(0, "/app")`, biến môi
  trường không quyết định được thứ tự.
- **Volume ẩn danh `-v /app`** — trông gọn và hôm nay còn xanh, nhưng Docker
  **copy-up nội dung image** vào volume rỗng: đo được `/app` hiện ra
  `.contract-allowlist.yaml`, `Dockerfile`… Image local dựng 19-07 tình cờ chưa có
  `scripts/smoke_lib`; build lại image là cây cạnh tranh **tự quay lại, im lặng**.
- **`:ro`** — `docker compose run -v …:ro` **không được áp**: trong container `touch`
  và `mkdir` đều rc=0 và tệp hiện ra trên host. `docker compose run` cũng không có
  `--mount`. Không được dựa vào read-only để bảo vệ thư mục che; guard mới là thứ bảo vệ.

⛔ **Chạy riêng từng tệp KHÔNG thay được lượt chạy chung.** Mọi hỏng hóc ở trên đều là ô
nhiễm chéo giữa các tệp trong cùng một tiến trình: `test_smoke_cli.py` chạy riêng cho
`45 passed, 2 skipped` ngay cả khi trong lượt chung nó đỏ 34 ca. Bằng chứng cổng phải là
**một lượt cho cả năm tệp**.

Oracle `300 passed, 5 skipped` neo tại `f598d156` trên `feat/smoke-stack-qltssmoke`.
Đây là số của một SHA, **không phải bất biến lâu dài**: thêm ca, đổi harness, đổi
workflow hay đổi image là hết hiệu lực và phải đo lại. Không trích số này cho SHA khác.

### A04. Khởi động dịch vụ có kiểm soát

Chỉ khởi động dịch vụ cần dùng; không gọi `down`:

```powershell
docker compose start postgres redis backend celery-worker celery-beat frontend
```

Chờ health thật:

- trang đăng nhập render được;
- API health trả đúng;
- migration không lỗi trong backend log;
- không có loop restart;
- Chrome console chưa có lỗi nền bất thường.
- celery worker/beat không loop restart và nhận đúng queue; nếu đang smoke notification/background task mà celery tắt thì ca là BLOCKED, không PASS nhờ gọi đồng bộ thủ công.

### A05. Seed phải tự chứng minh đúng hình dạng

Trước khi mở Chrome, seed/fixture validator phải exit non-zero nếu thiếu một trong các điều kiện:

- actor active, đúng role và unit; `ACC-A` và checker là hai user khác nhau;
- mỗi fixture trỏ tới đúng profile/fee/invoice độc lập theo bảng §5;
- Invoice cần thu ở trạng thái payable, số còn nợ đúng giá trị manifest;
- payment làm candidate nghi trùng nằm trong đúng cửa sổ ngày/số tiền;
- fixture FIFO có ít nhất hai Invoice payable và tổng remaining lớn hơn số sẽ thu;
- refund source payment là `verified`, số còn hoàn được đã trừ mọi refund pending/approved/refunded;
- profile rút có khoản tuition verified thực sự refundable;
- fixture dead-target có đủ `rejected`, `withdrawn`, `withdrawal_pending`, fee/invoice cancelled và fee `awaiting_accountant_confirmation`;
- kỳ kế toán bao phủ đúng ngày giao dịch theo múi giờ Việt Nam;
- overpayment fixture: từ #552 **đã có producer production** (`payment_service.check_overpayment` → `overpayment_amount=excess` → event `overpayment_recorded`), nên lượt mới phải sinh khoản dư **bằng đường thật** (thu vượt số còn nợ) chứ không seed thẳng bản ghi; chỉ dùng `seeded_resolution_only=true` khi đường thật không dựng được, và phải ghi lý do;
- mọi ID được ghi atomically vào `registry.json` trước khi bước Chrome đầu tiên chạy; ngoài ra mỗi action phải **khai dự kiến trước** rồi mới thao tác — danh sách cho phép điền sau khi đã thấy id lạ thì không chứng minh được gì. Khai bằng CLI, xem §A05.1; `registry.bat_dau_action()` là API bên dưới, không gọi tay.

Validator phải in một bảng `fixture_code -> IDs -> initial status -> amount`. Không dựa vào tên học sinh để tìm lại record sau mutation.

### A05.1. Sổ hành động — khai dự kiến TRƯỚC mỗi mutation

`registry.bat_dau_action()`/`ket_thuc_action()` có từ đầu nhưng cho tới 16-08-2026
**không có caller vận hành nào** — chỉ unit test gọi. Nghĩa là điều §A05 đòi hỏi
không thi hành được: bấm nút trên trình duyệt thì DB đổi trước, sổ ghi sau. Nay
dùng CLI, chạy TRÊN HOST (nó cần `docker`), từ gốc worktree smoke:

```bash
CID=$(docker compose -p qltssmoke -f docker-compose.yml -f docker-compose.smoke.yml \
      --env-file .env.smoke ps -q postgres)

# TRƯỚC khi bấm nút: khai ca và thay đổi dự kiến.
# KHÔNG khai bảng — cả 13 bảng của `BANG_THEO_DOI` được chụp TỰ ĐỘNG (xem dưới).
PYTHONPATH=Backend_FastAPI/scripts python -m smoke_lib.cli --action-begin \
  --run-id <RUN_ID> --thu-muc .smoke-evidence --pack P1 --container "$CID" \
  --ten <MÃ_CA> \
  --them-so-luong <bảng>=<N> [--them <bảng>=<id>] [--doi …] [--mat …]
# → in `chi_so=N`

#   … thao tác trên trình duyệt …

# SAU khi bấm: đối chiếu
PYTHONPATH=Backend_FastAPI/scripts python -m smoke_lib.cli --action-end \
  --run-id <RUN_ID> --thu-muc .smoke-evidence --pack P1 --container "$CID" \
  --chi-so N
```

Khai thay đổi bằng bốn cờ, dùng đúng cái hợp với ca:

| Cờ | Khi nào |
|---|---|
| `--them-so-luong payment=1` | server sinh id (hầu hết ca UI): chỉ biết **số lượng** |
| `--them payment=7` | id biết trước |
| `--doi invoice=4` | hàng đã có sẽ đổi nội dung |
| `--mat payment=3` | hàng sẽ biến mất |

Lệch **theo cả hai chiều** đều là dừng: thay đổi ngoài dự kiến làm mất khả năng
quy trách nhiệm, còn thay đổi đã khai mà KHÔNG xảy ra nghĩa là hệ thống không làm
việc ta vừa khẳng định nó làm.

⚠️ **Phạm vi quan sát không phải lựa chọn của người chạy.** CLI luôn chụp **cả 13
bảng** trong `registry.BANG_THEO_DOI` — `lead`, `admission_profile`, `fee`,
`invoice`, `payment`, `payment_transaction`, `payment_intent`,
`payment_import_batch`, `payment_import_row`, `refund_request`,
`overpayment_record`, `entity_audit_log`, `notification`. Không có cờ chọn bảng,
và đó là cố ý: một ca như FIN-02 chạm `fee`, `invoice`, `admission_profile`,
`entity_audit_log`, `notification` chứ không chỉ `payment`, còn người vận hành thì
sẽ quên.

Hệ quả khi khai dự kiến: **khai đủ mọi bảng mà ca thật sự làm đổi**. Khai thiếu là
LỆCH — đó là thiết kế, không phải phiền toái.

**Ca mới chưa biết chạm những bảng nào ⇒ quy trình RIÊNG, không làm trên run
nghiệm thu.** Đọc `ngoai_du_kien` rồi chép thẳng vào phần khai chính là điều §A05
cấm: danh sách cho phép điền sau khi đã thấy id lạ thì không chứng minh được gì —
và nếu delta ấy do lỗi sinh ra, thao tác đó **hợp thức hoá chính con bug**. Trên
run nghiệm thu nó cũng bất khả thi: action đã LỆCH thì máy trạng thái chỉ còn cho
`--cleanup`.

Đường đúng:

1. Mở một **run khám phá**, ghi rõ trong sổ là **không tính nghiệm thu**.
2. Chạy ca, đọc từng delta, **đối chiếu với contract/mã nguồn**: mỗi hàng phải
   giải thích được vì sao nó PHẢI xuất hiện. Không chép máy móc thành allowlist.
3. `--cleanup` run khám phá.
4. Mở **run-id MỚI**, baseline/bootstrap/seed lại từ đầu, rồi khai **toàn bộ kỳ
   vọng đã được xác nhận** ở bước 2 — trước mutation.

**Không sửa action hay registry của run cũ.** Bản khai chỉ có giá trị vì nó được
ghi trước khi biết kết quả; sửa lại sau là xoá đúng thứ làm nó thành bằng chứng.

⚠️ **Một CLI writer tại một thời điểm.** Sổ ghi bằng `os.replace` (atomic trong
một tiến trình) nhưng **không có khoá liên tiến trình**: hai lệnh `--action-begin`
chạy song song vẫn có thể đè nhau. Không chạy hai lượt smoke cùng lúc trên một sổ.

Bốn cổng chạy trước mỗi lần, không chỉ lần đầu: sổ phải đúng project + database +
**pack**; sổ phải đã có baseline; danh tính PostgreSQL thật phải khớp `danh_tinh`
ghi lúc baseline (cùng container VÀ cùng `system_identifier`).

⚠️ `--pack` bắt buộc. Trước 16-08 sổ chỉ kiểm project và database, nên seeder P1
chạy được trên sổ mở cho P2 — `smoke_finance_seed.py` chỉ dựng fixture P1 (không
có `F-REFUND-*`), và cleanup sau đó restore theo baseline của gói kia.

### A05.2. React #418 (hydration mismatch) — chính sách có điều kiện

Đo 16-08-2026 trên stack smoke, persona `ACC-A`: #418 xuất hiện **2 lần** trong
giai đoạn ngay sau đăng nhập (cách nhau 41 giây); điều hướng trực tiếp `/finance`
và `/dashboard/officer` sau đó **không** tái hiện. Chưa quy được nguyên nhân —
Socket.io có hoạt động nhưng không có bằng chứng nó là gốc.

Hậu quả kỹ thuật: React vứt cây HTML do server dựng rồi dựng lại ở client. Không
ghi DB, nhưng **thứ vừa nhìn thấy trên DOM có thể không còn là thứ đang có**. Vì
mọi kết luận smoke dựa trên quan sát DOM, xử lý như sau:

* **#418 TRƯỚC mutation**: bỏ ảnh chụp DOM/locator cũ, lấy lại mới rồi mới tiếp.
* **#418 TRONG hoặc NGAY SAU mutation**: **dừng ca đó**, đối chiếu API/DB trước.
  Tuyệt đối không retry theo cảm giác — sổ hành động đã khai dự kiến, retry mù là
  cách chắc chắn nhất để tạo bản ghi thứ hai.
* Ghi **timestamp + route** của mỗi lần #418 vào evidence.

FIN-00 vì vậy là **FAIL đã biết**, không phải PASS — nhưng nó không chặn P1.
Không gọi FIN-00 là PASS khi #418 còn xuất hiện.

## 4. Persona và ma trận quyền

Tạo sáu tài khoản thử, mỗi tài khoản có mật khẩu riêng và đúng một mục đích:

| Mã | Vai trò | Dùng để chứng minh |
|---|---|---|
| `ACC-A` | Accountant, đơn vị A | Ghi tiền, xác minh/từ chối, import, lập/chi refund, apply/refund overpayment |
| `MGR-A` | Manager, đơn vị A | Miễn/tính lại phí, hủy/phạt hóa đơn, duyệt/từ chối refund, void import, write-off |
| `ADM-A` | Admin | Dựng cấu hình/kỳ kế toán, thao tác quản trị và cleanup |
| `OFF-A` | Officer, đơn vị A | Thu application fee qua hồ sơ; chứng minh không có quyền Finance ngoài phạm vi |
| `ACC-B` | Accountant, đơn vị B | Kiểm IDOR chéo đơn vị |
| `CTV-A` | Cộng tác viên gắn đơn vị A | Kiểm hoa hồng tự phục vụ và che dữ liệu lead |

Quy tắc maker/checker:

- Người tạo refund không tự duyệt nếu policy yêu cầu tách vai.
- Payment do `ACC-A` ghi phải được verify/reject bằng actor được policy cho phép và không rơi vào đường tự xác minh trái luật.
- Mỗi ca âm phải chứng minh cả hai vế: nút không hiện/disabled **và** request giả lập không được backend chấp nhận.

## 5. Fixture tối thiểu

Fixture được tạo bằng seed riêng, deterministic và idempotent theo `RUN_ID`. Không dùng dữ liệu ngẫu nhiên không ghi registry.

| Mã | Dữ liệu đầu vào | Mục đích |
|---|---|---|
| `F-APP` | Hồ sơ đủ điều kiện thu application fee, chưa thu | Thu lệ phí hồ sơ qua tab Học phí |
| `F-FULL` | Hồ sơ có một khoản phí và một hóa đơn một đợt | Luồng thu tay cơ bản |
| `F-FIFO` | Khoản phí có ít nhất hai hóa đơn/đợt còn nợ | Phân bổ FIFO, thu tách nhiều hóa đơn |
| `F-DUP` | Hóa đơn có một payment phù hợp luật dò trùng | Luồng 409 -> review token -> xác nhận |
| `F-REJECT` | Hóa đơn riêng để ghi rồi từ chối | Không làm tăng tiền đã thu |
| `F-IMPORT` | Tối thiểu 6 dòng: hợp lệ, sai dữ liệu, không match, nghi trùng, hai dòng cùng Fee, dòng phân bổ FIFO | Preview/commit/retry/projection/void |
| `F-REFUND-OK` | Payment verified đủ số dư hoàn | Create -> approve -> process |
| `F-REFUND-NO` | Payment verified khác | Create -> reject |
| `F-OVER-APPLY` | Overpayment pending sinh bằng **đường thật** (thu vượt số còn nợ ⇒ `check_overpayment`); chỉ seed thẳng khi ghi rõ lý do | Apply **toàn bộ** sang nghĩa vụ khác cùng profile |
| `F-OVER-REFUND` | Overpayment pending seeded khác | Tạo refund từ tiền thừa; record chỉ đóng khi chi hoàn thành |
| `F-OVER-WO` | Overpayment pending seeded khác | Manager write-off toàn bộ |
| `F-FEE-OPS` | Ba fee độc lập | Waive, recalculate, cancel |
| `F-INV-OPS` | Ba invoice độc lập | Issue/penalty/cancel, replacement/supplemental nếu UI hỗ trợ |
| `F-PERIOD` | Kỳ kế toán hiện hành có ngày bao phủ dữ liệu thử | Summary/close và hàng rào sau close |
| `F-MAJOR` | Hồ sơ có thay đổi ngành cần confirm, nếu feature/data bật | Confirm major change |
| `F-IDOR-B` | Fee/invoice/payment thuộc đơn vị B | Chặn truy cập chéo đơn vị |
| `F-CONFIG` | Discount policy và installment plan mới, chưa được tham chiếu | CRUD cấu hình và snapshot khi tính phí |
| `F-COMMISSION` | Lead của CTV đạt trigger tạo commission và một record độc lập để reject | Policy -> record -> approve/reject/pay |
| `F-WITHDRAW` | Hồ sơ có tuition payment verified, còn số refundable; thêm một refund manual độc lập | Rút hồ sơ -> auto-refund -> finalize/cancel-withdrawal |
| `F-DEAD-TARGET` | Năm target độc lập: profile rejected/withdrawn/withdrawal_pending, fee/invoice cancelled, fee chờ xác nhận đổi ngành | Chứng minh mọi đường ghi tiền fail closed |
| `F-DATE` | Dữ liệu quanh 23:59/00:00 giờ VN, cuối tháng/năm và kỳ kế toán tương ứng | Ngày thu, mã hoàn, report/export và period boundary |

Trước lượt đầu, chụp baseline cho từng fixture:

- `fee.status`, `fee.total_amount`, `fee.paid_amount`, `duplicate_guard_version`;
- từng `invoice.status`, `total_amount`, `paid_amount`, `due_date`, `installment_no`;
- số lượng/payment IDs theo invoice;
- refund/overpayment hiện có;
- tổng dashboard, debt report và kỳ kế toán;
- audit count và notification count liên quan.

## 6. Quy ước bằng chứng

Mỗi ca dùng mã `FIN-xx`. Evidence tối thiểu:

```text
<RUN_ID>/FIN-xx/
  01-before.png
  02-action.png
  03-visible-result.png
  dom-before.txt
  dom-after.txt
  network.txt
  api-after.json
  db-after.txt
  console.txt
  downloads/
  result.md
```

`result.md` phải ghi:

- persona;
- URL;
- thời điểm;
- input nghiệp vụ;
- trạng thái/số tiền nhìn thấy trước và sau;
- ID bản ghi sinh ra;
- API/DB invariant đã đối soát;
- lỗi console/network;
- `PASS`, `FAIL` hoặc `BLOCKED` kèm lý do.
- locator đã dùng và số phần tử match trước thao tác;
- request mutation quan sát được: method, path, status, correlation/request ID nếu có; tuyệt đối không ghi review token/cookie.

Không được ghi `PASS` nếu thiếu `db-after` cho mutation tiền.

### 6.1. Macro thực thi cho từng bước Chrome

Áp dụng cùng một chuỗi, không ứng biến giữa các ca:

1. Ghi persona, URL, fixture IDs và baseline tiền/trạng thái.
2. Lấy DOM snapshot hiện tại; lưu excerpt chứa heading, target row/card và action.
3. Tạo locator từ snapshot, đếm và yêu cầu đúng một match.
4. Chụp `before` nếu hành động sắp làm đổi dữ liệu hoặc visual layout là bằng chứng.
5. Thực hiện đúng một action. Với double-click case, đó là input có chủ ý và phải ghi rõ.
6. Chờ tín hiệu có thẩm quyền: URL, dialog state, status badge hoặc refetch xong; không dùng sleep cố định làm oracle.
7. Lấy snapshot mới, console log và failed request sau state change.
8. Chụp `visible-result`; che dữ liệu nhạy cảm.
9. Đối soát API/DB theo ID. Nếu sai, dừng gói ngay trước khi fixture khác bị nhiễm.
10. Reload cứng hoặc mở lại bằng phiên mới tại checkpoint được yêu cầu; đối soát lần hai.
11. Ghi `result.md`, cập nhật `checkpoint.json` và registry ID atomically.

Với hai phiên, đặt tên rõ `maker`/`checker`; không dùng chung cookie jar rồi tưởng là hai actor. Với ca cache, không reload trước thời điểm cần quan sát stale/refetch vì reload sẽ phá chính điều kiện đang đo.

## 7. Chrome smoke theo thứ tự bắt buộc

Thứ tự dưới đây nhằm tránh dùng chung fixture đã bị biến đổi. Không đổi thứ tự nếu chưa cập nhật lại ma trận dữ liệu.

### FIN-00 — đăng nhập, điều hướng và tải trang

Chạy lần lượt với `ACC-A`, `MGR-A`, `ADM-A`, `OFF-A`; dùng `ACC-B`/`CTV-A` ở các ca phạm vi riêng:

1. Đăng nhập qua UI.
2. Mở trực tiếp và qua menu các trang:
   - `/finance`;
   - `/finance/fees`;
   - `/finance/invoices`;
   - `/finance/payments`;
   - `/finance/payments/import`;
   - `/finance/refunds`;
   - `/finance/overpayments`;
   - `/finance/accounting`;
   - `/finance/debt-report`.
   - `/finance/payments/return` không nằm trong menu; chỉ mở bằng URL có fixture intent ở FIN-19, không tính việc mở trần route này là navigation PASS.
3. Kiểm page title, heading, loading -> loaded, empty/error state và breadcrumb.
4. Reload cứng mỗi trang trọng yếu.
5. Xác nhận actor không có quyền nhận 404/403 đúng contract, không thấy chớp nội dung nhạy cảm trước khi bị chặn.

Đạt khi không có trang trắng, hydration error, redirect loop, 5xx hoặc quyền hiển thị sai.

### FIN-01 — dashboard và số liệu đầu kỳ

Persona: `ACC-A`.

1. Mở `/finance`.
2. Ghi bốn card: Chờ xác minh, Hóa đơn quá hạn, Thu hôm nay, Thu trong kỳ.
3. Mở từng quick action và quay lại.
4. Đổi filter thời gian/đơn vị nếu có.
5. Đối chiếu số hiển thị với API dashboard và truy vấn DB baseline.

Đạt khi card, danh sách đích và bộ lọc dùng cùng phạm vi đơn vị/thời gian.

### FIN-02 — thu application fee từ hồ sơ tuyển sinh

Persona: `OFF-A`; fixture `F-APP`.

1. Mở hồ sơ tuyển sinh bằng UI, vào tab Học phí.
2. Xác nhận application fee hiển thị đúng số tiền nguồn máy chủ; không tự suy giá ở client.
3. Chọn phương thức, nhập mã tham chiếu có `RUN_ID`, bấm thu đúng một lần.
4. Reload trang và mở lại tab.
5. Kiểm trạng thái lệ phí, mã giao dịch và hành động tiếp theo.

Đối soát bắt buộc:

- đúng một Fee, Invoice, Payment và PaymentTransaction được tạo/reconcile;
- số tiền bằng payload có thẩm quyền;
- payment/invoice/fee liên kết đúng hồ sơ;
- `fee_status` hồ sơ đã cập nhật;
- Lead chuyển trạng thái đúng luật nếu contract yêu cầu;
- bấm lại hoặc replay không sinh lần thu thứ hai;
- actor ngoài phạm vi không gọi được endpoint.

### FIN-03 — tính phí và phát hành hóa đơn

Persona: `ACC-A` cho calculate/issue; fixture mới thuộc `F-FULL` hoặc hồ sơ calculable riêng.

1. Từ dashboard bấm “Tính phí mới”.
2. Chọn hồ sơ từ picker bằng thông tin hiển thị, không dùng ID đoán.
3. Mở tuition preview, ghi base amount, discount, total và installment plan.
4. Tính phí qua UI.
5. Mở fee detail và invoice workspace.
6. Phát hành hóa đơn.
7. Reload và xác nhận trạng thái vẫn giữ.

Đối soát:

- tổng các installment bằng total fee;
- không có invoice âm/0 ngoài contract;
- trạng thái fee/invoice đúng;
- calculate double-click không tạo fee thứ hai;
- audit có actor và before/after phù hợp.

### FIN-04 — ghi payment tay rồi verify

Persona ghi: `ACC-A`; fixture `F-FULL`.

1. Từ `/finance/invoices`, lọc đúng invoice.
2. Bấm nút có tên truy cập “Thu tiền hóa đơn …”.
3. Kiểm số còn phải thu và pending amount vừa được refetch; trong lúc fetch phải hiện skeleton/khóa Lưu.
4. Nhập số tiền, ngày kế toán, phương thức, reference chứa `RUN_ID`.
5. Double-click nút Lưu nhanh; chỉ một request được chấp nhận.
6. Đóng/mở lại dialog.
7. Mở tab Chờ xác minh ở workspace và `/finance/payments`, tìm payment pending vừa tạo; online intent không được lẫn vào hàng manual pending.
8. Thử verify bằng chính maker: backend phải từ chối và payment vẫn pending.
9. Đăng xuất/đổi phiên sang checker khác maker, verify qua UI.
10. Reload invoice, fee, payments và dashboard.

Đối soát sau bước 5:

- đúng một payment `pending`;
- invoice/fee `paid_amount` chưa tăng nếu contract chỉ tăng khi verified;
- pending amount hiển thị đúng và ngăn thu vượt.

Đối soát sau verify:

- payment `verified`, có verifier/time;
- invoice và fee tăng đúng số tiền một lần;
- status `partial`/`paid` đúng số còn lại;
- `duplicate_guard_version` tăng;
- dashboard/debt thay đổi đúng;
- audit/notification chỉ phát một lần;
- reload/retry verify không cộng tiền lần hai.
- ngày thu hiển thị đúng ngày lịch Việt Nam đã nhập, không lùi một ngày do UTC.

### FIN-05 — ghi payment rồi reject

Persona: `ACC-A`; fixture `F-REJECT`.

1. Ghi payment pending qua dialog thật.
2. Từ danh sách payment bấm Từ chối, nhập lý do.
3. Reload toàn bộ bề mặt liên quan.

Đối soát:

- payment là `rejected`, giữ lý do/actor/time;
- invoice và fee `paid_amount` không tăng;
- pending amount giảm đúng;
- không tạo overpayment/refund;
- không thể verify payment đã rejected;
- audit và notification đúng một lần.

### FIN-06 — hàng rào nghi trùng khi ghi tay

Persona: `ACC-A`; fixture `F-DUP`.

> ⏱️ **Phiếu soát sống 15 phút — chuỗi phải chạy LIỀN MẠCH.**
>
> `duplicate_review_token.py` đặt `TTL_GIAY = 15 * 60`; `soat_phieu` fail-closed khi quá
> hạn. Nghĩa là **409 → tick xác nhận → submit lại** phải xong trong 15 phút kể từ lúc
> server cấp phiếu, tính từ **lần 409 cấp phiếu**, không phải từ lúc mở dialog.
>
> Đo được ở `BL20260817A`: chuỗi bị tách làm hai cổng duyệt, khoảng cách **17'56"** ⇒
> `POST /api/payments` trả **409** dù client có gửi phiếu (`co_gui_phieu=True`), và
> **không hàng nào được tạo**. Đó là hành vi đúng, không phải lỗi — nhưng nếu không biết
> thì rất dễ ghi nhầm thành "hàng rào chặn cả lượt hợp lệ".
>
> Vì vậy: **đừng chèn cổng phê duyệt vào giữa chuỗi này.** Nếu phiếu quá hạn, lấy phiếu
> mới bằng một lượt 409 mới rồi chạy lại liền mạch.

1. Mở dialog thu tiền và nhập dữ liệu khớp candidate đã seed.
2. Bấm Lưu; phải nhận giao diện `review_required`, thấy danh sách candidate, tổng và dấu hiệu truncated nếu có.
3. Không tick xác nhận, bấm tiếp: không được gửi quyền ghi.
4. Tick xác nhận và bấm Lưu.
5. Quan sát request thứ hai chỉ qua kết quả UI/log test; không lộ token trên DOM/storage/log.
6. Reload invoice/payment để đối soát.

Đạt khi:

- lần đầu không tạo payment;
- snapshot warning là một khối: token + candidates + total + truncated;
- lần hai dùng đúng review token do phản hồi 409 cấp, không dùng cờ legacy;
- ghi đúng một payment;
- lần submit thành công làm token cũ hết hiệu lực;
- replay token không tạo payment thứ hai.

Ca biến thể bắt buộc:

- sửa trường ràng buộc (invoice, phương thức, số tiền hoặc ngày): cảnh báo/tick bị xóa và phải soát lại;
- chỉ sửa ghi chú: không mất lượt soát;
- 409 thiếu token hoặc payload méo: không có đường xác nhận;
- candidate thay đổi giữa hai lần submit: token cũ bị từ chối, UI hiển thị snapshot mới;
- hơn 20 candidate: UI nói “hơn 20”/truncated, không báo 21 là tổng chính xác;
- đóng/reopen dialog: token cũ không hồi sinh;
- double-click ở `submitting` và `submitting_with_token`: chỉ một request.

### FIN-07 — cache cũ và mở lại dialog

Persona: **`ACC-A` và `ACC-B` — hai tài khoản KHÁC NHAU**; fixture riêng **`F-CACHE`**.

> 🔴 **Không dùng hai phiên của cùng `ACC-A`.** Hệ giữ **một phiên hoạt động cho mỗi
> người dùng**: đăng nhập lần hai **thu hồi** phiên trước. Đo được ở `BL20260817A` —
> `session 1`, `session 2` và `session 4` đều bị đặt `revoked_at`. Kịch bản "hai phiên
> cùng ACC-A" của bản runbook cũ **không dựng được**, không phải vì thiếu fixture mà vì
> chính sách single-active-session.
>
> Fixture phải là **`F-CACHE` riêng**: không tái dùng dữ liệu đã bị FIN-04/05/06 làm đổi,
> vì khi ấy không phân biệt được "cache cũ" với "dữ liệu đã đổi từ ca trước".

1. Phiên `ACC-A` mở dialog trên fixture `F-CACHE`, ghi nhận remaining/pending rồi đóng.
2. Phiên `ACC-B` tạo hoặc verify một payment làm dữ liệu thay đổi.
3. Phiên `ACC-A` mở lại dialog ngay khi cache còn dữ liệu.
4. Quan sát từ lúc mở đến khi refetch xong.

Đạt khi:

- trong lúc `isFetching`, remaining/pending cũ không được dùng như dữ liệu đã xác minh;
- có skeleton/loading phù hợp;
- nút Lưu bị khóa;
- sau fetch hiển thị số mới;
- không có cửa sổ nhập trùng do danh sách pending rỗng cũ.

### FIN-08 — phân bổ FIFO nhiều đợt (đường **import**)

Persona: `ACC-A`; fixture `F-FIFO`.

> 🔴 **Ghi tay là invoice-scoped — đây là contract, không phải lỗi.**
>
> `payment_service.py:406` chặn `amount > invoice.remaining_amount` bằng
> `BusinessRuleViolation`. Một khoản thu ghi tay khoá vào **đúng một** invoice và không
> được vượt phần còn lại của chính invoice đó. Phân bổ FIFO qua nhiều installment **chỉ
> tồn tại ở `payment_import_service.py`**; `grep FIFO frontend/src` trả **0** kết quả.
>
> Bản runbook cũ yêu cầu *"thu số tiền vượt invoice thứ nhất"* bằng UI ghi tay — thao tác
> đó **không thi hành được** và đã làm FIN-08 bị ghi `BLOCKED_CONTRACT` ở `BL20260817A`.
> Không mở rộng ghi tay thành cross-invoice để chiều kịch bản; kiểm FIFO ở đúng nơi nó sống.

**Phần A — ghi tay phải TỪ CHỐI, zero-delta.**

1. Mở fee có ít nhất hai invoice theo installment.
2. Ghi tay một khoản **vượt `invoice.remaining_amount`** của invoice thứ nhất.
3. Đạt khi: HTTP **400**, thông điệp `BusinessRuleViolation`, và **delta rỗng trên cả 13
   bảng** của `BANG_THEO_DOI` — không payment, không transaction, không đổi `paid_amount`.

**Phần B — FIFO chạy qua `/finance/payments/import`.**

4. Vào `/finance/payments/import`, nạp file có một dòng cho fee nhiều installment với số
   tiền vượt invoice đầu nhưng nhỏ hơn tổng còn nợ.
5. **Preview**: đối chiếu phân bổ dự kiến theo installment/due order **trước** khi commit.
6. **Commit**, rồi reload fee detail và từng invoice.

FIN-08 tập trung **preview + commit FIFO**. Các nhánh **retry và void** của đường import
vẫn thuộc **FIN-09**, không lặp ở đây.

Đối soát:

- phân bổ invoice theo installment/due order đã định;
- invoice đầu đủ tiền trước invoice sau;
- tổng payment thực tế bằng số nhập;
- tổng `paid_amount` các invoice bằng phần đã phân bổ;
- fee `paid_amount` không bị cộng lặp;
- audit linkage giữ đúng payment IDs của từng phần;
- không bỏ qua phép so số tiền chỉ vì một dòng bị tách FIFO.

### FIN-09 — import payment: preview, commit, retry và void

Persona commit: `ACC-A`; persona void: `MGR-A`; fixture/file `F-IMPORT`.

1. Mở `/finance/payments/import`.
2. Tải template từ UI (cả Excel lẫn CSV), mở file và kiểm:
   - **Header/định dạng — kiểm BẮT BUỘC.** Tên cột phải khớp `TEMPLATE_COLS`
     trong `payment_import_service.py`; CSV phải có BOM UTF-8 (thiếu là Excel
     locale VN đọc mojibake); parser khớp theo TÊN cột và chỉ đòi
     `REQUIRED_COLS`. Đã PASS tại `SMK20260810`.
   - **Template version — `NOT_SUPPORTED`.** Không tệp mẫu nào mang dấu phiên
     bản và parser cũng không kiểm; đây là giới hạn thiết kế đã biết, KHÔNG
     phải lỗi của lượt chạy. Không được ghi PASS trọn vẹn cho mục này. Muốn có
     contract versioning thì mở backlog/PR riêng — không mở rộng phạm vi PR
     đang mở.
3. Điền file có `RUN_ID` với tối thiểu các dòng:
   - hợp lệ một hóa đơn;
   - hai dòng cùng Fee cùng cần soát;
   - nghi trùng;
   - phân bổ FIFO;
   - dữ liệu sai;
   - không match.
4. Upload bằng UI và Preview.
5. Trước commit, đối soát DB: chưa có payment mới.
6. Kiểm `validation_status` từng dòng và tổng counter preview.
7. Commit lần một.
8. Kiểm dòng committed, failed và `duplicate_review_required` bằng trường máy đọc được; không dựa vào message tiếng Việt.
9. Với từng dòng bị giữ, xem snapshot, tick xác nhận và bấm “ghi tiếp”. Request phải mang đúng token theo từng `row_no`.
10. Reload batch result và tải file kết quả.
11. Dùng `MGR-A` void đúng batch qua UI; sau đó thử void/retry lại.
12. Ca conflict của bản vá deadlock. Khe thật KHÔNG phải khoảng thời gian giữa hai pha nhìn từ người dùng: pha commit chụp trọn tập Invoice của các Fee liên quan ngay khi bắt đầu, nên một đợt hoá đơn phát hành trước lúc bấm "Ghi tiền" sẽ nằm gọn trong ảnh chụp và commit chạy bình thường. Khe nằm TRONG LÒNG transaction commit — giữa lượt khoá toàn bộ Invoice và lượt khoá toàn bộ Fee (`payment_import_service.py`, quanh dòng 1478): đợt hoá đơn nào xuất hiện đúng lúc đó thì đường này không được phép xin thêm khoá Invoice, nên chỉ còn lối dừng sạch.
    Vì vậy ca phải có một phiên điều phối giữ khoá Fee để commit đứng chờ. Dùng psql là hợp lệ và cần thiết — thao tác được smoke (commit lô) vẫn đi trọn qua UI:
    - phiên psql: `BEGIN; SELECT id FROM fee WHERE id IN (<các fee trong lô>) ORDER BY id FOR UPDATE;` rồi giữ khoảng 15 giây;
    - trong lúc đó, UI bấm "Ghi tiền" → xác nhận. Commit khoá xong Invoice rồi đứng chờ Fee;
    - phiên psql `INSERT` một đợt hoá đơn mới cho một Fee trong lô rồi `COMMIT` để nhả khoá.
    Kỳ vọng: commit dừng sạch bằng 409 nêu đích danh id hoá đơn mới; không payment nào của lượt đó được ghi; lô giữ nguyên `preview`; UI hiển thị lỗi kèm hành động, không phải success giả. Sau đó reload rồi commit lại từ đầu với tập Invoice mới.
    Dọn dẹp: đợt hoá đơn chèn tay là RÁC — xoá bằng transaction có điều kiện (khoá đúng ID, kiểm `payment`/`payment_intent`/`overpayment_record` đều rỗng vì `payment_intent.invoice_id` là ON DELETE CASCADE, `DELETE ... RETURNING` đúng số dòng, đối soát tổng invoice về đúng `final_amount` rồi mới commit).

Đối soát commit:

- dòng committed có `payment_ids` không rỗng; dòng chưa committed có `payment_ids` rỗng;
- constraint `committed <=> payment_ids` giữ hai chiều;
- retry bỏ qua dòng đã committed và giữ nguyên bookkeeping của nó;
- payment của lượt trước được đưa vào tập loại trừ khi dò trùng;
- `total_amount` bằng tổng payment thật liên kết batch, không phải tổng tạm;
- các counter là projection từ trạng thái dòng, không drift;
- hai dòng cùng Fee được soát trọn vẹn trước lần ghi đầu và cùng ghi được sau một lượt xác nhận;
- token dòng này không xác nhận được dòng khác/batch khác;
- candidate thay đổi thì token cũ bị từ chối;
- batch chỉ đóng khi không còn dòng cần review theo contract;
- response HTTP thật -> token từng dòng -> retry thật đi trọn vòng.
- import auto-verified phải cập nhật invoice/fee ngay theo payment thật; không tạo hàng manual pending chờ checker.
- không có `40P01`, timeout hoặc partial commit khi phiên ghi tay cùng hoạt động; hậu quả DB được canh bởi D01, còn UI phải hiển thị conflict/retry có hành động rõ ràng thay vì success giả.

Đối soát void:

- chỉ đúng payment IDs của batch bị đảo;
- invoice/fee balances trở về đúng số trước batch;
- không resurrect invoice cancelled hoặc fee waived/cancelled;
- batch có trạng thái void/audit đúng;
- retry void không đảo lần hai;
- refund tạo đồng thời không được đi xuyên hàng rào payment lock.

### FIN-10 — refund được duyệt và chi

Persona tạo/chi: `ACC-A`; duyệt: `MGR-A`; fixture `F-REFUND-OK`.

1. `ACC-A` mở `/finance/refunds`, tạo yêu cầu hoàn cho payment verified.
2. Tạo yêu cầu **một phần**, rồi thử lập thêm yêu cầu vượt `payment.amount - pending - approved - refunded`: phải bị chặn.
3. Thử tự duyệt bằng chính requester: phải bị maker-checker chặn.
4. `MGR-A` khác requester mở item và Duyệt.
5. Reload invoice/fee/payment trước khi chi; approved chưa được trừ balance.
6. `ACC-A` bấm Chi tiền hoàn; một ca để trống reference để kiểm mã `HT-<id>-<ngày VN>`, một ca nhập reference riêng.
7. Reload mọi màn hình liên quan.

Đối soát:

- create tạo một request pending và chưa giảm balance;
- approve đổi trạng thái nhưng chưa ghi nhận chi tiền nếu contract quy định vậy;
- process chỉ chạy từ trạng thái hợp lệ;
- approve và process đều revalidate số còn hoàn được; yêu cầu có amount stale/vượt khả dụng không được mắc kẹt ở trạng thái đã duyệt không lối ra;
- reference chi tiền sinh/ghi tại thời điểm process;
- payment/refund/invoice/fee liên kết đúng;
- balances giảm đúng một lần tại đúng transition;
- trigger tăng guard version của cả Fee cũ và mới nếu refund chuyển payment/fee liên kết;
- replay process không chi hai lần;
- audit và notification đúng actor, đúng một lần.

### FIN-11 — refund bị từ chối

Persona tạo: `ACC-A`; từ chối: `MGR-A`; fixture `F-REFUND-NO`.

1. Tạo request qua UI.
2. Manager từ chối và nhập lý do.
3. Reload, thử approve/process request đã rejected.

Đạt khi request ở `rejected`, balances không đổi, lý do hiển thị đúng và không có đường process.

### FIN-12 — overpayment apply

Persona: `ACC-A`; fixture `F-OVER-APPLY`.

1. Mở `/finance/overpayments` và detail.
2. Bấm “Áp dụng tiền nộp thừa”.
3. Chọn nghĩa vụ đích hợp lệ cùng profile. Để trống amount hoặc nhập đúng **toàn bộ** `overpayment_amount`.
4. Xác nhận, reload cả nguồn và đích.

Ca âm bắt buộc:

- nhập amount nhỏ hơn tổng: backend phải từ chối vì partial apply chưa được hỗ trợ;
- amount lớn hơn remaining của invoice đích: từ chối;
- invoice thuộc profile/unit khác, cancelled hoặc profile ở trạng thái không payable: từ chối;
- sau apply thành công, retry/apply/refund/write-off cùng record đều bị chặn.

Đối soát phương trình bảo toàn:

```text
opening_overpayment = applied + refunded + written_off + closing_available
```

Nghĩa vụ đích tăng đúng toàn bộ phần apply, nguồn đóng `applied` đúng một lần; không apply chéo profile/đơn vị hoặc vượt remaining. Hiện không có partial balance còn lại hợp lệ.

### FIN-13 — overpayment refund

Persona: `ACC-A`; fixture `F-OVER-REFUND`.

1. Bấm “Tạo yêu cầu hoàn tiền nộp thừa”.
2. Khi refund còn pending/approved, thử apply/refund/write-off lại: tất cả phải bị chặn bởi linked open refund.
3. Chạy nhánh reject: link được giải phóng và overpayment trở lại trạng thái có thể xử lý.
4. Trên fixture khác, hoàn tất approve -> process theo vai trò.
5. Reload overpayment và refund list.

Đạt khi một refund request được liên kết; overpayment chỉ chuyển `refunded` sau khi chi hoàn thực sự. Reject không làm mất liability; process/retry không nhân đôi.

### FIN-14 — overpayment write-off

Persona: `MGR-A`; fixture `F-OVER-WO`.

1. Bấm “Xóa sổ tiền nộp thừa”.
2. Nhập lý do bắt buộc.
3. Reload và thử lặp lại.

Đối soát: chỉ manager/admin có quyền, số write-off đúng, balance không âm, không apply/refund được phần đã xóa sổ, audit đầy đủ.

### FIN-15 — thao tác trên fee

Persona: `MGR-A`; fixtures `F-FEE-OPS`.

Chạy trên ba fee độc lập:

1. Waive: xác nhận lý do, fee/invoice về trạng thái đúng, không còn thu được tiền.
2. Recalculate: kiểm preview trước/sau, tổng installment, balance và audit.
3. Cancel: chặn nếu đã có payment/refund không tương thích; nếu hợp lệ thì trạng thái đúng và không còn hành động thu.
4. Với `F-MAJOR`, xác nhận major change rồi kiểm tính lại/khóa đúng contract.

Ca quyền âm: `ACC-A` không thấy và không gọi được waive/recalculate/cancel.

### FIN-16 — thao tác trên invoice

Persona: `ACC-A` cho issue; `MGR-A` cho penalty/cancel; fixtures `F-INV-OPS`.

1. Issue invoice draft.
2. Apply penalty cho invoice hợp lệ; đối chiếu total và audit.
3. Cancel invoice hợp lệ; xác nhận không thu được sau cancel.
4. Mở VietQR/chuyển khoản, kiểm amount/reference/beneficiary đúng invoice.

Không quét hoặc thanh toán thật. QR smoke chỉ chứng minh dữ liệu hiển thị và intent trong sandbox.

Backend có endpoint supplemental/replacement nhưng frontend hiện không có action/consumer tương ứng. Không viết “nếu UI có” rồi cho qua: ghi rõ `NOT_EXPOSED_IN_UI`; kiểm contract hai endpoint ở regression API riêng. Nếu nghiệp vụ yêu cầu kế toán thực hiện chúng trên UI, đây là finding sản phẩm chứ không phải ca Chrome PASS.

### FIN-17 — kỳ kế toán

Persona: `ADM-A` cho create/close; `ACC-A` chỉ đọc; fixture `F-PERIOD`.

1. Mở `/finance/accounting`, xem current period và summary.
2. Tạo kỳ mới chỉ khi không phá kỳ đang dùng và fixture cho phép.
3. Đối chiếu opening/inflow/refund/closing với payment/refund đã chạy.
4. Close kỳ qua UI.
5. Thử đủ bốn mutation có ngày thuộc kỳ đã đóng: ghi tay, import, verify payment pending và process refund.
6. Mở lại summary sau reload.

Đạt khi:

- accountant không tự create/close;
- close không xảy ra khi summary/invariant chưa hợp lệ;
- mọi mutation sau close bị chặn trước khi ghi payment/transaction/balance;
- số tổng không đổi do reload/cache;
- audit close đầy đủ.

Nếu hệ thống không có route reopen công khai thì không được “test reopen” bằng gọi service/SQL và tính là UI pass.

**Trạng thái source tại `9950abe9`: expected FAIL.** `can_record_transaction()` chỉ tồn tại trong `AccountingPeriodService`, không có caller ở payment/import/refund. Ca này phải chạy để lấy bằng chứng, nhưng không được đổi FAIL thành PASS chỉ vì màn hình close hiển thị thành công.

### FIN-18 — debt report, dashboard và export

Persona: `ACC-A`/`MGR-A` theo quyền.

1. Mở `/finance/debt-report` với cùng filter thời gian/đơn vị.
2. So tổng debt, overdue, paid/pending với fee/invoice sau các hành trình.
3. Export debt report ở cả XLSX và CSV.
4. Từ invoice workspace, export danh sách học phí ở cả XLSX và CSV với đúng filter đang xem. Payment workspace hiện không có export UI; ghi `NOT_EXPOSED_IN_UI`, không giả ca bằng gọi endpoint không tồn tại.
5. Mở từng file tải về, kiểm header, encoding tiếng Việt, kiểu ngày/số, số dòng và tổng tiền.

Download event không đủ. File phải mở được và dữ liệu phải khớp danh sách/tổng đang hiển thị.

### FIN-19 — payment intent/QR và callback sandbox

Chỉ chạy khi gateway sandbox được cấu hình rõ ràng.

1. Tạo intent qua UI cho invoice test.
2. Kiểm amount, invoice, expiry và trạng thái hiển thị.
3. Reload/poll status theo UI.
4. Dùng callback sandbox có chữ ký test nếu harness chính thức hỗ trợ.
5. Replay callback và callback sai chữ ký.
6. Mở `/finance/payments/return` với các trạng thái success/failed/pending/cancelled/expired và `intent_id` hợp lệ; kiểm link quay lại đúng invoice.
7. Ca chống giả trạng thái: query nói `status=success` nhưng intent backend vẫn pending/failed. UI không được tuyên bố thanh toán thành công chỉ vì query string; trạng thái backend/callback đã xác minh phải là nguồn có thẩm quyền.
8. Ca payload méo: `intent_id` không phải số, ID không tồn tại, thiếu toàn bộ ID/status và `error/reference` đã URL-encode. Trang phải fail closed, không crash/hydration error và không render success giả.

Đạt khi callback hợp lệ tạo/verify đúng một payment; replay idempotent; callback sai bị từ chối; return page phản ánh trạng thái đã được backend xác minh; không charge thật.

Nếu không có sandbox: ghi `BLOCKED — external dependency`, không giả PASS bằng cách gọi service trực tiếp.

Riêng ca 7 không phụ thuộc sandbox: có thể seed intent pending/failed và mở return URL cục bộ. Tại `9950abe9`, source ưu tiên query param nên đây là expected FAIL cho tới khi sửa.

### FIN-20 — RBAC, IDOR và contract cũ

Chạy bằng Chrome session của từng persona và request âm có kiểm soát:

1. `OFF-A` không truy cập được workspace Finance ngoài quyền application fee.
2. `ACC-A` không có thao tác manager/admin đã liệt kê.
3. `MGR-A` không có quyền admin-only cho kỳ kế toán.
4. `ACC-A` mở URL trực tiếp tới `F-IDOR-B`: backend không rò tồn tại, trả đúng 404 contract.
5. Client cũ gọi preview duplicate với đủ hoặc thiếu một legacy query param: nhận 410, không có `items` để UI cũ hiểu sai.
6. Client cũ gửi `confirm_duplicate(s)` ở query/body: cờ không cấp quyền ghi.
7. Token review của user/unit/batch/row khác bị từ chối.

Không chỉ kiểm nút ẩn; phải chứng minh request trái quyền không tạo mutation trong DB.

### FIN-21 — responsive và khả dụng tối thiểu

Chạy các trang/dialog trọng yếu ở ba viewport:

- `1440 x 900`;
- `1280 x 800`;
- `390 x 844`.

Tối thiểu kiểm:

- invoice workspace và PaymentRecordDialog;
- payment import preview/result;
- refund/overpayment action dialog;
- accounting summary;
- debt report/export controls.

Đạt khi:

- không mất nút xác nhận/hủy;
- bảng có cách cuộn hoặc trình bày không che dữ liệu;
- focus vào dialog, Esc/close và keyboard navigation đúng;
- label/error liên kết được với input;
- số tiền/ngày không bị cắt gây hiểu sai;
- trạng thái loading/disabled nhìn thấy rõ;
- không có hydration error khi reload.

### FIN-22 — cấu hình discount và installment plan

Persona: `ADM-A`; `MGR-A`/`ACC-A` chỉ theo đúng quyền thực tế; fixture `F-CONFIG`.

#### Discount policy

1. Mở `/admin/tuition-discount`.
2. Tạo policy có mã chứa `RUN_ID`, điều kiện áp dụng deterministic và thời gian hiệu lực bao phủ ngày test.
3. Sửa một trường không làm đổi định danh; reload và kiểm dữ liệu.
4. Admin UI hiện không có calculator action; endpoint calculate thuộc regression API, ghi `NOT_EXPOSED_IN_UI`.
5. Tính một Fee đủ điều kiện qua FIN-03 và kiểm applied discount/final tuition là snapshot đúng policy tại thời điểm tính.
6. Sửa hoặc deactivate policy sau đó; fee cũ không được tự đổi lịch sử, fee mới phải dùng cấu hình mới.
7. Xóa/deactivate qua UI theo contract và kiểm không làm hỏng fee đã tham chiếu.

#### Installment plan

1. Mở `/admin/installment-plans`.
2. Tạo plan 2 hoặc 3 đợt, tổng `percent = 100`, `installment_no` liên tục và offset hợp lệ.
3. Kiểm các ca form âm: tổng khác 100, thiếu đợt, trùng mã, số đợt lệch chiều dài schedule.
4. Sửa plan khi chưa được dùng và reload.
5. Tính một Fee dùng plan đó; đối chiếu số invoice, thứ tự, due date và tổng tiền.
6. Thử đổi schedule/count khi plan đã được Fee tham chiếu: phải bị chặn.
7. Soft delete/deactivate; plan biến mất khỏi picker active nhưng lịch sử Fee vẫn đọc được.

Đối soát chung:

- quyền backend khớp quyền hiển thị, không dựa riêng vào role check ở client;
- số tiền cuối không bị client tự tính khác backend;
- snapshot trên Fee không drift khi cấu hình về sau thay đổi;
- audit đủ trước/sau cho mutation cấu hình.

### FIN-23 — hoa hồng cộng tác viên

Persona cấu hình: `ADM-A`; duyệt/chi: `MGR-A` hoặc `ADM-A`; tự xem: `CTV-A`; fixture `F-COMMISSION`.

1. Admin mở `/admin/commission-policies`, tạo policy có trigger và giá trị deterministic chứa `RUN_ID`.
2. Đẩy lead thử qua đúng transition nghiệp vụ tạo commission; không insert commission record trực tiếp nếu đang chứng minh trigger.
3. Manager mở `/admin/commissions`, lọc theo CTV/status và mở detail.
4. Approve record thứ nhất rồi Pay với reference chứa `RUN_ID`.
5. Reject record độc lập, nhập lý do và thử approve/pay lại.
6. `CTV-A` mở bề mặt tự phục vụ commission, đối chiếu tổng và danh sách của chính mình.
7. `CTV-A` thử mở record người khác; manager đơn vị A thử record đơn vị B.

Đạt khi:

- một trigger chỉ tạo một commission record;
- amount/policy snapshot/collaborator/lead liên kết đúng;
- state machine pending -> approved -> paid và pending -> rejected không có lối tắt;
- replay approve/pay không nhân đôi;
- payment reference/actor/time đúng;
- CTV chỉ thấy record của mình và thông tin lead được mask đúng contract;
- manager bị giới hạn theo đơn vị; admin nhìn được phạm vi cho phép;
- policy sửa sau đó không làm drift record lịch sử.

### FIN-24 — rút hồ sơ có tiền và vòng hoàn tự động

Persona: `OFF-A`, `MGR-A`, `ACC-A`, `ADM-A`; dùng hai bản sao độc lập của `F-WITHDRAW`.

#### Nhánh A — hoàn hết rồi finalize withdrawn

1. Xác minh hồ sơ đang ở trạng thái được phép rút và có tuition payment verified còn refundable.
2. `OFF-A` mở hồ sơ, bấm Rút hồ sơ, nhập lý do và xác nhận.
3. UI phải chuyển sang `withdrawal_pending`, hiển thị banner đang hoàn tiền; backend tự lập refund `source=withdrawal` đúng từng payment refundable.
4. Trong lúc pending, thử ghi tay, tạo intent, import vào Fee của hồ sơ và apply overpayment vào invoice của hồ sơ: tất cả phải bị chặn trước mutation.
5. Thử từ chối riêng một refund withdrawal: phải bị chặn; không được để hồ sơ kẹt với tập refund thiếu.
6. Manager duyệt và accountant chi từng refund.
7. Sau refund cuối, reload hồ sơ/fee/invoice/refund/lead.

Đạt khi:

- không refund application fee hoặc khoản không refundable trái contract;
- tổng refund bằng tổng refundable thực tế, không vượt payment;
- trước refund cuối hồ sơ vẫn `withdrawal_pending`;
- refund cuối tự finalize `withdrawn`, Lead về milestone rút đúng contract;
- fee/invoice đã void/cancel không bị `reverse_payment_balances` làm sống lại;
- không còn cờ `has_unrefunded_payment` sai và không thể thu thêm tiền;
- callback/audit/notification chỉ chạy một lần khi retry.

#### Nhánh B — admin hủy quá trình rút

1. Trước khi rút, tạo một refund manual hoặc overpayment độc lập còn mở.
2. Rút hồ sơ để hệ thống tạo thêm refund `source=withdrawal`.
3. `ADM-A` bấm Hủy rút hồ sơ.
4. Reload hồ sơ và refund list.

Đạt khi profile về `draft`; chỉ các refund `source=withdrawal` bị reject atomically; refund manual/overpayment có sẵn vẫn giữ nguyên; balance/payment không bị đảo và có thể tiếp tục quy trình hợp lệ.

### FIN-25 — ma trận target không được nhận tiền

Persona: `ACC-A`; fixture `F-DEAD-TARGET`.

Chạy cùng một ma trận hành động trên từng target:

| Target | Ghi tay | Verify pending đã tạo trước transition | Intent online | Import | Apply overpayment |
|---|---|---|---|---|---|
| Profile `rejected` | chặn | chặn | chặn | chặn | chặn |
| Profile `withdrawn` | chặn | chặn | chặn | chặn | chặn |
| Profile `withdrawal_pending` | chặn | chặn | chặn | chặn | chặn |
| Fee hoặc Invoice `cancelled` | chặn | chặn | chặn | chặn | chặn |
| Fee `awaiting_accountant_confirmation` | chặn | chặn | chặn | chặn | chặn |

Quy trình:

1. Với mỗi target, mở bề mặt Finance liên quan và xác nhận backend-owned action flag không mời người dùng thu tiền.
2. Nếu UI vẫn có action do cache, bấm phải nhận thông báo business rõ ràng, không success/empty state.
3. Dùng request âm có kiểm soát để chứng minh backend không ghi payment, transaction hoặc balance khi nút bị ẩn.
4. Với target đổi ngành, `ACC-A` xác nhận major change theo luồng maker-checker; reload rồi chứng minh action thu tiền chỉ mở lại sau khi cờ đã clear.

Đạt khi mọi đường dùng cùng invariant; import không trở thành lối vòng qua guard ghi tay.

### FIN-26 — ngày giờ Việt Nam và biên kỳ

Persona: `ACC-A`; fixture `F-DATE`.

1. Ghi payment với ngày đầu/cuối tháng và reload ở múi giờ trình duyệt Việt Nam.
2. Kiểm ngày gửi, ngày hiển thị, ngày dùng trong duplicate-review token và ngày xuất report/export là cùng ngày lịch VN.
3. Chi refund trước và sau 07:00 giờ VN; reference tự sinh phải dùng ngày làm việc VN, không lấy nhầm ngày UTC.
4. Kiểm input âm: 31/04, 29/02 năm không nhuận, ngày ngoài giới hạn nghiệp vụ và chuỗi không theo định dạng.
5. Lọc Payments/Invoices/Debt Report với `from=to` đúng một ngày; bản ghi ở đầu/cuối ngày phải xuất hiện đúng một lần.
6. Đặt hai giao dịch ở hai phía biên tháng; accounting summary và export phải xếp đúng kỳ.

Không đổi timezone máy/container giữa lượt mà không tạo RUN_ID mới. Nếu cần đo biên giờ thật, freeze time ở tầng test tự động; Chrome chỉ xác minh render và roundtrip ngày.

### FIN-27 — hai phiên, realtime và notification

Persona: maker `ACC-A`, checker khác maker; hai Chrome session độc lập.

1. Checker mở tab Chờ xác minh và ghi baseline notification.
2. Maker tạo một manual payment qua UI.
3. Không reload checker ngay: quan sát event/realtime hoặc refetch policy hiện tại; payment phải xuất hiện trong thời gian SLA đã định.
4. Checker verify; maker reload/mở invoice và phải thấy balance mới.
5. Lặp lại một request/reconnect để kiểm notification không nhân đôi.
6. Đăng xuất một session rồi xác minh session kia không bị mất auth/cache chéo.

Đạt khi notification `payment_received` và `payment_verified` đúng người/phạm vi, đúng một lần; không lộ dữ liệu đơn vị B; thiếu realtime phải có refetch/fallback rõ ràng, không giữ số cũ vô thời hạn.

## 8. Các invariant tài chính dùng cho mọi mutation

Sau bất kỳ hành động làm đổi tiền, phải kiểm toàn bộ nhóm phù hợp:

### 8.1. Bảo toàn tiền

```text
fee.paid_amount = tổng phần payment đã được ghi nhận hợp lệ cho fee
invoice.paid_amount = tổng phần payment hợp lệ phân bổ vào invoice
0 <= invoice.paid_amount <= invoice.total_amount, trừ contract overpayment rõ ràng
fee.remaining = fee.total_amount - fee.paid_amount - khoản điều chỉnh được định nghĩa
```

- Pending/rejected không được giả làm tiền đã thu.
- Refund/void chỉ đảo đúng phần đã ghi nhận, đúng một lần.
- Tổng batch/import lấy từ payment thật, không lấy counter tạm.
- Không có payment mồ côi, sai invoice/fee/profile/unit.

### 8.2. Trạng thái và liên kết

- `validation_status` mô tả kiểm đầu vào; `commit_status` mô tả ghi tiền. Không suy một trục từ trục kia.
- Dòng import `committed` khi và chỉ khi `payment_ids` hợp lệ, theo constraint DB.
- Counter/tổng batch là projection từ hàng và payment thật.
- Invoice/Fee/Payment/Refund/Overpayment transitions chỉ đi theo state machine hợp lệ.
- `created_by`, verifier, approver, processor và timestamp đúng actor/thời điểm.

### 8.3. Idempotency và chống replay

- Double-click, reload, back/forward, retry mạng và replay request không nhân đôi tiền.
- Review token bị ràng buộc bởi flow, user, unit, fee, invoice/batch/row, amount, ngày và guard version tương ứng.
- Ghi thành công làm token cũ hết hiệu lực.
- Callback gateway, verify/reject, process refund và void đều chịu retry an toàn theo contract.

### 8.4. Cache và nguồn sự thật

- Sau mutation, UI refetch và hiển thị dữ liệu backend trả về.
- Trong lúc refetch cached remaining/pending không được coi là đã xác minh.
- Reload cứng không làm số tiền/trạng thái quay về giá trị cũ.
- Hai tab cùng sửa một tài nguyên phải nhận conflict hoặc dữ liệu mới, không silent overwrite.

### 8.5. Audit và notification

- Mỗi transition quan trọng có đúng một audit record với actor, entity, before/after/reference.
- Notification sinh đúng event và đúng một lần; retry không gây flood.
- Không có notification “đã thu/đã hoàn” khi transaction mới pending hoặc đã thất bại.

## 9. Cổng C — đối soát chéo sau toàn bộ hành trình

Sau FIN-00..FIN-27:

1. Tổng payment verified theo ngày/đơn vị phải khớp:
   - danh sách Payments;
   - paid amount của invoices/fees;
   - dashboard;
   - debt report;
   - accounting summary;
   - file export.
2. Tổng refund processed phải khớp payment/refund/overpayment/accounting.
3. Tất cả batch import có counter, status, payment IDs và total nhất quán.
4. Không có payment/refund/overpayment mồ côi.
5. Không có `paid_amount < 0`, balance âm hoặc paid vượt total ngoài contract.
6. Không có audit thiếu actor hoặc notification lặp do retry.
7. Không có 5xx bất ngờ trong backend log theo cửa sổ thời gian `RUN_ID`.
8. Không có console error hoặc request thất bại bị UI nuốt thành thành công.

## 10. Cổng D — bắt buộc nhưng không được thay bằng Chrome

Chrome smoke tuần tự không chứng minh được các race dưới đây. Phải có test repository/service thật, hai transaction và barrier buộc xen kẽ.

### D01. Deadlock nhập lô với ghi tay — đã đóng, regression bắt buộc

Kịch bản tối thiểu:

1. Session A bắt đầu commit import có cùng Fee/Invoice với session B.
2. Barrier buộc A giữ khóa đầu tiên trước khi xin khóa tiếp theo.
3. Session B đi vào ghi tay và giữ khóa phía đối diện.
4. Cho hai session tiếp tục đồng thời.
5. Yêu cầu cả hai hoàn tất hoặc một bên nhận business conflict/retry có kiểm soát; không được `DeadlockDetectedError`, connection closed hoặc partial commit.
6. Đối soát đúng một payment theo mỗi intent hợp lệ và balances không drift.

Tại `9950abe9`, D01 đã xanh; mốc `0739946a` tái hiện đỏ `40P01`, bản sửa `5f65309f`. Mọi thay đổi sau này vào query khóa Invoice/Fee hoặc `commit_batch` phải chạy lại ba ca trong `test_import_vs_manual_deadlock.py`, không chỉ ca happy path.

### D02. Candidate đổi giữa warning và confirm

- Transaction A lấy warning/token.
- Transaction B ghi một payment phù hợp làm `duplicate_guard_version` tăng.
- A gửi token cũ.
- A phải bị từ chối và nhận snapshot mới; không tạo payment.

### D03. Hai dòng import cùng Fee

- Hai dòng đều cần review trước lần ghi đầu.
- Xác nhận một lượt cho cả hai.
- Cả hai ghi được hoặc cả batch rollback theo contract; không hết hạn dây chuyền sau dòng một.

### D04. Verify/reject/process/void đồng thời

Mỗi cặp sau cần test barrier:

- verify với reject cùng payment;
- verify với refund creation;
- refund process với process replay;
- import void với refund creation;
- hai void cùng batch;
- apply overpayment với refund/write-off cùng record.

Kết quả phải serializable theo một thứ tự hợp lệ, không deadlock, không âm balance, không cộng/đảo hai lần.

### D05. Trigger và migration

- `create_all()` hai lượt trên cùng schema đều commit sạch;
- đủ cột và đúng bốn trigger sau lượt hai;
- bản DDL test dùng `CREATE OR REPLACE TRIGGER`, migration gốc giữ đúng dạng cần thiết;
- update/delete refund làm tăng guard version cho cả `OLD.fee_id` và `NEW.fee_id` khi khác nhau;
- reverse check làm đúng test mục tiêu đỏ.

### D06. Kỳ kế toán phải chặn ở mọi đường ghi

Sau khi wiring guard được sửa, cần test trực tiếp tại ranh giới service/router cho:

- record manual payment với `payment_date` trong kỳ đóng;
- verify payment pending trong kỳ đóng;
- import có row date thuộc kỳ đóng và lô trộn hai kỳ;
- process refund với ngày chi thuộc kỳ đóng;
- callback gateway đến sau khi kỳ của giao dịch đã đóng;
- biên 23:59:59/00:00 theo timezone nghiệp vụ.

Mỗi ca phải chứng minh không có PaymentTransaction/balance mutation. Gỡ lời gọi guard thật phải làm ca tương ứng đỏ. Tại `9950abe9`, nhóm này chưa thể xanh vì `can_record_transaction()` chưa có caller; đó là finding cần sửa, không phải lý do bỏ D06.

## 11. Điều kiện PASS/FAIL/BLOCKED

### PASS cho một ca

Chỉ khi đủ:

- UI hành động thành công theo tín hiệu có thẩm quyền;
- không có 5xx/console error bất ngờ;
- API/DB hậu điều kiện đúng;
- audit/notification đúng nếu có;
- reload/retry không làm sai;
- evidence đủ.

### FAIL

Một trong các dấu hiệu sau là fail ngay:

- toast thành công nhưng DB không đổi hoặc đổi sai;
- đúng tổng toàn hệ thống nhưng sai payment IDs/từng dòng/từng invoice;
- UI dùng cache cũ trong lúc refetch để cho phép ghi;
- một hành động sinh hai request/payment;
- tiền, status, counter hoặc export không khớp;
- quyền chỉ bị ẩn ở UI nhưng backend vẫn cho ghi;
- lỗi 409/410/422/500 bị biến thành success/empty state;
- download có file nhưng file hỏng hoặc dữ liệu sai;
- deadlock/timeout/connection closed;
- cleanup không xác định được chính xác dữ liệu đã tạo.

### BLOCKED

Dùng khi môi trường hoặc dependency ngoài code không cho kiểm đúng contract, ví dụ gateway sandbox không có, migration không ở head hoặc fixture không dựng được. Lỗi code đã biết như return-page tin query hoặc payment bỏ qua kỳ đóng là `FAIL`, không phải `BLOCKED`. `BLOCKED` không được đổi tên thành `PASS`.

### GO cuối

Chỉ ghi:

```text
GO Finance smoke — <exact full SHA>
```

khi:

- A01..A04 đạt tại cùng SHA;
- FIN-00..FIN-27 đạt, trừ dependency sandbox được ghi rõ;
- mọi invariant Cổng C khớp;
- D01..D06 đạt;
- cleanup đạt;
- không còn finding P0/P1 mở trong phạm vi Finance.

Kết luận này chỉ áp dụng cho SHA, migration, browser, viewport và môi trường đã ghi; không có nghĩa là “hết mọi lỗi có thể tồn tại”.

## 12. Cleanup — drop + restore database riêng

⚠️ **ĐỔI THIẾT KẾ 14-08-2026.** Bản cũ của mục này dọn bằng cách xoá theo ID và theo thứ tự FK. Cách ấy **không dùng được**: `payment`/`payment_transaction`/`refund_request` có nhiều cạnh RESTRICT; `audit_log` và `notification` trỏ bằng `entity_id`/`source_id` **không có FK**; commission/accounting/config nằm ngoài cây profile. Xoá gốc nghĩa là hoặc bỏ sót, hoặc xoá lan sang miền Admissions.

Nay smoke chạy trên **database riêng `qlts_smoke`** (compose project `qltssmoke`), và cleanup là **drop + restore baseline**. Không cần biết bảng nào phụ thuộc bảng nào.

`qlts_dev` và production **tuyệt đối không bị chạm**: tên đích đóng cứng trong mã (`smoke_lib/baseline.py`), và danh tính đích còn được khoá bằng compose project + container id + `system_identifier` của cụm PostgreSQL — vì một server khác vẫn có thể chứa database trùng tên.

**Cleanup chạy TAY, tường minh.** Không đặt trong `finally`, không tự chạy khi một ca fail: lúc fail phải giữ hiện trường để thu log, ảnh và trạng thái DB. Happy path dùng cùng một lệnh đó.

Thứ tự:

1. Dừng tạo mutation mới, đóng mọi tab smoke.
2. Void/reverse các batch/payment được contract cho phép.
3. Hoàn tất hoặc hủy refund/overpayment đúng state machine; không sửa status trực tiếp.
4. Chụp post-cleanup dashboard/debt/accounting.
5. Chạy cleanup: **dừng service smoke → xác nhận 0 session → kiểm lại archive (`pg_restore --list`, TOC đủ bảng trọng yếu) → drop/create/restore → đối soát vân tay + Alembic head → mới mở lại dịch vụ**. Restore hoặc đối soát lỗi ⇒ ghi `HONG`, giữ dịch vụ đóng, không chạy pack tiếp theo.
6. Xác minh từng ID không còn hoặc còn lại đúng loại audit bắt buộc.
7. Xác minh không còn record chứa `RUN_ID` ngoài allowlist audit.
8. Xác minh tổng tiền của dữ liệu không-smoke bằng baseline.
9. Lưu cleanup report và exit non-zero nếu còn rác/sai số.
10. Dừng từng service đã tự khởi động nếu cần; không dùng `docker compose down`.

Nếu đã tạo dữ liệu mà registry ID bị mất: dừng cleanup tự động và xử lý thủ công có review. Không dùng pattern delete rộng để “dọn cho sạch”.

## 13. Ma trận truy vết bề mặt Finance

| Bề mặt/contract | Ca chính |
|---|---|
| Finance dashboard | FIN-01, FIN-18 |
| Fee list/detail/calculate/preview | FIN-03, FIN-15 |
| Fee waive/recalculate/cancel/major change | FIN-15 |
| Invoice list/detail/issue/QR/export | FIN-03, FIN-04, FIN-16, FIN-18 |
| Invoice supplemental/replacement API, chưa có UI | Regression API; `NOT_EXPOSED_IN_UI` ở FIN-16 |
| Payment list/manual/verify/reject | FIN-04, FIN-05 |
| Duplicate review token | FIN-06, FIN-07, D02 |
| FIFO nhiều installment | FIN-08 |
| Import template/preview/commit/result/void | FIN-09, D01, D03, D04 |
| Refund create/approve/reject/process | FIN-10, FIN-11, D04 |
| Overpayment apply/refund/write-off | FIN-12, FIN-13, FIN-14, D04 |
| Overpayment producer | ✅ **ĐÃ CÓ** từ #552 (`check_overpayment` trong `payment_service.py`) — nhận định "chưa có" đã lỗi thời, sửa 14-08-2026 |
| Accounting current/detail/summary/create/close và chặn giao dịch | FIN-17, FIN-18, D06 |
| Debt report/export | FIN-18 |
| Payment intent/callback | FIN-19 |
| Application fee | FIN-02 |
| RBAC/IDOR/legacy contracts | FIN-00, FIN-20 |
| Responsive/accessibility/hydration | FIN-21 |
| Discount policy/installment plan | FIN-03, FIN-08, FIN-22 |
| Commission policy/record/CTV view | FIN-23 |
| Withdrawal -> auto-refund -> finalize/cancel | FIN-24, FIN-10, FIN-11 |
| Non-payable/cancelled/major-change target guards | FIN-25 |
| Ngày VN, filter và biên kỳ | FIN-26, D06 |
| Realtime/notification hai phiên | FIN-27 |
| Trigger/migration | D05 |

## 14. Mẫu báo cáo cuối lượt

```markdown
# Finance smoke report — <RUN_ID>

- Branch:
- Full SHA:
- Dirty state:
- Migration head:
- Browser/version:
- Viewports:
- DB name/host (không ghi secret):
- Started/finished:

## Automated gates
- Backend Tier 1:
- Frontend type-check/Vitest/lint/attestation:
- Concurrency/period anchors D01..D06:

## Chrome results
- Mandatory passed:
- Failed:
- Blocked:
- Optional skipped and why:

## Financial reconciliation
- Verified payments:
- Processed refunds:
- Import totals:
- Overpayment conservation:
- Overpayment producer coverage: **mặc định là đường production** (đã có từ #552); `SEEDED_RESOLUTION_ONLY` chỉ khi có lý do ghi rõ:
- Dashboard/debt/accounting/export match:
- Audit/notification anomalies:

## Cleanup
- Reversed/voided IDs:
- Deleted fixture IDs:
- Remaining RUN_ID rows:
- Baseline delta:

## Verdict
BLOCK | GO Finance smoke — <full SHA>
```

## 15. Phạm vi của các Playwright spec hiện có

Các spec như `finance-lifecycle.spec.ts` và `finance-notification-workflow.spec.ts` vẫn có giá trị để kiểm contract/API và notification. Tuy nhiên, những bước dùng `page.request` không chứng minh form, reducer, cache, disabled state, double-click, dialog hay render Chrome hoạt động đúng.

Vì vậy:

- giữ chúng ở tầng regression hỗ trợ;
- thứ tự thêm spec UI thật: FIN-19 ca success giả và FIN-17 kỳ đóng (đang là finding), sau đó FIN-06/07 duplicate-cache, FIN-09 import retry/void, FIN-10 refund và FIN-24 withdrawal-finalize;
- không cộng một ca API-only vào số “Chrome UI smoke passed”;
- mọi spec mutation phải lưu và cleanup đúng ID, fail non-zero khi invariant tiền sai.
