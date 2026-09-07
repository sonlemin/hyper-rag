import Link from "next/link";

import { chip_vai, type Phien } from "@/api/phien";
import { MICROCOPY } from "@/microcopy";

/** Topbar 52px nền primary-deep: thương hiệu bên trái, chip vai bên phải.
 *  Chưa có phiên thì chip trống, không placeholder giả. Chip không bao giờ
 *  mang mức Lx (DESIGN.md, Do's and Don'ts).
 *
 *  Nút đăng xuất chỉ hiện khi có phiên: không có phiên thì không có gì để
 *  thoát, và một nút chết trên màn chờ là một nút người dùng bấm rồi tự hỏi vì
 *  sao không có gì xảy ra. */
export function Topbar({ phien, dang_xuat }: { phien: Phien | null; dang_xuat: () => void }) {
  return (
    <header className="topbar" data-topbar>
      <Link href="/" className="topbar__thuong_hieu">
        {MICROCOPY.thuong_hieu} <span>· {MICROCOPY.thuong_hieu_phu}</span>
      </Link>
      <div className="topbar__gian" />
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
