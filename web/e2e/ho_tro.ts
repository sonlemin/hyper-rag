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
