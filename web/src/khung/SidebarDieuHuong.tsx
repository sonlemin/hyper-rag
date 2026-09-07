"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { MICROCOPY } from "@/microcopy";
import dieu_huong from "./dieu_huong.json";

export const KHOA_SIDEBAR = "hyper_rag_sidebar";
type TrangThai = "mo" | "mini";

/** Mục được chọn khi pathname là chính nó hay route con của nó (`/x/y` chọn
 *  mục `/x`); mục `/` chỉ khớp đúng `/`. Dấu `/` cuối bị bỏ ở cả hai bên. */
export function la_muc_chon(duong_dan: string | null, muc: string): boolean {
  const cat = (d: string) => (d.length > 1 ? d.replace(/\/+$/, "") : d);
  const d = cat(duong_dan ?? "/");
  const m = cat(muc);
  if (m === "/") return d === "/";
  return d === m || d.startsWith(m + "/");
}

/** Sidebar hai trạng thái kiểu VS Code (216px / 52px), điều hướng duy nhất.
 *  Trạng thái nhớ trong `sessionStorage` và đọc trong `useEffect`: render đầu
 *  luôn là mở để server và client khớp nhau lúc hydrate. Chỉ liệt kê surface đã
 *  tồn tại (`dieu_huong.json`, test canh một-một với route). */
export function SidebarDieuHuong() {
  const duong_dan = usePathname();
  const [trang_thai, dat_trang_thai] = useState<TrangThai>("mo");

  useEffect(() => {
    try {
      if (window.sessionStorage.getItem(KHOA_SIDEBAR) === "mini") dat_trang_thai("mini");
    } catch {
      /* sessionStorage bị chặn: giữ mặc định mở */
    }
  }, []);

  function gap_mo() {
    const moi: TrangThai = trang_thai === "mo" ? "mini" : "mo";
    dat_trang_thai(moi);
    try {
      window.sessionStorage.setItem(KHOA_SIDEBAR, moi);
    } catch {
      /* không nhớ được thì vẫn đổi được trong phiên hiện tại */
    }
  }

  const mini = trang_thai === "mini";
  return (
    <nav
      className={mini ? "sidebar sidebar--mini" : "sidebar"}
      aria-label={MICROCOPY.dieu_huong_chinh}
      data-sidebar={trang_thai}
    >
      {dieu_huong.map((muc) => {
        const chon = la_muc_chon(duong_dan, muc.duong_dan);
        return (
          <Link
            key={muc.khoa}
            href={muc.duong_dan}
            className={chon ? "sidebar__muc sidebar__muc--chon" : "sidebar__muc"}
            aria-current={chon ? "page" : undefined}
            title={mini ? `${muc.nhan} · ${muc.phim_tat}` : undefined}
          >
            {mini ? (
              <span aria-hidden="true">{muc.icon}</span>
            ) : (
              <>
                <span>{muc.nhan}</span>
                <span className="sidebar__phim_tat">{muc.phim_tat}</span>
              </>
            )}
            {mini && <span className="sr-only">{muc.nhan}</span>}
          </Link>
        );
      })}
      <div className="sidebar__chan">
        <button
          type="button"
          className="sidebar__nut_gap"
          onClick={gap_mo}
          aria-expanded={!mini}
          title={mini ? MICROCOPY.mo_rong_menu : MICROCOPY.thu_gon_menu}
        >
          <i aria-hidden="true">{mini ? "»" : "«"}</i>
          {!mini && MICROCOPY.thu_gon_menu}
          {mini && <span className="sr-only">{MICROCOPY.mo_rong_menu}</span>}
        </button>
      </div>
    </nav>
  );
}
