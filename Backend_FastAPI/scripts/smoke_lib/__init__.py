"""Thư viện dùng chung cho harness Chrome smoke Finance.

Đặt ở `smoke_lib/` chứ không phải `scripts/smoke_*.py` là có chủ ý:
`.gitignore:317` che `Backend_FastAPI/scripts/smoke_*.py` vì một script cũ
(`smoke_e4_phase6_reset_passwords.py`) có mật khẩu hard-coded. Quy tắc ấy quét
theo TÊN TỆP nên nó che nhầm cả những script sạch. Code ở đây phải vào git —
harness không được review thì không khác gì không có harness — nên nó nằm
ngoài tầm của pattern đó.

Nguyên tắc chung cho mọi module trong gói này:

* **fail-closed**: thiếu một điều kiện thì thoát khác 0 và KHÔNG chạm dữ liệu;
* **không giá trị mặc định** cho URL, mật khẩu, tên database;
* **không ghi bí mật** vào registry (mật khẩu, token, cookie);
* mọi id được ghi **trước** khi mutation xảy ra, không tra cứu lại theo tên.
"""
