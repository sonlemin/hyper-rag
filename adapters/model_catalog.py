"""Nạp danh mục model và đơn giá từ `config/danh-muc-model.yaml` (story 2.2).

Cùng khuôn với `adapters/sensitivity_loader.py`: đọc bytes, băm sha256 thành
phiên bản, parse YAML bằng loader từ chối khóa trùng, kiểm lược đồ đóng, và
mọi cách hỏng cho **một** loại lỗi kèm tên file. Phiên bản đi vào `chi_tiet`
của mỗi sự kiện chi phí, nên một hàng `audit_log` nói được nó tính bằng bảng
giá nào - đổi giá giữa chừng thì hai nửa của một đợt không so được với nhau, và
phiên bản là thứ cho biết chỗ cắt.

Lược đồ có hai phần. `nha_cung_cap` nói *cách nối* (endpoint, tên biến môi
trường mang key hoặc host) và cờ `cuc_bo`; `models` nói *giá và hình dạng*
(loại, số chiều, ngữ cảnh). Cờ cục bộ đặt ở nhà cung cấp chứ không lặp ở từng
model: một model không thể vừa gọi Ollama vừa không cục bộ, và hai chỗ khai
cùng một điều là hai chỗ lệch nhau được.

Tên model, giá, endpoint **không** xuất hiện trong code Python (Never của
spec): đổi bảng không sửa code.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

DUONG_DAN_MAC_DINH: Path = (
    Path(__file__).resolve().parent.parent / "config" / "danh-muc-model.yaml"
)

LOAI_LLM: str = "llm"
LOAI_EMBEDDING: str = "embedding"
CAC_LOAI: frozenset[str] = frozenset({LOAI_LLM, LOAI_EMBEDDING})

KHOA_GOC: frozenset[str] = frozenset({"version", "nha_cung_cap", "models"})
VERSION_HO_TRO: int = 1

# Lược đồ đóng của một nhà cung cấp, theo cờ cục bộ. Provider API ngoài cần
# key và (tùy) endpoint; provider cục bộ chỉ cần biết host của nó.
KHOA_NCC_API: frozenset[str] = frozenset({"cuc_bo", "base_url", "bien_api_key"})
KHOA_NCC_CUC_BO: frozenset[str] = frozenset({"cuc_bo", "bien_host"})

# Lược đồ đóng của một model, theo loại. Khóa bắt buộc ở `KHOA_MODEL_CHUNG`;
# `extra_body` (story 2.4) là khóa **tùy chọn**, chỉ cho model của nhà cung cấp
# API ngoài: một bảng tham số riêng của provider (ví dụ tắt suy luận của
# DeepSeek) mà wrapper chuyển nguyên vẹn thành `extra_body=` của SDK OpenAI.
# Đặt ở danh mục để "tắt suy luận" là đổi YAML, không đổi code.
KHOA_MODEL_CHUNG: frozenset[str] = frozenset(
    {"loai", "nha_cung_cap", "gia_vao_usd_1m", "gia_ra_usd_1m", "max_token"}
)
KHOA_MODEL_EMBEDDING: frozenset[str] = KHOA_MODEL_CHUNG | {"so_chieu"}
KHOA_EXTRA_BODY: str = "extra_body"
KHOA_MODEL_TUY_CHON: frozenset[str] = frozenset({KHOA_EXTRA_BODY})


class ModelCatalogInvalid(ValueError):
    """File danh mục model không nạp được thành một bảng hợp lệ.

    Một loại lỗi cho mọi cách hỏng (file thiếu, YAML sai, khóa trùng, giá âm,
    provider chưa khai, model cục bộ có giá...): phản ứng đúng cho tất cả là sửa
    file rồi chạy lại. `code` ổn định để test assert trên `code`.
    """

    code = "MODEL_CATALOG_INVALID"


class ModelUnknown(LookupError):
    """Hỏi một model không có trong danh mục, hoặc có nhưng sai loại.

    Ném lúc *dựng* wrapper chứ không lúc gọi: một tên model gõ sai phải làm
    tiến trình không lên được, không phải làm lời gọi đầu tiên của người dùng
    hỏng.
    """

    code = "MODEL_UNKNOWN"


class _KhongTrungKhoa(yaml.SafeLoader):
    """SafeLoader từ chối khóa trùng: khai một model hai lần là một giá biến mất."""


def _mapping_khong_trung(loader, node, deep=False):
    da_thay = set()
    for khoa_node, _ in node.value:
        khoa = loader.construct_object(khoa_node, deep=deep)
        if khoa in da_thay:
            raise yaml.constructor.ConstructorError(
                "khi nạp danh mục model",
                node.start_mark,
                f"khóa trùng {khoa!r}",
                khoa_node.start_mark,
            )
        da_thay.add(khoa)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_KhongTrungKhoa.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_khong_trung
)


@dataclass(frozen=True)
class NhaCungCap:
    """Cách nối tới một nhà cung cấp; giá trị key/host đọc từ môi trường lúc dựng."""

    ten: str
    cuc_bo: bool
    base_url: str | None = None
    bien_api_key: str | None = None
    bien_host: str | None = None


@dataclass(frozen=True)
class MucModel:
    """Một model đã kiểm: giá, loại, hình dạng, và cờ cục bộ kế thừa từ provider."""

    ten: str
    loai: str
    nha_cung_cap: str
    cuc_bo: bool
    gia_vao_usd_1m: float
    gia_ra_usd_1m: float
    max_token: int
    so_chieu: int | None = None
    # Tham số riêng của nhà cung cấp gửi kèm mỗi lời gọi chat (`extra_body=` của
    # SDK OpenAI); `None` là không gửi gì. Chỉ model API ngoài mới có.
    extra_body: Mapping | None = None

    def chi_phi_usd(self, token_vao: int, token_ra: int) -> float:
        """Chi phí một lời gọi theo đơn giá của bảng; đơn vị giá là USD trên 1M token."""
        return (
            token_vao * self.gia_vao_usd_1m + token_ra * self.gia_ra_usd_1m
        ) / 1_000_000


@dataclass(frozen=True)
class DanhMucModel:
    """Danh mục đã kiểm, bất biến, kèm sha256 của chính file sinh ra nó."""

    models: Mapping[str, MucModel]
    nha_cung_cap: Mapping[str, NhaCungCap]
    version: str

    def muc(self, ten: str, loai: str | None = None) -> MucModel:
        """Mục của một model; thiếu hoặc sai loại là `ModelUnknown`."""
        if ten not in self.models:
            raise ModelUnknown(
                f"model {ten!r} không có trong danh mục (đang có {sorted(self.models)})"
            )
        muc = self.models[ten]
        if loai is not None and muc.loai != loai:
            raise ModelUnknown(
                f"model {ten!r} là loại {muc.loai!r}, không phải {loai!r}"
            )
        return muc

    def nha_cung_cap_cua(self, muc: MucModel) -> NhaCungCap:
        return self.nha_cung_cap[muc.nha_cung_cap]


def tai_danh_muc_model(path: str | Path) -> DanhMucModel:
    """Nạp một file danh mục thành `DanhMucModel` đã kiểm."""
    duong_dan = Path(path)
    try:
        noi_dung = duong_dan.read_bytes()
    except OSError as loi:
        raise ModelCatalogInvalid(
            f"không đọc được file danh mục model {duong_dan}: {loi}"
        ) from None
    version = hashlib.sha256(noi_dung).hexdigest()
    try:
        van_ban = noi_dung.decode("utf-8")
    except UnicodeDecodeError as loi:
        raise ModelCatalogInvalid(
            f"file danh mục model {duong_dan} không phải UTF-8: {loi}"
        ) from None
    try:
        raw = yaml.load(van_ban, Loader=_KhongTrungKhoa)
    except yaml.YAMLError as loi:
        raise ModelCatalogInvalid(
            f"YAML hỏng ở {duong_dan}: {str(loi).replace(chr(10), ' ')}"
        ) from loi
    try:
        ncc = _kiem_nha_cung_cap(raw)
        models = _kiem_models(raw, ncc)
    except ModelCatalogInvalid as loi:
        raise ModelCatalogInvalid(f"{duong_dan}: {loi}") from None
    return DanhMucModel(
        models=MappingProxyType(models),
        nha_cung_cap=MappingProxyType(ncc),
        version=version,
    )


def danh_muc_mac_dinh() -> DanhMucModel:
    """Danh mục chốt của repo."""
    return tai_danh_muc_model(DUONG_DAN_MAC_DINH)


def _ten_hop_le(ten, vai_tro: str) -> str:
    if not isinstance(ten, str) or not ten.strip():
        raise ModelCatalogInvalid(f"tên {vai_tro} {ten!r} không hợp lệ")
    return ten.strip()


def _chuoi_hoac_none(gia_tri, ten_truong: str, ten_muc: str) -> str | None:
    if gia_tri is None:
        return None
    if not isinstance(gia_tri, str) or not gia_tri.strip():
        raise ModelCatalogInvalid(f"{ten_muc}: {ten_truong} phải là chuỗi hoặc null")
    return gia_tri.strip()


def _kiem_nha_cung_cap(raw) -> dict[str, NhaCungCap]:
    if not isinstance(raw, dict):
        raise ModelCatalogInvalid(f"gốc file phải là một bảng, nhận được {type(raw).__name__}")
    la = set(raw) - KHOA_GOC
    if la:
        raise ModelCatalogInvalid(f"khóa lạ ở cấp gốc: {sorted(la)}")
    version = raw.get("version")
    # Số nguyên thật: `true` (bool là con của int) và `1.0` đều bị từ chối.
    if isinstance(version, bool) or not isinstance(version, int) or version != VERSION_HO_TRO:
        raise ModelCatalogInvalid(
            f"version phải là số nguyên {VERSION_HO_TRO}, nhận được {version!r}"
        )
    bang = raw.get("nha_cung_cap")
    if not isinstance(bang, dict) or not bang:
        raise ModelCatalogInvalid("`nha_cung_cap` phải là một bảng không rỗng")
    ket_qua: dict[str, NhaCungCap] = {}
    for ten, muc in bang.items():
        ten = _ten_hop_le(ten, "nhà cung cấp")
        if not isinstance(muc, dict):
            raise ModelCatalogInvalid(f"nhà cung cấp {ten!r} phải là một bảng")
        cuc_bo = muc.get("cuc_bo")
        if not isinstance(cuc_bo, bool):
            raise ModelCatalogInvalid(f"nhà cung cấp {ten!r}: `cuc_bo` phải là true/false")
        khoa_cho_phep = KHOA_NCC_CUC_BO if cuc_bo else KHOA_NCC_API
        la = set(muc) - khoa_cho_phep
        if la:
            raise ModelCatalogInvalid(f"nhà cung cấp {ten!r}: khóa lạ {sorted(la)}")
        if cuc_bo:
            bien_host = _chuoi_hoac_none(muc.get("bien_host"), "bien_host", f"nhà cung cấp {ten!r}")
            if bien_host is None:
                raise ModelCatalogInvalid(f"nhà cung cấp cục bộ {ten!r} phải khai `bien_host`")
            ket_qua[ten] = NhaCungCap(ten=ten, cuc_bo=True, bien_host=bien_host)
        else:
            bien_key = _chuoi_hoac_none(
                muc.get("bien_api_key"), "bien_api_key", f"nhà cung cấp {ten!r}"
            )
            if bien_key is None:
                raise ModelCatalogInvalid(
                    f"nhà cung cấp API {ten!r} phải khai `bien_api_key` (tên biến môi trường)"
                )
            ket_qua[ten] = NhaCungCap(
                ten=ten,
                cuc_bo=False,
                base_url=_chuoi_hoac_none(muc.get("base_url"), "base_url", f"nhà cung cấp {ten!r}"),
                bien_api_key=bien_key,
            )
    return ket_qua


def _so_khong_am(gia_tri, ten_truong: str, ten_model: str) -> float:
    # `bool` là con của `int`: `gia_vao_usd_1m: true` mà thành 1 USD là một
    # bảng chạy được mà không ai định khai như vậy.
    if isinstance(gia_tri, bool) or not isinstance(gia_tri, (int, float)):
        raise ModelCatalogInvalid(f"model {ten_model!r}: {ten_truong} phải là số")
    if not math.isfinite(gia_tri):
        raise ModelCatalogInvalid(f"model {ten_model!r}: {ten_truong} phải là số hữu hạn")
    if gia_tri < 0:
        raise ModelCatalogInvalid(f"model {ten_model!r}: {ten_truong} không được âm")
    return float(gia_tri)


def _so_nguyen_duong(gia_tri, ten_truong: str, ten_model: str) -> int:
    if isinstance(gia_tri, bool) or not isinstance(gia_tri, int) or gia_tri <= 0:
        raise ModelCatalogInvalid(
            f"model {ten_model!r}: {ten_truong} phải là số nguyên dương"
        )
    return gia_tri


def _kiem_models(raw, ncc: Mapping[str, NhaCungCap]) -> dict[str, MucModel]:
    bang = raw.get("models")
    if not isinstance(bang, dict) or not bang:
        raise ModelCatalogInvalid("`models` phải là một bảng không rỗng")
    ket_qua: dict[str, MucModel] = {}
    for ten, muc in bang.items():
        ten = _ten_hop_le(ten, "model")
        if not isinstance(muc, dict):
            raise ModelCatalogInvalid(f"model {ten!r} phải là một bảng")
        loai = muc.get("loai")
        if not isinstance(loai, str) or loai not in CAC_LOAI:
            raise ModelCatalogInvalid(
                f"model {ten!r}: `loai` phải là một trong {sorted(CAC_LOAI)}, nhận được {loai!r}"
            )
        khoa_bat_buoc = KHOA_MODEL_EMBEDDING if loai == LOAI_EMBEDDING else KHOA_MODEL_CHUNG
        la = set(muc) - khoa_bat_buoc - KHOA_MODEL_TUY_CHON
        if la:
            raise ModelCatalogInvalid(f"model {ten!r}: khóa lạ {sorted(la)}")
        thieu = khoa_bat_buoc - set(muc)
        if thieu:
            raise ModelCatalogInvalid(f"model {ten!r}: thiếu {sorted(thieu)}")
        ten_ncc = muc["nha_cung_cap"]
        if not isinstance(ten_ncc, str) or ten_ncc not in ncc:
            raise ModelCatalogInvalid(
                f"model {ten!r}: nhà cung cấp {ten_ncc!r} chưa khai trong `nha_cung_cap`"
            )
        gia_vao = _so_khong_am(muc["gia_vao_usd_1m"], "gia_vao_usd_1m", ten)
        gia_ra = _so_khong_am(muc["gia_ra_usd_1m"], "gia_ra_usd_1m", ten)
        cuc_bo = ncc[ten_ncc].cuc_bo
        if cuc_bo and (gia_vao or gia_ra):
            raise ModelCatalogInvalid(
                f"model {ten!r} chạy trên nhà cung cấp cục bộ {ten_ncc!r} thì giá phải là 0"
            )
        extra_body = _kiem_extra_body(muc, ten, loai, cuc_bo)
        ket_qua[ten] = MucModel(
            ten=ten,
            loai=loai,
            nha_cung_cap=ten_ncc,
            cuc_bo=cuc_bo,
            gia_vao_usd_1m=gia_vao,
            gia_ra_usd_1m=gia_ra,
            max_token=_so_nguyen_duong(muc["max_token"], "max_token", ten),
            so_chieu=(
                _so_nguyen_duong(muc["so_chieu"], "so_chieu", ten)
                if loai == LOAI_EMBEDDING
                else None
            ),
            extra_body=extra_body,
        )
    return ket_qua


def _dong_bang(gia_tri):
    """Bảng lồng nhau thành bản chỉ đọc, để mục danh mục thật sự bất biến."""
    if isinstance(gia_tri, dict):
        return MappingProxyType({k: _dong_bang(v) for k, v in gia_tri.items()})
    if isinstance(gia_tri, list):
        return tuple(_dong_bang(v) for v in gia_tri)
    return gia_tri


def _kiem_extra_body(muc: dict, ten_model: str, loai: str, cuc_bo: bool):
    """`extra_body` chỉ hợp lệ cho model `llm` của nhà cung cấp API ngoài.

    Có *khóa* (kể cả `null`) ở model embedding hay ở provider cục bộ là từ chối
    file: embedding không đi qua `chat.completions`, Ollama không đi qua SDK
    OpenAI, nên tham số sẽ bị lặng lẽ bỏ qua - một bảng cấu hình nói một điều
    mà hệ làm điều khác. Giá trị phải là bảng không rỗng và tuần tự hóa được
    thành JSON (SDK gửi nó trong body request); YAML nạp ra ngày tháng hay tập
    hợp thì nổ ở đây, không nổ ở lời gọi đầu tiên.
    """
    if KHOA_EXTRA_BODY not in muc:
        return None
    gia_tri = muc[KHOA_EXTRA_BODY]
    if loai != LOAI_LLM:
        raise ModelCatalogInvalid(
            f"model {ten_model!r} loại {loai!r} không nhận `{KHOA_EXTRA_BODY}`: chỉ model llm của API ngoài"
        )
    if cuc_bo:
        raise ModelCatalogInvalid(
            f"model {ten_model!r} chạy trên nhà cung cấp cục bộ không nhận `{KHOA_EXTRA_BODY}`"
        )
    if not isinstance(gia_tri, dict) or not gia_tri:
        raise ModelCatalogInvalid(f"model {ten_model!r}: `{KHOA_EXTRA_BODY}` phải là một bảng không rỗng")
    try:
        json.dumps(gia_tri, ensure_ascii=False)
    except (TypeError, ValueError) as loi:
        raise ModelCatalogInvalid(
            f"model {ten_model!r}: `{KHOA_EXTRA_BODY}` không tuần tự hóa được thành JSON: {loi}"
        ) from None
    return _dong_bang(gia_tri)
