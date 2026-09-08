"use client";

import { useEffect, useRef, useState, type PointerEvent as PointerEventReact } from "react";
import { useRouter } from "next/navigation";

import { ids_cua, lay_do_thi } from "@/api/do_thi";
import type { TrichDan } from "@/api/hoi_dap";
import { LoiApi, MA_MANG } from "@/api/goi";
import { duong_het_phien, la_het_phien, nhan_vai, xoa_token } from "@/api/phien";
import { TOKENS } from "@/design/bien_css";
import { HopLoi } from "@/khung/HopLoi";
import { dien, MICROCOPY } from "@/microcopy";

import { dung_khung, type Khung } from "./do_thi_khung";
import { nhom_cua, ThanCoSlab } from "./ThanCoSlab";
import { VungDoThi } from "./VungDoThi";

// Vỏ drawer đồ thị (story 4.6, FR-19). Trượt từ phải trong màn chat: header,
// grip kéo giãn, vùng canvas, legend đáy.
//
// **Một chỗ quyết khi nào gọi lại `/do-thi`**: effect dưới, khóa `[mo, id lượt
// drawer, vai đang xem]`. Lượt mới và đổi vai là hai lý do phải vẽ lại, và cả
// hai đi qua đúng effect ấy - nếu không, drawer đứng lại ở đồ thị của một vai
// khác sau khi người dùng đã đổi vai, đúng thứ EXPERIENCE.md trạng thái C cấm.
//
// **Server lọc lại toàn bộ.** Đổi vai là gọi lại đúng danh sách id ấy chứ
// không lọc lại phía client: `citations` không mang cạnh, không mang entity,
// không mang `masked`, và nó là **tập dùng** của lượt (story 3.8) chứ không
// phải thứ adapter cho phép vẽ (ADR-018).

/** Khoảng cho phép của độ rộng drawer, phần trăm chiều ngang vùng main. */
export const RONG_TOI_THIEU = 28;
export const RONG_TOI_DA = 72;

/** Độ rộng mặc định, đọc thẳng từ `spacing.drawer-width` của token (38%). */
function rong_mac_dinh(): number {
  return Number.parseFloat(TOKENS.spacing["drawer-width"]);
}

/** Lượt mà drawer đang vẽ: lượt mới nhất **có envelope** (trả lời hoặc từ
 *  chối). Xem Design Notes của spec 4.6: dùng lại `id_tra_loi_moi_nhat` của
 *  4.4 (chỉ đếm lượt trả lời) làm nhịp 3 của demo hỏng theo cách tệ nhất -
 *  `sale_ba` bị chặn, chat hiện template từ chối, mà drawer vẫn đứng nguyên đồ
 *  thị của Tech Support ở lượt trước, tức dữ liệu của **một vai khác** còn
 *  trên màn sau khi người dùng đã đổi vai. Lượt từ chối có `citations: []` nên
 *  nó rơi vào đúng nhánh empty-state, không cần một nhánh riêng và không
 *  request nào bay đi. */
export type LuotDrawer = {
  id: number;
  citations: TrichDan[];
};

type TrangThai =
  | { loai: "trong" }
  | { loai: "dang_tai" }
  | { loai: "co"; khung: Khung }
  | { loai: "loi"; ma: string };

export function DrawerDoThi({
  mo,
  dong,
  luot,
  vai,
  ma_sang,
}: {
  mo: boolean;
  dong: () => void;
  luot: LuotDrawer | null;
  /** Vai **đang xem** (vai của phiên), thứ quyết định server lọc thế nào. */
  vai: string;
  /** Mã vòng đang sáng: mã đã chọn, hay mã đang hover. */
  ma_sang: string | null;
}) {
  const router = useRouter();
  const vo = useRef<HTMLElement>(null);
  const [rong, dat_rong] = useState(rong_mac_dinh);
  const [trang_thai, dat] = useState<TrangThai>({ loai: "trong" });
  const thoi_keo = useRef<(() => void) | null>(null);

  const id_luot = luot === null ? null : luot.id;

  useEffect(() => {
    if (!mo) return;
    // Không lượt nào, hay lượt không có nguồn nào: **không request nào bay
    // đi**. Một lượt từ chối và một lượt không hyperedge nào ra cùng một
    // empty-state, cùng một chuỗi - L0 vô hình tuyệt đối, drawer không đếm,
    // không để chỗ trống, không phân biệt "không có" với "không được thấy".
    const cac = luot === null ? [] : luot.citations;
    if (cac.length === 0) {
      dat({ loai: "trong" });
      return;
    }
    let con_song = true;
    dat({ loai: "dang_tai" });
    lay_do_thi(ids_cua(cac))
      .then((than) => {
        if (!con_song) return;
        const khung_moi = dung_khung(than, cac);
        // Không vòng nào vẽ được là **đúng empty-state ấy**, byte giống ca
        // lượt từ chối: EXPERIENCE.md chốt "một empty-state trung tính duy
        // nhất, dùng chung cho mọi lý do trống, không phân biệt được các lý
        // do, chống kênh dò". Một canvas trắng cộng một legend rỗng thì nói
        // được rằng "có gửi id đi mà không nhận về vòng nào", tức phân biệt
        // được "không có" với "không được thấy" - đúng thứ L0 vô hình cấm.
        dat(khung_moi.vong.length === 0 ? { loai: "trong" } : { loai: "co", khung: khung_moi });
      })
      .catch((that_bai: unknown) => {
        if (!con_song) return;
        // Luật phân loại lỗi khai một chỗ (`phien.ts`): 401 là hết phiên và đó
        // là **nhánh duy nhất** của drawer được điều hướng. Mọi mã khác báo tại
        // chỗ bằng hộp đỏ mang `data-ma-loi` và giữ nguyên URL - kể cả một đồ
        // thị sai hình, vì một empty-state cho một lỗi hệ thống là đúng chỗ
        // NFR-10 đòi phân biệt được.
        if (la_het_phien(that_bai)) {
          xoa_token();
          router.replace(duong_het_phien());
          return;
        }
        const l = that_bai instanceof LoiApi ? that_bai : new LoiApi(MA_MANG, 0);
        dat({ loai: "loi", ma: l.code });
      });
    return () => {
      con_song = false;
    };
    // Ba khóa và chỉ ba: mở drawer, đổi lượt, đổi vai. `luot` là một object
    // dựng lại mỗi lần render nên nó không được làm khóa; `id_luot` định danh
    // nó, và một lượt đã có envelope thì envelope ấy không đổi nữa.
  }, [mo, id_luot, vai]);

  // Gỡ listener kéo nếu drawer bị tháo giữa một cú kéo: một `pointermove` treo
  // trên `window` sau khi component biến mất là một handler gọi `dat_rong` của
  // một component đã tháo.
  useEffect(() => {
    return () => {
      if (thoi_keo.current !== null) thoi_keo.current();
    };
  }, []);

  function bat_dau_keo(su_kien: PointerEventReact<HTMLDivElement>) {
    su_kien.preventDefault();
    const cha = vo.current?.parentElement;
    if (!cha) return;
    const hop = cha.getBoundingClientRect();
    function keo(ev: PointerEvent) {
      const phan_tram = ((hop.right - ev.clientX) / hop.width) * 100;
      dat_rong(Math.min(RONG_TOI_DA, Math.max(RONG_TOI_THIEU, phan_tram)));
    }
    function thoi() {
      window.removeEventListener("pointermove", keo);
      window.removeEventListener("pointerup", thoi);
      thoi_keo.current = null;
    }
    thoi_keo.current = thoi;
    window.addEventListener("pointermove", keo);
    window.addEventListener("pointerup", thoi);
  }

  if (!mo) return null;

  const khung = trang_thai.loai === "co" ? trang_thai.khung : null;
  const cac_nhom = nhom_cua(luot === null ? [] : luot.citations);

  return (
    <aside
      className="drawer_do_thi"
      data-drawer-do-thi
      data-trang-thai={trang_thai.loai}
      data-ma-sang={ma_sang ?? undefined}
      ref={vo}
      style={{ width: `${rong}%` }}
    >
      <div
        className="drawer_do_thi__grip"
        data-grip-drawer
        role="separator"
        aria-orientation="vertical"
        aria-label={MICROCOPY.nhan_grip}
        title={MICROCOPY.nhan_grip}
        onPointerDown={bat_dau_keo}
      >
        <i />
        <i />
        <i />
      </div>
      <div className="drawer_do_thi__than">
        <div className="graph_head">
          <b>{MICROCOPY.tieu_de_do_thi}</b>
          {/* Chip nói vai **đang xem**, tức vai mà server vừa lọc theo. Nó
              không bao giờ mang Lx (DESIGN.md Do's and Don'ts): mức là thuộc
              tính của cặp (vai, nội dung), không của vai. */}
          <span className="graph_head__chip" data-chip-vai-do-thi>
            {dien("chip_vai_dang_xem", { vai: nhan_vai(vai) })}
          </span>
          <button
            type="button"
            className="graph_head__dong"
            onClick={dong}
            aria-label={MICROCOPY.dong}
            title={MICROCOPY.dong}
            data-dong-drawer
          >
            ✕
          </button>
        </div>

        {trang_thai.loai === "dang_tai" && <p data-dang-tai>{MICROCOPY.dang_tai}</p>}

        {trang_thai.loai === "trong" && (
          <p className="drawer_do_thi__trong" data-do-thi-trong>
            {MICROCOPY.do_thi_trong}
          </p>
        )}

        {trang_thai.loai === "loi" && (
          <div className="drawer_do_thi__loi" data-ma-loi={trang_thai.ma}>
            <HopLoi>{MICROCOPY.loi_he_thong}</HopLoi>
          </div>
        )}

        {khung !== null && <VungDoThi khung={khung} ma_sang={ma_sang} />}

        {khung !== null && (
          <div className="legend" data-legend-do-thi>
            {/* Legend là chỗ `label` đầy đủ của một vòng đọc được: `cau_fact`
                dài ("chủ thể: App01; nguyên nhân: [cause:masked]") nên nó
                không nhét vừa một vòng tròn, và canvas thì không cho ai đọc
                chữ bên trong nó. */}
            {khung.vong.map((v) => (
              <span className="legend__vong" key={v.ma} data-legend-vong={v.ma}>
                <i
                  className="legend__o"
                  style={{ borderColor: `var(--mau-graph-ring-${v.mau})` }}
                  aria-hidden="true"
                />
                <b>{v.ma}</b>
                {/* `label` là `cau_fact` dựng từ giá trị **đã che**, nên nó
                    mang dấu che của server. Cùng luật hiển thị với `answer`
                    của 4.4: dấu che thành slab bôi đen, mọi chuỗi khác nguyên
                    văn. Một `[cause:masked]` trần giữa legend là chữ của ngữ
                    cảnh LLM lọt lên máy chiếu. */}
                <span className="legend__label">
                  <ThanCoSlab van_ban={v.label} cac_nhom={cac_nhom} />
                </span>
              </span>
            ))}
            <span className="legend__chu_thich">{MICROCOPY.chu_thich_do_thi}</span>
          </div>
        )}
      </div>
    </aside>
  );
}
