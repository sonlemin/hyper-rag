"use client";

import { dien } from "@/microcopy";
import { nhan_slot } from "@/nhan";

import { tach_slab } from "./dau_che";

/** Một đoạn văn bản của server với dấu che thay bằng slab bôi đen, ngay tại vị
 *  trí của nó (story 4.4, FR-15; dùng lại ở legend drawer của 4.6).
 *
 *  Slab là **hiển thị best-effort** trên văn bản do LLM hay `cau_fact` sinh
 *  (chốt brief §6: không test an ninh nào trên `answer`), nên một chuỗi không
 *  nhận ra là chữ thường và giữ nguyên văn. Tập nhóm để nhận diện
 *  `[owner:<nhóm>]` lấy từ `owner_group` của **chính lượt đang hiện**, đúng
 *  khuôn `core.masking.la_dau_che` - dựng lại tập chuỗi hợp lệ rồi khớp trọn,
 *  không một regex tự do (nó nuốt mất một tên entity thật bắt đầu bằng
 *  `[owner:`).
 *
 *  `[owner:<nhóm>]` render **giữ tên nhóm** ("[người phụ trách: DevOps]") còn
 *  `[owner:group]` render "[người phụ trách: che]": AD-9 tổng quát hóa `owner`
 *  về mức nhóm chứ không xóa nó, và FR-14 đòi placeholder nói được nhóm nào.
 *  Bôi tên nhóm thành "che" là vứt đi đúng thứ server cố ý cho ra.
 *
 *  Ở file riêng chứ không trong `ManChat.tsx`: từ story 4.6 legend của drawer
 *  hiện `label` của node hyperedge, tức `core.facts.cau_fact` dựng từ giá trị
 *  **đã che** - cùng bốn họ dấu che, cùng luật hiển thị. Hai bản chép của luật
 *  ấy là hai bản lệch nhau ở lần sửa đầu, và `ManChat` đã nhập `DrawerDoThi`
 *  nên một `export` ở đó là một vòng nhập giữa hai module React. */
/** Chữ của một mảnh dấu che, đúng thứ `ThanCoSlab` render ra. */
function chu_cua_slab(manh: { vai: string; nhom: string | null }): string {
  return manh.nhom === null
    ? dien("slab_che", { ten_slot: nhan_slot(manh.vai) })
    : dien("slab_owner", { ten_slot: nhan_slot(manh.vai), nhom: manh.nhom });
}

/** Cùng một đoạn văn bản, nhưng **thành chuỗi thuần**: dấu che đã thay bằng
 *  chữ của slab, mọi chuỗi khác nguyên văn.
 *
 *  Dùng cho `title` của legend drawer, chỗ CSS cắt cụt hàng bằng
 *  `text-overflow: ellipsis`. Phải đi qua đúng phép thay của `ThanCoSlab`, chứ
 *  không phải `label` thô: một `title="...[cause:masked]"` là dấu che của ngữ
 *  cảnh LLM lọt lên màn qua một cửa sau, ngược đúng câu `Always` của spec 4.6
 *  ("nhãn `[cause:masked]` mà server trả về **không** vào màn"). */
export function van_ban_co_slab(van_ban: string, cac_nhom: string[]): string {
  return tach_slab(van_ban, cac_nhom)
    .map((manh) => (manh.loai === "chu" ? manh.van_ban : chu_cua_slab(manh)))
    .join("");
}

export function ThanCoSlab({
  van_ban,
  cac_nhom,
}: {
  van_ban: string;
  /** Tên các nhóm phụ trách có mặt trong lượt, để nhận diện `[owner:<nhóm>]`. */
  cac_nhom: string[];
}) {
  return (
    <>
      {tach_slab(van_ban, cac_nhom).map((manh, i) =>
        manh.loai === "chu" ? (
          <span key={i}>{manh.van_ban}</span>
        ) : (
          <span key={i} className="slab" data-slab={manh.vai}>
            {chu_cua_slab(manh)}
          </span>
        ),
      )}
    </>
  );
}

/** Tên nhóm phụ trách có mặt trong một lượt, khử `null`. */
export function nhom_cua(citations: { owner_group: string | null }[]): string[] {
  return citations.map((c) => c.owner_group).filter((n): n is string => n !== null);
}
