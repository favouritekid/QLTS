"""CLI của harness smoke: `--baseline` trước pack, `--cleanup` sau pack.

    python -m scripts.smoke_lib.cli --baseline --run-id SMK20260815
    python -m scripts.smoke_lib.cli --cleanup  --run-id SMK20260815

Chạy TRÊN HOST (không phải trong container backend): nó cần `docker` để nói
chuyện với container postgres của project `qltssmoke`.

Vì sao mọi thứ đi qua `ChayLenh`
--------------------------------
Toàn bộ lời gọi hệ thống nằm sau một đối tượng duy nhất, và đối tượng ấy luôn
dùng `subprocess.run(argv, shell=False, check=True)`:

* `shell=False` + argv dạng danh sách ⇒ không có shell nào diễn giải chuỗi, nên
  một tên chứa `;` hay `$(...)` chỉ là một tham số vô hại (SQL injection thì
  chặn ở tầng khác — allowlist định danh trong `baseline.py`);
* `check=True` ⇒ lệnh hỏng là ném lỗi, không phải trả mã thoát để ai đó quên
  kiểm. Đúng lớp lỗi "lệnh trả 0 mà việc không xảy ra" mà cả repo này đã va
  nhiều lần;
* tách khỏi logic ⇒ test thay `ChayLenh` bằng stub và chạy được trọn hai lệnh
  mà không cần Docker, không cần database.

Thứ tự BẮT BUỘC của `--cleanup`
-------------------------------
1. đọc registry bằng `doc_cho_cleanup` (ba tham số bắt buộc);
2. **kiểm lại** môi trường + danh tính container — danh tính có thể đã đổi kể
   từ lúc ghi baseline;
3. dừng service ứng dụng của stack smoke, xác nhận **0 session**;
4. kiểm lại archive (checksum + `pg_restore --list` + TOC);
5. drop → create → restore;
6. đối soát vân tay + Alembic head;
7. **chỉ khi ĐẠT** mới mở lại dịch vụ.

Hỏng ở bất kỳ bước nào từ 5 trở đi ⇒ ghi `HONG` vào registry và **giữ dịch vụ
đóng**. Một database ở trạng thái không xác định mà dịch vụ vẫn chạy là cách
chắc chắn để lượt sau ghi tiếp lên đống đổ nát.

Cleanup **chỉ chạy tay**. Cố ý không đặt trong `finally` của bất kỳ pack nào:
lúc một ca fail, hiện trường là thứ đắt nhất đang có.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from . import anh_chup, baseline, registry

# Service ứng dụng của stack smoke — phải dừng trước khi drop database.
# `postgres` cố ý KHÔNG nằm đây: nó là thứ ta gửi lệnh tới.
SERVICE_UNG_DUNG = ("backend", "celery-worker", "celery-beat", "frontend")


class BoCompose:
    """Bộ tệp Compose + env file dùng để ĐIỀU KHIỂN stack smoke.

    Bản trước gọi `docker compose -p qltssmoke stop …` trần. `-p` chỉ chọn TÊN
    PROJECT, không chọn MODEL: từ gốc repo, Compose sẽ tự nạp
    `docker-compose.yml` + `docker-compose.override.yml` (dev) và đọc
    `.env.production` mặc định. Nghĩa là lệnh dựng stack và lệnh dọn stack nói về
    hai model khác nhau — dọn nhầm, hoặc đổ vì thiếu biến, tuỳ máy.

    Không có giá trị mặc định nào ở đây, và đó là cố ý: không tồn tại bộ Compose
    nào đúng cho mọi máy, nên một mặc định chỉ là một cách hỏng im lặng.
    """

    def __init__(self, tep_compose: Sequence[str], env_file: str):
        tep = [str(x) for x in (tep_compose or []) if str(x).strip()]
        if not tep:
            raise LoiCLI(
                "thiếu --compose-file: không có tệp compose thì `-p qltssmoke` "
                "sẽ nạp model mặc định của thư mục hiện tại (kèm override dev)"
            )
        if not str(env_file or "").strip():
            raise LoiCLI(
                "thiếu --compose-env-file: thiếu nó thì `QLTS_ENV_FILE` không "
                "được đặt và model rơi về `.env.production`"
            )
        self.tep_compose = tep
        self.env_file = str(env_file)

    def lenh(self, *duoi: str) -> List[str]:
        argv = ["docker", "compose", "-p", baseline._PROJECT_DUY_NHAT]
        for f in self.tep_compose:
            argv += ["-f", f]
        argv += ["--env-file", self.env_file]
        return argv + list(duoi)

    def van_tay(self, chay: "ChayLenh", *, app_env: str) -> str:
        """Kiểm model THẬT rồi mới trả vân tay. Không ghi output ra đĩa ở đâu cả.

        `app_env` bắt buộc: nó được đối chiếu với `APP_ENV` đã render trong model.
        Trước đây `--app-env` chỉ là chuỗi người gọi tự khai — khai `development`
        trong khi model nạp `.env.production` thì không có gì phát hiện ra.
        """
        return baseline.van_tay_model(
            chay(self.lenh("config", "--format", "json")), app_env=app_env
        )


class LoiCLI(RuntimeError):
    pass


class ChayLenh:
    """Bọc `subprocess.run` — luôn `shell=False`, luôn `check=True`.

    Cố ý KHÔNG có tham số nới lỏng. Bản đầu có `cho_phep_loi=True` đổi thành
    `check=False`; chưa ai gọi, nhưng một escape hatch chưa dùng vẫn là escape
    hatch — và nó làm câu "luôn `check=True`" thành không đúng.
    """

    def __init__(self, in_lenh: bool = True) -> None:
        self.in_lenh = in_lenh

    def __call__(self, argv: Sequence[str]) -> str:
        if self.in_lenh:
            print("  $ " + " ".join(argv), file=sys.stderr)
        # `encoding="utf-8"` TƯỜNG MINH, không dùng `text=True` trần.
        #
        # `text=True` để Python chọn codec theo locale — trên Windows là cp1252.
        # PostgreSQL trả UTF-8, và dữ liệu thật của hệ này là tiếng Việt, nên
        # `SELECT` bất kỳ bảng nào có chữ Việt sẽ ném `UnicodeDecodeError`
        # ("can't decode byte 0x90"). Đã đo trên bảng `notification` của
        # `qlts_smoke`. Trước 16-08-2026 không lộ vì mọi lệnh psql của harness
        # chỉ trả ASCII: số đếm, sha256, `version_num`.
        #
        # `errors="strict"` là cố ý: thay ký tự hỏng bằng dấu thay thế sẽ đổi
        # vân tay hàng một cách âm thầm, và khi ấy ảnh chụp nói dối.
        ket = subprocess.run(
            list(argv), shell=False, check=True, capture_output=True,
            encoding="utf-8", errors="strict",
        )
        return ket.stdout


def _docker_exec(cid: str, argv: Sequence[str]) -> List[str]:
    return ["docker", "exec", "-i", cid, *argv]


def _nhan_container(chay: ChayLenh, cid: str) -> Mapping[str, str]:
    tho = chay(
        ["docker", "inspect", cid, "--format",
         "{{range $k, $v := .Config.Labels}}{{$k}}={{$v}}\n{{end}}"]
    )
    nhan = {}
    for dong in tho.splitlines():
        if "=" in dong:
            k, _, v = dong.partition("=")
            nhan[k.strip()] = v.strip()
    return nhan


def _danh_tinh(chay: ChayLenh, cid: str, *, nen: Optional[Mapping[str, str]] = None):
    """Đọc và kiểm danh tính đích. Gọi lại TRƯỚC MỖI mutation."""
    sid = chay(
        _docker_exec(cid, baseline.lenh_system_identifier(user="qlts"))
    ).strip()
    return baseline.kiem_danh_tinh(
        project=baseline._PROJECT_DUY_NHAT,
        container_id=cid,
        nhan_container=_nhan_container(chay, cid),
        system_identifier=sid,
        danh_tinh_baseline=nen,
    )


def _alembic_head(chay: ChayLenh, cid: str, ten_db: str) -> str:
    baseline.kiem_dich(ten_db)
    return chay(
        _docker_exec(cid, [
            "psql", "-U", "qlts", "-d", ten_db, "-At", "-v", "ON_ERROR_STOP=1",
            "-c", "SELECT version_num FROM alembic_version;",
        ])
    ).strip()


def _van_tay(chay: ChayLenh, cid: str, ten_db: str) -> str:
    baseline.kiem_dich(ten_db)
    tho = chay(
        _docker_exec(cid, [
            "psql", "-U", "qlts", "-d", ten_db, "-At", "-F", "|",
            "-v", "ON_ERROR_STOP=1",
            "-c", baseline.cau_lenh_van_tay(baseline.BANG_TRONG_YEU),
        ])
    )
    dem = baseline.phan_tich_van_tay(tho, bang_bat_buoc=baseline.BANG_TRONG_YEU)
    return registry.van_tay(dem)


# =============================================================================
# --baseline
# =============================================================================
def _goc_repo() -> Path:
    """Gốc repo tìm bằng MỐC `.git`, không đếm số tầng thư mục."""
    for thu_muc in Path(__file__).resolve().parents:
        if (thu_muc / ".git").exists():
            return thu_muc
    raise LoiCLI("không tìm được gốc repo (không thấy .git ở thư mục cha nào)")


def kiem_git_sha(chay: ChayLenh, git_sha: str) -> str:
    """SHA phải đúng hình dạng, đúng cây đang chạy, VÀ cây phải sạch.

    Ba chỗ từng fail-open, sửa cả ba:

    * bản đầu chỉ kiểm "khác rỗng" nên `--git-sha banana` được ghi thẳng;
    * bản sau so `if that and that != git_sha` — `git rev-parse` trả chuỗi rỗng
      (lệnh chạy sai thư mục, không phải repo…) thì **bỏ qua phép so**, và một
      SHA bịa vẫn vào registry;
    * cây bẩn: HEAD khớp không có nghĩa mã đang chạy là mã của commit ấy. Neo
      registry vào `2ca5d1a5` trong khi làm việc trên thay đổi chưa commit là
      nói dối về thứ đã được smoke.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", git_sha or ""):
        raise LoiCLI(f"--git-sha phải là 40 ký tự hex, nhận {git_sha!r}")

    goc = _goc_repo()
    that = chay(["git", "-C", str(goc), "rev-parse", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", that):
        raise LoiCLI(
            f"`git rev-parse HEAD` tại {goc} trả {that!r} — không phải SHA. "
            "Không có gì để đối chiếu thì KHÔNG được coi là đã đối chiếu."
        )
    if that != git_sha:
        raise LoiCLI(
            f"--git-sha {git_sha[:12]}… ≠ HEAD đang checkout {that[:12]}…. "
            "Registry phải neo vào đúng cây được smoke."
        )

    ban = chay(["git", "-C", str(goc), "status", "--porcelain"]).strip()
    if ban:
        so_dong = len(ban.splitlines())
        raise LoiCLI(
            f"cây làm việc tại {goc} có {so_dong} thay đổi chưa commit. HEAD "
            "khớp KHÔNG có nghĩa mã đang chạy là mã của commit ấy — registry sẽ "
            "neo vào một SHA không mô tả đúng thứ vừa được smoke.\n"
            f"{ban[:400]}"
        )
    return git_sha


def chay_baseline(
    *, chay: ChayLenh, bo: BoCompose, thu_muc: Path, run_id: str, git_sha: str,
    pack: str, cid: str, thu_muc_dump: Path, app_env: str,
    ten_db: str = "qlts_smoke",
) -> Path:
    baseline.kiem_moi_truong(app_env=app_env, ten_db=ten_db)
    # Không có tham số tắt đối chiếu: một escape hatch trên đường production là
    # thứ sẽ được dùng đúng lúc không nên dùng.
    git_sha = kiem_git_sha(chay, git_sha)
    danh_tinh = _danh_tinh(chay, cid)

    # Đo + KIỂM model trước `Registry.mo()` và trước `pg_dump`. Bản trước đo tận
    # lúc ghi registry: `compose config` hỏng ở đó nghĩa là run-id đã bị chiếm và
    # một tệp dump rác đã nằm trên đĩa — hỏng ở giai đoạn không còn dọn được bằng
    # cách "chưa làm gì cả".
    vt_model = bo.van_tay(chay, app_env=app_env)

    reg = registry.Registry.mo(
        thu_muc, run_id=run_id, git_sha=git_sha, pack=pack,
        project=baseline._PROJECT_DUY_NHAT, database=ten_db,
    )

    thu_muc_dump.mkdir(parents=True, exist_ok=True)
    ten_tep = f"{run_id}.dump"
    trong_container = f"/tmp/{ten_tep}"
    tren_host = thu_muc_dump / ten_tep

    chay(_docker_exec(cid, baseline.lenh_dump(
        ten_db=ten_db, user="qlts", duong_trong_container=trong_container)))
    chay(["docker", "cp", f"{cid}:{trong_container}", str(tren_host)])

    # Kiểm archive NGAY: một bản dump hỏng phát hiện lúc này là phiền, phát hiện
    # lúc cleanup là mất database.
    toc = chay(_docker_exec(cid, baseline.lenh_liet_ke(
        duong_trong_container=trong_container)))
    sha = baseline.kiem_archive(
        duong=tren_host, dau_ra_pg_restore_list=toc, ma_thoat_pg_restore_list=0
    )

    reg.ghi_baseline(
        duong_dump=str(tren_host), sha256=sha,
        alembic_head=_alembic_head(chay, cid, ten_db),
        van_tay_metrics=_van_tay(chay, cid, ten_db),
        danh_tinh=danh_tinh,
        van_tay_model=vt_model,
    )
    print(f"[baseline] {run_id}: {tren_host} ({sha[:12]}…)")
    return tren_host


# =============================================================================
# --action-begin / --action-end
# =============================================================================
# Sổ HÀNH ĐỘNG: khai dự kiến TRƯỚC khi thao tác, đối chiếu SAU.
#
# `registry.bat_dau_action()`/`ket_thuc_action()` có từ đầu nhưng KHÔNG có caller
# vận hành nào — chỉ unit test gọi. Nghĩa là hợp đồng §A05 ("khai dự kiến trước
# mỗi mutation") không thi hành được: bấm nút trên trình duyệt thì DB đổi trước,
# sổ ghi sau, và không gì chứng minh được rằng chỉ đúng những hàng dự kiến đã đổi.
# Hai chế độ dưới đây là caller ấy.
#
# Ba cổng chạy trước MỖI lần, không phải chỉ lần đầu:
#   * sổ phải đúng project + database + **pack** (pack là cổng mới — xem
#     `Registry.doc`: thiếu nó thì seeder P1 chạy được trên sổ P2);
#   * sổ phải đã có baseline — không có mốc lùi thì không được phép mutate;
#   * danh tính PostgreSQL thật phải khớp `danh_tinh` đã ghi lúc baseline, tức
#     cùng container VÀ cùng cụm (`system_identifier`). Một stack dựng lại giữa
#     chừng sẽ bị bắt ở đây chứ không phải lúc cleanup.


def _sql_tren_dich(chay: ChayLenh, cid: str, ten_db: str):
    """Trả về hàm chạy một câu SQL trên đúng đích, đã kiểm tên database."""
    baseline.kiem_dich(ten_db)

    def f(sql: str) -> str:
        return chay(_docker_exec(cid, [
            "psql", "-U", "qlts", "-d", ten_db, "-At", "-v", "ON_ERROR_STOP=1",
            "-c", sql,
        ]))

    return f


def _so_cho_action(
    chay: ChayLenh, *, thu_muc: Path, run_id: str, pack: str, cid: str, ten_db: str
) -> "registry.Registry":
    if not str(pack or "").strip():
        raise LoiCLI(
            "--pack bắt buộc với action. Sổ của gói khác phải bị CHẶN, không phải "
            "bị bỏ qua: fixture gói này ghi vào sổ gói kia thì cleanup sẽ restore "
            "theo baseline của gói kia."
        )
    reg = registry.Registry.doc(
        thu_muc, run_id,
        project_mong_doi=baseline._PROJECT_DUY_NHAT,
        database_mong_doi=ten_db,
        pack_mong_doi=pack,
    )
    if not reg.du_lieu.get("baseline"):
        raise LoiCLI(
            f"sổ {run_id!r} chưa có baseline. Không có mốc để lùi về thì một ca "
            "hỏng giữa chừng là hỏng vĩnh viễn — chạy `--baseline` trước."
        )
    # `nen=` để `kiem_danh_tinh` so với danh tính đã ghi lúc baseline.
    _danh_tinh(chay, cid, nen=reg.du_lieu.get("danh_tinh"))
    return reg


def chay_action_bat_dau(
    *, chay: ChayLenh, thu_muc: Path, run_id: str, pack: str, cid: str,
    ten: str,
    them: Optional[Mapping[str, Sequence[str]]] = None,
    them_so_luong: Optional[Mapping[str, int]] = None,
    doi: Optional[Mapping[str, Sequence[str]]] = None,
    mat: Optional[Mapping[str, Sequence[str]]] = None,
    ten_db: str = "qlts_smoke",
) -> int:
    reg = _so_cho_action(chay, thu_muc=thu_muc, run_id=run_id, pack=pack, cid=cid,
                         ten_db=ten_db)
    # PHAM VI QUAN SAT KHONG PHAI LUA CHON CUA NGUOI CHAY.
    #
    # Ban truoc nhan `--bang`: nguoi van hanh tu chon bang nao duoc nhin. Thay
    # doi o bang bi bo sot thanh VO HINH — va bo sot la chuyen thuong, vi mot ca
    # nhu FIN-02 cham toi `fee`, `invoice`, `admission_profile`, `audit_log`,
    # `notification` chu khong chi `payment`. Mot so hanh dong chi nhin nhung cho
    # nguoi chay nho ra thi khong chung minh duoc "chi dung nhung hang da khai
    # moi doi".
    #
    # Nay chup CA `registry.BANG_THEO_DOI`. `ket_thuc_action` duyet
    # `set(truoc) | set(sau) | bang-da-khai`, nen moi thay doi trong 13 bang deu
    # bi doi chieu, khai hay khong. Chi phi: 13 truy van dem, moi truy van vai ms.
    bang = list(registry.BANG_THEO_DOI)
    truoc = anh_chup.chup(bang, _sql_tren_dich(chay, cid, ten_db))
    chi_so = reg.bat_dau_action(
        ten, truoc,
        bang_du_kien=bang,
        them_du_kien=them,
        them_so_luong_du_kien=them_so_luong,
        doi_du_kien=doi,
        mat_du_kien=mat,
    )
    tong = sum(len(v) for v in truoc.values())
    print(f"[action-begin] {ten}: chi_so={chi_so} · {len(truoc)} bảng · {tong} hàng đã chụp")
    return chi_so


def chay_action_ket_thuc(
    *, chay: ChayLenh, thu_muc: Path, run_id: str, pack: str, cid: str,
    chi_so: int, ten_db: str = "qlts_smoke",
) -> Dict[str, Dict[str, List[str]]]:
    if chi_so < 0:
        raise LoiCLI(
            f"chi so {chi_so} am — so am chon action theo chieu nguoc trong Python"
        )
    reg = _so_cho_action(chay, thu_muc=thu_muc, run_id=run_id, pack=pack, cid=cid,
                         ten_db=ten_db)
    try:
        ban_ghi = reg.du_lieu["actions"][chi_so]
    except (IndexError, KeyError, TypeError):
        raise LoiCLI(f"không có action chỉ số {chi_so} trong sổ {run_id!r}")

    # Bảng lấy từ CHÍNH ảnh chụp TRƯỚC, không nhận lại từ dòng lệnh: chụp SAU trên
    # một tập bảng khác là so hai thứ không so được, và sai lệch ấy sẽ hiện ra
    # thành "mất sạch hàng" ở bảng vắng mặt.
    bang = sorted(ban_ghi.get("truoc") or {})
    if not bang:
        raise LoiCLI(f"action {chi_so} không có ảnh chụp TRƯỚC — sổ hỏng")

    sau = anh_chup.chup(bang, _sql_tren_dich(chay, cid, ten_db))
    delta = reg.ket_thuc_action(chi_so, sau)
    print(f"[action-end] {ban_ghi.get('ten')}: ĐẠT")
    for bang_ten, phan in sorted(delta.items()):
        for loai, ids in sorted(phan.items()):
            if ids:
                print(f"    {bang_ten}.{loai}: {', '.join(map(str, ids))}")
    return delta


# =============================================================================
# --cleanup
# =============================================================================
# Template của `docker compose ps` — cố ý KHÔNG có `.RestartCount`.
#
# `formatter.ContainerContext` của Compose không có trường ấy; đưa vào là
# `template parsing error: can't evaluate field RestartCount`. Đã đo trên
# Docker thật. `RestartCount` chỉ tồn tại trong `docker inspect`, nên phải hỏi
# hai lần: Compose cho danh sách service, `inspect` cho số lần khởi động lại.
TEMPLATE_PS = "{{.Service}}|{{.State}}|{{.Health}}|{{.ID}}"


_RE_INSPECT = re.compile(r"^([0-9a-f]{64})\|(\d+)\|(\S*)$")


def _inspect_container(chay: ChayLenh, cid: str) -> tuple:
    """`(full_id, restart_count, oneoff)` — fail-closed về hình dạng.

    `docker inspect` trả rỗng hoặc sai dạng thì phải là LỖI: bản trước để
    `so_restart=""`, và hai nhịp cùng rỗng bằng nhau nên "ổn định" thành đúng
    trong khi ta chưa đo được gì.
    """
    tho = chay([
        "docker", "inspect", "--format",
        '{{.Id}}|{{.RestartCount}}|{{index .Config.Labels "com.docker.compose.oneoff"}}',
        cid,
    ]).strip()
    khop = _RE_INSPECT.match(tho)
    if not khop:
        raise LoiCLI(
            f"`docker inspect` cho {cid} trả {tho!r} — không đúng dạng "
            "`<64 hex>|<số>|<oneoff>`. Không đo được thì KHÔNG được coi là đã đo."
        )
    full_id, so_restart, oneoff = khop.groups()
    if not full_id.startswith(cid):
        raise LoiCLI(
            f"id đầy đủ {full_id[:16]}… không bắt đầu bằng id Compose {cid} — "
            "hai lệnh đang nói về hai container khác nhau."
        )
    return full_id, so_restart, oneoff


def _trang_thai_service(chay: ChayLenh, bo: BoCompose) -> Mapping[str, tuple]:
    """`{service: (state, health, full_id, restart_count)}`.

    Hai chỗ phải cẩn thận:

    * **Nhiều container cùng một service.** Mỗi `docker compose run` để lại một
      container one-off mang đúng nhãn service ấy. Đo thật trên stack dev:
      `backend|running|4df6…` và `backend|exited|7fbf…`, cái sau là one-off. Gán
      `ket[ten] = …` theo thứ tự dòng thì dòng sau ghi đè dòng trước — một
      one-off `running` xếp sau container chính đã chết sẽ cho readiness xanh
      giả. Nay one-off bị loại theo nhãn `com.docker.compose.oneoff`, và mỗi
      service phải còn **đúng một** container: 0 hoặc >1 đều là dừng.
    * `RestartCount` chỉ có ở `docker inspect` (xem `TEMPLATE_PS`).
    """
    tho = chay(bo.lenh("ps", "-a", "--format", TEMPLATE_PS))
    gom: Dict[str, list] = {}
    for dong in tho.splitlines():
        phan = (dong.strip().split("|") + ["", "", ""])[:4]
        ten, state, health, cid = phan
        if not ten or not cid:
            continue
        full_id, so_restart, oneoff = _inspect_container(chay, cid)
        if oneoff.lower() == "true":
            continue  # container của `compose run`, không thuộc stack đang chạy
        gom.setdefault(ten, []).append((state, health, full_id, so_restart))

    ket = {}
    for ten in SERVICE_UNG_DUNG:
        ds = gom.get(ten, [])
        if len(ds) > 1:
            raise LoiCLI(
                f"service {ten!r} có {len(ds)} container không phải one-off: "
                f"{[x[2][:12] for x in ds]}. Không xác định được cái nào là "
                "stack đang chạy — dừng thay vì đoán."
            )
        if ds:
            ket[ten] = ds[0]
    return ket


"""Chờ bốn service thật sự sẵn sàng, không chỉ 'running'."""

# Hai service này CÓ healthcheck ⇒ bắt buộc `healthy`. Health rỗng nghĩa là
# healthcheck chưa chạy xong (hoặc container được dựng thiếu healthcheck) —
# cả hai đều KHÔNG phải "sẵn sàng".
SERVICE_CO_HEALTH = ("backend", "frontend")


def _cho_san_sang(*, chay: ChayLenh, bo: BoCompose, ngu, han_giay: int,
                  nhip: int = 3) -> None:
    """Chờ tới khi bốn service thật sự sẵn sàng.

    Hai điều kiện, mỗi cái đóng một cách tự lừa:

    * `backend`/`frontend` phải `health == "healthy"`. Bản đầu viết
      `elif hl and hl not in {"healthy", ""}` — chuỗi rỗng đi lọt, nên một
      container `running` mà healthcheck chưa chạy xong vẫn được coi là sẵn sàng.
    * hai Celery không có healthcheck, nên "ổn định" được đo bằng **container id
      và RestartCount không đổi qua hai nhịp**. So mỗi trạng thái là không đủ:
      một container crashloop luôn có khoảnh khắc `running`, và lần `running`
      sau đã là một container/lần khởi động khác.
    """
    con = han_giay
    truoc: Optional[Mapping[str, tuple]] = None
    trang_thai: Mapping[str, tuple] = {}
    while con > 0:
        trang_thai = _trang_thai_service(chay, bo)
        chua = []
        for s in SERVICE_UNG_DUNG:
            st, hl, _cid, _rs = trang_thai.get(s, ("<không thấy>", "", "", ""))
            if st != "running":
                chua.append(f"{s}={st}")
            elif s in SERVICE_CO_HEALTH and hl != "healthy":
                chua.append(f"{s}=health:{hl or '<rỗng>'}")

        if not chua:
            if truoc is not None:
                doi = [
                    f"{s}: {truoc[s][2][:12]}/{truoc[s][3]} → "
                    f"{trang_thai[s][2][:12]}/{trang_thai[s][3]}"
                    for s in SERVICE_UNG_DUNG
                    if s in truoc and (
                        truoc[s][2] != trang_thai[s][2]
                        or truoc[s][3] != trang_thai[s][3]
                    )
                ]
                if not doi:
                    return  # hai nhịp liên tiếp: cùng container, cùng số lần restart
                chua = [f"chưa ổn định ({'; '.join(doi)})"]
            truoc = trang_thai
        else:
            truoc = None
        ngu(nhip)
        con -= nhip
    raise LoiCLI(
        f"quá {han_giay}s mà service chưa sẵn sàng: {dict(trang_thai)}"
    )


def _preflight_archive(*, chay: ChayLenh, cid: str, bl: Mapping[str, str]) -> None:
    """Chép archive vào container rồi chứng minh **chính bản đó** dùng được."""
    tren_host = Path(bl["duong_dump"])
    trong_container = f"/tmp/{tren_host.name}"
    chay(["docker", "cp", str(tren_host), f"{cid}:{trong_container}"])

    toc = chay(_docker_exec(cid, baseline.lenh_liet_ke(
        duong_trong_container=trong_container)))
    baseline.kiem_archive(
        duong=tren_host, dau_ra_pg_restore_list=toc,
        ma_thoat_pg_restore_list=0, sha_mong_doi=bl["sha256"],
    )

    # ⚠️ Phép kiểm trên nói về tệp TRÊN HOST. `pg_restore` lại đọc bản trong
    # container — hai tệp khác nhau. Hash chính tệp sắp được đọc, nếu không thì
    # một archive khác có TOC hợp lệ nằm sẵn ở `/tmp/<run>.dump` vẫn được
    # restore trong khi ta báo "checksum khớp".
    sha_container = baseline.doc_sha256_tu_sha256sum(
        chay(_docker_exec(cid, baseline.lenh_sha256_trong_container(
            duong_trong_container=trong_container)))
    )
    if sha_container != bl["sha256"]:
        raise LoiCLI(
            f"archive TRONG CONTAINER có sha {sha_container[:12]}… ≠ baseline "
            f"{bl['sha256'][:12]}…. Tệp sắp được restore không phải tệp đã ghi "
            "baseline — dừng TRƯỚC khi drop."
        )


def chay_cleanup(
    *, chay: ChayLenh, bo: BoCompose, thu_muc: Path, run_id: str, cid: str,
    thu_muc_dump: Path, app_env: str, ten_db: str = "qlts_smoke",
    ngu=time.sleep, han_cho_giay: int = 180,
) -> None:
    reg = registry.Registry.doc_cho_cleanup(
        thu_muc, run_id, project=baseline._PROJECT_DUY_NHAT,
        database=ten_db, goc_dump_cho_phep=thu_muc_dump,
    )
    bl = reg.du_lieu["baseline"]

    # (2) Kiểm lại — danh tính có thể đã đổi kể từ lúc ghi baseline.
    baseline.kiem_moi_truong(app_env=app_env, ten_db=ten_db)
    _danh_tinh(chay, cid, nen=reg.du_lieu.get("danh_tinh"))

    # (2b) …và MODEL cũng có thể đã đổi. Danh tính container chứng minh "vẫn đúng
    # cái postgres ấy"; nó KHÔNG chứng minh lệnh `stop`/`start` sắp chạy sẽ nhắm
    # đúng stack đó. Hai lệnh cùng `-p qltssmoke` mà khác `-f`/`--env-file` là hai
    # model khác nhau — đúng lỗ hổng của bản trước.
    vt_model = bo.van_tay(chay, app_env=app_env)
    vt_nen = bl.get("van_tay_model", "")
    if vt_model != vt_nen:
        raise LoiCLI(
            "model Compose lúc cleanup KHÁC lúc ghi baseline "
            f"({vt_model[:12]}… ≠ {vt_nen[:12]}…). Kiểm lại `--compose-file` và "
            "`--compose-env-file` — cleanup đang điều khiển một stack khác."
        )

    # (3)–(4) Từ lúc DỪNG service trở đi, mọi lỗi phải được ghi lại: database
    # vẫn an toàn (chưa drop), nhưng stack smoke đang ở trạng thái NỬA CHỪNG —
    # service đã tắt. Bản đầu để `cleanup=None` ở đây, nên sổ không nói gì về
    # việc dịch vụ đang đóng.
    da_stop = False
    try:
        chay(bo.lenh("stop", *SERVICE_UNG_DUNG))
        da_stop = True
        con = chay(_docker_exec(cid, baseline.lenh_dem_session(
            ten_db=ten_db, user="qlts"))).strip()
        if con != "0":
            raise LoiCLI(
                f"còn {con} session mở tới {ten_db} sau khi dừng service. Drop "
                "lúc này sẽ đổ, hoặc tệ hơn là drop một database đang được ghi."
            )
        _preflight_archive(chay=chay, cid=cid, bl=bl)
    except Exception as e:
        # Chỉ được khẳng định "đang đóng" khi lệnh stop THỰC SỰ exit 0. Nếu
        # chính stop hỏng thì ta không biết service đang ở đâu — nói "đang đóng"
        # lúc ấy là ghi vào sổ một điều chưa kiểm.
        mo_ta = ("service đang ĐÓNG" if da_stop
                 else "trạng thái service KHÔNG XÁC ĐỊNH (lệnh stop cũng hỏng)")
        reg.ghi_cleanup(
            trang_thai="BO_QUA", van_tay_sau="",
            ghi_chu=f"preflight hỏng TRƯỚC khi drop (DB nguyên vẹn), {mo_ta}: {e}"[:500],
        )
        raise LoiCLI(
            f"preflight cleanup hỏng: {e}\nDatabase KHÔNG bị đụng; {mo_ta}."
        ) from e

    trong_container = f"/tmp/{Path(bl['duong_dump']).name}"

    # (5)–(6) Từ đây mọi lỗi đều ghi HONG và GIỮ DỊCH VỤ ĐÓNG.
    try:
        for lenh in baseline.lenh_drop_tao(ten_db=ten_db, user="qlts"):
            chay(_docker_exec(cid, lenh))
        chay(_docker_exec(cid, baseline.lenh_restore(
            ten_db=ten_db, user="qlts", duong_trong_container=trong_container)))

        vt = _van_tay(chay, cid, ten_db)
        baseline.kiem_sau_restore(
            van_tay_baseline=bl["van_tay_metrics"], van_tay_hien_tai=vt,
            alembic_baseline=bl["alembic_head"],
            alembic_hien_tai=_alembic_head(chay, cid, ten_db),
        )
    except Exception as e:
        reg.ghi_cleanup(trang_thai="HONG", van_tay_sau="", ghi_chu=str(e)[:500])
        raise LoiCLI(
            f"cleanup HỎNG: {e}\n"
            f"Database {ten_db} đang ở trạng thái KHÔNG xác định. Dịch vụ được "
            "giữ ĐÓNG có chủ ý — không chạy pack tiếp theo, dựng lại từ đầu."
        ) from e

    # (7) Mở lại dịch vụ, chờ SẴN SÀNG, rồi ĐO LẠI, rồi mới ghi ĐẠT.
    #
    # ⚠️ `ps --status running` một mình KHÔNG đủ. `docker-entrypoint.sh` của
    # backend chạy `alembic upgrade head` + `sync_notification_rules` lúc khởi
    # động: container "running" có thể đang GHI VÀO database vừa restore. Nếu ghi
    # `DAT` lúc ấy, sổ khẳng định "đã về nền" trong khi nền đang bị sửa.
    #
    # Nên: start → chờ healthy/ổn định → **đo lại vân tay + Alembic** → so lại
    # với baseline → chỉ khi vẫn khớp mới `DAT`.
    vt_sau: Optional[str] = None
    try:
        chay(bo.lenh("start", *SERVICE_UNG_DUNG))
        _cho_san_sang(chay=chay, bo=bo, ngu=ngu, han_giay=han_cho_giay)

        vt_sau = _van_tay(chay, cid, ten_db)
        baseline.kiem_sau_restore(
            van_tay_baseline=bl["van_tay_metrics"], van_tay_hien_tai=vt_sau,
            alembic_baseline=bl["alembic_head"],
            alembic_hien_tai=_alembic_head(chay, cid, ten_db),
        )
    except Exception as e:
        # Start một phần rồi hỏng ⇒ có service đang chạy trên một database ta
        # không còn khẳng định được gì. Cố đóng lại cả bốn trước khi báo.
        ghi_them = ""
        try:
            chay(bo.lenh("stop", *SERVICE_UNG_DUNG))
            ghi_them = " Đã stop lại cả bốn service."
        except Exception as e2:
            ghi_them = f" KHÔNG stop lại được service: {e2}"
        # ⚠️ Lưu vân tay ĐO ĐƯỢC SAU START, không phải `vt` (đo trước start).
        # Nếu chính startup làm lệch DB thì `vt` là con số đã lỗi thời, và ghi
        # nó vào ô "van_tay_sau" là ghi một trạng thái không còn tồn tại — người
        # điều tra sẽ so nhầm và kết luận DB vẫn đúng nền.
        if vt_sau is None:
            mo_ta_vt = "chưa đo được vân tay sau start (hỏng trước bước đo)"
        else:
            mo_ta_vt = f"vân tay sau start = {vt_sau[:12]}…, nền = {bl['van_tay_metrics'][:12]}…"
        reg.ghi_cleanup(
            trang_thai="HONG", van_tay_sau=(vt_sau or ""),
            ghi_chu=(f"DB đã về nền ngay sau restore, nhưng giai đoạn mở lại dịch "
                     f"vụ hỏng: {e}. {mo_ta_vt}.{ghi_them}")[:500],
        )
        raise LoiCLI(
            f"restore đạt nhưng giai đoạn mở lại dịch vụ hỏng: {e}\n"
            f"{ghi_them.strip()} Không chạy pack tiếp theo trước khi kiểm tay."
        ) from e

    reg.ghi_cleanup(trang_thai="DAT", van_tay_sau=vt_sau)
    print(f"[cleanup] {run_id}: ĐẠT — restore về baseline, dịch vụ đã sẵn sàng, "
          "vân tay vẫn khớp sau khi service chạy lại")


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Harness smoke Finance")
    che_do = p.add_mutually_exclusive_group(required=True)
    che_do.add_argument("--baseline", action="store_true")
    che_do.add_argument("--cleanup", action="store_true")
    che_do.add_argument("--action-begin", action="store_true")
    che_do.add_argument("--action-end", action="store_true")
    p.add_argument("--run-id", required=True)
    p.add_argument("--container", required=True, help="container id của postgres smoke")
    p.add_argument("--thu-muc", type=Path, required=True, help="gốc registry")
    # `--thu-muc-dump`/`--app-env`/`--compose-*` chi thuoc ve baseline va cleanup.
    # Action khong dump, khong goi lenh compose nao — bat chung o day chi lam
    # nguoi chay phai bia gia tri, va mot gia tri bia thi khong ai kiem.
    # Thieu chung O DUNG che do can chung van la DUNG (xem kiem ngay duoi).
    p.add_argument("--thu-muc-dump", type=Path, default=None)
    p.add_argument("--app-env", default="")
    p.add_argument("--git-sha", default="")
    p.add_argument("--pack", default="")
    # BẮT BUỘC, không default: xem docstring `BoCompose`. Một mặc định ở đây chỉ
    # là một cách hỏng im lặng trên máy có `docker-compose.override.yml` của dev.
    p.add_argument(
        "--compose-file", action="append", default=None, metavar="TEP",
        help="tệp compose dựng nên stack smoke; lặp lại đúng thứ tự đã dùng",
    )
    p.add_argument(
        "--compose-env-file", default="", metavar="TEP",
        help="env file đã dùng lúc dựng (phải đặt QLTS_ENV_FILE)",
    )
    # --- rieng cho action ---
    p.add_argument("--ten", default="", metavar="MA_CA",
                   help="ma ca, vd FIN-02.a1 — di vao so hanh dong")
    p.add_argument("--them", action="append", default=[], metavar="BANG=ID[,ID]")
    p.add_argument("--them-so-luong", action="append", default=[], metavar="BANG=N",
                   help="dung khi server sinh id: khai SO LUONG hang se them")
    p.add_argument("--doi", action="append", default=[], metavar="BANG=ID[,ID]")
    p.add_argument("--mat", action="append", default=[], metavar="BANG=ID[,ID]")
    p.add_argument("--chi-so", type=int, default=None,
                   help="chi so action tra ve boi --action-begin")
    a = p.parse_args(argv)

    chay = ChayLenh()
    try:
        if a.action_begin or a.action_end:
            # Action khong dung BoCompose: no khong goi lenh compose nao.
            #
            # Co sai che do phai la DUNG, khong phai bi bo qua im lang: dat
            # `--them payment=7` o lenh `--action-end` nghia la nguoi chay tuong
            # minh vua khai mot ky vong — bo qua no thi ho doc ket qua "DAT" nhu
            # la ky vong ay da duoc kiem.
            sai_che_do = []
            if a.action_end:
                sai_che_do = [
                    ten for ten, gt in (
                        ("--ten", a.ten), ("--them", a.them),
                        ("--them-so-luong", a.them_so_luong),
                        ("--doi", a.doi), ("--mat", a.mat),
                    ) if gt
                ]
            else:
                sai_che_do = ["--chi-so"] if a.chi_so is not None else []
            if sai_che_do:
                raise LoiCLI(
                    f"che do nay khong dung {', '.join(sai_che_do)} — dat chung o "
                    "day la khai mot ky vong ma khong ai kiem"
                )
            if a.action_begin:
                if not a.ten:
                    raise LoiCLI("--action-begin can --ten (ma ca)")
                chay_action_bat_dau(
                    chay=chay, thu_muc=a.thu_muc, run_id=a.run_id, pack=a.pack,
                    cid=a.container, ten=a.ten,
                    them=anh_chup.doc_cap(a.them, ten_co="--them") or None,
                    them_so_luong=anh_chup.doc_so_luong(
                        a.them_so_luong, ten_co="--them-so-luong") or None,
                    doi=anh_chup.doc_cap(a.doi, ten_co="--doi") or None,
                    mat=anh_chup.doc_cap(a.mat, ten_co="--mat") or None,
                )
            else:
                if a.chi_so is None:
                    raise LoiCLI("--action-end can --chi-so")
                # `--chi-so -1` chon action CUOI theo indexing cua Python — mot
                # so am go nham se ket thuc nham action ma khong bao gi.
                if a.chi_so < 0:
                    raise LoiCLI(
                        f"--chi-so={a.chi_so} am. So am chon action theo chieu "
                        "nguoc trong Python; chi so that luon >= 0."
                    )
                chay_action_ket_thuc(
                    chay=chay, thu_muc=a.thu_muc, run_id=a.run_id, pack=a.pack,
                    cid=a.container, chi_so=a.chi_so,
                )
            return 0

        # baseline/cleanup: bon tham so duoi day moi that su bat buoc.
        thieu = [
            ten for ten, gt in (
                ("--thu-muc-dump", a.thu_muc_dump),
                ("--app-env", a.app_env),
                ("--compose-file", a.compose_file),
                ("--compose-env-file", a.compose_env_file),
            ) if not gt
        ]
        if thieu:
            raise LoiCLI(f"che do nay can: {', '.join(thieu)}")
        bo = BoCompose(a.compose_file, a.compose_env_file)
        if a.baseline:
            if not a.pack:
                raise LoiCLI("--baseline cần --pack")
            chay_baseline(
                chay=chay, bo=bo, thu_muc=a.thu_muc, run_id=a.run_id, git_sha=a.git_sha,
                pack=a.pack, cid=a.container, thu_muc_dump=a.thu_muc_dump,
                app_env=a.app_env,
            )
        elif a.cleanup:
            chay_cleanup(
                chay=chay, bo=bo, thu_muc=a.thu_muc, run_id=a.run_id, cid=a.container,
                thu_muc_dump=a.thu_muc_dump, app_env=a.app_env,
            )
    except (LoiCLI, baseline.ChanLai, registry.LoiRegistry,
            anh_chup.LoiAnhChup) as e:
        print(f"DỪNG: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
