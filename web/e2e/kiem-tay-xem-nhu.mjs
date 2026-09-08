// Kiểm tay nhịp "xem như" bằng chromium thật trên máy chủ (story 4.5).
//
// Không phải một ca Playwright: nó gọi máy chủ thật và **tốn tiền LLM thật** (2
// lời gọi mỗi lượt hỏi), nên nó không nằm trong `npm run test:e2e` và không
// chạy ở hook CI. Cùng khuôn và cùng chỗ với `kiem-tay.mjs` của story 4.4, và
// vì cùng một lý do: `web/e2e/` có `@playwright/test`, thư mục ấy đã bị
// `.dockerignore` loại, và đuôi `.mjs` nên `testMatch` không nhặt nó.
//
// Nó chấm đúng ba điều mà 16 ca mock của `xem-nhu.spec.ts` **không** chấm được,
// vì cả ba đứng trên một máy chủ thật:
//   1. Danh mục vai trên dropdown bằng đúng `GET /auth/vai` của bảng chính sách
//      đang chạy - lời hứa của AD-4 đo trên bảng thật chứ không trên một mock.
//   2. Ba nhịp demo ra ba kết quả khác nhau cho **cùng một câu hỏi**: DevOps
//      trả lời đủ, Tech Support ra slab đen, Sale/BA ra template từ chối không
//      trích dẫn. Đây là nhịp 1-2-3 của đường demo 90 giây.
//   3. Lịch sử giữ nguyên: lượt cũ không đổi một byte sau khi đổi vai, và mỗi
//      lần đổi chèn đúng một divider.
//
// Chạy:
//   node web/e2e/kiem-tay-xem-nhu.mjs [--goc http://103.69.194.185:3000] [--cau "..."]
// Mật khẩu lấy từ `.env` gốc repo theo tên `DEMO_MAT_KHAU_<TÊN>`.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const GOC_REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RONG = 1280;

/** Câu ghim của cả epic (EXPERIENCE.md nhịp 1, `scripts/cong-m2.sh` B2/B4/B5). */
const CAU_GHIM = "Sự cố App01 lỗi 502 nguyên nhân là gì?";

function mat_khau(tai_khoan) {
  const env = readFileSync(resolve(GOC_REPO, ".env"), "utf-8");
  const m = env.match(new RegExp(`^DEMO_MAT_KHAU_${tai_khoan.toUpperCase()}=(.*)$`, "m"));
  if (!m) throw new Error(`.env không có DEMO_MAT_KHAU_${tai_khoan.toUpperCase()}`);
  return m[1].trim();
}

/** Nhãn vai đọc **từ chính `web/src/api/phien.ts`**, không chép lại: một bản
 *  chép thứ hai ở đây sẽ báo xanh cho đúng cái nó chép sai. */
function nhan_vai_cua_web() {
  const tho = readFileSync(resolve(GOC_REPO, "web/src/api/phien.ts"), "utf-8");
  const m = tho.match(/export const NHAN_VAI(?::[^=]*)? = \{(.*?)\n\};/s);
  if (!m) throw new Error("phien.ts không có bảng NHAN_VAI");
  return Object.fromEntries(
    [...m[1].matchAll(/^\s*([a-z_][a-z0-9_]*):\s*"([^"]*)"/gm)].map((x) => [x[1], x[2]]),
  );
}

function doc_tham_so(argv) {
  const ra = { goc: "http://103.69.194.185:3000", cau: CAU_GHIM };
  for (let i = 0; i < argv.length; i += 1) {
    const co = argv[i];
    if (co !== "--goc" && co !== "--cau") continue;
    // Cờ đứng cuối `argv` mà không có giá trị: `argv[++i]` là `undefined`, và
    // nó đi thẳng vào một URL `undefined/dang-nhap` hay một câu hỏi `undefined`
    // gửi tới máy chủ thật - tức một lần chạy **tốn tiền LLM** cho một tham số
    // gõ thiếu. Dừng ngay với một câu nói được sai ở đâu.
    const gia_tri = argv[i + 1];
    if (gia_tri === undefined || gia_tri.startsWith("--")) {
      throw new Error(`${co} thiếu giá trị`);
    }
    i += 1;
    if (co === "--goc") ra.goc = gia_tri;
    else ra.cau = gia_tri;
  }
  return ra;
}

const ts = doc_tham_so(process.argv.slice(2));
const NHAN_VAI = nhan_vai_cua_web();

let so_fail = 0;
let so_pass = 0;
function ghi(ten, dat, chi_tiet = "") {
  if (dat) so_pass += 1;
  else so_fail += 1;
  console.log(`${dat ? "  PASS" : "  FAIL"}  ${ten}${dat ? "" : `  <- ${chi_tiet}`}`);
}

const trinh_duyet = await chromium.launch();
const page = await trinh_duyet.newPage({ viewport: { width: RONG, height: 900 } });

// Thân bọc `try/finally`: Chromium phải đóng và tổng kết phải in ra **kể cả**
// khi một phép kiểm dội (một selector không tìm thấy, một `waitForResponse`
// quá hạn). Không có nó thì một lần chạy hỏng để lại một tiến trình trình
// duyệt treo và không một dòng nào nói đã chấm được bao nhiêu trước khi hỏng.
try {
  await page.goto(`${ts.goc}/dang-nhap`);
  await page.fill("#o_tai_khoan", "dev01");
  await page.fill("#o_mat_khau", mat_khau("dev01"));
  await page.click("button[type=submit]");
  await page.waitForSelector("[data-chip-vai]");
  console.log(`\n# ${await page.textContent("[data-chip-vai]")}  @ ${ts.goc}\n`);

  async function hoi(cau) {
    const truoc = await page.locator("[data-luot]").count();
    await page.fill("[data-o-hoi]", cau);
    await page.click("[data-nut-gui]");
    await page.waitForFunction(
      (n) =>
        document.querySelectorAll("[data-luot]").length === n &&
        !document.querySelector("[data-luot]:last-of-type [data-dang-cho]"),
      truoc + 1,
      { timeout: 300000 },
    );
    const cuoi = page.locator("[data-luot]").last();
    return {
      tu_choi: (await cuoi.locator("[data-tu-choi]").count()) === 1,
      than: (await cuoi.locator(".luot__than").textContent()) ?? "",
      so_slab: await cuoi.locator("[data-slab]").count(),
      so_cite: await cuoi.locator("[data-cite-row]").count(),
      meta: (await cuoi.locator("[data-luot-meta]").textContent()) ?? "",
    };
  }

  async function doi_vai(vai) {
    await page.click("[data-nut-xem-nhu]");
    await page.waitForSelector("[data-menu-vai]");
    await page.click(`[data-muc-vai="${vai}"]`);
    await page.waitForFunction(
      (v) => document.querySelector("[data-chip-vai]")?.textContent?.includes(v),
      NHAN_VAI[vai],
      { timeout: 30000 },
    );
  }

  // --- (1) Dropdown bằng đúng danh mục vai của bảng chính sách đang chạy -------
  //
  // **Đợi đúng phản hồi quanh cú bấm**, không nghe `page.on("response")` rồi so
  // ngay sau `waitForSelector`: handler ấy `await r.json()` bên trong, nên biến
  // giữ danh mục có thể còn `null` lúc phép so chạy - một cuộc đua **trong chính
  // phép kiểm**, và nó FAIL ngẫu nhiên với `api null` ở đúng thứ duy nhất đo
  // được lời hứa AD-4 trên bảng thật.

  const [phan_hoi_vai] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/auth/vai") && r.status() === 200),
    page.click("[data-nut-xem-nhu]"),
  ]);
  const vai_tu_api = (await phan_hoi_vai.json()).vai;
  await page.waitForSelector("[data-menu-vai]");
  const tren_man = await page.locator("[data-muc-vai]").evaluateAll((cac) =>
    cac.map((e) => e.getAttribute("data-muc-vai")),
  );
  ghi(
    "dropdown liệt kê đúng danh mục vai của GET /auth/vai",
    JSON.stringify(tren_man) === JSON.stringify(vai_tu_api),
    `màn ${JSON.stringify(tren_man)} vs api ${JSON.stringify(vai_tu_api)}`,
  );
  const chu_menu = (await page.locator("[data-menu-vai]").textContent()) ?? "";
  ghi(
    "mỗi vai hiện nhãn tiếng Việt, không khóa snake_case",
    tren_man.every((v) => chu_menu.includes(NHAN_VAI[v] ?? v)) &&
      !tren_man.some((v) => v.includes("_") && chu_menu.includes(v)),
    chu_menu.replace(/\s+/g, " ").slice(0, 200),
  );
  ghi(
    "chưa mượn vai thì không mục thoát, không chip hổ phách",
    (await page.locator("[data-thoat-xem-nhu]").count()) === 0 &&
      (await page.locator("[data-chip-xem-nhu]").count()) === 0,
  );
  await page.keyboard.press("Escape");

  // --- (2) Ba nhịp demo trên cùng một câu hỏi ---------------------------------

  console.log(`\n--- nhịp 1: DevOps · ${ts.cau}`);
  const n1 = await hoi(ts.cau);
  console.log(`  ${n1.meta}\n  ${n1.than.slice(0, 160)}`);
  ghi("nhịp 1 trả lời được, không slab", !n1.tu_choi && n1.so_slab === 0, JSON.stringify(n1));
  const html_luot1 = await page.locator("[data-luot]").first().innerHTML();

  console.log("\n--- đổi sang xem như Tech Support");
  await doi_vai("tech_support");
  ghi(
    "chip hổ phách và chip vai thật cùng hiện",
    (await page.locator("[data-chip-xem-nhu]").textContent())?.includes(NHAN_VAI.tech_support) ===
      true && (await page.locator("[data-chip-vai-that]").textContent()) === "dev01 · DevOps",
  );
  ghi("một divider sau lần đổi đầu", (await page.locator("[data-moc-doi-vai]").count()) === 1);
  ghi(
    "lượt 1 không đổi một byte sau khi đổi vai",
    (await page.locator("[data-luot]").first().innerHTML()) === html_luot1,
  );

  console.log(`\n--- nhịp 2: Tech Support · ${ts.cau}`);
  const n2 = await hoi(ts.cau);
  console.log(`  ${n2.meta}\n  ${n2.than.slice(0, 160)}`);
  ghi("nhịp 2 mang slab đen", !n2.tu_choi && n2.so_slab >= 1, JSON.stringify(n2));
  ghi("nhịp 2 nói đúng vai trên dòng meta", n2.meta.includes(NHAN_VAI.tech_support), n2.meta);

  console.log("\n--- đổi sang xem như Sale/BA");
  // Chụp lại **ngay trước** lần đổi: phép so "không đổi một byte" chỉ có nghĩa
  // qua một lần đổi vai, không qua một lượt hỏi mới. Một lượt trả lời mới làm
  // khối nguồn của lượt cũ thu gọn (`id_tra_loi_moi_nhat` của story 4.4), và đó
  // là hành vi đúng chứ không phải một lần viết lại theo vai.
  const html_luot1_truoc_lan3 = await page.locator("[data-luot]").first().innerHTML();
  await doi_vai("sale_ba");
  ghi("hai divider sau lần đổi thứ hai", (await page.locator("[data-moc-doi-vai]").count()) === 2);
  ghi(
    "lượt 1 không đổi một byte qua lần đổi thứ hai",
    (await page.locator("[data-luot]").first().innerHTML()) === html_luot1_truoc_lan3,
  );

  console.log(`\n--- nhịp 3: Sale/BA · ${ts.cau}`);
  const n3 = await hoi(ts.cau);
  console.log(`  ${n3.meta}\n  ${n3.than.slice(0, 160)}`);
  ghi(
    "nhịp 3 là template từ chối, không trích dẫn, không slab",
    n3.tu_choi && n3.so_cite === 0 && n3.so_slab === 0,
    JSON.stringify(n3),
  );

  // --- (3) Thoát xem như, và không cuộn ngang ---------------------------------

  console.log("\n--- bấm ✕ thoát xem như");
  await page.click("[data-thoat-nhanh]");
  await page.waitForFunction(
    (v) => document.querySelector("[data-chip-vai]")?.textContent?.includes(v),
    NHAN_VAI.devops,
    { timeout: 30000 },
  );
  ghi("chip hổ phách biến mất", (await page.locator("[data-chip-xem-nhu]").count()) === 0);
  ghi("ba divider tất cả", (await page.locator("[data-moc-doi-vai]").count()) === 3);
  // Qua cả ba lần đổi vai và hai lượt hỏi, phần **do vai quyết định** của lượt 1
  // còn nguyên: dòng meta vẫn nói DevOps và câu trả lời vẫn là câu đầy đủ, không
  // slab nào. So bằng nội dung chứ không bằng `innerHTML`: hai lượt trả lời mới
  // đã làm khối nguồn của lượt 1 thu gọn, và đó là luật của 4.4 chứ không phải
  // một lần viết lại theo vai mới (NFR-09).
  const luot1 = page.locator("[data-luot]").first();
  ghi(
    "lượt 1 vẫn mang meta DevOps và câu trả lời đầy đủ sau cả ba lần đổi",
    ((await luot1.locator("[data-luot-meta]").textContent()) ?? "").includes(NHAN_VAI.devops) &&
      ((await luot1.locator(".luot__than").textContent()) ?? "") === n1.than &&
      (await luot1.locator("[data-slab]").count()) === 0,
  );
  ghi(
    `không cuộn ngang ở ${RONG}px`,
    (await page.evaluate(() => document.scrollingElement.scrollWidth)) <= RONG,
  );
  ghi(
    "không id hyperedge thật nào trong DOM",
    !/\bhe-[0-9a-f]{8,}/.test(await page.content()),
  );

  await page.screenshot({
    path: resolve(GOC_REPO, "eval/anh_bang_chung/kiem-tay-4-5-xem-nhu.png"),
  });
} finally {
  await trinh_duyet.close();
  console.log(`\n== ${so_pass} PASS, ${so_fail} FAIL`);
}
process.exit(so_fail === 0 ? 0 : 1);
