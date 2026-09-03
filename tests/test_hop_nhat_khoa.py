"""Hợp nhất khóa đa nguồn: hàm thuần và bảng hạng độ nhạy (story 2.1, FR-11).

Viết trước cơ chế (FR-27). Bộ này đo hai thứ tách nhau:

- `core.keys.hop_nhat_khoa` - hàm thuần, không I/O, không đọc file: cùng scope
  lấy hạng cao nhất, khác scope ra "không khóa". Nó là nơi *quyết định*, ba
  adapter chỉ đi qua nó.
- `adapters.sensitivity_loader` - nửa I/O: đọc file hạng, băm sha256 làm phiên
  bản, từ chối mọi cách khai hỏng. Cùng khuôn với `adapters/policy_loader.py`.

Hai sentinel là hai trạng thái khác nhau và bộ test giữ chúng khác nhau:
`CHUA_GHI` nghĩa là id chưa từng vào kho, `KHONG_KHOA` nghĩa là đã hợp nhất ra
"không khóa". Gộp chúng làm một là một id đa nguồn khác scope được cấp lại khóa
ở lần nạp thứ ba - đúng lỗ mà story này đóng.
"""

import pytest

from adapters.sensitivity_loader import (
    DUONG_DAN_MAC_DINH,
    SensitivityRanksInvalid,
    bang_hang_mac_dinh,
    tai_hang_do_nhay,
)
from core.keys import (
    CHUA_GHI,
    KHONG_KHOA,
    SensitivityRankUnknown,
    filter_key,
    hop_nhat_khoa,
)

# Bảng hạng dựng tay cho phần test hàm thuần: hàm không đọc file, nên bảng của
# nó là một tham số bình thường và test không cần chạm đĩa.
HANG = {"runbook": 10, "bao_cao_su_co": 20, "bi_mat_ha_tang": 30}

RUNBOOK = filter_key("noi_bo", "runbook")
SU_CO = filter_key("noi_bo", "bao_cao_su_co")
HA_TANG = filter_key("noi_bo", "bi_mat_ha_tang")
KHACH_A_SU_CO = filter_key("khach_hang_a", "bao_cao_su_co")


# --- Hàm thuần: bốn hàng đầu của I/O Matrix -------------------------------


def test_id_chua_tung_ghi_nhan_khoa_moi():
    """Không có gì để hợp nhất thì khóa của tài liệu đang nạp thắng."""
    assert hop_nhat_khoa(CHUA_GHI, RUNBOOK, hang=HANG) == RUNBOOK


def test_cung_scope_nhay_sau_thi_siet_lai():
    """`noi_bo:runbook` gặp `noi_bo:bi_mat_ha_tang` ra hạng cao hơn (hàng 1)."""
    assert hop_nhat_khoa(RUNBOOK, HA_TANG, hang=HANG) == HA_TANG


def test_cung_scope_nhay_truoc_thi_khong_noi_long():
    """`noi_bo:bi_mat_ha_tang` gặp `noi_bo:runbook` giữ nguyên hạng cao (hàng 2).

    Đây là chiều mà last-write-wins làm sai: nạp lại một entity dưới một tài
    liệu thường hơn không được nới quyền của nó ra.
    """
    assert hop_nhat_khoa(HA_TANG, RUNBOOK, hang=HANG) == HA_TANG


def test_cung_khoa_thi_giu_nguyen():
    """Nạp lại đúng cùng một nhãn là phép đồng nhất, không phải một ca riêng."""
    assert hop_nhat_khoa(SU_CO, SU_CO, hang=HANG) == SU_CO


def test_khac_scope_ra_khong_khoa():
    """Hai scope chạm cùng một id thì không khóa nào đúng cho nó (hàng 3).

    Lấy khóa của scope này là để lộ sang scope kia; lấy khóa của scope kia là
    ngược lại. Không có khóa nào đúng, nên sentinel là "không khóa" chứ không
    phải một khóa thứ ba.
    """
    assert hop_nhat_khoa(RUNBOOK, KHACH_A_SU_CO, hang=HANG) is KHONG_KHOA


def test_khac_scope_cung_loai_noi_dung_van_ra_khong_khoa():
    """Nửa trái của khóa một mình nó quyết định, không cần khác loại nội dung."""
    assert (
        hop_nhat_khoa(SU_CO, KHACH_A_SU_CO, hang=HANG) is KHONG_KHOA
    )


def test_khong_khoa_la_trang_thai_hut():
    """Đã "không khóa" thì lần nạp sau không cấp lại khóa được.

    Ca thật: entity X vào từ tài liệu scope1, rồi từ tài liệu scope2 (thành
    không khóa), rồi từ một tài liệu scope1 nữa. Nguồn scope2 vẫn còn đó, nên
    trả khóa scope1 cho X là để lộ đúng thứ vừa giấu đi. Trạng thái hút cũng là
    lý do `CHUA_GHI` phải khác `KHONG_KHOA`.
    """
    assert hop_nhat_khoa(KHONG_KHOA, RUNBOOK, hang=HANG) is KHONG_KHOA
    assert hop_nhat_khoa(KHONG_KHOA, HA_TANG, hang=HANG) is KHONG_KHOA


def test_hop_nhat_khong_phu_thuoc_thu_tu_nap():
    """Hai thứ tự nạp cho cùng một kết quả - đó là điều làm đợt nạp lặp lại được."""
    for a, b in ((RUNBOOK, HA_TANG), (SU_CO, RUNBOOK), (RUNBOOK, KHACH_A_SU_CO)):
        assert hop_nhat_khoa(a, b, hang=HANG) == hop_nhat_khoa(b, a, hang=HANG)


def test_loai_noi_dung_la_o_nhan_moi_bi_tu_choi():
    """Loại nội dung không có hạng là từ chối, không phải đoán hạng (hàng 4)."""
    with pytest.raises(SensitivityRankUnknown) as loi:
        hop_nhat_khoa(CHUA_GHI, filter_key("noi_bo", "hop_dong"), hang=HANG)
    assert loi.value.code == "SENSITIVITY_RANK_UNKNOWN"
    assert "hop_dong" in str(loi.value)


def test_loai_noi_dung_la_o_khoa_cu_cung_bi_tu_choi():
    """Khóa cũ ngoài bảng hạng cũng nổ: so hạng với một số bịa ra là che sai.

    Ca này có thật khi ai đó gỡ một loại nội dung khỏi file hạng sau khi đã
    nạp. Đổi hạng là re-ingest (Ask First của spec), nên câu trả lời đúng là
    dừng chứ không phải đoán.
    """
    with pytest.raises(SensitivityRankUnknown):
        hop_nhat_khoa(filter_key("noi_bo", "hop_dong"), RUNBOOK, hang=HANG)


def test_khoa_moi_sai_dang_la_value_error():
    """Khóa mới phải do `filter_key` sinh ra; sai dạng là `ValueError` như cũ."""
    with pytest.raises(ValueError):
        hop_nhat_khoa(CHUA_GHI, "khong-co-dau-phan-tach", hang=HANG)


def test_khoa_cu_sai_kieu_la_type_error():
    """Số hay list ở khe khóa cũ là lỗi lập trình, không phải một trạng thái."""
    for xau in (7, ["noi_bo:runbook"], object()):
        with pytest.raises(TypeError):
            hop_nhat_khoa(xau, RUNBOOK, hang=HANG)


def test_hai_sentinel_khong_bang_nhau():
    """`CHUA_GHI` và `KHONG_KHOA` phải phân biệt được, kể cả bằng `==`."""
    assert CHUA_GHI is not KHONG_KHOA
    assert CHUA_GHI != KHONG_KHOA
    assert KHONG_KHOA is None
    # `repr` nói đúng tên nó: sentinel rơi vào một thông điệp lỗi mà in ra
    # `<object object at 0x...>` là một thông điệp không giúp được ai.
    assert repr(CHUA_GHI) == "CHUA_GHI"


def test_ham_thuan_khong_sua_bang_hang():
    """Hàm hợp nhất không được chạm bảng hạng nó nhận."""
    ban_sao = dict(HANG)
    hop_nhat_khoa(RUNBOOK, HA_TANG, hang=HANG)
    assert HANG == ban_sao


# --- Loader: khuôn `policy_loader`, một loại lỗi duy nhất ------------------


def test_file_mac_dinh_nap_duoc_va_phu_moi_loai_noi_dung_cua_fixture():
    """File hạng chốt trong repo phải phủ mọi loại nội dung đang có dữ liệu.

    Thiếu một loại là cả lô mang loại đó bị từ chối lúc ingest - đúng thiết kế,
    nhưng phải phát hiện ở đây chứ không phải giữa một đợt nạp corpus.
    """
    from tests.fixtures.du_lieu_dung_tay import CHUNKS, HYPEREDGES, TAI_LIEU_GOC

    bang = tai_hang_do_nhay(DUONG_DAN_MAC_DINH)
    dang_dung = {
        muc["content_type"] for muc in (*HYPEREDGES, *CHUNKS, *TAI_LIEU_GOC)
    }
    thieu = dang_dung - set(bang.hang)
    assert not thieu, f"loại nội dung chưa có hạng độ nhạy: {sorted(thieu)}"


def test_bang_hang_phu_moi_loai_noi_dung_cua_moi_bang_chinh_sach():
    """Mọi loại nội dung khai trong `config/policy-*.yaml` phải có hạng độ nhạy.

    Đây là chỗ hai file cấu hình gặp nhau, và chúng lệch nhau được: thêm một
    loại nội dung vào bảng chính sách mà quên bảng hạng thì mọi lô mang loại đó
    bị `SensitivityRankUnknown` từ chối - đúng thiết kế, nhưng phát hiện *giữa
    một đợt nạp corpus* thay vì lúc người ta còn đang sửa file. Test này kéo nó
    về đúng lúc sửa file.

    Không phải validator đơn điệu của AD-5 (story 3.2, và nó đọc cùng hai file
    này để trả lời một câu hỏi khác - mức tiết lộ có đơn điệu theo độ nhạy
    không). Ở đây chỉ là một phép bao hàm tập hợp, không cần quyết định thiết kế
    nào.

    **Quét thư mục, không liệt kê tên file.** FR-28 đòi hoán đổi bốn cấu hình
    đo, nên bảng thứ ba và thứ tư sẽ xuất hiện; liệt kê tên thì chúng lọt lưới
    đúng vào lúc chúng mới nhất và ít ai đọc nhất.
    """
    import yaml

    thu_muc = DUONG_DAN_MAC_DINH.parent
    cac_bang = sorted(thu_muc.glob("policy-*.yaml"))
    # Guard cho chính phép quét: một glob viết sai cho danh sách rỗng và test
    # này xanh mãi mà không đọc file nào.
    assert len(cac_bang) >= 2, (
        f"chỉ tìm thấy {[p.name for p in cac_bang]} trong {thu_muc}: phép quét"
        " bảng chính sách hỏng, và khi đó test này không canh gì"
    )

    hang = tai_hang_do_nhay(DUONG_DAN_MAC_DINH).hang
    thieu: dict[str, set[str]] = {}
    for duong_dan in cac_bang:
        raw = yaml.safe_load(duong_dan.read_text(encoding="utf-8"))
        loai_khai = set()
        for cau_hinh in (raw.get("roles") or {}).values():
            # Cả hai chỗ khai loại nội dung: cột mức tiết lộ và bảng slot bị
            # che. `masked_slots` khai một loại mà `disclosure` không có là một
            # lỗi khác (validator của `core/policy.py` bắt), nhưng nếu nó lọt
            # thì loại đó vẫn cần hạng.
            loai_khai |= set(cau_hinh.get("disclosure") or {})
            loai_khai |= set(cau_hinh.get("masked_slots") or {})
        con_thieu = loai_khai - set(hang)
        if con_thieu:
            thieu[duong_dan.name] = con_thieu
        # Mỗi bảng phải khai *ít nhất một* loại: một file rỗng hay parse ra
        # `None` sẽ cho tập rỗng và lặng lẽ qua phép bao hàm.
        assert loai_khai, f"{duong_dan.name} không khai loại nội dung nào"

    assert not thieu, (
        "loại nội dung khai trong bảng chính sách mà không có hạng độ nhạy:"
        f" {thieu}. Thêm hạng vào config/hang-do-nhay.yaml, hoặc bỏ loại đó"
        " khỏi bảng chính sách - lô nào mang nó cũng sẽ bị từ chối cả lô."
    )


def test_bang_hang_mac_dinh_dung_chinh_file_trong_repo():
    """Adapter không cấu hình đường dẫn thì dùng đúng file chốt của repo."""
    assert bang_hang_mac_dinh().hang == tai_hang_do_nhay(DUONG_DAN_MAC_DINH).hang
    assert bang_hang_mac_dinh().version == tai_hang_do_nhay(DUONG_DAN_MAC_DINH).version


def test_version_la_sha256_cua_noi_dung_file(tmp_path):
    """Phiên bản bảng hạng tính như `policy_version`: sha256 nội dung nguyên trạng.

    Đổi một dấu cách là một bảng hạng khác, vì một hạng đổi là mọi khóa đã ghi
    có thể sai - thứ chỉ re-ingest chữa được.
    """
    import hashlib

    f = tmp_path / "hang.yaml"
    f.write_text("version: 1\nranks:\n  runbook: 10\n", encoding="utf-8")
    bang = tai_hang_do_nhay(f)
    assert bang.version == hashlib.sha256(f.read_bytes()).hexdigest()
    assert bang.hang == {"runbook": 10}


def test_bang_hang_bat_bien(tmp_path):
    """Bảng đã nạp không sửa được từ ngoài: nó là cấu hình đóng băng."""
    import dataclasses

    f = tmp_path / "hang.yaml"
    f.write_text("version: 1\nranks:\n  runbook: 10\n", encoding="utf-8")
    bang = tai_hang_do_nhay(f)
    with pytest.raises(TypeError):
        bang.hang["runbook"] = 99
    with pytest.raises(dataclasses.FrozenInstanceError):
        bang.version = "khac"


def test_tra_hang_cua_loai_noi_dung(tmp_path):
    """`hang_cua` là cửa tra một loại nội dung, lạ thì cùng mã lỗi với hàm thuần."""
    f = tmp_path / "hang.yaml"
    f.write_text("version: 1\nranks:\n  runbook: 10\n", encoding="utf-8")
    bang = tai_hang_do_nhay(f)
    assert bang.hang_cua("runbook") == 10
    with pytest.raises(SensitivityRankUnknown) as loi:
        bang.hang_cua("hop_dong")
    assert loi.value.code == "SENSITIVITY_RANK_UNKNOWN"


CACH_KHAI_HONG = {
    "goc_khong_phai_bang": "- runbook\n",
    "thieu_ranks": "version: 1\n",
    "ranks_rong": "version: 1\nranks: {}\n",
    "ranks_khong_phai_bang": "version: 1\nranks: [runbook]\n",
    "hang_khong_phai_so": "version: 1\nranks:\n  runbook: cao\n",
    "hang_la_bool": "version: 1\nranks:\n  runbook: true\n",
    "hang_la_so_thuc": "version: 1\nranks:\n  runbook: 1.5\n",
    "hai_loai_cung_hang": "version: 1\nranks:\n  runbook: 10\n  su_co: 10\n",
    "khoa_trung": "version: 1\nranks:\n  runbook: 10\n  runbook: 20\n",
    "loai_rong": "version: 1\nranks:\n  '': 10\n",
    "loai_co_dau_phan_tach": "version: 1\nranks:\n  'noi_bo:runbook': 10\n",
    "khoa_la_o_goc": "version: 1\nranks:\n  runbook: 10\nghi_chu: x\n",
    "thieu_version": "ranks:\n  runbook: 10\n",
    "version_la": "version: 2\nranks:\n  runbook: 10\n",
    "yaml_hong": "version: 1\nranks:\n  runbook: [\n",
}


@pytest.mark.parametrize("ten", sorted(CACH_KHAI_HONG))
def test_moi_cach_khai_hong_deu_ra_mot_loai_loi(tmp_path, ten):
    """Mọi cách hỏng cho cùng một exception kèm tên file (khuôn `load_policy`).

    Hai hàng đáng nói riêng. `hai_loai_cung_hang`: "hạn chế nhất" không xác
    định được khi hai loại nội dung cùng hạng, nên bảng phải cấm chứ không để
    hàm hợp nhất chọn bừa. `loai_co_dau_phan_tach`: loại nội dung mang dấu `:`
    thì `split_key` tách sai và hạng tra trượt.
    """
    f = tmp_path / "hang.yaml"
    f.write_text(CACH_KHAI_HONG[ten], encoding="utf-8")
    with pytest.raises(SensitivityRanksInvalid) as loi:
        tai_hang_do_nhay(f)
    assert loi.value.code == "SENSITIVITY_RANKS_INVALID"
    assert str(f) in str(loi.value)


def test_file_khong_doc_duoc_cung_mot_loai_loi(tmp_path):
    """File thiếu và đường dẫn là thư mục đều ra `SensitivityRanksInvalid`."""
    with pytest.raises(SensitivityRanksInvalid):
        tai_hang_do_nhay(tmp_path / "khong-co.yaml")
    with pytest.raises(SensitivityRanksInvalid):
        tai_hang_do_nhay(tmp_path)


def test_file_khong_phai_utf8(tmp_path):
    f = tmp_path / "hang.yaml"
    f.write_bytes(b"version: 1\nranks:\n  runbook: 10\n\xff\xfe")
    with pytest.raises(SensitivityRanksInvalid):
        tai_hang_do_nhay(f)


def test_hang_cua_file_mac_dinh_doi_mot_chieu():
    """13 loại nội dung của corpus xếp đúng một chiều, từ FAQ tới bí mật hạ tầng.

    Kỳ vọng viết tay ở đây, không suy từ chính file: đó là điều làm cho một lần
    sửa nhầm thứ tự trong YAML thành một test đỏ chứ không thành một chính sách
    mới không ai duyệt. Chuỗi này là thứ tự mà bảng chính sách đầy đủ của story
    3.2 phải đơn điệu theo (AD-5), nên nó được viết ra đủ 13 mắt chứ không rút
    gọn thành "min < max".
    """
    hang = tai_hang_do_nhay(DUONG_DAN_MAC_DINH).hang
    assert (
        hang["faq"]
        < hang["tai_lieu_san_pham"]
        < hang["sop"]
        < hang["troubleshooting"]
        < hang["runbook"]
        < hang["known_issue"]
        < hang["vong_doi_ticket"]
        < hang["canh_bao"]
        < hang["bao_cao_su_co"]
        < hang["postmortem"]
        < hang["log"]
        < hang["cmdb"]
        < hang["bi_mat_ha_tang"]
    )
    assert len(hang) == 13, "bảng 13 hạng của story 2.8; thêm loại là thêm một mắt ở trên"


def test_ba_hang_da_dong_bang_giu_nguyen_so():
    """10/20/30 là số của story 2.1; đổi chúng là re-ingest 10 tài liệu bộ vàng.

    Khóa quyền đã ghi của bộ vàng được tính bằng đúng ba số này. Thêm loại mới
    vào khoảng trống không đụng chúng, và test này là chỗ nói ra điều đó.
    """
    hang = tai_hang_do_nhay(DUONG_DAN_MAC_DINH).hang
    assert (hang["runbook"], hang["bao_cao_su_co"], hang["bi_mat_ha_tang"]) == (10, 20, 30)
