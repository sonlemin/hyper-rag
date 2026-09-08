"use client";

import { useEffect, useId, useRef, useState } from "react";

import { LoiApi, MA_MANG } from "@/api/goi";
import {
  chip_vai_that,
  la_dang_xem_nhu,
  la_het_phien,
  nhan_vai,
  tai_khoan_that,
  vai_that,
  type Phien,
} from "@/api/phien";
import { danh_muc_vai, doi_vai, thoat_xem_nhu, type KetCucDoiVai } from "@/api/xem_nhu";
import { dien, MICROCOPY, type KhoaMicrocopy } from "@/microcopy";
import { mo_ta_vai } from "@/nhan";

import { HopLoi } from "./HopLoi";

// Nút "⇄ Xem như", dropdown của nó, chip hổ phách và chip vai thật - **một**
// component, vì cả bốn thứ đọc cùng một nguồn (claim `act` của token) và vì hai
// đường thoát (mục cuối menu, nút ✕ trên chip) phải đi qua đúng một hàm. Hai
// bản chép của phép thoát là hai bản mà một trong hai quên xử lý ca kho bị chặn.
//
// **`role="menu"` là một hợp đồng, không một nhãn.** Phần tử mang vai ấy chứa
// **chỉ** `menuitem*`; tiêu đề đứng ngoài và nối vào bằng `aria-labelledby`,
// khối trạng thái và khối lỗi cũng đứng ngoài. Up/Down/Home/End di chuyển
// focus, và focus vào menu ngay khi mở. Khai một vai trợ năng rồi không giữ
// đúng hợp đồng của nó tệ hơn là không khai: trình đọc màn hình báo "menu, 5
// mục" cho một khối có một đoạn văn và một `role="alert"` bên trong.
//
// Nhưng **không** `aria-modal`: ⌘K phải còn chạy trong lúc menu mở (ca e2e của
// 4.1 ghim đúng điều kiện đó). Một dropdown chọn vai không giành cả bàn phím
// của trang, và đó là nhịp thật của buổi demo - chọn vai rồi gõ ngay câu kế.
//
// Điều khiển này **chỉ được vẽ cho phiên có `demo` hoặc `admin`**, và đó là nửa
// giao diện của FR-18 chứ không phải cơ chế: nửa cơ chế là ba tuyến API cùng
// từ chối, và nó có test riêng ở `tests/test_xac_thuc.py`. Ẩn một nút không
// phải một phép kiểm quyền.

/** Chọn mọi mục bấm được của menu, theo đúng thứ tự DOM. */
const CHON_MUC = '[role="menuitemradio"], [role="menuitem"]';

type TrangThaiVai =
  | { loai: "chua_doc" }
  | { loai: "dang_doc" }
  | { loai: "xong"; cac_vai: string[] }
  | { loai: "loi"; ma: string };

/** Một mục vai trong menu. Dấu ✓ nằm ở một ô cố định bên trái **mọi** mục nên
 *  các dòng thẳng cột dù chỉ một dòng có dấu; `aria-checked` là thứ trình đọc
 *  màn hình đọc, ✓ chỉ là hình. */
function MucVai({
  vai,
  dang_chon,
  chon,
}: {
  vai: string;
  dang_chon: boolean;
  chon: () => void;
}) {
  const mo_ta = mo_ta_vai(vai);
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={dang_chon}
      tabIndex={-1}
      className="menu_vai__muc"
      data-muc-vai={vai}
      data-dang-chon={dang_chon ? "1" : undefined}
      onClick={chon}
    >
      <span className="menu_vai__dau" aria-hidden="true">
        {dang_chon ? "✓" : ""}
      </span>
      <span className="menu_vai__chu">
        <span className="menu_vai__ten">{nhan_vai(vai)}</span>
        {mo_ta !== null && <span className="menu_vai__mo_ta">{mo_ta}</span>}
      </span>
    </button>
  );
}

type ThuocTinh = {
  phien: Phien;
  /** Gọi **sau mỗi lần đổi vai thành công** kèm **vai mới**, kể cả khi vai ấy
   *  bằng vai đang mang: khung ghi lần đổi vào dãy rồi đọc lại `/auth/toi`, còn
   *  màn chat chèn một divider cho mỗi phần tử mới của dãy.
   *
   *  Tên vai đi kèm ngay tại đây chứ không đọc lại từ phiên: lời gọi vừa thành
   *  công **biết** nó đổi sang vai nào, còn phiên thì còn là vai cũ cho tới khi
   *  `/auth/toi` trả về. Suy divider từ chênh lệch tên vai nuốt mất đúng ca
   *  người trình bày bấm lại dòng đang có dấu ✓. */
  da_doi: (vai_moi: string) => void;
  /** 401 giữa một lần đổi vai. Khung là **nơi duy nhất** điều hướng vì một lỗi
   *  (luật của 4.2), nên component này báo lên chứ không tự `router.replace`. */
  het_phien: () => void;
};

export function MenuXemNhu({ phien, da_doi, het_phien }: ThuocTinh) {
  const [mo, dat_mo] = useState(false);
  const [vai, dat_vai] = useState<TrangThaiVai>({ loai: "chua_doc" });
  const [loi_doi, dat_loi_doi] = useState<KhoaMicrocopy | null>(null);
  const nut = useRef<HTMLButtonElement>(null);
  const khoi = useRef<HTMLDivElement>(null);
  const danh_sach = useRef<HTMLDivElement>(null);
  // Chốt chống bấm hai lần ở **ref**, không ở state: hai cú bấm trong cùng một
  // tick đọc cùng một giá trị state cũ nên cả hai đều lọt (cùng khuôn với màn
  // đăng nhập 4.2 và composer 4.3), và hai lần đổi vai song song là hai token
  // ghi đè nhau trong kho.
  const dang_goi = useRef(false);
  const id_menu = useId();
  const id_tieu_de = useId();

  // Esc đóng và **trả focus về nút mở**; bấm ra ngoài cũng đóng. Không bẫy Tab
  // và không `aria-modal`: đây là một menu, không phải một lớp che cả trang.
  useEffect(() => {
    if (!mo) return;
    function phim(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      e.preventDefault();
      dat_mo(false);
      nut.current?.focus();
    }
    function ngoai(e: MouseEvent) {
      const dich = e.target as Node;
      if (khoi.current?.contains(dich) || nut.current?.contains(dich)) return;
      dat_mo(false);
    }
    document.addEventListener("keydown", phim);
    document.addEventListener("mousedown", ngoai);
    return () => {
      document.removeEventListener("keydown", phim);
      document.removeEventListener("mousedown", ngoai);
    };
  }, [mo]);

  // Focus vào menu khi nó có mục để focus: mục đang chọn nếu có, không thì mục
  // đầu. Một menu mở ra mà focus còn ở nút thì Up/Down không đi đâu cả, và
  // người dùng bàn phím phải Tab vào - tức nó không cư xử như một menu.
  const so_muc = vai.loai === "xong" ? vai.cac_vai.length : 0;
  useEffect(() => {
    if (!mo || so_muc === 0) return;
    const cac = danh_sach.current?.querySelectorAll<HTMLElement>(CHON_MUC);
    if (!cac || cac.length === 0) return;
    const dang_chon = danh_sach.current?.querySelector<HTMLElement>('[aria-checked="true"]');
    (dang_chon ?? cac[0]).focus();
  }, [mo, so_muc]);

  /** Up/Down/Home/End di chuyển focus giữa các mục, vòng lại ở hai đầu. */
  function dieu_huong(e: React.KeyboardEvent<HTMLDivElement>) {
    const cac = Array.from(danh_sach.current?.querySelectorAll<HTMLElement>(CHON_MUC) ?? []);
    if (cac.length === 0) return;
    const i = cac.indexOf(document.activeElement as HTMLElement);
    let ke: HTMLElement | undefined;
    if (e.key === "ArrowDown") ke = cac[(i + 1 + cac.length) % cac.length];
    else if (e.key === "ArrowUp") ke = cac[(i - 1 + cac.length) % cac.length];
    else if (e.key === "Home") ke = cac[0];
    else if (e.key === "End") ke = cac[cac.length - 1];
    if (!ke) return;
    e.preventDefault();
    ke.focus();
  }

  function ma_cua(loi: unknown): string {
    return loi instanceof LoiApi ? loi.code : MA_MANG;
  }

  /** Đọc danh mục vai **mỗi lần mở**, không cache suốt vòng đời trang.
   *
   *  Bảng chính sách hoán được lúc chạy (`POST /admin/policy`, story 3.2) và
   *  cùng một tài khoản `admin` mở được cả hai tuyến, nên một danh sách đọc một
   *  lần rồi giữ mãi là một dropdown liệt kê một vai đã biến mất - bấm vào ra
   *  400 `VAI_KHONG_CO`, và giao diện hiện nó thành "Hệ thống gặp lỗi".
   *
   *  Danh sách cũ **ở nguyên trên màn** trong lúc đọc lại: một lần nháy "Đang
   *  tải..." mỗi lần mở menu là một dropdown giật dưới tay người trình bày.
   *  Hàng I/O Matrix "Không cờ nào" (không gọi `/auth/vai`) vẫn đúng vì cả
   *  component này không được vẽ cho phiên thiếu cờ. */
  function mo_menu() {
    dat_mo(true);
    dat_loi_doi(null);
    if (vai.loai !== "xong") dat_vai({ loai: "dang_doc" });
    danh_muc_vai()
      .then((cac_vai) => dat_vai({ loai: "xong", cac_vai }))
      .catch((loi: unknown) => {
        if (la_het_phien(loi)) {
          het_phien();
          return;
        }
        dat_vai({ loai: "loi", ma: ma_cua(loi) });
      });
  }

  /** Một lần đổi vai: gọi API, ghi token, rồi báo cho khung đọc lại phiên.
   *
   *  Ba kết cục hỏng phân biệt được, và mỗi cái nói một chuyện khác nhau:
   *  kho bị chặn thì **không** đổi vai trên màn (token cũ vẫn là token mọi lời
   *  gọi sau dùng) và menu ở nguyên để người dùng đọc câu giải thích; 401 là
   *  hết phiên và khung xử lý; mọi mã còn lại - 403 thiếu cờ, 400 vai lạ, 5xx,
   *  `MANG` - báo tại chỗ và giữ nguyên URL, đúng luật phân loại lỗi của 4.2. */
  async function chay(vai_moi: string, goi_api: () => Promise<KetCucDoiVai>) {
    if (dang_goi.current) return;
    dang_goi.current = true;
    dat_loi_doi(null);
    try {
      const kq = await goi_api();
      if (kq.loai === "khong_giu_duoc") {
        dat_loi_doi("khong_giu_duoc_phien");
        return;
      }
      if (kq.loai === "than_la") {
        dat_loi_doi("loi_he_thong");
        return;
      }
      dat_mo(false);
      da_doi(vai_moi);
    } catch (that_bai: unknown) {
      if (la_het_phien(that_bai)) {
        het_phien();
        return;
      }
      dat_loi_doi("loi_he_thong");
    } finally {
      dang_goi.current = false;
    }
  }

  const dang_xem_nhu = la_dang_xem_nhu(phien);

  return (
    <div className="xem_nhu">
      {/* Chip hổ phách trước nút, chip vai thật sau - đúng thứ tự mockup. Cả
          hai chỉ có mặt khi đang mượn vai; lúc thường thì chip vai của topbar
          đã nói đúng chuyện đó rồi. Chip không bao giờ mang Lx, cùng luật với
          chip vai của 4.1: mức tiết lộ là hàm của vai × loại nội dung, không
          phải một nhãn dán lên một vai. */}
      {dang_xem_nhu && (
        <span className="chip_xem_nhu" data-chip-xem-nhu>
          {dien("chip_xem_nhu", { vai: nhan_vai(phien.vai) })}
          <button
            type="button"
            className="chip_xem_nhu__x"
            onClick={() => void chay(vai_that(phien), thoat_xem_nhu)}
            title={MICROCOPY.thoat_xem_nhu}
            aria-label={MICROCOPY.thoat_xem_nhu}
            data-thoat-nhanh
          >
            ✕
          </button>
        </span>
      )}

      <button
        type="button"
        ref={nut}
        className="nut_xem_nhu"
        aria-haspopup="menu"
        aria-expanded={mo}
        aria-controls={mo ? id_menu : undefined}
        onClick={() => (mo ? dat_mo(false) : mo_menu())}
        data-nut-xem-nhu
      >
        {MICROCOPY.nut_xem_nhu}
        <span className="nut_xem_nhu__caret" aria-hidden="true">
          ▾
        </span>
      </button>

      {dang_xem_nhu && (
        <span className="chip_vai_that" data-chip-vai-that>
          {chip_vai_that(phien)}
        </span>
      )}

      {/* **Một** tấm nổi cho cả menu lẫn hộp lỗi, không hai tấm cùng
          `position: absolute; top: calc(100% + 6px)`. Bản đầu tách chúng ra và
          một lần đổi vai hỏng thì menu **vẫn mở** (chỉ ca thành công mới đóng),
          nên hộp lỗi phủ đúng lên menu; ca e2e chỉ đòi hộp có chữ nên nó xanh
          với cả trạng thái chồng hình. Gộp làm một thì hộp lỗi luôn nằm **dưới**
          mục cuối, và đó là thứ đo được bằng hai `boundingBox`. */}
      {(mo || loi_doi !== null) && (
        <div className="menu_vai" ref={khoi} data-tam-xem-nhu>
          {mo && (
            <>
              {/* Tiêu đề đứng **ngoài** phần tử `menu` và nối vào bằng
                  `aria-labelledby`: một `menu` chỉ được chứa `menuitem*`. */}
              <div className="menu_vai__tieu_de" id={id_tieu_de}>
                {MICROCOPY.tieu_de_menu_vai}
              </div>

              {vai.loai === "dang_doc" && (
                <p className="menu_vai__trang">{MICROCOPY.dang_tai}</p>
              )}
              {vai.loai === "loi" && (
                <div className="menu_vai__trang" data-ma-loi={vai.ma}>
                  <HopLoi>{MICROCOPY.loi_he_thong}</HopLoi>
                </div>
              )}
              {/* Danh mục rỗng (thân 200 sai hình) mở ra một menu chỉ có tiêu
                  đề, và người dùng không có cách nào biết vì sao. Nói ra. */}
              {vai.loai === "xong" && vai.cac_vai.length === 0 && (
                <p className="menu_vai__trang" data-khong-co-vai>
                  {MICROCOPY.khong_co_vai}
                </p>
              )}

              <div
                className="menu_vai__danh_sach"
                id={id_menu}
                role="menu"
                aria-labelledby={id_tieu_de}
                ref={danh_sach}
                onKeyDown={dieu_huong}
                data-menu-vai
              >
                {vai.loai === "xong" &&
                  vai.cac_vai.map((v) => (
                    <MucVai
                      key={v}
                      vai={v}
                      dang_chon={v === phien.vai}
                      chon={() => void chay(v, () => doi_vai(v))}
                    />
                  ))}

                {/* Mục thoát tách ở đáy, và chỉ có mặt khi đang mượn vai: một
                    mục "Thoát xem như" trên một phiên thường là một nút bấm vào
                    ra 400. */}
                {dang_xem_nhu && (
                  <button
                    type="button"
                    role="menuitem"
                    tabIndex={-1}
                    className="menu_vai__thoat"
                    onClick={() => void chay(vai_that(phien), thoat_xem_nhu)}
                    data-thoat-xem-nhu
                  >
                    <span className="menu_vai__x" aria-hidden="true">
                      ✕
                    </span>
                    {MICROCOPY.thoat_xem_nhu}
                    <span className="menu_vai__ve">
                      {dien("ve_vai_that", {
                        tai_khoan: tai_khoan_that(phien),
                        vai: nhan_vai(vai_that(phien)),
                      })}
                    </span>
                  </button>
                )}
              </div>
            </>
          )}

          {loi_doi !== null && (
            <div className="menu_vai__loi" data-loi-doi-vai={loi_doi}>
              <HopLoi>{MICROCOPY[loi_doi]}</HopLoi>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
