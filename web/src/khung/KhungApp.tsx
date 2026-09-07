"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { goi, LoiApi, MA_MANG } from "@/api/goi";
import {
  dang_xuat,
  doc_token,
  DUONG_DANG_NHAP,
  duong_het_phien,
  la_het_phien,
  la_phien,
  xoa_token,
  type Phien,
} from "@/api/phien";
import { MICROCOPY } from "@/microcopy";
import { HopLoi } from "./HopLoi";
import { SidebarDieuHuong } from "./SidebarDieuHuong";
import { Topbar } from "./Topbar";

// Màn đăng nhập (story 4.2). Hằng sống ở `phien.ts` từ story 4.3, vì màn chat
// là nơi thứ hai điều hướng về đó khi hết phiên; nơi nào cần thì nhập thẳng từ
// đó, khung không re-export (một re-export không ai dùng là một cửa thứ hai để
// hai bản chép mọc lên).

// Route **mở**: không cần phiên, khung không gọi `/auth/toi` và không gate,
// render **trần** (không topbar, không sidebar) vì màn đăng nhập là màn đứng
// riêng. Hôm nay chỉ màn đăng nhập; test pytest đòi `/dang-nhap` luôn nằm
// trong đây.
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
  | { loai: "loi"; loi: LoiApi };

/** Khung app: topbar, sidebar, thân. Đọc phiên qua `GET /auth/toi` khi có token
 *  trong sessionStorage; không token thì không gọi API. 401 là xóa token và về
 *  màn đăng nhập với `ly_do=het_han` (thông báo trung tính, không hộp đỏ); lỗi
 *  khác (mạng, 5xx, thân không phải phiên) là hộp đỏ trong thân, chip trống,
 *  không về đăng nhập. */
export function KhungApp({ children }: { children: ReactNode }) {
  const router = useRouter();
  const duong_dan = usePathname();
  const [trang_thai, dat] = useState<TrangThai>({ loai: "dang_doc" });

  // Route mở nhận ra **ngay trong thân render**, không qua một trạng thái khởi
  // tạo rồi đợi `useEffect` lật lại: trạng thái đầu là `dang_doc`, nên một
  // vòng qua effect có nghĩa là HTML prerender và lần render client đầu của
  // `/dang-nhap` là khung đầy đủ với "Đang tải...", tức một nháy khung trước
  // card. Playwright không thấy nó vì `toHaveCount(0)` tự chờ; người xem thì có.
  const mo = ROUTE_MO.includes(duong_dan);

  // Phụ thuộc `duong_dan`: sau khi `ghi_token` rồi push client-side, token mới
  // phải được đọc lại thay vì kẹt ở `khong_token` của lần render trước.
  useEffect(() => {
    let con_song = true;
    if (mo) return;
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
        // Luật phân loại lỗi khai một chỗ (`phien.ts`): chỉ hết phiên mới được
        // đá về màn đăng nhập. 403 và 5xx báo tại chỗ, giữ nguyên URL.
        if (la_het_phien(l)) {
          xoa_token();
          router.replace(duong_het_phien());
          return;
        }
        dat({ loai: "loi", loi: l });
      });
    return () => {
      con_song = false;
    };
  }, [router, duong_dan, mo]);

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

  // Đăng xuất: xóa token rồi về màn đăng nhập **không** `ly_do` (hết phiên và
  // tự thoát là hai chuyện khác nhau, và người tự thoát không cần được báo là
  // phiên đã hết hạn).
  function thoat() {
    dang_xuat();
    router.replace(DUONG_DANG_NHAP);
  }

  // Route mở render trần: màn đăng nhập không có topbar và không có sidebar,
  // và nó không được gate bởi chính phiên mà nó sắp tạo. Đứng sau mọi hook
  // (luật hook) nhưng vẫn trong cùng một lần render, nên không có khung nào
  // kịp hiện ra.
  if (mo) return <>{children}</>;

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
      // Ngõ cụt nếu không có lối ra: token còn nguyên nên mỗi lần tải lại rơi
      // đúng vào đây, và nút đăng xuất ẩn vì chưa có phiên. Một liên kết, không
      // tự điều hướng - 403 và 5xx không được đá người dùng đi (spec 4.2 Never).
      than = (
        <div data-ma-loi={trang_thai.loi.code}>
          <HopLoi>{MICROCOPY.loi_he_thong}</HopLoi>
          <p className="loi_loi_thoat">
            <Link href={DUONG_DANG_NHAP}>{MICROCOPY.lien_ket_ve_dang_nhap}</Link>
          </p>
        </div>
      );
      break;
    case "co_phien":
      than = children;
  }

  return (
    <div className="khung" data-khung={trang_thai.loai}>
      <Topbar phien={phien} dang_xuat={thoat} />
      <div className="than">
        <SidebarDieuHuong />
        <main className="noi_dung">
          <PhienContext.Provider value={phien}>{than}</PhienContext.Provider>
        </main>
      </div>
    </div>
  );
}
