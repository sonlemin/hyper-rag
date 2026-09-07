import { expect, test } from "@playwright/test";

import { type Page } from "@playwright/test";

import {
  chan_moi_api,
  co_token,
  dem_goi_toi,
  duong_anh,
  mock_login,
  mock_toi,
  rong_cuon,
  token_trong_kho,
  TOKEN_CO_SAN,
} from "./ho_tro";

// Màn đăng nhập và vòng đời phiên (story 4.2). Mười ba ca theo I/O Matrix của
// spec (11 hàng, cộng ca lỗi mạng và ca token toàn khoảng trắng). Không lượt
// nào ra máy chủ thật: mọi `/api/**` chưa mock bị chặn ở `beforeEach`, và mỗi
// ca mock đúng tuyến nó cần. Đồ dùng chung ở `ho_tro.ts`.

const TOKEN = "token-jwt-gia";
const ANH_DANG_NHAP = duong_anh("dang-nhap-4-2-1280.png");

test.beforeEach(async ({ page }) => {
  await chan_moi_api(page);
});

async function dien_va_gui(page: Page, ten = "dev01", mat_khau = "mat-khau") {
  await page.locator("#o_tai_khoan").fill(ten);
  await page.locator("#o_mat_khau").fill(mat_khau);
  await page.locator("[data-nut-dang-nhap]").click();
}

test("đăng nhập đúng: ghi token, về /, chip 'dev01 · DevOps'", async ({ page }) => {
  await mock_login(page, { token: TOKEN, token_type: "bearer" });
  await mock_toi(page);
  await page.goto("/dang-nhap");
  await dien_va_gui(page);
  await page.waitForURL((u) => u.pathname === "/");
  expect(await token_trong_kho(page)).toBe(TOKEN);
  await expect(page.locator("[data-chip-vai]")).toHaveText("dev01 · DevOps");
});

test("sai tài khoản hoặc mật khẩu: một thông điệp gộp, hai ô đỏ, mật khẩu trống", async ({
  page,
}) => {
  await mock_login(page, { error: { code: "DANG_NHAP_SAI", message: "x" } }, 401);
  await page.goto("/dang-nhap");
  await dien_va_gui(page, "dev01", "sai-mat-khau");

  const hop = page.locator("[data-hop-loi]");
  await expect(hop).toHaveCount(1);
  await expect(hop).toHaveText(/Sai tài khoản hoặc mật khẩu/);
  // Không bao giờ nói trường nào sai, và không lộ mã lỗi ra màn hình.
  await expect(page.locator("body")).not.toContainText("DANG_NHAP_SAI");
  await expect(page.locator("#o_tai_khoan")).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#o_mat_khau")).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#o_mat_khau")).toHaveValue("");
  await expect(page.locator("#o_tai_khoan")).toHaveValue("dev01");
  await expect(page.locator("#o_mat_khau")).toBeFocused();
  expect(new URL(page.url()).pathname).toBe("/dang-nhap");
  expect(await token_trong_kho(page)).toBeNull();
});

test("API chết lúc đăng nhập (5xx): lỗi hệ thống, không câu 'sai tài khoản'", async ({ page }) => {
  await mock_login(page, { error: { code: "KHO_KHONG_SAN_SANG", message: "x" } }, 503);
  await page.goto("/dang-nhap");
  await dien_va_gui(page);
  await expect(page.locator("[data-loai-loi]")).toHaveAttribute("data-loai-loi", "he_thong");
  await expect(page.locator("[data-hop-loi]")).toContainText("Hệ thống gặp lỗi");
  await expect(page.locator("[data-hop-loi]")).not.toContainText("Sai tài khoản");
  expect(new URL(page.url()).pathname).toBe("/dang-nhap");
});

test("lỗi mạng lúc đăng nhập: lỗi hệ thống, không điều hướng", async ({ page }) => {
  await page.route("**/api/auth/login", (route) => route.abort("connectionrefused"));
  await page.goto("/dang-nhap");
  await dien_va_gui(page);
  await expect(page.locator("[data-loai-loi]")).toHaveAttribute("data-loai-loi", "he_thong");
  expect(new URL(page.url()).pathname).toBe("/dang-nhap");
});

test("thân 200 thiếu token: lỗi hệ thống, không ghi token, không điều hướng", async ({ page }) => {
  await mock_login(page, {});
  await page.goto("/dang-nhap");
  await dien_va_gui(page);
  await expect(page.locator("[data-loai-loi]")).toHaveAttribute("data-loai-loi", "he_thong");
  expect(await token_trong_kho(page)).toBeNull();
  expect(new URL(page.url()).pathname).toBe("/dang-nhap");
});

test("thân 200 mang token toàn khoảng trắng: lỗi hệ thống, không ghi gì vào kho", async ({
  page,
}) => {
  // Nhánh `trim()` của `token_dang_nhap`: ca `{}` chỉ chạm nửa `typeof`, còn
  // một token `"   "` qua được phép kiểm rỗng ngây thơ rồi đi thẳng vào header
  // `Bearer` và làm mọi lời gọi sau đó 401.
  await mock_login(page, { token: "   ", token_type: "bearer" });
  await page.goto("/dang-nhap");
  await dien_va_gui(page);
  await expect(page.locator("[data-loai-loi]")).toHaveAttribute("data-loai-loi", "he_thong");
  expect(await token_trong_kho(page)).toBeNull();
  expect(new URL(page.url()).pathname).toBe("/dang-nhap");
});

test("kho bị chặn: nói phiên không giữ được, ở lại màn", async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.setItem = () => {
      throw new Error("kho bi chan");
    };
  });
  await mock_login(page, { token: TOKEN, token_type: "bearer" });
  await page.goto("/dang-nhap");
  await dien_va_gui(page);
  await expect(page.locator("[data-loai-loi]")).toHaveAttribute(
    "data-loai-loi",
    "khong_giu_duoc_phien",
  );
  await expect(page.locator("[data-hop-loi]")).toContainText("không giữ được phiên");
  expect(new URL(page.url()).pathname).toBe("/dang-nhap");
});

test("phiên hết hạn giữa chừng: về /dang-nhap?ly_do=het_han, thông báo trung tính", async ({
  page,
}) => {
  await co_token(page);
  await mock_toi(page, { error: { code: "TOKEN_KHONG_HOP_LE", message: "x" } }, 401);
  await page.goto("/");
  await page.waitForURL(/\/dang-nhap\?ly_do=het_han/);
  expect(await token_trong_kho(page)).toBeNull();
  await expect(page.locator("[data-thong-bao-phien]")).toContainText(
    "Phiên làm việc đã hết hạn",
  );
  // Hết phiên không phải lỗi hệ thống: không hộp đỏ ở đâu trên màn (NFR-10).
  await expect(page.locator("[data-hop-loi]")).toHaveCount(0);
  await expect(page.locator("[data-man-dang-nhap]")).toBeVisible();
});

test("thiếu quyền (403): ở lại URL cũ, hộp đỏ có mã, token còn nguyên", async ({ page }) => {
  await co_token(page);
  await mock_toi(page, { error: { code: "THIEU_QUYEN_DEMO_ADMIN", message: "x" } }, 403);
  await page.goto("/");
  await expect(page.locator("[data-ma-loi]")).toHaveAttribute(
    "data-ma-loi",
    "THIEU_QUYEN_DEMO_ADMIN",
  );
  expect(new URL(page.url()).pathname).toBe("/");
  expect(await token_trong_kho(page)).toBe(TOKEN_CO_SAN);
});

test("đăng xuất: xóa token, về /dang-nhap không ly_do, không báo hết hạn", async ({ page }) => {
  await co_token(page);
  await mock_toi(page);
  await page.goto("/");
  await expect(page.locator("[data-chip-vai]")).toHaveText("dev01 · DevOps");
  await page.locator("[data-dang-xuat]").click();
  await page.waitForURL((u) => u.pathname === "/dang-nhap");
  expect(new URL(page.url()).search).toBe("");
  expect(await token_trong_kho(page)).toBeNull();
  await expect(page.locator("[data-thong-bao-phien]")).toHaveCount(0);
  await expect(page.locator("[data-man-dang-nhap]")).toBeVisible();
});

test("vào thẳng /dang-nhap khi đã có token: vẫn hiện form, không gọi /auth/toi", async ({
  page,
}) => {
  await co_token(page);
  const so_goi = await dem_goi_toi(page);
  await page.goto("/dang-nhap");
  await expect(page.locator("[data-man-dang-nhap]")).toBeVisible();
  await expect(page.locator("[data-nut-dang-nhap]")).toBeVisible();
  expect(so_goi()).toBe(0);
  expect(new URL(page.url()).pathname).toBe("/dang-nhap");
  expect(await token_trong_kho(page)).toBe(TOKEN_CO_SAN);
});

test("gửi hai lần: đúng một POST, nút disabled mang chữ đang gửi", async ({ page }) => {
  const so_goi = await mock_login(page, { token: TOKEN, token_type: "bearer" }, 200, 800);
  await mock_toi(page);
  await page.goto("/dang-nhap");
  await page.locator("#o_tai_khoan").fill("dev01");
  await page.locator("#o_mat_khau").fill("mat-khau");
  const nut = page.locator("[data-nut-dang-nhap]");
  await nut.click();
  await expect(nut).toBeDisabled();
  await expect(nut).toHaveText("Đang đăng nhập...");
  // `dispatchEvent` bỏ qua phép kiểm khả dụng của Playwright, nên nó thử đúng
  // thứ mà một người dùng sốt ruột làm: bấm lần nữa lúc nút đang khóa.
  await nut.dispatchEvent("click");
  await page.locator("#o_mat_khau").press("Enter");
  await page.waitForURL((u) => u.pathname === "/");
  expect(so_goi()).toBe(1);
});

test("1280px: không cuộn ngang, không topbar, không sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/dang-nhap");
  await expect(page.locator("[data-man-dang-nhap]")).toBeVisible();
  await expect(page.locator("[data-topbar]")).toHaveCount(0);
  await expect(page.getByRole("navigation")).toHaveCount(0);
  const rong = await rong_cuon(page);
  expect(rong).toBeLessThanOrEqual(1280);
  const the = page.locator("[data-man-dang-nhap] form");
  expect(await the.evaluate((e) => e.getBoundingClientRect().width)).toBe(400);
  await page.screenshot({ path: ANH_DANG_NHAP, fullPage: false });
});
