"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { goi, LoiApi, MA_MANG } from "@/api/goi";
import { doc_token, la_phien, xoa_token, type Phien } from "@/api/phien";
import { MICROCOPY } from "@/microcopy";
import { HopLoi } from "./HopLoi";
import { SidebarDieuHuong } from "./SidebarDieuHuong";
import { Topbar } from "./Topbar";

// Route đăng nhập do story 4.2 dựng; hôm nay là 404 hợp lệ.
export const DUONG_DANG_NHAP = "/dang-nhap";

// Route **mở**: không cần phiên, khung không gọi `/auth/toi` và không gate,
// render thẳng nội dung với chip trống. Hôm nay chỉ màn đăng nhập; test pytest
// đòi `/dang-nhap` luôn nằm trong đây.
export const ROUTE_MO = [DUONG_DANG_NHAP];

// Phiên hiện tại cho trang con (null khi chưa có phiên hay route mở). Trang
// mẫu `/mau` đọc cờ `admin` từ đây; không trang nào tự gọi `/auth/toi` lần hai.
const PhienContext = createContext<Phien | null>(null);
export function usePhien(): Phien | null {
  return useContext(PhienContext);
}

type TrangThai =
  | { loai: "dang_doc" }
  | { loai: "khong_token" }
  | { loai: "co_phien"; phien: Phien }
  | { loai: "loi"; loi: LoiApi }
  | { loai: "mo" };

/** Khung app: topbar, sidebar, thân. Đọc phiên qua `GET /auth/toi` khi có token
 *  trong sessionStorage; không token thì không gọi API. 401 là xóa token và về
 *  màn đăng nhập với `ly_do=het_han` (thông báo trung tính, không hộp đỏ); lỗi
 *  khác (mạng, 5xx, thân không phải phiên) là hộp đỏ trong thân, chip trống,
 *  không về đăng nhập. */
export function KhungApp({ children }: { children: ReactNode }) {
  const router = useRouter();
  const duong_dan = usePathname();
  const [trang_thai, dat] = useState<TrangThai>({ loai: "dang_doc" });

  // Phụ thuộc `duong_dan`: sau khi 4.2 `ghi_token` rồi push client-side, token
  // mới phải được đọc lại thay vì kẹt ở `khong_token` của lần render trước.
  useEffect(() => {
    let con_song = true;
    if (ROUTE_MO.includes(duong_dan)) {
      dat({ loai: "mo" });
      return;
    }
    if (!doc_token()) {
      dat({ loai: "khong_token" });
      return;
    }
    dat({ loai: "dang_doc" });
    goi<unknown>("/auth/toi")
      .then((than) => {
        if (!con_song) return;
        if (!la_phien(than)) throw new LoiApi(MA_MANG, 200);
        dat({ loai: "co_phien", phien: than });
      })
      .catch((loi: unknown) => {
        if (!con_song) return;
        const l = loi instanceof LoiApi ? loi : new LoiApi(MA_MANG, 0);
        if (l.status === 401) {
          xoa_token();
          router.replace(`${DUONG_DANG_NHAP}?ly_do=het_han`);
          return;
        }
        dat({ loai: "loi", loi: l });
      });
    return () => {
      con_song = false;
    };
  }, [router, duong_dan]);

  // ⌘K / Ctrl+K focus ô hỏi (phần tử mang `data-o-hoi`) nếu trang có và không
  // modal nào đang mở (Esc đóng modal, phím tắt không được xuyên qua nó).
  useEffect(() => {
    function phim(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "k") return;
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      const o = document.querySelector<HTMLElement>("[data-o-hoi]");
      if (o) {
        e.preventDefault();
        o.focus();
      }
    }
    document.addEventListener("keydown", phim);
    return () => document.removeEventListener("keydown", phim);
  }, []);

  const phien = trang_thai.loai === "co_phien" ? trang_thai.phien : null;
  let than: ReactNode;
  switch (trang_thai.loai) {
    case "dang_doc":
      than = <p data-dang-tai>{MICROCOPY.dang_tai}</p>;
      break;
    case "khong_token":
      than = (
        <p data-dang-nhap-de-bat-dau>
          <Link href={DUONG_DANG_NHAP}>{MICROCOPY.dang_nhap_de_bat_dau}</Link>
        </p>
      );
      break;
    case "loi":
      than = (
        <div data-ma-loi={trang_thai.loi.code}>
          <HopLoi>{MICROCOPY.loi_he_thong}</HopLoi>
        </div>
      );
      break;
    case "co_phien":
    case "mo":
      than = children;
  }

  return (
    <div className="khung" data-khung={trang_thai.loai}>
      <Topbar phien={phien} />
      <div className="than">
        <SidebarDieuHuong />
        <main className="noi_dung">
          <PhienContext.Provider value={phien}>{than}</PhienContext.Provider>
        </main>
      </div>
    </div>
  );
}
