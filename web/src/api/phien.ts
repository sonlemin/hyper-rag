// Phiên phía trình duyệt: token JWT ở `sessionStorage` (không kho bền nào khác,
// phiên chết khi đóng tab), cộng nhãn tiếng Việt của vai người dùng.

export const KHOA_TOKEN = "hyper_rag_token";

/** Thân của `GET /auth/toi` (api/main.py). */
export type Phien = {
  tai_khoan: string;
  vai: string;
  khong_gian: string;
  demo: boolean;
  admin: boolean;
};

/** Thân trả về có đúng hình phiên không: `tai_khoan` và `vai` phải là chuỗi.
 *  Một thân lạ (proxy trả HTML, envelope khác) không được thành chip
 *  `undefined · undefined`; caller coi nó là lỗi hệ thống. */
export function la_phien(than: unknown): than is Phien {
  if (typeof than !== "object" || than === null) return false;
  const t = than as Record<string, unknown>;
  return typeof t.tai_khoan === "string" && typeof t.vai === "string";
}

function kho(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function doc_token(): string | null {
  try {
    return kho()?.getItem(KHOA_TOKEN) ?? null;
  } catch {
    return null;
  }
}

/** Ghi token; trả `false` khi kho bị chặn (chế độ riêng tư, quota), để màn
 *  đăng nhập nói được là phiên không giữ được thay vì lặng lẽ mất. */
export function ghi_token(token: string): boolean {
  try {
    const k = kho();
    if (!k) return false;
    k.setItem(KHOA_TOKEN, token);
    return true;
  } catch {
    return false;
  }
}

export function xoa_token(): void {
  try {
    kho()?.removeItem(KHOA_TOKEN);
  } catch {
    /* kho bị chặn: không có gì để xóa */
  }
}

// Nhãn tiếng Việt của vai người dùng (5 vai PRD 1.5). Khóa lạ hiện nguyên khóa:
// một nhãn đoán là một chỗ để UI nói khác với token.
const NHAN_VAI: Record<string, string> = {
  devops: "DevOps",
  tech_support: "Tech Support",
  sale_ba: "Sale/BA",
  truong_nhom: "Trưởng nhóm",
  admin: "Admin",
};

export function nhan_vai(vai: string): string {
  return NHAN_VAI[vai] ?? vai;
}

/** Nội dung chip vai trên topbar: "Tên · Vai". Không bao giờ gắn Lx. */
export function chip_vai(phien: Phien): string {
  return `${phien.tai_khoan} · ${nhan_vai(phien.vai)}`;
}
