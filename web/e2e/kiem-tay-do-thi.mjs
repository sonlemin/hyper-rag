// Kiểm tay drawer đồ thị bằng chromium thật trên máy chủ (story 4.6).
//
// Không phải một ca Playwright: nó gọi máy chủ thật và **tốn tiền LLM thật** (2
// lời gọi mỗi lượt hỏi), nên nó không nằm trong `npm run test:e2e` và không
// chạy ở hook CI. Cùng khuôn và cùng chỗ với `kiem-tay.mjs` của 4.4 và
// `kiem-tay-xem-nhu.mjs` của 4.5, và vì cùng một lý do: `web/e2e/` có
// `@playwright/test`, thư mục ấy đã bị `.dockerignore` loại, và đuôi `.mjs` nên
// `testMatch` không nhặt nó.
//
// Nó chấm đúng bốn điều mà 19 ca mock của `do-thi.spec.ts` **không** chấm được,
// vì cả bốn đứng trên dữ liệu thật:
//   1. Số vòng bằng `citations.length` của chính lượt ấy, và `/do-thi` nhận
//      **đúng** danh sách id mà `/hoi-dap` vừa trả - hai thân đối chiếu từng id.
//   2. Hover từng cite-row làm sáng **đúng** vòng mang mã ấy, trên một đồ thị
//      mà số vòng và hình dạng do kho quyết chứ không do một mock.
//   3. Đổi vai đổi hình: cùng danh sách id, `/do-thi` gọi lại, và vai hẹp hơn
//      cho ít vòng hơn hay có đỉnh `•••` - tức server thật sự lọc lại.
//   4. Không id hyperedge thật nào trong DOM, và không cuộn ngang ở 1280.
//
// Chạy:
//   node web/e2e/kiem-tay-do-thi.mjs [--tai-khoan dev01] [--goc http://103.69.194.185:3000] [--cau "..."]
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

/** Mã hiển thị của citation thứ `i`, đọc luật từ chính `web/src/api/hoi_dap.ts`
 *  (tiền tố cộng hai chữ số) thay vì chép `HE-` vào đây. */
function ma_hien_thi_cua_web() {
  const tho = readFileSync(resolve(GOC_REPO, "web/src/api/hoi_dap.ts"), "utf-8");
  const m = tho.match(/export const TIEN_TO_MA_HIEN_THI = "([^"]*)"/);
  if (!m) throw new Error("hoi_dap.ts không có TIEN_TO_MA_HIEN_THI");
  const tien_to = m[1];
  return (i) => `${tien_to}${String(i + 1).padStart(2, "0")}`;
}

function doc_tham_so(argv) {
  const ra = { goc: "http://103.69.194.185:3000", cau: CAU_GHIM, tai_khoan: "dev01" };
  const co_ten = { "--goc": "goc", "--cau": "cau", "--tai-khoan": "tai_khoan" };
  for (let i = 0; i < argv.length; i += 1) {
    const ten = co_ten[argv[i]];
    if (!ten) continue;
    // Cờ đứng cuối `argv` mà không có giá trị: `argv[++i]` là `undefined`, và
    // nó đi thẳng vào một URL `undefined/dang-nhap` hay một câu hỏi
    // `undefined` gửi tới máy chủ thật - tức một lần chạy **tốn tiền LLM** cho
    // một tham số gõ thiếu. Dừng ngay với một câu nói được sai ở đâu.
    const gia_tri = argv[i + 1];
    if (gia_tri === undefined || gia_tri.startsWith("--")) {
      throw new Error(`${argv[i]} thiếu giá trị`);
    }
    i += 1;
    ra[ten] = gia_tri;
  }
  return ra;
}

const ts = doc_tham_so(process.argv.slice(2));
const NHAN_VAI = nhan_vai_cua_web();
const ma_hien_thi = ma_hien_thi_cua_web();

/** Nhãn tiếng Việt của một vai. Vai vắng trong `NHAN_VAI` là một câu **nói
 *  được sai ở đâu**, không một `undefined` đi thẳng vào một `waitForFunction`
 *  rồi treo 30 giây rồi dội một lỗi không liên quan. */
function nhan(vai) {
  const ra = NHAN_VAI[vai];
  if (ra === undefined) {
    throw new Error(`vai "${vai}" không có nhãn trong web/src/api/phien.ts`);
  }
  return ra;
}

/** Hai vai của nhịp 2 và nhịp 3 trên đường demo (EXPERIENCE.md). Chúng được
 *  **đối chiếu với bảng chính sách đang chạy** trước khi dùng, nên một bảng
 *  thiếu vai ra một câu nói rõ thay vì một menu không có mục để bấm. */
const VAI_NHIP_2 = "tech_support";
const VAI_NHIP_3 = "sale_ba";

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
// quá hạn).
let hong = null;
try {
  await page.goto(`${ts.goc}/dang-nhap`);
  await page.fill("#o_tai_khoan", ts.tai_khoan);
  await page.fill("#o_mat_khau", mat_khau(ts.tai_khoan));
  // Vai thật đọc từ chính `/auth/toi` của phiên vừa mở, không chép cứng
  // `devops`: `--tai-khoan` nhận bất kỳ tài khoản nào trong seed, và in tên
  // một vai khác vai đang chạy là một dòng log nói sai về phép đo.
  const [phan_hoi_toi] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/auth/toi") && r.status() === 200),
    page.click("button[type=submit]"),
  ]);
  const vai_that = (await phan_hoi_toi.json()).vai;
  await page.waitForSelector("[data-chip-vai]");
  console.log(`\n# ${await page.textContent("[data-chip-vai]")}  @ ${ts.goc}\n`);

  /** Hỏi một câu, trả về envelope thật của lượt ấy. */
  async function hoi(cau) {
    const truoc = await page.locator("[data-luot]").count();
    const cho = page.waitForResponse(
      (r) => r.url().endsWith("/api/hoi-dap") && r.request().method() === "POST",
      { timeout: 300000 },
    );
    await page.fill("[data-o-hoi]", cau);
    await page.click("[data-nut-gui]");
    const phan_hoi = await cho;
    await page.waitForFunction(
      (n) =>
        document.querySelectorAll("[data-luot]").length === n &&
        !document.querySelector("[data-luot]:last-of-type [data-dang-cho]"),
      truoc + 1,
      { timeout: 300000 },
    );
    return phan_hoi.json();
  }

  /** Đợi đúng lời gọi `/do-thi` quanh một thao tác, trả về `{gui, than}`. */
  async function quanh_do_thi(thao_tac) {
    const cho = page.waitForResponse(
      (r) => r.url().endsWith("/api/do-thi") && r.request().method() === "POST",
      { timeout: 120000 },
    );
    await thao_tac();
    const phan_hoi = await cho;
    await page.waitForSelector('[data-vung-do-thi][data-da-ve="1"], [data-do-thi-trong]');
    return {
      gui: JSON.parse(phan_hoi.request().postData() ?? "{}"),
      than: await phan_hoi.json(),
    };
  }

  async function so_vong_tren_man() {
    const el = page.locator("[data-vung-do-thi]");
    if ((await el.count()) === 0) return 0;
    return Number(await el.getAttribute("data-so-vong"));
  }

  async function doi_vai(vai) {
    await page.click("[data-nut-xem-nhu]");
    await page.waitForSelector("[data-menu-vai]");
    // Bảng chính sách hoán được lúc chạy, nên một vai của kịch bản demo có thể
    // vắng trong bảng đang chạy. Nói ra thay vì để `click` treo 30 giây.
    if ((await page.locator(`[data-muc-vai="${vai}"]`).count()) === 0) {
      const co = await page
        .locator("[data-muc-vai]")
        .evaluateAll((cac) => cac.map((e) => e.getAttribute("data-muc-vai")));
      throw new Error(`bảng chính sách đang chạy không có vai ${vai}; nó có ${co.join(", ")}`);
    }
    await page.click(`[data-muc-vai="${vai}"]`);
    await page.waitForFunction(
      (v) => document.querySelector("[data-chip-vai]")?.textContent?.includes(v),
      nhan(vai),
      { timeout: 30000 },
    );
  }

  // --- (1) Một lượt thật, drawer mở bằng nút -----------------------------------

  console.log(`--- nhịp 1: ${nhan(vai_that)} · ${ts.cau}`);
  const e1 = await hoi(ts.cau);
  const id_that = e1.citations.map((c) => c.id);
  console.log(`  ${e1.citations.length} citation, mức ${e1.citations.map((c) => c.level).join(",")}`);

  const lan_1 = await quanh_do_thi(() => page.click("[data-nut-do-thi]"));
  ghi(
    "/do-thi nhận đúng danh sách id mà /hoi-dap vừa trả",
    JSON.stringify(lan_1.gui.hyperedge_ids) === JSON.stringify(id_that),
    `gửi ${JSON.stringify(lan_1.gui.hyperedge_ids)} vs citations ${JSON.stringify(id_that)}`,
  );
  const so_vong_1 = await so_vong_tren_man();
  ghi(
    "số vòng bằng số citation của lượt",
    so_vong_1 === e1.citations.length,
    `${so_vong_1} vòng vs ${e1.citations.length} citation`,
  );
  const so_node_he = lan_1.than.graph.nodes.filter((n) => n.kind === "hyperedge").length;
  ghi(
    "màn hình vẽ đúng số node hyperedge mà server trả về, không bỏ vòng nào",
    so_vong_1 === so_node_he,
    `${so_vong_1} vòng vs ${so_node_he} node hyperedge`,
  );
  const so_dinh = Number(await page.getAttribute("[data-vung-do-thi]", "data-so-dinh"));
  const so_dinh_che = Number(await page.getAttribute("[data-vung-do-thi]", "data-so-dinh-che"));
  const che_that = lan_1.than.graph.nodes.filter((n) => n.kind === "entity" && n.masked).length;
  console.log(`  đồ thị: ${so_vong_1} vòng · ${so_dinh} đỉnh · ${so_dinh_che} đỉnh che`);
  ghi("số đỉnh che khớp `masked` của thân trả về", so_dinh_che === che_that, `${so_dinh_che} vs ${che_that}`);

  // --- (2) Hover từng cite-row làm sáng đúng vòng ------------------------------

  const so_hang = await page.locator("[data-cite-row]").count();
  for (let i = 0; i < so_hang; i += 1) {
    const ma = ma_hien_thi(i);
    await page.locator("[data-cite-row]").nth(i).hover();
    const sang = await page.getAttribute("[data-drawer-do-thi]", "data-ma-sang");
    const chu = await page.locator(`[data-dang-sang="${ma}"]`).count();
    ghi(`hover hàng ${i + 1} làm sáng ${ma} kèm chú thích chữ`, sang === ma && chu === 1, `sáng=${sang} chú thích=${chu}`);
  }
  await page.mouse.move(2, 2);
  ghi(
    "rời hover thì không vòng nào sáng",
    (await page.getAttribute("[data-drawer-do-thi]", "data-ma-sang")) === null,
  );

  // --- (3) Không id thật trong DOM, không cuộn ngang ---------------------------

  const html = await page.locator("[data-drawer-do-thi]").innerHTML();
  const lo = id_that.filter((id) => html.includes(id));
  ghi("không id hyperedge thật nào trong DOM của drawer", lo.length === 0, lo.join(", "));
  ghi(
    "legend hiện đủ mã HE-nn của từng vòng",
    (await page.locator("[data-legend-vong]").count()) === so_vong_1,
  );
  const rong_cuon = await page.evaluate(() => document.scrollingElement.scrollWidth);
  ghi(`không cuộn ngang ở ${RONG}px`, rong_cuon <= RONG, `scrollWidth=${rong_cuon}`);
  await page.screenshot({
    path: resolve(GOC_REPO, "eval", "anh_bang_chung", "kiem-tay-4-6-do-thi.png"),
  });

  // --- (4) Đổi vai: cùng id, server lọc lại ------------------------------------

  console.log(`\n--- nhịp 2: đổi sang ${nhan(VAI_NHIP_2)}`);
  const lan_2 = await quanh_do_thi(() => doi_vai(VAI_NHIP_2));
  ghi(
    "đổi vai gọi lại /do-thi với **đúng** danh sách id ấy",
    JSON.stringify(lan_2.gui.hyperedge_ids) === JSON.stringify(id_that),
    `gửi ${JSON.stringify(lan_2.gui.hyperedge_ids)}`,
  );
  const so_vong_2 = await so_vong_tren_man();
  const che_2 = (await page.locator("[data-vung-do-thi]").count())
    ? Number(await page.getAttribute("[data-vung-do-thi]", "data-so-dinh-che"))
    : 0;
  console.log(`  vai hẹp hơn: ${so_vong_2} vòng · ${che_2} đỉnh che (trước: ${so_vong_1} · ${so_dinh_che})`);
  ghi(
    "server lọc lại: ít vòng hơn, hay có thêm đỉnh che",
    so_vong_2 < so_vong_1 || che_2 > so_dinh_che,
    `${so_vong_2}/${che_2} so với ${so_vong_1}/${so_dinh_che}`,
  );
  ghi(
    "chip drawer nói đúng vai đang xem",
    (await page.textContent("[data-chip-vai-do-thi]"))?.includes(nhan(VAI_NHIP_2)) === true,
  );

  console.log(`\n--- nhịp 2b: ${nhan(VAI_NHIP_2)} hỏi lại câu ghim`);
  const e2 = await hoi(ts.cau);
  if (e2.refused) {
    ghi(
      "lượt từ chối ra empty-state, không vòng nào",
      (await page.locator("[data-do-thi-trong]").count()) === 1,
    );
  } else {
    await page.waitForSelector('[data-vung-do-thi][data-da-ve="1"], [data-do-thi-trong]');
    const so_vong_2b = await so_vong_tren_man();
    ghi(
      "drawer vẽ lại theo lượt mới",
      so_vong_2b === e2.citations.length,
      `${so_vong_2b} vòng vs ${e2.citations.length} citation`,
    );
  }

  // --- (5) Nhịp 3: vai bị chặn ra đúng empty-state -----------------------------

  console.log(`\n--- nhịp 3: đổi sang ${nhan(VAI_NHIP_3)} rồi hỏi lại`);
  await doi_vai(VAI_NHIP_3);
  const e3 = await hoi(ts.cau);
  ghi("nhịp 3 là lượt từ chối, không trích dẫn", e3.refused && e3.citations.length === 0, JSON.stringify(e3.meta));
  await page.waitForSelector("[data-do-thi-trong]");
  ghi(
    "drawer về đúng empty-state trung tính, không vòng nào của vai trước còn trên màn",
    (await page.locator("[data-do-thi-trong]").count()) === 1 &&
      (await page.locator("[data-vung-do-thi]").count()) === 0,
  );
} catch (loi) {
  // Một exception (selector không thấy, `waitForResponse` quá hạn) là một lần
  // chạy **hỏng**, không một lần chạy 0 FAIL. Bản đầu để `process.exit` trong
  // `finally` nên nó in tổng kết rồi thoát mã 0, ngược đúng lý do `try/finally`
  // được thêm ở 4.5: đóng trình duyệt và in tổng kết, chứ không nuốt lỗi.
  hong = loi;
  console.log(`  FAIL  lần chạy dội: ${loi instanceof Error ? loi.message : String(loi)}`);
  so_fail += 1;
} finally {
  await trinh_duyet.close();
  console.log(`\n${so_pass} PASS · ${so_fail} FAIL`);
  if (hong !== null) console.error(hong);
  process.exit(so_fail === 0 && hong === null ? 0 : 1);
}
