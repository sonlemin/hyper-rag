"use client";

import { useId } from "react";

import { ma_hien_thi, type TrichDan } from "@/api/hoi_dap";
import { dien, MICROCOPY } from "@/microcopy";
import { nhan_loai, nhan_scope } from "@/nhan";

import { useHoverDoThi } from "./hover_do_thi";

// Khối nguồn của một lượt trả lời (story 4.4, FR-14/FR-15; hover trích dẫn của
// story 4.6, FR-19).
//
// `web/` **chỉ hiển thị**: server đã lọc và đã che, nên khối này không bỏ, không
// gộp, không sắp lại và không cắt một citation nào, và không suy mức từ
// `masked_slots` - mức đến thẳng từ `level` của chính citation. Story 3.8 đã hạ
// tập citation từ 95 xuống 2 bằng khóa `nguon` của prompt, nhưng nhánh dự phòng
// của nó trả lại cả tập thấy kèm WARNING; một trần phía `web/` là một phép lọc
// thứ hai đứng ngoài cửa quyền, và nó giấu đúng lúc server đang báo động.
//
// Id hyperedge thật không bao giờ vào DOM: tên nguồn là mã hiển thị `HE-nn`
// đánh theo thứ tự citation trong lượt, thứ mà 4.6 dùng lại cho vòng đồ thị.

/** Một hàng nguồn: số vuông, mã hiển thị, scope, nhãn loại, badge mức.
 *
 *  Hàng L1 nghiêng hổ phách và mang thêm câu "còn một phần bị hạn chế, liên hệ
 *  {nhóm}" (EXPERIENCE.md Accessibility Floor: trạng thái che không được dựa
 *  vào màu đơn lẻ, nên nó phải có **chữ** bên cạnh badge). Câu ấy nêu tên nhóm
 *  nên nó chỉ hiện khi citation mang `owner_group`.
 *
 *  **Nối dây với drawer chỉ khi hàng thuộc lượt drawer đang vẽ** (`noi_day`).
 *  Mã `HE-nn` đánh theo thứ tự citation **trong lượt**, nên `HE-01` của một
 *  lượt cũ trỏ vào một citation khác hẳn `HE-01` của lượt drawer đang vẽ; hover
 *  một hàng cũ mà làm sáng một vòng là nói sai về nguồn ngay giữa buổi demo.
 *  Hàng không nối dây giữ nguyên hình dạng của 4.3/4.4: ô số là một `<span>`
 *  `aria-hidden`, không phải một nút bấm được mà không làm gì. */
function CiteRow({
  trich_dan,
  so,
  noi_day,
}: {
  trich_dan: TrichDan;
  so: number;
  noi_day: boolean;
}) {
  const han_che = trich_dan.level === "L1";
  const ma = ma_hien_thi(so);
  const { ma_hover, dat_ma_hover, chon_vong } = useHoverDoThi();
  const dang_sang = noi_day && ma_hover === ma;
  return (
    <div
      className="cite_row"
      data-cite-row
      data-muc={trich_dan.level}
      onMouseEnter={noi_day ? () => dat_ma_hover(ma) : undefined}
      onMouseLeave={noi_day ? () => dat_ma_hover(null) : undefined}
    >
      {noi_day ? (
        <button
          type="button"
          className="cite_row__so"
          data-cite-so={ma}
          onClick={() => chon_vong(ma)}
          onFocus={() => dat_ma_hover(ma)}
          onBlur={() => dat_ma_hover(null)}
          aria-label={ma}
          title={MICROCOPY.nut_do_thi}
        >
          {so + 1}
        </button>
      ) : (
        <span className="cite_row__so" aria-hidden="true">
          {so + 1}
        </span>
      )}
      <span className="cite_row__ma">{ma}</span>
      <span className="cite_row__scope">{nhan_scope(trich_dan.scope)}</span>
      <span className="cite_row__loai">{nhan_loai(trich_dan.content_type)}</span>
      {han_che && trich_dan.owner_group !== null && (
        <span className="cite_row__han_che">
          {dien("placeholder_l1_trich_dan", { nhom: trich_dan.owner_group })}
        </span>
      )}
      {/* Chú thích **chữ** của hover, thứ hai tín hiệu phi màu mà story 4.6
          thêm vào cạnh độ dày viền: `graph-hover` một mình là một chỉ báo yếu
          (2,30:1 trên nền trắng), và Accessibility Floor cấm dựa vào màu đơn
          lẻ. Nó cũng là thứ Playwright đọc được, vì canvas thì không. */}
      {dang_sang && (
        <span className="cite_row__dang_sang" data-dang-sang={ma}>
          {dien("chu_thich_dang_sang", { ma })}
        </span>
      )}
      {/* Nghĩa của badge chỉ nằm trong `title` là nghĩa không tới được bằng
          bàn phím và không tới được trên màn cảm ứng. `aria-label` ghép mức
          với chính câu tooltip (dấu `·` cùng quy ước với chip vai của topbar)
          để trình đọc màn hình đọc trọn nghĩa; nó đè nội dung nên phải mang cả
          mức, nếu không "L1" biến mất khỏi luồng đọc. */}
      <span
        className="badge_muc"
        data-badge-muc
        title={MICROCOPY.tooltip_badge_muc}
        aria-label={`${trich_dan.level} · ${MICROCOPY.tooltip_badge_muc}`}
      >
        {trich_dan.level}
      </span>
    </div>
  );
}

/** Khối nguồn thu gọn được.
 *
 *  Lượt trả lời **mới nhất** mở danh sách, lượt cũ thu gọn thành "Nguồn (n) ▸"
 *  (EXPERIENCE.md Component Patterns); trạng thái mở do người dùng đặt thì giữ
 *  nguyên, nên `mo` là một giá trị do `ManChat` giữ theo từng lượt chứ không
 *  phải state cục bộ ở đây.
 *
 *  Không citation nào thì **không có khối** - không một "Nguồn (0)". Lượt từ
 *  chối đi qua đúng nhánh ấy: `citations` rỗng nên DOM của nó giữ nguyên byte
 *  như story 4.3 (L0 vô hình tuyệt đối). */
export function KhoiNguon({
  citations,
  mo,
  dat_mo,
  id_luot,
}: {
  citations: TrichDan[];
  mo: boolean;
  dat_mo: (mo: boolean) => void;
  /** Id lượt chứa khối này; so với `id_luot_drawer` để biết có nối dây không.
   *  `null` là "không thuộc lượt nào" (trang mẫu `/mau`). */
  id_luot?: number | null;
}) {
  // Id duy nhất cho mỗi khối nguồn trên trang: một `aria-controls` trỏ vào một
  // id trùng nhau giữa các lượt là trỏ vào danh sách của lượt khác. `useId()`
  // sinh id ổn định giữa server và client nên nó không gây lệch hydration.
  const id_ds = useId();
  const { id_luot_drawer } = useHoverDoThi();
  const noi_day =
    id_luot !== undefined && id_luot !== null && id_luot === id_luot_drawer;
  if (citations.length === 0) return null;
  return (
    <div className="khoi_nguon" data-khoi-nguon data-mo={mo ? "1" : "0"}>
      <button
        type="button"
        className="khoi_nguon__nhan"
        aria-expanded={mo}
        aria-controls={id_ds}
        onClick={() => dat_mo(!mo)}
        data-nut-khoi-nguon
      >
        <span>{dien("khoi_nguon", { n: citations.length })}</span>
        <span className="khoi_nguon__caret" aria-hidden="true">
          {mo ? "▾" : "▸"}
        </span>
      </button>
      {mo && (
        <div className="khoi_nguon__ds" id={id_ds}>
          {citations.map((c, i) => (
            <CiteRow key={ma_hien_thi(i)} trich_dan={c} so={i} noi_day={noi_day} />
          ))}
        </div>
      )}
    </div>
  );
}
