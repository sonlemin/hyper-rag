"use client";

import { type TrichDan } from "@/api/hoi_dap";
import { dien, MICROCOPY } from "@/microcopy";
import { nhan_slot, VAI_SLOT } from "@/nhan";

import { VAI_OWNER } from "./dau_che";

// Dòng hạn chế L1 dưới một lượt trả lời (story 4.4, FR-14/FR-20).
//
// Đây là **điểm xin break-glass duy nhất** (EXPERIENCE.md: nội dung L0 vô hình
// nên không có kênh xin), nên nút phải có mặt từ story này dù nó còn khóa; Epic
// 5 chỉ bật nó lên. Nút **không gọi tuyến nào** hôm nay.

/** Hai thứ mà dòng hạn chế nói: những vai bị che và những nhóm phải liên hệ. */
export type TomTatHanChe = {
  /** Vai bị che, hợp lại, **trừ `owner`**, theo thứ tự danh mục 8 vai. */
  cac_vai: string[];
  /** Nhóm phụ trách **duy nhất theo thứ tự xuất hiện** trong `citations`. */
  cac_nhom: string[];
};

/** Gom hạn chế của một lượt từ chính `citations` mà server trả về.
 *
 *  Chỉ đọc citation **L1 có `owner_group`**, và hai điều kiện ấy đi cùng nhau
 *  trên **một** citation chứ không phải hai lượt gom độc lập. Câu ra là "Còn n
 *  phần bị hạn chế (...) - liên hệ nhóm X", tức nó khẳng định nhóm X giữ đúng
 *  những vai vừa liệt kê. Gom rời thì một citation che `cause` mà không khai
 *  nhóm, đứng cạnh một citation L1 khác chỉ che `owner` của nhóm DevOps, ra
 *  "Còn 1 phần bị hạn chế (nguyên nhân) - liên hệ nhóm DevOps": bảo người dùng
 *  đi hỏi một nhóm không giữ vai bị che đó, và ở một sản phẩm break-glass thì
 *  đó là gửi một yêu cầu tới sai người.
 *
 *  `owner` bị bỏ khỏi phép đếm: `masked_slots` ở L2 cũng mang nó
 *  (`vai_phai_che_hieu_luc` luôn thêm `owner`, AD-9), nên đếm cả `owner` là nói
 *  "người phụ trách bị hạn chế" trong đúng câu vừa nêu tên nhóm phụ trách. Hệ
 *  quả: một citation L1 chỉ che `owner` **không sinh dòng nào** - đúng, vì bảng
 *  chính sách không che gì thêm ở đó.
 *
 *  Bỏ qua citation L2: một hyperedge L2 đọc đầy đủ, phần `owner` bị tổng quát
 *  hóa của nó không phải một hạn chế để xin break-glass. */
export function tom_tat_han_che(citations: TrichDan[]): TomTatHanChe {
  const vai = new Set<string>();
  const cac_nhom: string[] = [];
  for (const c of citations) {
    if (c.level !== "L1" || c.owner_group === null) continue;
    for (const v of c.masked_slots) {
      if (v !== VAI_OWNER) vai.add(v);
    }
    if (!cac_nhom.includes(c.owner_group)) cac_nhom.push(c.owner_group);
  }
  return { cac_vai: VAI_SLOT.filter((v) => vai.has(v)), cac_nhom };
}

/** Ổ khóa của dòng hạn chế, vẽ bằng SVG chứ không bằng emoji.
 *
 *  EXPERIENCE.md cho phép icon 🔒 trong note, nhưng glyph ấy chỉ có ở font
 *  emoji: image `node:20-alpine` của service `web` không cài font nào như thế
 *  và máy chiếu của hội đồng cũng không chắc có, nên nó ra một ô vuông trắng -
 *  tệ hơn là không có icon. `currentColor` để nó đi theo màu hổ phách của dòng,
 *  `aria-hidden` vì chữ ngay cạnh đã nói trọn nghĩa. */
function IconKhoa() {
  return (
    <svg
      className="note_l1__icon"
      viewBox="0 0 16 16"
      width="14"
      height="14"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M4.5 7V5a3.5 3.5 0 1 1 7 0v2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <rect x="2.75" y="7" width="10.5" height="7" rx="1.2" fill="currentColor" />
    </svg>
  );
}

/** Dòng note-l1 kèm nút xin truy cập khẩn cấp, hay `null` khi không có gì để nói.
 *
 *  Không dòng nào khi không citation L1 **nào vừa khai nhóm vừa che một vai
 *  ngoài `owner`**. Hai vế ấy là hai vế của cùng một điều kiện trên một
 *  citation (xem `tom_tat_han_che`), nên hai nhánh dưới đây chỉ là hai cách
 *  tập gom ra rỗng.
 *
 *  Vì sao vắng nhóm là vắng cả dòng chứ không phải một dòng cụt: câu chữ kết
 *  bằng "liên hệ nhóm X", và một câu kết bằng khoảng trắng nói ít hơn là không
 *  nói. Phần "cái gì bị che" thì slab trong chính câu trả lời đã nói ở đúng vị
 *  trí và không phụ thuộc nhóm. `owner_group` là `null` chỉ khi
 *  `config/nhom-phu-trach.yaml` chưa khai loại nội dung ấy - một lỗ cấu hình
 *  phải vá ở cấu hình, không phải ở một chuỗi UI. */
export function DongHanChe({ citations }: { citations: TrichDan[] }) {
  const { cac_vai, cac_nhom } = tom_tat_han_che(citations);
  if (cac_vai.length === 0 || cac_nhom.length === 0) return null;
  return (
    <div className="note_l1" data-han-che>
      <IconKhoa />
      <span className="note_l1__chu">
        {dien("dong_han_che_l1", {
          n: cac_vai.length,
          cac_slot: cac_vai.map(nhan_slot).join(", "),
          nhom: cac_nhom.join(", "),
        })}
      </span>
      {/* Nút giữ `disabled` (epic 4 chốt: Epic 5 chỉ bật lên), nhưng một nút
          `disabled` **không focus được**, nên `title` của nó không tới được
          bằng bàn phím và không tới được trên màn cảm ứng. Câu ấy vì vậy còn
          một bản đọc được không cần hover, đặt cạnh nút trong luồng đọc. Cùng
          lý lẽ đã đặt chữ "còn một phần bị hạn chế" cạnh badge L1 của cite-row:
          nghĩa của một điều khiển không được sống trong một tooltip. */}
      <button
        type="button"
        className="nut_break_glass"
        disabled
        title={MICROCOPY.tooltip_chua_kha_dung}
        data-nut-xin-truy-cap
      >
        {MICROCOPY.nut_xin_truy_cap}
      </button>
      <span className="sr-only" data-ghi-chu-nut>
        {MICROCOPY.tooltip_chua_kha_dung}
      </span>
    </div>
  );
}
