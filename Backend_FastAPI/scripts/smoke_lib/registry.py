"""Registry của một lượt smoke — sổ cái các id, ghi atomically.

Vì sao cần
----------
Runbook §A05 đòi mọi id được ghi **trước** khi mutation xảy ra: khi một ca hỏng
giữa chừng, sổ này là thứ duy nhất cho biết lượt chạy đã đụng vào những bản ghi
nào. Tra ngược theo tên hay theo thời gian tạo đều sai — tên trùng được, và job
nền chạy song song cũng tạo bản ghi trong cùng khoảng thời gian.

Sổ này KHÔNG phải cơ chế dọn dẹp. Cleanup đi bằng **restore database
`qlts_smoke`** (xem `baseline.py`). Registry tồn tại để đối soát, để điều tra
khi fail, và để chứng minh sau cleanup rằng trạng thái đã về nền.

Bốn bất biến, mỗi cái từng là một cách tự lừa
---------------------------------------------
1. **Ghi atomic, và RAM không được lệch đĩa.** Bản đầu mutate `self.du_lieu`
   rồi mới `_luu()`; `_luu()` hỏng thì tệp cũ còn nguyên nhưng đối tượng trong
   bộ nhớ đã đổi — lần ghi sau lưu luôn thay đổi lẽ ra đã thất bại. Nay mọi
   thay đổi diễn ra trên **bản sao**, chỉ gán vào `self.du_lieu` sau khi ghi
   xuống đĩa thành công.
2. **Intent phải khai TRƯỚC mutation.** `cho_phep_moi` truyền lúc kết thúc
   action không chứng minh được điều gì: người viết ca nhìn thấy id lạ rồi thêm
   nó vào danh sách cho phép là xong. Nay `bat_dau_action()` ghi dự kiến xuống
   đĩa trước, `ket_thuc_action()` chỉ **tiêu thụ** intent đã lưu.
3. **Delta ba chiều.** Chỉ so id mới thì bỏ sót hai ca: bản ghi **biến mất**, và
   bản ghi **cùng id nhưng đổi nội dung** (amount/status) — đúng thứ mà smoke
   Finance cần chứng minh. Ảnh chụp vì thế là `{bảng: {id: vân tay hàng}}`.
4. **Đọc lại phải validate.** Một `registry.json` sửa tay không được tin thẳng:
   schema, project/database, checksum và vị trí tệp dump đều phải kiểm lại.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


class LoiRegistry(RuntimeError):
    """Sai sót đủ nghiêm trọng để dừng lượt smoke."""


_KHOA_CAM = re.compile(
    r"(pass(word|wd)?|secret|token|cookie|authorization|api[_-]?key|"
    r"session[_-]?id|bearer|credential)",
    re.IGNORECASE,
)

BANG_THEO_DOI = (
    "lead",
    "admission_profile",
    "fee",
    "invoice",
    "payment",
    "payment_transaction",
    "payment_intent",
    "payment_import_batch",
    "payment_import_row",
    "refund_request",
    "overpayment_record",
    "audit_log",
    "notification",
)

_KHOA_BAT_BUOC = {
    "run_id", "git_sha", "pack", "project", "database",
    "baseline", "goc", "ids", "actions", "cleanup",
}

# Ảnh chụp: {bảng: {id(str): vân tay hàng}}
AnhChup = Dict[str, Dict[str, str]]


def _bay_gio() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _kiem_khong_co_bi_mat(du_lieu: Any, duong_dan: str = "") -> None:
    if isinstance(du_lieu, dict):
        for khoa, gia_tri in du_lieu.items():
            if _KHOA_CAM.search(str(khoa)):
                raise LoiRegistry(
                    f"registry chứa khoá nghi là bí mật: {duong_dan}{khoa!r}. "
                    "Sổ này được đọc bằng mắt và đính vào report."
                )
            _kiem_khong_co_bi_mat(gia_tri, f"{duong_dan}{khoa}.")
    elif isinstance(du_lieu, (list, tuple)):
        for i, pt in enumerate(du_lieu):
            _kiem_khong_co_bi_mat(pt, f"{duong_dan}[{i}].")


def _ghi_atomic(duong: Path, du_lieu: Dict[str, Any]) -> None:
    _kiem_khong_co_bi_mat(du_lieu)
    duong.parent.mkdir(parents=True, exist_ok=True)
    fd, tam = tempfile.mkstemp(dir=str(duong.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(du_lieu, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tam, duong)
    except BaseException:
        Path(tam).unlink(missing_ok=True)
        raise


def van_tay(du_lieu: Any) -> str:
    chuoi = json.dumps(du_lieu, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(chuoi.encode("utf-8")).hexdigest()


def van_tay_hang(truong: Mapping[str, Any]) -> str:
    """Vân tay của MỘT hàng — để bắt thay đổi nội dung ở cùng id.

    Truyền đúng những trường mà ca đang khẳng định điều gì đó (amount, status,
    paid_amount…). Không truyền cả hàng: `updated_at` đổi mỗi lần ghi sẽ làm mọi
    hàng luôn "đã đổi", và một tín hiệu luôn bật thì không còn là tín hiệu.
    """
    return van_tay(dict(truong))[:16]


class Registry:
    def __init__(self, duong: Path, du_lieu: Dict[str, Any]) -> None:
        self.duong = duong
        self.du_lieu = du_lieu

    # --- ghi: mutate trên bản sao, chỉ nhận khi đã xuống đĩa ---------------
    def _ghi(self, thay_doi) -> None:
        ban_sao = copy.deepcopy(self.du_lieu)
        thay_doi(ban_sao)
        ban_sao["cap_nhat_luc"] = _bay_gio()
        _ghi_atomic(self.duong, ban_sao)
        self.du_lieu = ban_sao

    # --- vòng đời ----------------------------------------------------------
    @classmethod
    def mo(
        cls, thu_muc: Path, *, run_id: str, git_sha: str, pack: str,
        project: str, database: str,
    ) -> "Registry":
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", run_id):
            raise LoiRegistry(f"run_id không hợp lệ: {run_id!r}")
        duong = thu_muc / run_id / "registry.json"
        if duong.exists():
            raise LoiRegistry(
                f"{duong} đã tồn tại. Một run_id chỉ mở MỘT lần — mở lại sẽ xoá "
                "dấu vết những gì lượt trước đã đụng."
            )
        du_lieu: Dict[str, Any] = {
            "run_id": run_id, "git_sha": git_sha, "pack": pack,
            "project": project, "database": database, "mo_luc": _bay_gio(),
            "baseline": None, "danh_tinh": None,
            "goc": {"lead_ids": [], "profile_ids": []},
            "ids": {}, "actions": [], "cleanup": None,
        }
        _ghi_atomic(duong, du_lieu)
        return cls(duong, du_lieu)

    @classmethod
    def doc(
        cls, thu_muc: Path, run_id: str, *,
        project_mong_doi: Optional[str] = None,
        database_mong_doi: Optional[str] = None,
        goc_dump_cho_phep: Optional[Path] = None,
    ) -> "Registry":
        """Đọc lại sổ — và KHÔNG tin nó cho tới khi kiểm xong.

        `registry.json` là tệp trên đĩa, sửa tay được. Cleanup đọc nó rồi drop
        database, nên mọi trường mà cleanup dựa vào đều phải kiểm lại ở đây.
        """
        duong = thu_muc / run_id / "registry.json"
        if not duong.is_file():
            raise LoiRegistry(f"không thấy registry {duong}")
        try:
            du_lieu = json.loads(duong.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise LoiRegistry(f"{duong} không phải JSON hợp lệ: {e}") from e
        if not isinstance(du_lieu, dict):
            raise LoiRegistry(f"{duong} không phải một object JSON")

        thieu = sorted(_KHOA_BAT_BUOC - set(du_lieu))
        if thieu:
            raise LoiRegistry(f"{duong} thiếu khoá bắt buộc: {thieu}")
        if du_lieu.get("run_id") != run_id:
            raise LoiRegistry(
                f"run_id trong tệp ({du_lieu.get('run_id')!r}) khác thư mục "
                f"({run_id!r}) — sổ đã bị chép nhầm chỗ"
            )
        if project_mong_doi is not None and du_lieu.get("project") != project_mong_doi:
            raise LoiRegistry(
                f"project {du_lieu.get('project')!r} ≠ {project_mong_doi!r}"
            )
        if database_mong_doi is not None and du_lieu.get("database") != database_mong_doi:
            raise LoiRegistry(
                f"database {du_lieu.get('database')!r} ≠ {database_mong_doi!r} — "
                "sổ này không thuộc về đích đang định dọn"
            )

        bl = du_lieu.get("baseline")
        if bl is not None:
            if not isinstance(bl, dict):
                raise LoiRegistry("baseline không phải object")
            for khoa in ("duong_dump", "sha256", "alembic_head", "van_tay_metrics",
                         "van_tay_model"):
                if not bl.get(khoa):
                    raise LoiRegistry(f"baseline thiếu {khoa}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(bl["sha256"])):
                raise LoiRegistry(f"baseline.sha256 không phải SHA-256: {bl['sha256']!r}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(bl["van_tay_metrics"])):
                raise LoiRegistry(
                    f"baseline.van_tay_metrics không phải SHA-256: "
                    f"{bl['van_tay_metrics']!r} — đây là thứ cleanup so sau "
                    "restore, một chuỗi tuỳ ý làm phép so mất nghĩa"
                )
            # Cùng lý do, và đường ĐỌC phải kiểm chứ không chỉ đường GHI: một sổ
            # hỏng (sửa tay, ghi dở, chép từ lượt khác) mà `van_tay_model` là rác
            # thì phép so ở cleanup vẫn "chạy" — nó chỉ luôn lệch, và người đọc
            # log sẽ đi tìm nhầm nguyên nhân ở bộ Compose.
            if not re.fullmatch(r"[0-9a-f]{64}", str(bl["van_tay_model"])):
                raise LoiRegistry(
                    f"baseline.van_tay_model không phải SHA-256: "
                    f"{bl['van_tay_model']!r}"
                )
            if not du_lieu.get("danh_tinh"):
                raise LoiRegistry(
                    "có baseline nhưng thiếu `danh_tinh` — không biết bản dump "
                    "này thuộc container/cụm PostgreSQL nào"
                )
            if goc_dump_cho_phep is not None:
                dump = Path(str(bl["duong_dump"])).resolve()
                goc = Path(goc_dump_cho_phep).resolve()
                if not dump.is_relative_to(goc):
                    raise LoiRegistry(
                        f"đường dump {dump} nằm ngoài {goc}. Cleanup đọc đường này "
                        "rồi restore từ đó — một đường trỏ ra ngoài là đường để "
                        "nạp dữ liệu lạ vào database."
                    )
        _kiem_khong_co_bi_mat(du_lieu)
        return cls(duong, du_lieu)

    @classmethod
    def doc_cho_cleanup(
        cls, thu_muc: Path, run_id: str, *,
        project: str, database: str, goc_dump_cho_phep: Path,
    ) -> "Registry":
        """Đường đọc dành riêng cho cleanup — ba tham số đều BẮT BUỘC.

        `doc()` để chúng optional là hợp lý cho việc đọc-để-xem. Nhưng cleanup
        thì drop database dựa trên sổ này, và một lối gọi quên truyền tham số sẽ
        bỏ qua đúng ba phép kiểm quan trọng nhất mà không báo gì. Ở đây không có
        giá trị mặc định để mà quên.
        """
        reg = cls.doc(
            thu_muc, run_id,
            project_mong_doi=project,
            database_mong_doi=database,
            goc_dump_cho_phep=goc_dump_cho_phep,
        )
        if not reg.du_lieu.get("baseline"):
            raise LoiRegistry(
                "sổ chưa có baseline — không có gì để restore về. Cleanup phải "
                "dừng chứ không được drop database rồi mới phát hiện."
            )
        return reg

    # --- baseline + danh tính ---------------------------------------------
    def ghi_baseline(
        self, *, duong_dump: str, sha256: str, alembic_head: str,
        van_tay_metrics: str, danh_tinh: Mapping[str, str],
        van_tay_model: str,
    ) -> None:
        if self.du_lieu.get("baseline"):
            raise LoiRegistry("baseline đã được ghi; không ghi đè")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
            raise LoiRegistry(f"sha256 không hợp lệ: {sha256!r}")
        # Bắt buộc, không default: thiếu vân tay model thì cleanup không còn cách
        # nào biết nó đang điều khiển đúng stack đã đo baseline.
        if not re.fullmatch(r"[0-9a-f]{64}", van_tay_model or ""):
            raise LoiRegistry(f"van_tay_model không hợp lệ: {van_tay_model!r}")

        def _td(d):
            d["baseline"] = {
                "duong_dump": duong_dump, "sha256": sha256,
                "alembic_head": alembic_head, "van_tay_metrics": van_tay_metrics,
                "van_tay_model": van_tay_model,
                "luc": _bay_gio(),
            }
            d["danh_tinh"] = dict(danh_tinh)

        self._ghi(_td)

    # --- ownership roots ---------------------------------------------------
    def them_goc(
        self, *, lead_ids: Iterable[int] = (), profile_ids: Iterable[int] = ()
    ) -> None:
        def _td(d):
            g = d["goc"]
            g["lead_ids"] = sorted(set(g["lead_ids"]) | {int(x) for x in lead_ids})
            g["profile_ids"] = sorted(
                set(g["profile_ids"]) | {int(x) for x in profile_ids}
            )

        self._ghi(_td)

    def ghi_ids(self, bang: str, ids: Iterable[int]) -> None:
        if bang not in BANG_THEO_DOI:
            raise LoiRegistry(
                f"bảng {bang!r} không có trong BANG_THEO_DOI. Thêm bảng là việc "
                "có chủ ý: nó mở rộng phạm vi smoke được phép chạm tới."
            )

        def _td(d):
            cu = set(d["ids"].get(bang, []))
            d["ids"][bang] = sorted(cu | {int(x) for x in ids})

        self._ghi(_td)

    def tat_ca_ids(self) -> Dict[str, List[int]]:
        return {k: list(v) for k, v in self.du_lieu["ids"].items()}

    # --- ảnh chụp ----------------------------------------------------------
    @staticmethod
    def chuan_hoa(anh_chup: Mapping[str, Mapping[Any, str]]) -> AnhChup:
        return {
            str(bang): {str(k): str(v) for k, v in sorted(hang.items(), key=lambda x: str(x[0]))}
            for bang, hang in sorted(anh_chup.items())
        }

    # --- action: intent khai TRƯỚC, tiêu thụ SAU ---------------------------
    def bat_dau_action(
        self, ten: str, truoc: AnhChup, *,
        bang_du_kien: Iterable[str],
        them_du_kien: Optional[Mapping[str, Iterable[Any]]] = None,
        them_so_luong_du_kien: Optional[Mapping[str, int]] = None,
        doi_du_kien: Optional[Mapping[str, Iterable[Any]]] = None,
        mat_du_kien: Optional[Mapping[str, Iterable[Any]]] = None,
    ) -> int:
        """Ghi dự kiến xuống đĩa TRƯỚC khi thao tác. Trả về chỉ số action.

        Hai cách khai phần **thêm**, dùng đúng cái hợp với ca:

        * `them_du_kien={"payment": ["7"]}` — khi id biết trước (ta tự chọn).
        * `them_so_luong_du_kien={"payment": 1}` — khi **server sinh id**, tức
          hầu hết ca UI. Ta không thể biết id trước, nhưng vẫn khai được rằng
          "đúng một hàng payment sẽ xuất hiện"; id thật được ghi lại sau.

        Thiếu vế thứ hai thì mọi ca có id do server sinh buộc phải khai rỗng, và
        khi ấy `ket_thuc_action` sẽ báo mọi thứ là ngoài dự kiến — guard hoá ra
        cản đúng đường lành, và người dùng sẽ tắt nó.
        """
        bang_du_kien = [str(b) for b in bang_du_kien]
        la = [b for b in bang_du_kien if b not in BANG_THEO_DOI]
        if la:
            raise LoiRegistry(f"bảng dự kiến ngoài BANG_THEO_DOI: {la}")

        truoc = self.chuan_hoa(truoc)

        # ⚠️ Rỗng KHÔNG phải một quan sát hợp lệ. `truoc={}` + `bang_du_kien=[]`
        # đi lọt qua phép so bên dưới (hai tập rỗng bằng nhau), rồi vòng đối soát
        # ở `ket_thuc_action` không duyệt bảng nào và action thành "DAT" —
        # registry tuyên bố đạt trong khi nó chưa hề nhìn vào cái gì.
        #
        # Phân biệt với ca LÀNH: `{"payment": {}}` là có quan sát bảng `payment`,
        # chỉ là bảng ấy không có hàng nào. Ca đó phải qua.
        if not bang_du_kien:
            raise LoiRegistry(
                f"action {ten!r}: `bang_du_kien` rỗng — không khai quan sát bảng "
                "nào thì không có gì để đối soát, và 'không thấy gì' sẽ bị đọc "
                "nhầm thành 'không có gì sai'."
            )
        if not truoc:
            raise LoiRegistry(
                f"action {ten!r}: ảnh chụp TRƯỚC rỗng — cần ít nhất một bảng "
                'được quan sát (bảng không có hàng thì chụp `{"payment": {}}`, '
                "không phải `{}`)."
            )

        # Ảnh chụp và dự kiến phải nói về CÙNG tập bảng. Nếu không, ta có thể
        # khai dự kiến `fee` trong khi chỉ chụp `payment` — action vẫn "DAT" mà
        # chẳng phép kiểm nào chạm tới `fee`.
        if set(bang_du_kien) != set(truoc):
            raise LoiRegistry(
                f"bang_du_kien {sorted(bang_du_kien)} khác tập bảng trong ảnh "
                f"chụp {sorted(truoc)}. Dự kiến chỉ có nghĩa khi nó nói về đúng "
                "những bảng được quan sát."
            )

        so_luong = {str(k): int(v) for k, v in (them_so_luong_du_kien or {}).items()}
        if any(v < 0 for v in so_luong.values()):
            raise LoiRegistry("them_so_luong_du_kien không nhận số âm")

        # Mọi expectation phải nói về bảng CÓ trong ảnh chụp. Khai cho bảng không
        # được chụp thì không phép kiểm nào chạm tới nó — dự kiến hoá ra trang trí.
        _them = {k: sorted(str(x) for x in v) for k, v in (them_du_kien or {}).items()}
        _doi = {k: sorted(str(x) for x in v) for k, v in (doi_du_kien or {}).items()}
        _mat = {k: sorted(str(x) for x in v) for k, v in (mat_du_kien or {}).items()}
        for ten_khai, khai in (
            ("them_du_kien", _them), ("doi_du_kien", _doi),
            ("mat_du_kien", _mat), ("them_so_luong_du_kien", so_luong),
        ):
            la_b = sorted(set(khai) - set(truoc))
            if la_b:
                raise LoiRegistry(
                    f"{ten_khai} khai cho bảng không có trong ảnh chụp: {la_b}"
                )

        # Một bảng chỉ được khai phần THÊM bằng MỘT cách. Khai cả hai thì lúc đối
        # soát không biết cách nào là chuẩn, và nhánh nào cũng có lý do bỏ qua nhánh kia.
        ca_hai = sorted(set(_them) & set(so_luong))
        if ca_hai:
            raise LoiRegistry(
                f"bảng {ca_hai} khai phần thêm bằng CẢ id cụ thể lẫn số lượng — "
                "chọn một: id khi ta tự chọn, số lượng khi server sinh id."
            )

        ban_ghi = {
            "ten": ten,
            "bat_dau_luc": _bay_gio(),
            "trang_thai": "DANG_CHAY",
            "truoc": truoc,
            "du_kien": {
                "bang": sorted(bang_du_kien),
                "them": _them,
                "doi": _doi,
                "mat": _mat,
                "them_so_luong": so_luong,
            },
        }
        chi_so = len(self.du_lieu["actions"])
        self._ghi(lambda d: d["actions"].append(ban_ghi))
        return chi_so

    def ket_thuc_action(self, chi_so: int, sau: AnhChup) -> Dict[str, Dict[str, List[str]]]:
        """Tiêu thụ intent đã lưu, tính delta ba chiều, chặn thứ ngoài dự kiến."""
        try:
            ban_ghi = self.du_lieu["actions"][chi_so]
        except (IndexError, KeyError):
            raise LoiRegistry(f"không có action chỉ số {chi_so}")
        if ban_ghi.get("trang_thai") != "DANG_CHAY":
            raise LoiRegistry(
                f"action {ban_ghi.get('ten')!r} đã kết thúc — không kết thúc hai lần"
            )

        truoc: AnhChup = ban_ghi["truoc"]
        sau = self.chuan_hoa(sau)
        du_kien = ban_ghi["du_kien"]

        # Phòng thủ đầu thứ hai: ảnh chụp SAU rỗng cũng không phải quan sát.
        # `bat_dau_action` đã chặn `truoc` rỗng, nhưng người gọi vẫn có thể
        # truyền `{}` ở đây — và khi ấy mọi bảng sẽ hiện ra như "mất sạch hàng",
        # hoặc tệ hơn là không bảng nào được duyệt.
        if not sau:
            raise LoiRegistry(
                f"action {ban_ghi['ten']!r}: ảnh chụp SAU rỗng — cần chụp lại "
                "đúng những bảng đã chụp ở bước trước, kể cả khi chúng không có hàng."
            )

        thieu_bang = [b for b in truoc if b not in sau]
        thua_bang = [b for b in sau if b not in truoc]

        delta: Dict[str, Dict[str, List[str]]] = {}
        lech: Dict[str, Dict[str, List[str]]] = {}

        # ⚠️ Duyệt CẢ bảng có thay đổi LẪN bảng chỉ có dự kiến. Bản đầu chỉ duyệt
        # bảng có delta rồi `continue` khi delta rỗng, nên nhánh "khai mà KHÔNG
        # xảy ra" không bao giờ chạy: kỳ vọng một refund, hệ thống tạo 0, action
        # vẫn DAT. Đó đúng là định nghĩa xanh giả.
        moi_bang = set(truoc) | set(sau)
        for loai in ("them", "doi", "mat", "them_so_luong"):
            moi_bang |= set(du_kien.get(loai, {}))

        for bang in sorted(moi_bang):
            t, s = truoc.get(bang, {}), sau.get(bang, {})
            them = sorted(set(s) - set(t))
            mat = sorted(set(t) - set(s))
            doi = sorted(k for k in (set(t) & set(s)) if t[k] != s[k])
            if them or mat or doi:
                delta[bang] = {"them": them, "mat": mat, "doi": doi}

            phan: Dict[str, List[str]] = {}
            sl_khai = du_kien.get("them_so_luong", {}).get(bang)
            if sl_khai is not None:
                # Khai bằng số lượng: so ĐỘ DÀI, kể cả khi thực tế bằng 0.
                if len(them) != sl_khai:
                    phan["them_sai_so_luong"] = [f"khai {sl_khai}, thực {len(them)}"]
            else:
                khai_them = set(du_kien.get("them", {}).get(bang, []))
                thua = sorted(set(them) - khai_them)
                thieu = sorted(khai_them - set(them))
                if thua:
                    phan["them_ngoai_du_kien"] = thua
                if thieu:
                    phan["them_khai_ma_KHONG_xay_ra"] = thieu

            for loai, thuc in (("doi", doi), ("mat", mat)):
                khai = set(du_kien.get(loai, {}).get(bang, []))
                thua = sorted(set(thuc) - khai)
                thieu = sorted(khai - set(thuc))
                if thua:
                    phan[f"{loai}_ngoai_du_kien"] = thua
                if thieu:
                    phan[f"{loai}_khai_ma_KHONG_xay_ra"] = thieu

            if phan:
                lech[bang] = phan
        ngoai_du_kien = lech

        def _td(d):
            bg = d["actions"][chi_so]
            bg["sau"] = sau
            bg["delta"] = delta
            bg["ket_thuc_luc"] = _bay_gio()
            bg["trang_thai"] = "LECH" if (ngoai_du_kien or thieu_bang or thua_bang) else "DAT"
            if ngoai_du_kien:
                bg["ngoai_du_kien"] = ngoai_du_kien
            if thieu_bang:
                bg["thieu_bang"] = thieu_bang
            if thua_bang:
                bg["thua_bang"] = thua_bang
            for bang, phan in delta.items():
                if bang in BANG_THEO_DOI:
                    cu = set(d["ids"].get(bang, []))
                    them_int = {int(x) for x in phan["them"] if str(x).isdigit()}
                    d["ids"][bang] = sorted(cu | them_int)

        self._ghi(_td)

        if thieu_bang or thua_bang:
            raise LoiRegistry(
                f"action {ban_ghi['ten']!r}: ảnh chụp lệch tập bảng — "
                f"thiếu={thieu_bang} thừa={thua_bang}. Hai ảnh chụp không so được "
                "với nhau thì delta không có nghĩa."
            )
        if ngoai_du_kien:
            raise LoiRegistry(
                f"action {ban_ghi['ten']!r} LỆCH dự kiến đã khai trước: "
                f"{ngoai_du_kien}. Lệch theo cả hai chiều đều là dừng — thay đổi "
                "ngoài dự kiến làm mất khả năng quy trách nhiệm, còn thay đổi đã "
                "khai mà KHÔNG xảy ra nghĩa là hệ thống không làm việc ta vừa "
                "khẳng định nó làm."
            )
        return delta

    # --- cleanup -----------------------------------------------------------
    def ghi_cleanup(self, *, trang_thai: str, van_tay_sau: str, ghi_chu: str = "") -> None:
        if trang_thai not in {"DAT", "HONG", "BO_QUA"}:
            raise LoiRegistry(f"trạng thái cleanup lạ: {trang_thai!r}")

        def _td(d):
            d["cleanup"] = {
                "trang_thai": trang_thai, "van_tay_sau": van_tay_sau,
                "ghi_chu": ghi_chu, "luc": _bay_gio(),
            }

        self._ghi(_td)
