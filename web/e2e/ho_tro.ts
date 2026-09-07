import path from "node:path";

import { type Page } from "@playwright/test";

// Đồ dùng chung của lưới Playwright. Không mang `.spec.` trong tên nên
// `testMatch` mặc định không nhặt nó thành một file test rỗng.
//
// Vì sao tách: hai spec đầu đã chép nhau và đã lệch một chỗ vô cớ (token giả
// mang hai tên khác nhau), và 4.3-4.7 còn thêm spec nữa.

/** Phiên mẫu của `GET /auth/toi`: `dev01`, DevOps, đủ hai cờ demo và admin. */
export const PHIEN = {
  tai_khoan: "dev01",
  vai: "devops",
  khong_gian: "synth",
  demo: true,
  admin: true,
};

/** Token giả đặt sẵn trong kho trước khi trang tải. */
export const TOKEN_CO_SAN = "token-co-san";

/** Thư mục ảnh bằng chứng có commit. */
export function duong_anh(ten: string): string {
  return path.resolve(__dirname, "..", "..", "eval", "anh_bang_chung", ten);
}

/** Chặn **mọi** `/api/**` chưa mock: không lượt nào đi ra máy chủ thật. Route
 *  đăng ký sau thắng route đăng ký trước, nên mock cụ thể của từng ca vẫn ăn. */
export async function chan_moi_api(page: Page) {
  await page.route("**/api/**", (route) => route.abort("connectionrefused"));
}

/** Đặt token **một lần** cho phiên: init script chạy lại ở mỗi lần tải trang,
 *  nên nó phải tự nhận ra đã đặt rồi, nếu không ca 401 (khung xóa token rồi
 *  điều hướng) lại thấy token mọc lên sau lần tải kế. */
export async function co_token(page: Page) {
  await page.addInitScript((token) => {
    if (!sessionStorage.getItem("e2e_da_dat_token")) {
      sessionStorage.setItem("hyper_rag_token", token);
      sessionStorage.setItem("e2e_da_dat_token", "1");
    }
  }, TOKEN_CO_SAN);
}

export async function mock_toi(page: Page, than: unknown = PHIEN, status = 200) {
  await page.route("**/api/auth/toi", (route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(than) }),
  );
}

/** Mock `/auth/toi` và trả về bộ đếm số lần tuyến bị gọi. */
export async function dem_goi_toi(page: Page): Promise<() => number> {
  let so = 0;
  await page.route("**/api/auth/toi", (route) => {
    so += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(PHIEN),
    });
  });
  return () => so;
}

/** Mock `POST /auth/login` và trả về bộ đếm. `cho_ms` giữ phản hồi lại để ca
 *  "gửi hai lần" quan sát được trạng thái đang gửi. */
export async function mock_login(
  page: Page,
  than: unknown,
  status = 200,
  cho_ms = 0,
): Promise<() => number> {
  let so = 0;
  await page.route("**/api/auth/login", async (route) => {
    so += 1;
    if (cho_ms > 0) await new Promise((xong) => setTimeout(xong, cho_ms));
    await route.fulfill({
      status,
      contentType: "application/json",
      body: typeof than === "string" ? than : JSON.stringify(than),
    });
  });
  return () => so;
}

export async function rong_cuon(page: Page): Promise<number> {
  return page.evaluate(() => document.scrollingElement!.scrollWidth);
}

export async function token_trong_kho(page: Page): Promise<string | null> {
  return page.evaluate(() => sessionStorage.getItem("hyper_rag_token"));
}

/** Envelope mẫu của `POST /hoi-dap` (AD-8, năm khóa). `sua` ghi đè từng khóa. */
export function envelope(sua: Record<string, unknown> = {}) {
  return {
    answer: "App01 lỗi 502 vì PHP-FPM hết bộ nhớ.",
    refused: false,
    citations: [],
    graph: { nodes: [], edges: [] },
    meta: { role: "devops", space: "synth", policy_version: "day-du@1" },
    ...sua,
  };
}

/** Một citation sáu khóa đóng (`adapters.trich_dan.KHOA_TRICH_DAN`). 4.3 chỉ
 *  đếm chúng, nhưng mock phải đúng hình để `la_envelope` không đổi cách xử. */
export function trich_dan(id: string) {
  return {
    id,
    level: "L2",
    scope: "noi_bo",
    content_type: "runbook",
    masked_slots: [],
    owner_group: null,
  };
}

/** Mock `POST /hoi-dap` và trả về bộ đếm. `cho_ms` giữ phản hồi lại để ca "đang
 *  chờ" và ca "gửi hai lần" quan sát được trạng thái đang chờ. Cùng khuôn với
 *  `mock_login`. */
export async function mock_hoi_dap(
  page: Page,
  than: unknown,
  status = 200,
  cho_ms = 0,
): Promise<() => number> {
  let so = 0;
  await page.route("**/api/hoi-dap", async (route) => {
    so += 1;
    if (cho_ms > 0) await new Promise((xong) => setTimeout(xong, cho_ms));
    await route.fulfill({
      status,
      contentType: "application/json",
      body: typeof than === "string" ? than : JSON.stringify(than),
    });
  });
  return () => so;
}

/** Thân lỗi chuẩn `{error: {code, message}}` của `api/`. */
export function loi_api(code: string) {
  return { error: { code, message: "loi" } };
}
