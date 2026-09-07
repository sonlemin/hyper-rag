// Hệ token thiết kế: một nguồn là `tokens.json` (bản chép của frontmatter
// DESIGN.md, `tests/test_web_khung.py` canh từng giá trị). File này chỉ có hàm
// thuần: đổi token thành CSS variables lúc build và phân giải tham chiếu
// `{colors.x}` của khối `components`. Không có file CSS token viết tay thứ hai.

import tokens from "./tokens.json";

export type Tokens = typeof tokens;
export const TOKENS: Tokens = tokens;

// Tiền tố biến CSS theo khối: `colors.primary-deep` -> `--mau-primary-deep`,
// `typography.base.fontSize` -> `--chu-base-co`, `rounded.md` -> `--bo-md`,
// `spacing.topbar-height` -> `--khoang-topbar-height`. `components` không thành
// biến: mỗi component đọc thẳng token qua `phan_giai`.
const TIEN_TO: Record<string, string> = {
  colors: "mau",
  rounded: "bo",
  spacing: "khoang",
};

// Thuộc tính chữ đổi sang hậu tố tiếng Việt, cùng quy ước tên với phần Python.
const HAU_TO_CHU: Record<string, string> = {
  fontFamily: "font",
  fontSize: "co",
  lineHeight: "cao-dong",
  fontWeight: "dam",
  letterSpacing: "gian-chu",
};

type CayToken = Record<string, unknown>;

/** Phân giải một tham chiếu `{khoi.khoa}` thành giá trị token; chuỗi không có
 *  tham chiếu trả nguyên. Tham chiếu tới khóa không tồn tại là lỗi lúc render,
 *  không phải một chuỗi rỗng lặng lẽ. */
export function phan_giai(gia_tri: string, cay: CayToken = TOKENS): string {
  return gia_tri.replace(/\{(\w+)\.([\w-]+)\}/g, (_, khoi: string, khoa: string) => {
    const nhom = cay[khoi] as Record<string, unknown> | undefined;
    const ket_qua = nhom?.[khoa];
    if (typeof ket_qua !== "string") {
      throw new Error(`token không có ${khoi}.${khoa}`);
    }
    return ket_qua;
  });
}

/** Mọi cặp `--ten: gia_tri` sinh từ ba khối phẳng và khối typography. */
export function cac_bien_css(cay: Tokens = TOKENS): Array<[string, string]> {
  const ra: Array<[string, string]> = [];
  for (const [khoi, tien_to] of Object.entries(TIEN_TO)) {
    const nhom = cay[khoi as keyof Tokens] as Record<string, string>;
    for (const [khoa, gia_tri] of Object.entries(nhom)) {
      ra.push([`--${tien_to}-${khoa}`, gia_tri]);
    }
  }
  for (const [ten, muc] of Object.entries(cay.typography)) {
    for (const [thuoc_tinh, gia_tri] of Object.entries(muc as Record<string, string>)) {
      const hau_to = HAU_TO_CHU[thuoc_tinh];
      if (!hau_to) throw new Error(`typography.${ten}.${thuoc_tinh} chưa có tên biến`);
      ra.push([`--chu-${ten}-${hau_to}`, gia_tri]);
    }
  }
  return ra;
}

/** Khối `:root { ... }` chèn vào `<style>` của root layout (server component). */
export function bien_css(cay: Tokens = TOKENS): string {
  const dong = cac_bien_css(cay).map(([ten, gia_tri]) => `  ${ten}: ${gia_tri};`);
  return `:root {\n${dong.join("\n")}\n}\n`;
}

/** Bộ thuộc tính đã phân giải của một component trong `tokens.components`. */
export function component(ten: keyof Tokens["components"]): Record<string, string> {
  const muc = TOKENS.components[ten] as Record<string, string>;
  const ra: Record<string, string> = {};
  for (const [k, v] of Object.entries(muc)) ra[k] = phan_giai(v);
  return ra;
}
