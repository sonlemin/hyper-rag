"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { goi } from "@/api/goi";
import {
  ghi_token,
  la_sai_thong_tin,
  LY_DO_HET_HAN,
  THAM_SO_LY_DO,
  token_dang_nhap,
  TRUONG_MAT_KHAU,
  TRUONG_TAI_KHOAN,
  TUYEN_DANG_NHAP,
} from "@/api/phien";
import { HopLoi } from "@/khung/HopLoi";
import { MICROCOPY } from "@/microcopy";

// Đích sau khi đăng nhập xong: trang "Hỏi đáp".
const DUONG_SAU_DANG_NHAP = "/";

// Id của khối lỗi, để hai ô trỏ tới bằng `aria-describedby` khi chúng đỏ.
const ID_LOI = "loi_dang_nhap";

/** Ba kết cục hỏng của một lần gửi, mỗi kết cục một câu chữ khác nhau:
 *  - `dang_nhap`: 401 **kèm mã `DANG_NHAP_SAI`**, tức sai tài khoản hoặc mật khẩu;
 *  - `he_thong`: mọi lỗi khác (5xx, mạng, 413, 401 hạ tầng, thân 200 thiếu `token`);
 *  - `khong_giu_duoc_phien`: đăng nhập đúng nhưng kho trình duyệt bị chặn.
 *  Trộn ba thứ này vào một câu là nói với người dùng rằng họ gõ sai mật khẩu
 *  trong khi máy chủ đang chết. */
type LoaiLoi = "dang_nhap" | "he_thong" | "khong_giu_duoc_phien";

const CAU_LOI: Record<LoaiLoi, string> = {
  dang_nhap: MICROCOPY.loi_dang_nhap,
  he_thong: MICROCOPY.loi_he_thong,
  khong_giu_duoc_phien: MICROCOPY.khong_giu_duoc_phien,
};

/** Màn đăng nhập đứng riêng: không topbar, không sidebar (`KhungApp` trả thẳng
 *  children cho `ROUTE_MO`). Card 400px trên nền app, thương hiệu phía trên,
 *  hai ô, một nút, một dòng lối thoát. Không đăng ký, không quên mật khẩu,
 *  không nhớ đăng nhập (FR-17).
 *
 *  Màn **không** tự điều hướng đi khi kho đã có token: một màn tự đá đi làm
 *  người dùng không đăng nhập lại được bằng tài khoản khác, và khi token đã
 *  hỏng thì nó là một vòng lặp chỉ chặn được bằng một tham số URL.
 *
 *  Mật khẩu không vào state React: hai ô đọc bằng ref lúc gửi, nên không có
 *  bản chép nào của nó sống qua một lần gửi. */
export function ManDangNhap() {
  const router = useRouter();
  const tham_so = useSearchParams();
  const o_tai_khoan = useRef<HTMLInputElement>(null);
  const o_mat_khau = useRef<HTMLInputElement>(null);
  // Chốt chống gửi hai lần nằm ở **ref**, không ở state: hai lần bấm trong cùng
  // một tick đọc cùng một giá trị state cũ nên cả hai đều lọt, còn ref đổi ngay
  // trong lần bấm đầu. State `dang_gui` chỉ để vẽ nút.
  const dang_gui_ref = useRef(false);
  const [dang_gui, dat_dang_gui] = useState(false);
  const [loi, dat_loi] = useState<LoaiLoi | null>(null);
  const [da_gui_lan_dau, dat_da_gui_lan_dau] = useState(false);

  // Thông báo hết phiên là **trung tính**: chữ xám, không icon cảnh báo, không
  // `HopLoi` (EXPERIENCE.md State Patterns, NFR-10). Hộp đỏ là ngôn ngữ của
  // fail-closed; hết phiên trùng ngôn ngữ đó thì hai thứ khác hẳn nhau trông
  // giống nhau trên máy chiếu. Nó biến mất **hẳn** từ lần gửi đầu tiên, không
  // theo `loi === null`: nếu theo `loi` thì nó mọc lại giữa lần gửi thứ hai,
  // vì đầu mỗi lần gửi lỗi cũ bị xóa.
  const hien_het_han =
    !da_gui_lan_dau && tham_so.get(THAM_SO_LY_DO) === LY_DO_HET_HAN;

  /** Kết thúc một lần gửi hỏng: hiện câu chữ và mở khóa nút cho lần thử sau. */
  function dung_lai(loai: LoaiLoi) {
    dat_loi(loai);
    dat_dang_gui(false);
    dang_gui_ref.current = false;
  }

  async function gui(su_kien: FormEvent<HTMLFormElement>) {
    su_kien.preventDefault();
    if (dang_gui_ref.current) return;
    dang_gui_ref.current = true;
    dat_da_gui_lan_dau(true);
    dat_loi(null);
    dat_dang_gui(true);
    try {
      const than = await goi<unknown>(TUYEN_DANG_NHAP, {
        than: {
          [TRUONG_TAI_KHOAN]: o_tai_khoan.current?.value ?? "",
          [TRUONG_MAT_KHAU]: o_mat_khau.current?.value ?? "",
        },
        khong_token: true,
      });
      const token = token_dang_nhap(than);
      if (token === null) {
        // 200 mà không có token dùng được: lỗi hệ thống, không phải đăng nhập
        // thành công và cũng không phải sai mật khẩu.
        dung_lai("he_thong");
        return;
      }
      if (!ghi_token(token)) {
        dung_lai("khong_giu_duoc_phien");
        return;
      }
      // Thành công: **không** mở khóa nút. `router.replace` còn đang bay, và
      // một nút bấm lại được trong khoảng đó là một POST thứ hai.
      router.replace(DUONG_SAU_DANG_NHAP);
      return;
    } catch (that_bai: unknown) {
      // 401 ở **tuyến đăng nhập** kèm mã `DANG_NHAP_SAI` nghĩa là sai tài khoản
      // hoặc mật khẩu, không phải hết phiên: chưa có phiên nào để hết. Một 401
      // hạ tầng (proxy trả thân HTML, mã `MANG`) rơi xuống nhánh hệ thống.
      if (la_sai_thong_tin(that_bai)) {
        // Một thông điệp gộp, không bao giờ nói trường nào sai (chống dò tài
        // khoản, cùng tinh thần với `api/xac_thuc.py`).
        dung_lai("dang_nhap");
        if (o_mat_khau.current) {
          o_mat_khau.current.value = "";
          o_mat_khau.current.focus();
        }
        return;
      }
      dung_lai("he_thong");
    }
  }

  // Chỉ **nút** bị khóa lúc đang gửi, không khóa hai ô: một ô `disabled` mất
  // focus, và nhánh 401 cần trả focus về ô mật khẩu ngay trong lượt đó.
  const sai_o = loi === "dang_nhap";
  const lop_o = sai_o ? "o_nhap o_nhap--loi" : "o_nhap";
  const ta_loi = sai_o ? ID_LOI : undefined;

  return (
    <main className="man_dang_nhap" data-man-dang-nhap>
      <div className="man_dang_nhap__giua">
        <div className="man_dang_nhap__thuong_hieu">
          <div className="man_dang_nhap__ten">{MICROCOPY.thuong_hieu}</div>
          <div className="man_dang_nhap__phu">{MICROCOPY.thuong_hieu_phu}</div>
        </div>

        <form className="the the_dang_nhap" onSubmit={gui} noValidate>
          <h1 className="the_dang_nhap__tieu_de">{MICROCOPY.dang_nhap_tieu_de}</h1>

          {hien_het_han && (
            <p className="thong_bao_phien" role="status" data-thong-bao-phien>
              {MICROCOPY.phien_het_han}
            </p>
          )}

          {loi !== null && (
            <div className="the_dang_nhap__loi" id={ID_LOI} data-loai-loi={loi}>
              <HopLoi>{CAU_LOI[loi]}</HopLoi>
            </div>
          )}

          <div className="the_dang_nhap__truong">
            <label htmlFor="o_tai_khoan">{MICROCOPY.o_tai_khoan}</label>
            <input
              id="o_tai_khoan"
              name={TRUONG_TAI_KHOAN}
              type="text"
              className={lop_o}
              ref={o_tai_khoan}
              autoComplete="username"
              autoFocus
              aria-invalid={sai_o}
              aria-describedby={ta_loi}
            />
          </div>

          <div className="the_dang_nhap__truong">
            <label htmlFor="o_mat_khau">{MICROCOPY.o_mat_khau}</label>
            <input
              id="o_mat_khau"
              name={TRUONG_MAT_KHAU}
              type="password"
              className={lop_o}
              ref={o_mat_khau}
              autoComplete="current-password"
              aria-invalid={sai_o}
              aria-describedby={ta_loi}
            />
          </div>

          <button
            type="submit"
            className="nut_chinh nut_chinh--rong"
            disabled={dang_gui}
            data-nut-dang-nhap
          >
            {dang_gui ? MICROCOPY.dang_gui_dang_nhap : MICROCOPY.nut_dang_nhap}
          </button>

          <p className="the_dang_nhap__loi_thoat">{MICROCOPY.lien_he_quan_tri}</p>
        </form>
      </div>
    </main>
  );
}
