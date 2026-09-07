import { expect, test } from "@playwright/test";

import {
  chan_moi_api,
  co_token,
  dem_goi_toi,
  duong_anh,
  mock_toi,
  PHIEN,
  rong_cuon,
} from "./ho_tro";

// Bài smoke khung app (story 4.1). `/api/auth/toi` mock bằng `page.route`,
// token đặt vào sessionStorage trước khi trang tải. Đồ dùng chung ở `ho_tro.ts`.
// Ảnh chụp 1280px lưu vào `eval/anh_bang_chung/khung-4-1-1280.png` (có commit).

const ANH_KHUNG = duong_anh("khung-4-1-1280.png");

test.beforeEach(async ({ page }) => {
  await chan_moi_api(page);
});

test("có token: chip 'dev01 · DevOps', topbar 52px, khung render", async ({ page }) => {
  await co_token(page);
  await mock_toi(page);
  await page.goto("/");
  await expect(page.locator("[data-chip-vai]")).toHaveText("dev01 · DevOps");
  const cao = await page.locator("[data-topbar]").evaluate((e) => e.getBoundingClientRect().height);
  expect(cao).toBe(52);
  await expect(page.getByRole("heading", { name: "Hỏi đáp" })).toBeVisible();
  await expect(page.locator("[data-chip-vai]")).not.toContainText(/L[012]/);
  await page.screenshot({ path: ANH_KHUNG, fullPage: false });
});

test("vai lạ hiện nguyên khóa", async ({ page }) => {
  await co_token(page);
  await mock_toi(page, { ...PHIEN, tai_khoan: "x", vai: "truong_nhom_moi" });
  await page.goto("/");
  await expect(page.locator("[data-chip-vai]")).toHaveText("x · truong_nhom_moi");
});

test("không token: chip trống, 'Đăng nhập để bắt đầu', không gọi /auth/toi", async ({ page }) => {
  const so_goi = await dem_goi_toi(page);
  await page.goto("/");
  await expect(page.locator("[data-dang-nhap-de-bat-dau]")).toContainText("Đăng nhập để bắt đầu");
  await expect(page.locator("[data-dang-nhap-de-bat-dau] a")).toHaveAttribute("href", "/dang-nhap");
  await expect(page.locator("[data-chip-vai]")).toHaveText("");
  expect(so_goi()).toBe(0);
});

// Story 4.2 đổi hợp đồng của route mở: từ "bọc khung với chip trống" thành
// **render trần**. Màn đăng nhập là màn đứng riêng, không topbar không sidebar.
test("route mở /dang-nhap: không gate, không gọi /auth/toi, không khung", async ({ page }) => {
  const so_goi = await dem_goi_toi(page);
  await page.goto("/dang-nhap");
  await expect(page.locator("[data-man-dang-nhap]")).toBeVisible();
  await expect(page.locator("[data-topbar]")).toHaveCount(0);
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await expect(page.locator("[data-dang-nhap-de-bat-dau]")).toHaveCount(0);
  expect(so_goi()).toBe(0);
});

test("token hết hạn (401): xóa token, về /dang-nhap?ly_do=het_han, không hộp đỏ", async ({ page }) => {
  await co_token(page);
  await mock_toi(page, { error: { code: "TOKEN_KHONG_HOP_LE", message: "x" } }, 401);
  await page.goto("/");
  await page.waitForURL(/\/dang-nhap\?ly_do=het_han/);
  expect(await page.evaluate(() => sessionStorage.getItem("hyper_rag_token"))).toBeNull();
  await expect(page.locator("[data-hop-loi]")).toHaveCount(0);
});

test("API chết (5xx): hộp đỏ trong thân, chip trống, không về đăng nhập", async ({ page }) => {
  await co_token(page);
  await mock_toi(page, { error: { code: "KHO_KHONG_SAN_SANG", message: "x" } }, 503);
  await page.goto("/");
  await expect(page.locator("[data-hop-loi]")).toContainText("Hệ thống gặp lỗi");
  await expect(page.locator("[data-ma-loi]")).toHaveAttribute("data-ma-loi", "KHO_KHONG_SAN_SANG");
  await expect(page.locator("[data-chip-vai]")).toHaveText("");
  await expect(page.locator("[data-dang-xuat]")).toHaveCount(0);
  // Ngõ cụt phải có lối ra: token còn nguyên nên tải lại vẫn rơi vào đây, và
  // nút thoát thì ẩn. Một liên kết, không tự điều hướng.
  await expect(page.getByRole("link", { name: "Về màn đăng nhập" })).toBeVisible();
  expect(page.url()).not.toContain("/dang-nhap");
});

test("lỗi mạng: hộp đỏ mã MANG", async ({ page }) => {
  await co_token(page);
  await page.route("**/api/auth/toi", (route) => route.abort("connectionrefused"));
  await page.goto("/");
  await expect(page.locator("[data-hop-loi]")).toBeVisible();
  await expect(page.locator("[data-ma-loi]")).toHaveAttribute("data-ma-loi", "MANG");
  await expect(page.locator("[data-chip-vai]")).toHaveText("");
});

test("200 mà thân là HTML: hộp đỏ, không chip", async ({ page }) => {
  await co_token(page);
  await page.route("**/api/auth/toi", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<html><body>proxy</body></html>" }),
  );
  await page.goto("/");
  await expect(page.locator("[data-ma-loi]")).toHaveAttribute("data-ma-loi", "MANG");
  await expect(page.locator("[data-chip-vai]")).toHaveText("");
});

test("200 mà thân JSON thiếu tai_khoan/vai: hộp đỏ, không chip 'undefined · undefined'", async ({ page }) => {
  await co_token(page);
  await mock_toi(page, { khong_gian: "synth", vai: 7 });
  await page.goto("/");
  await expect(page.locator("[data-ma-loi]")).toHaveAttribute("data-ma-loi", "MANG");
  await expect(page.locator("[data-chip-vai]")).toHaveText("");
});

test("sidebar: thu gọn về 52px và nhớ sau reload", async ({ page }) => {
  await co_token(page);
  await mock_toi(page);
  await page.goto("/");
  const sidebar = page.getByRole("navigation", { name: "Điều hướng chính" });
  expect(await sidebar.evaluate((e) => e.getBoundingClientRect().width)).toBe(216);
  await page.getByRole("button", { name: "Thu gọn" }).click();
  await expect(sidebar).toHaveAttribute("data-sidebar", "mini");
  expect(await sidebar.evaluate((e) => e.getBoundingClientRect().width)).toBe(52);
  await page.reload();
  await expect(sidebar).toHaveAttribute("data-sidebar", "mini");
  expect(await sidebar.evaluate((e) => e.getBoundingClientRect().width)).toBe(52);
  await page.getByRole("button", { name: "Mở rộng" }).click();
  await expect(sidebar).toHaveAttribute("data-sidebar", "mo");
});

test("1280px không cuộn ngang: / ở cả hai trạng thái sidebar, và /mau", async ({ page }) => {
  await co_token(page);
  await mock_toi(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.locator("[data-chip-vai]")).toHaveText("dev01 · DevOps");
  expect(await rong_cuon(page)).toBeLessThanOrEqual(1280);
  await page.getByRole("button", { name: "Thu gọn" }).click();
  await expect(page.getByRole("navigation")).toHaveAttribute("data-sidebar", "mini");
  expect(await rong_cuon(page)).toBeLessThanOrEqual(1280);
  await page.goto("/mau");
  await expect(page.locator("[data-o-hoi]")).toBeVisible();
  expect(await rong_cuon(page)).toBeLessThanOrEqual(1280);
});

test("Ctrl+K focus ô hỏi, nhưng không khi modal đang mở", async ({ page }) => {
  await co_token(page);
  await mock_toi(page);
  await page.goto("/mau");
  await expect(page.locator("[data-o-hoi]")).toBeVisible();
  await page.keyboard.press("Control+k");
  await expect(page.locator("[data-o-hoi]")).toBeFocused();
  await page.locator("[data-mo-hop-thoai]").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Control+k");
  await expect(page.locator("[data-o-hoi]")).not.toBeFocused();
  await page.keyboard.press("Escape");
});

test("modal trên trang mẫu: rộng 560px, Esc đóng, focus về nút mở", async ({ page }) => {
  await co_token(page);
  await mock_toi(page);
  await page.goto("/mau");
  const nut = page.locator("[data-mo-hop-thoai]");
  await nut.click();
  const hop = page.getByRole("dialog");
  await expect(hop).toBeVisible();
  expect(await hop.evaluate((e) => e.getBoundingClientRect().width)).toBe(560);
  await page.keyboard.press("Escape");
  await expect(hop).toHaveCount(0);
  await expect(nut).toBeFocused();
});

test("modal: re-render giữa chừng rồi Esc, focus vẫn về nút mở", async ({ page }) => {
  await co_token(page);
  await mock_toi(page);
  await page.goto("/mau");
  const nut = page.locator("[data-mo-hop-thoai]");
  await nut.click();
  const dem = page.locator("[data-dem]");
  await dem.click();
  await dem.click();
  await expect(dem).toHaveText("Đếm 2");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(nut).toBeFocused();
});

test("modal: Tab và Shift+Tab quay vòng trong hộp", async ({ page }) => {
  await co_token(page);
  await mock_toi(page);
  await page.goto("/mau");
  await page.locator("[data-mo-hop-thoai]").click();
  const hop = page.getByRole("dialog");
  const nut_dong_x = hop.getByRole("button", { name: "Đóng" }).first();
  const nut_cuoi = hop.locator(".hop_thoai__chan button");
  await expect(nut_dong_x).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(nut_cuoi).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(nut_dong_x).toBeFocused();
  // Ba lần Tab: ✕ -> Đếm -> Đóng (chân) -> quay về ✕
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(nut_dong_x).toBeFocused();
  await page.keyboard.press("Escape");
});

test("trang mẫu in tỷ lệ tương phản, không cặp nào dưới sàn", async ({ page }) => {
  await co_token(page);
  await mock_toi(page);
  await page.goto("/mau");
  const cac = page.locator("[data-cap-tuong-phan]");
  await expect(cac).toHaveCount(9);
  for (const dong of await cac.allTextContents()) expect(dong).toContain("đạt");
});

test("/mau: không admin thì 404 của Next, admin thì thấy bộ mẫu", async ({ page }) => {
  await co_token(page);
  await mock_toi(page, { ...PHIEN, admin: false });
  await page.goto("/mau");
  await expect(page.locator("[data-bo-mau]")).toHaveCount(0);
  await expect(page.getByText("404")).toBeVisible();
  await mock_toi(page);
  await page.goto("/mau");
  await expect(page.locator("[data-bo-mau]")).toBeVisible();
});

test("/api/health thật qua rewrite (cần API_NOI_BO trỏ máy chủ)", async ({ page }) => {
  test.skip(!process.env.API_NOI_BO, "đặt API_NOI_BO=http://<máy chủ>:8000 trước `npm run test:e2e` để ca này chạy");
  await page.unroute("**/api/**");
  const phan_hoi = await page.request.get("/api/health");
  expect(phan_hoi.status()).toBe(200);
  expect(await phan_hoi.json()).toEqual({ status: "ok" });
});
