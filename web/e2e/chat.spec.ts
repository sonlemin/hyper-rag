import { expect, test } from "@playwright/test";

import {
  CAU_HOI,
  chan_moi_api,
  co_token,
  duong_anh,
  envelope,
  hoi_bang_nut,
  loi_api,
  mock_hoi_dap,
  mock_toi,
  rong_cuon,
  token_trong_kho,
  TOKEN_CO_SAN,
  trich_dan,
  vao_chat,
} from "./ho_tro";

// Chat console và bốn nấc của một lượt (story 4.3). Mười lăm ca theo đúng 15
// hàng I/O Matrix của spec. Không lượt nào ra máy chủ thật: mọi `/api/**` chưa
// mock bị chặn ở `beforeEach`, và mỗi ca mock đúng tuyến nó cần.

const ANH_CHAT = duong_anh("chat-4-3-1280.png");

test.beforeEach(async ({ page }) => {
  await chan_moi_api(page);
  await co_token(page);
  await mock_toi(page);
});

test("màn trống lần đầu: chỉ composer, không lượt nào, không màn chào", async ({ page }) => {
  await vao_chat(page);
  await expect(page.locator("[data-luot]")).toHaveCount(0);
  await expect(page.locator("[data-o-hoi]")).toBeVisible();
  await expect(page.locator("[data-o-hoi]")).toHaveAttribute(
    "placeholder",
    "Đặt câu hỏi về kho tri thức IT...",
  );
  await expect(page.locator("[data-nut-gui]")).toBeEnabled();
});

test("Enter gửi: đúng một POST thân {cau_hoi}, ô hỏi trống lại", async ({ page }) => {
  const than: string[] = [];
  const bearer: string[] = [];
  await page.route("**/api/hoi-dap", async (route) => {
    than.push(route.request().postData() ?? "");
    bearer.push(route.request().headers()["authorization"] ?? "");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(envelope()),
    });
  });
  await vao_chat(page);
  await page.locator("[data-o-hoi]").fill(CAU_HOI);
  await page.locator("[data-o-hoi]").press("Enter");
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  expect(than).toEqual([JSON.stringify({ cau_hoi: CAU_HOI })]);
  // Mock trọn tuyến nên nó xanh kể cả khi Bearer không được gắn; đây là chỗ duy
  // nhất chấm rằng token thật đi kèm request.
  expect(bearer).toEqual([`Bearer ${TOKEN_CO_SAN}`]);
  await expect(page.locator("[data-o-hoi]")).toHaveValue("");
  await expect(page.locator("[data-luot-hoi]")).toHaveText(CAU_HOI);
});

test("Shift+Enter: xuống dòng trong ô, không gửi", async ({ page }) => {
  const dem = await mock_hoi_dap(page, envelope());
  await vao_chat(page);
  await page.locator("[data-o-hoi]").fill("dòng một");
  await page.locator("[data-o-hoi]").press("Shift+Enter");
  await page.locator("[data-o-hoi]").pressSequentially("dòng hai");
  await expect(page.locator("[data-o-hoi]")).toHaveValue("dòng một\ndòng hai");
  await expect(page.locator("[data-luot]")).toHaveCount(0);
  expect(dem()).toBe(0);
});

test("câu toàn khoảng trắng: không request nào, không lượt nào", async ({ page }) => {
  const dem = await mock_hoi_dap(page, envelope());
  await vao_chat(page);
  await hoi_bang_nut(page, "   ");
  await expect(page.locator("[data-luot]")).toHaveCount(0);
  expect(dem()).toBe(0);
  // Ô trống hẳn cũng vậy.
  await page.locator("[data-o-hoi]").fill("");
  await page.locator("[data-nut-gui]").click();
  await expect(page.locator("[data-luot]")).toHaveCount(0);
  expect(dem()).toBe(0);
});

test("đang chờ: ba chấm và 'Đang truy vấn...', nút Gửi khóa", async ({ page }) => {
  await mock_hoi_dap(page, envelope(), 200, 1200);
  await vao_chat(page);
  await hoi_bang_nut(page);

  const cho = page.locator("[data-dang-cho]");
  await expect(cho).toHaveCount(1);
  await expect(cho).toContainText("Đang truy vấn...");
  await expect(cho.locator(".ba_cham i")).toHaveCount(3);
  await expect(page.locator("[data-nut-gui]")).toBeDisabled();
  // Lượt câu hỏi đã hiện ngay, và bong bóng chờ nằm sau nó.
  await expect(page.locator("[data-luot-hoi]")).toHaveText(CAU_HOI);
  // Rồi envelope về: bong bóng chờ biến thành lượt trả lời, nút mở lại.
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  await expect(page.locator("[data-dang-cho]")).toHaveCount(0);
  await expect(page.locator("[data-nut-gui]")).toBeEnabled();
});

test("trả lời: bong bóng lệch trái, meta đúng vai và số trích dẫn", async ({ page }) => {
  await mock_hoi_dap(
    page,
    envelope({ citations: [trich_dan("he-01"), trich_dan("he-02")], meta: { role: "devops", space: "synth", policy_version: "day-du@1" } }),
  );
  await vao_chat(page);
  await hoi_bang_nut(page);

  const tra_loi = page.locator("[data-tra-loi]");
  await expect(tra_loi).toHaveCount(1);
  await expect(tra_loi.locator("[data-luot-meta]")).toHaveText(
    "Copilot · trả lời theo quyền DevOps · 2 trích dẫn",
  );
  // Tên vai in đậm, và cùng màu với cả dòng meta.
  await expect(tra_loi.locator("[data-luot-meta] b")).toHaveText("DevOps");
  await expect(tra_loi).toContainText("App01 lỗi 502 vì PHP-FPM hết bộ nhớ.");
  await expect(page.locator("[data-hop-loi]")).toHaveCount(0);
  // Câu hỏi lệch phải, trả lời lệch trái.
  const hop_hoi = await page.locator("[data-luot-hoi]").boundingBox();
  const hop_tra_loi = await tra_loi.boundingBox();
  expect(hop_hoi!.x).toBeGreaterThan(hop_tra_loi!.x);
});

test("từ chối: template FR-16, meta không có vế trích dẫn, không hộp đỏ", async ({ page }) => {
  await mock_hoi_dap(page, envelope({ answer: null, refused: true, citations: [] }));
  await vao_chat(page);
  await hoi_bang_nut(page);

  const tu_choi = page.locator("[data-tu-choi]");
  await expect(tu_choi).toHaveCount(1);
  await expect(tu_choi).toContainText(
    "Tôi không tìm thấy thông tin phù hợp để trả lời câu hỏi này.",
  );
  await expect(tu_choi.locator("[data-luot-meta]")).toHaveText(
    "Copilot · trả lời theo quyền DevOps",
  );
  await expect(tu_choi).not.toContainText("trích dẫn");
  await expect(page.locator("[data-hop-loi]")).toHaveCount(0);
  await expect(page.locator("[data-tra-loi]")).toHaveCount(0);
});

test("hai lý do từ chối: hai lượt có DOM giống hệt nhau", async ({ page }) => {
  // Hai envelope byte-identical (lý do chỉ nằm trong audit, response không mang
  // nó), nên hai lượt phải giống nhau từng pixel - kể cả dòng meta.
  await mock_hoi_dap(page, envelope({ answer: null, refused: true, citations: [] }));
  await vao_chat(page);
  await hoi_bang_nut(page, "câu ngoài corpus");
  await expect(page.locator("[data-tu-choi]")).toHaveCount(1);
  await hoi_bang_nut(page, "câu chạm bí mật hạ tầng");
  await expect(page.locator("[data-tu-choi]")).toHaveCount(2);

  const dom = await page.locator("[data-tu-choi]").evaluateAll((cac) => cac.map((e) => e.outerHTML));
  expect(dom[0]).toBe(dom[1]);
});

test("500 PERMISSION_CONTEXT_MISSING: hộp đỏ mang mã, lượt cũ giữ nguyên", async ({ page }) => {
  await mock_hoi_dap(page, envelope());
  await vao_chat(page);
  await hoi_bang_nut(page, "câu trả lời được");
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);

  await mock_hoi_dap(page, loi_api("PERMISSION_CONTEXT_MISSING"), 500);
  await hoi_bang_nut(page, "câu gặp lỗi");

  await expect(page.locator("[data-ma-loi='PERMISSION_CONTEXT_MISSING']")).toHaveCount(1);
  await expect(page.locator("[data-hop-loi]")).toHaveText(/Hệ thống gặp lỗi, thử lại sau/);
  // Lịch sử giữ nguyên và không bị đá đi đâu.
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  await expect(page.locator("[data-luot]")).toHaveCount(2);
  expect(new URL(page.url()).pathname).toBe("/");
  await expect(page.locator("[data-nut-gui]")).toBeEnabled();
});

test("503 KHO_KHONG_SAN_SANG: cùng hộp đỏ, mã khác", async ({ page }) => {
  await mock_hoi_dap(page, loi_api("KHO_KHONG_SAN_SANG"), 503);
  await vao_chat(page);
  await hoi_bang_nut(page);
  await expect(page.locator("[data-ma-loi='KHO_KHONG_SAN_SANG']")).toHaveCount(1);
  expect(new URL(page.url()).pathname).toBe("/");
});

test("400 CAU_HOI_QUA_DAI: hộp đỏ mang mã đó, không điều hướng", async ({ page }) => {
  await mock_hoi_dap(page, loi_api("CAU_HOI_QUA_DAI"), 400);
  await vao_chat(page);
  await hoi_bang_nut(page, "x".repeat(50));
  await expect(page.locator("[data-ma-loi='CAU_HOI_QUA_DAI']")).toHaveCount(1);
  expect(new URL(page.url()).pathname).toBe("/");
  expect(await token_trong_kho(page)).not.toBeNull();
});

test("401 giữa một lượt: xóa token, về /dang-nhap?ly_do=het_han, không hộp đỏ", async ({
  page,
}) => {
  await mock_hoi_dap(page, loi_api("TOKEN_KHONG_HOP_LE"), 401);
  await vao_chat(page);
  await hoi_bang_nut(page);

  await page.waitForURL((u) => u.pathname === "/dang-nhap");
  expect(new URL(page.url()).searchParams.get("ly_do")).toBe("het_han");
  expect(await token_trong_kho(page)).toBeNull();
  await expect(page.locator("[data-thong-bao-phien]")).toBeVisible();
  await expect(page.locator("[data-hop-loi]")).toHaveCount(0);
});

test("envelope sai hình: hộp đỏ lỗi hệ thống, không lượt trả lời trống", async ({ page }) => {
  // Sáu cách một thân 200 sai lược đồ, mỗi cách chạm một nhánh của `la_envelope`.
  // Ca nặng nhất là `refused: "false"`: chuỗi ấy **truthy** trong JavaScript nên
  // một câu trả lời thật render thành template từ chối FR-16.
  const bien_the: Array<[string, Record<string, unknown>]> = [
    ["thiếu refused", (() => { const e = envelope() as Record<string, unknown>; delete e.refused; return e; })()],
    ["refused là chuỗi", envelope({ refused: "false" }) as Record<string, unknown>],
    ["citations null", envelope({ citations: null }) as Record<string, unknown>],
    ["meta.role sai kiểu", envelope({ meta: { role: 7, space: "synth", policy_version: "day-du@1" } }) as Record<string, unknown>],
    ["meta.role rỗng", envelope({ meta: { role: "", space: "synth", policy_version: "day-du@1" } }) as Record<string, unknown>],
    ["trả lời mà answer rỗng", envelope({ refused: false, answer: "   " }) as Record<string, unknown>],
  ];

  await vao_chat(page);
  for (let i = 0; i < bien_the.length; i += 1) {
    const [ten, than] = bien_the[i];
    await mock_hoi_dap(page, than);
    await hoi_bang_nut(page, `câu số ${i + 1}`);
    await expect(page.locator("[data-ma-loi='ENVELOPE_LA']"), ten).toHaveCount(i + 1);
  }
  // Không lượt trả lời trống, không lượt từ chối giả, và không bị đá đi đâu.
  await expect(page.locator("[data-tra-loi]")).toHaveCount(0);
  await expect(page.locator("[data-tu-choi]")).toHaveCount(0);
  await expect(page.locator("[data-ma-loi='MANG']")).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe("/");
  // Câu hỏi được trả về composer để bấm gửi lại, không phải gõ lại cả câu.
  await expect(page.locator("[data-o-hoi]")).toHaveValue(`câu số ${bien_the.length}`);
});

test("Enter giữa một tổ hợp gõ tiếng Việt: không gửi, không lượt nào", async ({ page }) => {
  const dem = await mock_hoi_dap(page, envelope());
  await vao_chat(page);
  await page.locator("[data-o-hoi]").fill("Sự cố App0");
  // `isComposing` chỉ đặt được qua constructor, nên ca này phải dispatch tay.
  await page.locator("[data-o-hoi]").evaluate((o) => {
    o.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true }));
  });
  await expect(page.locator("[data-luot]")).toHaveCount(0);
  expect(dem()).toBe(0);
  // Và Enter thật (không tổ hợp) vẫn gửi được ngay sau đó.
  await page.locator("[data-o-hoi]").press("Enter");
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  expect(dem()).toBe(1);
});

test("bấm Gửi hai lần lúc đang chờ: đúng một request", async ({ page }) => {
  const dem = await mock_hoi_dap(page, envelope(), 200, 700);
  await vao_chat(page);
  await page.locator("[data-o-hoi]").fill(CAU_HOI);
  // Hai lần bấm trong **cùng một tick**: state `dang_cho` chưa kịp đổi nên chốt
  // phải nằm ở ref (spec 4.3, khuôn của màn đăng nhập 4.2).
  await page.evaluate(() => {
    const nut = document.querySelector<HTMLButtonElement>("[data-nut-gui]")!;
    nut.click();
    nut.click();
  });
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  expect(dem()).toBe(1);
  await expect(page.locator("[data-luot]")).toHaveCount(1);
});

test("1280px với ba lượt: không cuộn ngang, composer vẫn thấy", async ({ page }) => {
  await mock_hoi_dap(page, envelope({ citations: [trich_dan("he-01"), trich_dan("he-02")] }));
  await vao_chat(page);
  await hoi_bang_nut(page, CAU_HOI);
  await expect(page.locator("[data-tra-loi]")).toHaveCount(1);
  await hoi_bang_nut(page, "SOP-12 gồm những bước nào khi khởi động lại pool PHP-FPM?");
  await expect(page.locator("[data-tra-loi]")).toHaveCount(2);
  await hoi_bang_nut(page, "Ai phụ trách App01 và liên hệ thế nào khi ngoài giờ?");
  await expect(page.locator("[data-tra-loi]")).toHaveCount(3);

  expect(await rong_cuon(page)).toBeLessThanOrEqual(1280);
  await expect(page.locator("[data-o-hoi]")).toBeInViewport();
  await expect(page.locator("[data-nut-gui]")).toBeInViewport();
  // Lượt mới nhất phải tự nằm trong tầm nhìn: một khối cuộn không tự cuộn là
  // một câu trả lời người dùng không thấy.
  await expect(page.locator("[data-tra-loi]").last()).toBeInViewport();
  await page.screenshot({ path: ANH_CHAT, fullPage: false });
});
