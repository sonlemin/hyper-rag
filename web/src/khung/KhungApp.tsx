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
//
// Context mang **hai** thứ từ story 4.5: phiên, và **dãy tên vai** của mọi lần
// đổi vai đã xảy ra trong phiên trang này, theo thứ tự. Màn chat đọc dãy ấy để
// chèn divider.
//
// Một **dãy** chứ không một bộ đếm, và cũng không một chênh lệch tên vai giữa
// hai lượt. Ba ca hỏng, mỗi ca loại một phương án:
//
//   - suy từ chênh lệch `phien.vai` nuốt mất lần bấm lại đúng dòng đang có dấu
//     ✓ và cả cặp "đổi đi rồi đổi về" (EXPERIENCE.md: **mỗi lần** đổi vai chèn
//     một divider);
//   - một bộ đếm cộng với tên vai đọc từ `phien.vai` lúc chèn thì mốc mang tên
//     vai **vừa rời đi** nếu lần đọc phiên chưa xong - đo được ở ca e2e "đổi đi
//     rồi đổi về";
//   - một bộ đếm mà hai lần đổi chồng nhau (lần đọc thứ nhất bị effect hủy) thì
//     một lần đọc xác nhận cả hai, và màn chat chèn **một** mốc cho **hai** lần
//     đổi thật.
//
// Dãy tên vai đóng cả ba: tên vai đến từ chính lời gọi vừa thành công, nên nó
// không phụ thuộc lần đọc phiên và cũng không lẫn giữa hai lần đổi chồng nhau.
type NoiDungPhien = { phien: Phien | null; cac_lan_doi: readonly string[] };

const PhienContext = createContext<NoiDungPhien>({ phien: null, cac_lan_doi: [] });

export function usePhien(): Phien | null {
  return useContext(PhienContext).phien;
}

/** Dãy vai của mọi lần đổi vai đã xảy ra, theo thứ tự, chỉ dài thêm. Màn chat
 *  chèn một mốc cho mỗi phần tử nó chưa thấy. */
export function useCacLanDoiVai(): readonly string[] {
  return useContext(PhienContext).cac_lan_doi;
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
  // Dãy vai của mọi lần đổi đã xảy ra. Ghi **ngay khi lời gọi đổi vai thành
  // công**, không đợi lần đọc phiên: token mới đã ký và hàng `role_swap` đã ghi
  // ở phía máy chủ, nên lần đổi ấy là một sự thật rồi, và tên vai thì chính lời
  // gọi vừa trả về. Nhờ vậy mốc không bao giờ mang tên vai cũ và hai lần đổi
  // chồng nhau vẫn ra hai mốc.
  const [cac_lan_doi, dat_cac_lan_doi] = useState<readonly string[]>([]);
  // Khóa đọc lại phiên: đổi giá trị là effect dưới chạy lại và gọi `/auth/toi`.
  // Một `useState` chứ không một lời gọi tay ở nơi khác, để **đúng một** chỗ
  // trong app đọc phiên và không có đường nào cho hai lời gọi song song.
  const [nhip_doc, dat_nhip_doc] = useState(0);
  // Có đang đọc lại phiên trong khi màn vẫn hiện phiên cũ không. Bỏ `dang_doc`
  // ở nhánh đọc lại là đúng (nó từng unmount cả lịch sử chat), nhưng nó để lại
  // một trạng thái **vô hình**: một `/auth/toi` treo giữ vai cũ trên topbar vô
  // thời hạn trong khi token đã đổi, tức màn hình nói một vai còn máy chủ trả
  // lời theo vai khác. Đánh dấu ra DOM để trạng thái ấy nhìn thấy được.
  const [dang_doc_lai, dat_dang_doc_lai] = useState(false);

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
    // Giữ phiên đang có trong lúc đọc lại. Đặt thẳng `dang_doc` là `than` đổi
    // sang "Đang tải..." và **children bị unmount**, tức toàn bộ lịch sử chat
    // trong bộ nhớ trang biến mất mỗi lần đổi vai - đúng thứ Never của story
    // 4.5 cấm ("không xóa lịch sử chat khi đổi vai"), và một lượt đang bay
    // cũng mất theo. Chỉ lần đọc đầu (chưa có phiên nào) mới hiện màn chờ.
    dat((cu) => (cu.loai === "co_phien" ? cu : { loai: "dang_doc" }));
    // Đọc lại vì một lần đổi vai (`nhip_doc > 0`) thì màn vẫn hiện phiên cũ,
    // nên trạng thái ấy phải nhìn thấy được thay vì im lặng.
    dat_dang_doc_lai(nhip_doc > 0);
    goi<unknown>("/auth/toi")
      .then((than) => {
        if (!con_song) return;
        if (!la_phien(than)) throw new LoiApi(MA_MANG, 200);
        dat({ loai: "co_phien", phien: than });
        dat_dang_doc_lai(false);
      })
      .catch((loi: unknown) => {
        if (!con_song) return;
        dat_dang_doc_lai(false);
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
  }, [router, duong_dan, mo, nhip_doc]);

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

  /** Vừa đổi vai xong: ghi lần đổi vào dãy rồi đọc lại phiên từ token mới.
   *
   *  Hai việc, hai vai trò khác nhau. Dãy `cac_lan_doi` là **lịch sử thao tác**
   *  và nó ghi ngay, vì lần đổi đã xảy ra thật ở phía máy chủ (token mới đã ký,
   *  hàng `role_swap` đã ghi) và `vai_moi` đến thẳng từ lời gọi ấy. Còn phiên
   *  thì **đọc lại** chứ không tự sửa theo vai vừa chọn: `web/` không giữ một
   *  bản chép của "đang là vai gì" (luật một cửa của 4.2), nguồn duy nhất là
   *  claim mà máy chủ vừa ký, và tự sửa là mở đúng cửa cho màn hình nói một vai
   *  còn máy chủ trả lời theo vai khác. */
  function da_doi_vai(vai_moi: string) {
    dat_cac_lan_doi((cu) => [...cu, vai_moi]);
    dat_nhip_doc((n) => n + 1);
  }

  /** Hết phiên giữa một lần đổi vai. Nhánh điều hướng **duy nhất** của khung,
   *  dùng chung với nhánh 401 của effect đọc phiên (luật của `phien.ts`). */
  function het_phien() {
    xoa_token();
    router.replace(duong_het_phien());
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
    <div
      className="khung"
      data-khung={trang_thai.loai}
      data-dang-doc-lai={dang_doc_lai ? "1" : undefined}
    >
      <Topbar
        phien={phien}
        dang_xuat={thoat}
        da_doi_vai={da_doi_vai}
        het_phien={het_phien}
      />
      <div className="than">
        <SidebarDieuHuong />
        <main className="noi_dung">
          <PhienContext.Provider value={{ phien, cac_lan_doi }}>{than}</PhienContext.Provider>
        </main>
      </div>
    </div>
  );
}
