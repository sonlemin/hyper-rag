import Link from "next/link";

import { chip_vai, type Phien } from "@/api/phien";
import { MICROCOPY } from "@/microcopy";

import { MenuXemNhu } from "./MenuXemNhu";

/** Topbar 52px nền primary-deep: thương hiệu bên trái, chip vai bên phải.
 *  Chưa có phiên thì chip trống, không placeholder giả. Chip không bao giờ
 *  mang mức Lx (DESIGN.md, Do's and Don'ts).
 *
 *  Nút đăng xuất chỉ hiện khi có phiên: không có phiên thì không có gì để
 *  thoát, và một nút chết trên màn chờ là một nút người dùng bấm rồi tự hỏi vì
 *  sao không có gì xảy ra.
 *
 *  Điều khiển "xem như" (story 4.5) đứng trong khe giữa `topbar__gian` và chip
 *  vai, và **chỉ vẽ cho phiên có `demo` hoặc `admin`** - hai cờ đọc thẳng từ
 *  claim, không suy từ vai đang mang, nên một phiên đang mượn một vai không cờ
 *  vẫn thoát ra được. Ẩn nút không phải một phép kiểm quyền: nửa cơ chế của
 *  FR-18 là ba tuyến API cùng từ chối, có test riêng ở `tests/test_xac_thuc.py`. */
export function Topbar({
  phien,
  dang_xuat,
  da_doi_vai,
  het_phien,
}: {
  phien: Phien | null;
  dang_xuat: () => void;
  da_doi_vai: (vai_moi: string) => void;
  het_phien: () => void;
}) {
  return (
    <header className="topbar" data-topbar>
      <Link href="/" className="topbar__thuong_hieu">
        {MICROCOPY.thuong_hieu} <span>· {MICROCOPY.thuong_hieu_phu}</span>
      </Link>
      <div className="topbar__gian" />
      {phien && (phien.demo || phien.admin) && (
        <MenuXemNhu phien={phien} da_doi={da_doi_vai} het_phien={het_phien} />
      )}
      <span className="chip_vai" data-chip-vai>
        {phien ? chip_vai(phien) : ""}
      </span>
      {phien && (
        <button type="button" className="topbar__nut_thoat" onClick={dang_xuat} data-dang-xuat>
          {MICROCOPY.nut_dang_xuat}
        </button>
      )}
    </header>
  );
}
