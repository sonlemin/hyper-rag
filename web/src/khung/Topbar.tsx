import Link from "next/link";

import { chip_vai, type Phien } from "@/api/phien";
import { MICROCOPY } from "@/microcopy";

/** Topbar 52px nền primary-deep: thương hiệu bên trái, chip vai bên phải.
 *  Chưa có phiên thì chip trống, không placeholder giả. Chip không bao giờ
 *  mang mức Lx (DESIGN.md, Do's and Don'ts). */
export function Topbar({ phien }: { phien: Phien | null }) {
  return (
    <header className="topbar" data-topbar>
      <Link href="/" className="topbar__thuong_hieu">
        {MICROCOPY.thuong_hieu} <span>· {MICROCOPY.thuong_hieu_phu}</span>
      </Link>
      <div className="topbar__gian" />
      <span className="chip_vai" data-chip-vai>
        {phien ? chip_vai(phien) : ""}
      </span>
    </header>
  );
}
