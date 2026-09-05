"""Mọi khoản treo trong `deferred-work.md` phải có chủ, và chủ phải còn sống.

Luật ở CLAUDE.md mục "Sổ nợ `deferred-work.md` khi chốt một story". Test này là
phần canh bằng máy của luật đó, sinh ra từ retro Epic 2.

**Vì sao cần.** Retro Epic 2 rà 86 khoản treo và tìm thấy 17 khoản không trỏ đi
đâu cả, cộng nhiều khoản trỏ vào một story đã `done`. Ba kiểu mồ côi, và cả ba
đều **lặng** - khoản trông như có chủ cho tới khi đọc kỹ:

1. Địa chỉ trỏ vào story đã đóng ("vòng sau của 2.6"). Epic 2 đóng thì chúng hết
   chủ mà không ai được báo.
2. Địa chỉ có điều kiện chưa bao giờ xảy ra ("2.12 nếu nó nạp lại `real`"), và
   ADR-013 sau đó chốt `real` không nạp lại nữa nên điều kiện không bao giờ đúng.
3. Địa chỉ là một mô tả chứ không phải một story ("story kế tiếp nào chạm
   `adapters/thu_lai.py`"). Không story nào cam kết việc đó.

Cùng bài học với luật 1000 dòng của file test: retro Epic 2 tìm thấy quy ước đó
chỉ sống trong một artifact review và vỡ ở bảy file ngay epic sau, trong khi luật
chiều import ở `tests/test_import_lint.py` có test và giữ nguyên qua hai epic.
Một luật không có tripwire không sống qua một epic.

**Phạm vi cố ý hẹp.** Test đọc *địa chỉ được khai gần nhất* của mỗi khoản treo và
đòi nó phân giải ra ít nhất một trong ba thứ: một story key có thật và chưa
`done`, một epic chưa `done`, hoặc một quyết định của sonlm **có mốc**. Nó không
chấm chất lượng địa chỉ và không đọc được ý định; nó chỉ chặn ba kiểu mồ côi ở
trên. Một địa chỉ dở nhưng phân giải được vẫn qua, và đó là giới hạn đã biết.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SO_NO = REPO_ROOT / "_bmad-output" / "implementation-artifacts" / "deferred-work.md"
SPRINT = REPO_ROOT / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"

# Một khoản: khối bắt đầu bằng `- source_spec:` cho tới khối kế tiếp.
BAT_DAU = re.compile(r"\n(?=- source_spec:)")
# Khóa story trong `sprint-status.yaml` là `<epic>-<so>-<slug>`; khóa epic là
# `epic-<so>` và `epic-<so>-retrospective`.
KHOA_STORY = re.compile(r"^(\d+)-(\d+)-")


def _khoi_so_no() -> list[str]:
    noi_dung = SO_NO.read_text(encoding="utf-8")
    than = noi_dung[noi_dung.find("- source_spec:") :]
    return [k for k in BAT_DAU.split(than) if k.strip().startswith("- source_spec:")]


def _truong(khoi: str, ten: str) -> str | None:
    m = re.search(rf"^  {ten}:", khoi, re.M)
    return khoi[m.start() :] if m else None


def _story_nguon(khoi: str) -> str:
    ten = re.search(r"source_spec: `([^`]+)`", khoi).group(1).split("/")[-1]
    m = re.match(r"spec-(\d+)-(\d+)", ten)
    return f"{m.group(1)}.{m.group(2)}" if m else ten


def _dia_chi_moi_nhat(khoi: str) -> str:
    """Phần khai địa chỉ gần nhất: `tien_do` cuối nếu có, không thì `evidence`.

    Một khoản được cập nhật nhiều lần thì địa chỉ đúng là địa chỉ *mới nhất*;
    đọc cả khối là đọc luôn những địa chỉ đã bị thay.
    """
    vi_tri = [m.start() for m in re.finditer(r"^  tien_do:", khoi, re.M)]
    return khoi[vi_tri[-1] :] if vi_tri else khoi


def _trang_thai_sprint() -> dict[str, str]:
    dev = yaml.safe_load(SPRINT.read_text(encoding="utf-8"))["development_status"]
    return {str(k): str(v) for k, v in dev.items()}


def _story_chua_xong(trang_thai: dict[str, str]) -> set[str]:
    """Tập `<epic>.<so>` của mọi story key chưa `done`."""
    chua: set[str] = set()
    for khoa, tt in trang_thai.items():
        m = KHOA_STORY.match(khoa)
        if m and tt != "done":
            chua.add(f"{m.group(1)}.{int(m.group(2))}")
    return chua


def _epic_chua_xong(trang_thai: dict[str, str]) -> set[str]:
    return {
        khoa.split("-")[1]
        for khoa, tt in trang_thai.items()
        if re.fullmatch(r"epic-\d+", khoa) and tt != "done"
    }


def _story_duoc_nhac(doan: str) -> set[str]:
    """Mọi `<epic>.<so>` mà đoạn văn nhắc tới, dạng `2.13` hoặc `7-5`.

    Bỏ số phiên bản ba phần (`5.26.30`) và mọi thứ trong dấu nháy ngược: một
    đường dẫn `adapters/trich_xuat.py:291` không phải một địa chỉ story.
    """
    sach = re.sub(r"\d+\.\d+\.\d+", " ", doan)
    sach = re.sub(r"`[^`]*`", " ", sach)
    ra: set[str] = set()
    for epic, so in re.findall(r"\b([1-8])[.\-](\d{1,2})\b", sach):
        if 1 <= int(so) <= 9:
            ra.add(f"{epic}.{int(so)}")
    return ra


def _co_moc_cua_sonlm(doan: str) -> bool:
    """Khoản để sonlm quyết chỉ hợp lệ khi nó nêu một mốc.

    "sonlm quyết" trần là khoản trôi qua cả epic mà không ai thấy - đó là điều
    retro Epic 2 quan sát được trên bốn khoản.
    """
    if "sonlm" not in doan:
        return False
    return bool(
        re.search(r"chương\s*\d", doan)
        or re.search(r"[Tt]rước (khi|story|đợt|lần)", doan)
        or re.search(r"chậm nhất", doan)
        or _story_duoc_nhac(doan)
    )


def _khoan_treo() -> list[tuple[str, str, str]]:
    """(story nguồn, tóm tắt, đoạn khai địa chỉ) của mọi khoản chưa `resolved`."""
    ra = []
    for khoi in _khoi_so_no():
        if _truong(khoi, "resolved") is not None:
            continue
        tom_tat = re.search(r"summary: (.*)", khoi).group(1)
        ra.append((_story_nguon(khoi), tom_tat, _dia_chi_moi_nhat(khoi)))
    return ra


def test_moi_khoan_treo_deu_co_chu():
    """Không khoản treo nào mồ côi: địa chỉ phải phân giải ra một chủ còn sống."""
    trang_thai = _trang_thai_sprint()
    story_song = _story_chua_xong(trang_thai)
    epic_song = _epic_chua_xong(trang_thai)

    mo_coi = []
    for nguon, tom_tat, doan in _khoan_treo():
        nhac = _story_duoc_nhac(doan) - {nguon}
        tuong_lai = nhac & story_song
        epic = {e for e in re.findall(r"[Ee]pic\s*(\d+)", doan)} & epic_song
        if not tuong_lai and not epic and not _co_moc_cua_sonlm(doan):
            mo_coi.append(f"[{nguon}] {tom_tat[:110]}")

    assert not mo_coi, (
        f"{len(mo_coi)} khoản treo không có chủ. Địa chỉ phải là một story key có "
        "thật và chưa done, một epic chưa done, hoặc một quyết định của sonlm kèm "
        "mốc. Xem CLAUDE.md mục 'Sổ nợ deferred-work.md khi chốt một story'.\n  "
        + "\n  ".join(mo_coi)
    )


def test_khong_khoan_nao_tro_vao_story_da_done():
    """Địa chỉ trỏ vào một story đã `done` là mồ côi lặng, kiểu hay gặp nhất.

    Khoản vẫn có vẻ có chủ khi đọc lướt, nhưng chủ của nó đã đóng sổ. Ca này
    tách khỏi test trên để thông điệp nói đúng chuyện gì đã xảy ra.
    """
    trang_thai = _trang_thai_sprint()
    story_song = _story_chua_xong(trang_thai)
    da_xong = {
        f"{m.group(1)}.{int(m.group(2))}"
        for khoa, tt in trang_thai.items()
        if (m := KHOA_STORY.match(khoa)) and tt == "done"
    }

    chet = []
    for nguon, tom_tat, doan in _khoan_treo():
        nhac = _story_duoc_nhac(doan) - {nguon}
        # Chỉ báo khi **mọi** story được nhắc đều đã done và không có chủ nào khác.
        if nhac and nhac <= da_xong and not (nhac & story_song):
            epic = {e for e in re.findall(r"[Ee]pic\s*(\d+)", doan)} & _epic_chua_xong(
                trang_thai
            )
            if not epic and not _co_moc_cua_sonlm(doan):
                chet.append(f"[{nguon}] trỏ tới {sorted(nhac)} (đã done) :: {tom_tat[:90]}")

    assert not chet, (
        f"{len(chet)} khoản trỏ vào story đã done. Gán địa chỉ mới bằng một mục "
        "`tien_do` kèm lý do vì sao story cũ không trả được.\n  " + "\n  ".join(chet)
    )


def test_moi_khoan_co_dung_mot_ban_cua_moi_truong():
    """Không khối nào mang hai lần cùng một khóa.

    Hai mục `tien_do` trong một khối là YAML hỏng và là cách dễ nhất để một lần
    cập nhật giấu mất lần trước. Cập nhật một khoản đã có `tien_do` thì nối vào
    block scalar sẵn có, cách nhau một dòng trắng, không thêm khóa thứ hai.
    """
    loi = []
    for khoi in _khoi_so_no():
        khoa = re.findall(r"^  ([a-z_]+):", khoi, re.M)
        trung = sorted({k for k in khoa if khoa.count(k) > 1})
        if trung:
            tom_tat = re.search(r"summary: (.*)", khoi).group(1)
            loi.append(f"{trung} :: {tom_tat[:90]}")
    assert not loi, "Khối mang khóa trùng:\n  " + "\n  ".join(loi)


def test_bo_do_bat_dung_ba_kieu_mo_coi(tmp_path, monkeypatch):
    """Chính bộ dò phải bắt được ba kiểu mồ côi và không bắt nhầm khoản lành.

    Không có ca này thì một lần sửa làm bộ dò luôn trả rỗng vẫn để mọi test trên
    xanh, tức luật ngừng canh mà không ai thấy.
    """
    so_no = tmp_path / "deferred-work.md"
    so_no.write_text(
        "# Deferred work\n\n"
        "- source_spec: `x/spec-2-6-a.md`\n"
        "  summary: Không trỏ đi đâu cả.\n"
        "  evidence: Một khoản không nêu địa chỉ nào.\n"
        "\n"
        "- source_spec: `x/spec-2-6-b.md`\n"
        "  summary: Trỏ vào story đã done.\n"
        "  evidence: Địa chỉ story 2.1.\n"
        "\n"
        "- source_spec: `x/spec-2-6-c.md`\n"
        "  summary: sonlm quyết trần.\n"
        "  evidence: Địa chỉ sonlm quyết.\n"
        "\n"
        "- source_spec: `x/spec-2-6-d.md`\n"
        "  summary: Khoản lành.\n"
        "  evidence: Địa chỉ story 3.2.\n"
        "\n"
        "- source_spec: `x/spec-2-6-e.md`\n"
        "  summary: Khoản lành nhờ mốc của sonlm.\n"
        "  evidence: sonlm quyết, chậm nhất trước khi viết chương 3.\n",
        encoding="utf-8",
    )
    sprint = tmp_path / "sprint-status.yaml"
    sprint.write_text(
        "development_status:\n"
        "  epic-2: done\n"
        "  2-1-mot-story: done\n"
        "  2-6-story-nguon: done\n"
        "  epic-3: backlog\n"
        "  3-2-story-song: backlog\n",
        encoding="utf-8",
    )
    import sys

    mod = sys.modules[__name__]
    monkeypatch.setattr(mod, "SO_NO", so_no)
    monkeypatch.setattr(mod, "SPRINT", sprint)

    treo = mod._khoan_treo()
    assert len(treo) == 5

    trang_thai = mod._trang_thai_sprint()
    song = mod._story_chua_xong(trang_thai)
    assert song == {"3.2"}

    with pytest.raises(AssertionError) as loi:
        mod.test_moi_khoan_treo_deu_co_chu()
    thong_diep = str(loi.value)
    assert "Không trỏ đi đâu cả" in thong_diep
    assert "Trỏ vào story đã done" in thong_diep
    assert "sonlm quyết trần" in thong_diep
    # Hai khoản lành không được vào danh sách.
    assert "Khoản lành." not in thong_diep
    assert "Khoản lành nhờ mốc" not in thong_diep

    with pytest.raises(AssertionError) as loi2:
        mod.test_khong_khoan_nao_tro_vao_story_da_done()
    assert "Trỏ vào story đã done" in str(loi2.value)
    assert "Không trỏ đi đâu cả" not in str(loi2.value)
