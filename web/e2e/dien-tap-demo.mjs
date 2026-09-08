// Diễn tập đường demo ba nhịp trên máy chủ thật (story 4.7).
//
// Không phải một ca Playwright: nó gọi máy chủ thật và **tốn tiền LLM thật**
// (tới 3 lời gọi LLM mỗi lượt hỏi từ story 4.7), nên nó không nằm trong
// `npm run test:e2e` và không chạy ở hook CI. Cùng khuôn và cùng chỗ với ba
// `kiem-tay*.mjs` của 4.4, 4.5 và 4.6, và vì cùng một lý do: `web/e2e/` có
// `@playwright/test`, thư mục ấy đã bị `.dockerignore` loại, và đuôi `.mjs` nên
// `testMatch` không nhặt nó.
//
// Nó đo hai thứ mà `web/e2e/demo-ba-nhip.spec.ts` (mock) **không** đo được, và
// cố ý không chép lại những gì ba kịch bản kiểm tay trước đã chấm:
//   1. **Thời gian từng nhịp** và tổng, đối chiếu quỹ 90 giây của bài demo.
//      Quá quỹ là WARNING chứ không FAIL: NFR-08 không đặt SLA, nên một lần
//      chạy chậm là một con số phải biết trước buổi bảo vệ, không một lỗi.
//   2. **Tần suất** ba thứ chỉ đo được bằng cách chạy nhiều lần trên dữ liệu
//      thật: lượt bị từ chối vì `tu_khoa_rong` (khoản sổ nợ đuôi từ khóa hỏng),
//      hai họ dấu che tiếng Anh `[description:l2_only]` và `[neighbor_id:no_key]`
//      lọt vào `answer` (khoản sổ nợ hai họ dấu che), và số lần nhìn thấy hiện
//      tượng ghép mảnh - câu trả lời nói ra gần đúng phần vừa bị che trong khi
//      dòng hạn chế ngay dưới khẳng định nó bị hạn chế (khoản sổ nợ ghép mảnh).
//
// Chạy:
//   node web/e2e/dien-tap-demo.mjs [--lan 3] [--goc http://103.69.194.185:3000]
//                                  [--tai-khoan dev01] [--cau "..."] [--quy 90]
// Mật khẩu lấy từ `.env` gốc repo theo tên `DEMO_MAT_KHAU_<TÊN>`.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const GOC_REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RONG = 1280;

/** Câu ghim của cả epic (EXPERIENCE.md nhịp 1, `scripts/cong-m2.sh` B2/B4/B5). */
const CAU_GHIM = "Sự cố App01 lỗi 502 nguyên nhân là gì?";

/** Quỹ thời gian của bài demo, tính bằng giây (brief: demo 90 giây). Nó là một
 *  **quỹ**, không một SLA: NFR-08 không đặt trần độ trễ, và trần lý thuyết của
 *  một lượt (`api.hoi_dap.tran_mot_truy_van_giay`) là 348 giây. Quá quỹ là một
 *  WARNING để người trình bày biết trước, không một FAIL. */
const QUY_GIAY = 90;

/** Hai vai của nhịp 2 và nhịp 3 trên đường demo (EXPERIENCE.md). */
const VAI_NHIP_2 = "tech_support";
const VAI_NHIP_3 = "sale_ba";

/** Hai họ dấu che **không phải vai slot**, nên slab của 4.4 cố ý để chúng
 *  nguyên văn và chúng ra màn hình dưới dạng chuỗi tiếng Anh giữa một câu tiếng
 *  Việt. Đọc từ `core/masking.py` chứ không chép: một bản chép ở đây báo xanh
 *  cho đúng cái nó chép sai, và `core/` là nơi bốn họ dấu che được sinh ra. */
function hai_ho_dau_che_ngoai_vai() {
  const tho = readFileSync(resolve(GOC_REPO, "core/masking.py"), "utf-8");
  const ra = [];
  for (const ten of ["MASK_REASON_L2_ONLY", "MASK_REASON_NO_KEY"]) {
    const m = tho.match(new RegExp(`^${ten}[^=]*=\\s*"([^"]*)"`, "m"));
    if (!m) throw new Error(`core/masking.py không có hằng ${ten}`);
    ra.push(m[1]);
  }
  // Hai hằng ấy là **lý do**, dấu che là `[<trường>:<lý do>]` (`dau_che_truong`).
  return ra.map((ly_do) => new RegExp(`\\[[a-z_]+:${ly_do}\\]`));
}

function mat_khau(tai_khoan) {
  const env = readFileSync(resolve(GOC_REPO, ".env"), "utf-8");
  const m = env.match(new RegExp(`^DEMO_MAT_KHAU_${tai_khoan.toUpperCase()}=(.*)$`, "m"));
  if (!m) throw new Error(`.env không có DEMO_MAT_KHAU_${tai_khoan.toUpperCase()}`);
  return m[1].trim();
}

/** Nhãn vai đọc **từ chính `web/src/api/phien.ts`**, không chép lại. */
function nhan_vai_cua_web() {
  const tho = readFileSync(resolve(GOC_REPO, "web/src/api/phien.ts"), "utf-8");
  const m = tho.match(/export const NHAN_VAI(?::[^=]*)? = \{(.*?)\n\};/s);
  if (!m) throw new Error("phien.ts không có bảng NHAN_VAI");
  return Object.fromEntries(
    [...m[1].matchAll(/^\s*([a-z_][a-z0-9_]*):\s*"([^"]*)"/gm)].map((x) => [x[1], x[2]]),
  );
}

function doc_tham_so(argv) {
  const ra = {
    goc: "http://103.69.194.185:3000",
    cau: CAU_GHIM,
    tai_khoan: "dev01",
    lan: 1,
    quy: QUY_GIAY,
  };
  const co_ten = {
    "--goc": "goc",
    "--cau": "cau",
    "--tai-khoan": "tai_khoan",
    "--lan": "lan",
    "--quy": "quy",
  };
  for (let i = 0; i < argv.length; i += 1) {
    const ten = co_ten[argv[i]];
    if (!ten) {
      // Bỏ qua im lặng một token mở đầu `--` là để `--lann 5` chạy với mặc
      // định rồi **tiêu tiền LLM thật** cho một lần chạy không đo thứ người gõ
      // muốn đo. Cùng lý lẽ đã chặn ca cờ thiếu giá trị ngay dưới.
      if (argv[i].startsWith("--")) {
        throw new Error(`cờ không nhận ra: ${argv[i]}; nhận ${Object.keys(co_ten).join(" ")}`);
      }
      continue;
    }
    // Cờ đứng cuối `argv` mà không có giá trị đi thẳng vào một URL
    // `undefined/dang-nhap` hay một câu hỏi `undefined` gửi tới máy chủ thật,
    // tức một lần chạy **tốn tiền LLM** cho một tham số gõ thiếu.
    const gia_tri = argv[i + 1];
    if (gia_tri === undefined || gia_tri.startsWith("--")) {
      throw new Error(`${argv[i]} thiếu giá trị`);
    }
    i += 1;
    ra[ten] = ten === "lan" || ten === "quy" ? Number(gia_tri) : gia_tri;
  }
  if (!Number.isInteger(ra.lan) || ra.lan < 1) throw new Error(`--lan phải là số nguyên >= 1`);
  if (!Number.isFinite(ra.quy) || ra.quy <= 0) throw new Error(`--quy phải là số giây > 0`);
  return ra;
}

const ts = doc_tham_so(process.argv.slice(2));
const NHAN_VAI = nhan_vai_cua_web();
const HO_DAU_CHE_NGOAI_VAI = hai_ho_dau_che_ngoai_vai();

function nhan(vai) {
  const ra = NHAN_VAI[vai];
  if (ra === undefined) throw new Error(`vai "${vai}" không có nhãn trong web/src/api/phien.ts`);
  return ra;
}

let so_fail = 0;
let so_pass = 0;
let so_canh_bao = 0;
function ghi(ten, dat, chi_tiet = "") {
  if (dat) so_pass += 1;
  else so_fail += 1;
  console.log(`  ${dat ? "PASS" : "FAIL"}  ${ten}${dat ? "" : `  <- ${chi_tiet}`}`);
}
function canh_bao(cau) {
  so_canh_bao += 1;
  console.log(`  WARN  ${cau}`);
}

/** Bảng tần suất cộng dồn qua mọi lần chạy.
 *
 *  `luot` đếm **mọi** lượt, còn `luot_dang_le_tra_loi_duoc` là mẫu số của
 *  `tu_choi_bat_thuong`: nhịp 3 (`sale_ba`) **luôn** bị từ chối theo thiết kế,
 *  nên gộp nó vào mẫu số là chia một tử số của hai nhịp cho một mẫu số của ba,
 *  tức một tỷ lệ nhỏ hơn thật một phần ba mà không ai thấy. */
const tan_suat = {
  luot: 0,
  luot_dang_le_tra_loi_duoc: 0,
  tu_choi_bat_thuong: 0,
  dau_che_ngoai_vai: 0,
  ghep_manh: 0,
};
/** Thời gian từng nhịp của từng lần chạy, giây. */
const cac_lan = [];

const trinh_duyet = await chromium.launch();
const page = await trinh_duyet.newPage({ viewport: { width: RONG, height: 900 } });

let hong = null;
try {
  await page.goto(`${ts.goc}/dang-nhap`);
  await page.fill("#o_tai_khoan", ts.tai_khoan);
  await page.fill("#o_mat_khau", mat_khau(ts.tai_khoan));
  const [phan_hoi_toi] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/auth/toi") && r.status() === 200),
    page.click("button[type=submit]"),
  ]);
  const vai_that = (await phan_hoi_toi.json()).vai;
  await page.waitForSelector("[data-chip-vai]");
  console.log(`\n# diễn tập ${ts.lan} lần · ${await page.textContent("[data-chip-vai]")} @ ${ts.goc}`);
  console.log(`# câu ghim: ${ts.cau}`);
  console.log(`# quỹ thời gian: ${ts.quy} giây cho ba nhịp\n`);

  /** Hỏi một câu, trả về `{envelope, giay}`. Đồng hồ đo **từ lúc bấm Gửi tới
   *  lúc lượt hiện xong trên màn**, không tới lúc phản hồi HTTP về: thứ hội
   *  đồng chờ là màn hình, không là một gói tin. */
  async function hoi(cau) {
    const truoc = await page.locator("[data-luot]").count();
    const cho = page.waitForResponse(
      (r) => r.url().endsWith("/api/hoi-dap") && r.request().method() === "POST",
      { timeout: 400000 },
    );
    const bat_dau = Date.now();
    await page.fill("[data-o-hoi]", cau);
    await page.click("[data-nut-gui]");
    const phan_hoi = await cho;
    await page.waitForFunction(
      (n) => {
        // `[data-luot]:last-of-type` là **sai**: `ManChat` xen một
        // `[data-moc-doi-vai]` cùng thẻ `<div>` giữa các lượt, nên sau một lần
        // đổi vai selector ấy không khớp gì, mệnh đề phủ định thành đúng, và
        // phép chờ trả về **trước khi** lượt vẽ xong - tức đồng hồ đo thiếu
        // đúng ở nhịp 2 và nhịp 3.
        const cac = document.querySelectorAll("[data-luot]");
        if (cac.length !== n) return false;
        return !cac[cac.length - 1].querySelector("[data-dang-cho]");
      },
      truoc + 1,
      { timeout: 400000 },
    );
    const giay = (Date.now() - bat_dau) / 1000;
    // Một thân không phải 200 (`waitForResponse` không lọc status) đi thẳng vào
    // `envelope.citations.length` và một `TypeError` giết mọi vòng `--lan` còn
    // lại cùng **cả hai** bảng tổng kết - tức một lần chạy đã trả tiền LLM mà
    // không in ra số nào. Kiểm hình rồi trả một envelope rỗng để nơi gọi `ghi()`
    // FAIL và đi tiếp.
    if (phan_hoi.status() !== 200) {
      ghi(`lượt hỏi trả HTTP ${phan_hoi.status()}`, false, (await phan_hoi.text()).slice(0, 200));
      return { envelope: { refused: null, answer: null, citations: [], meta: {} }, giay };
    }
    const envelope = await phan_hoi.json();
    if (typeof envelope !== "object" || envelope === null || !Array.isArray(envelope.citations)) {
      ghi("thân /hoi-dap sai hình", false, JSON.stringify(envelope).slice(0, 200));
      return { envelope: { refused: null, answer: null, citations: [], meta: {} }, giay };
    }
    return { envelope, giay };
  }

  async function doi_vai(vai) {
    const bat_dau = Date.now();
    // Chờ chip **đổi khỏi văn bản trước đó**, không chỉ `includes(nhãn mới)`:
    // nếu nhãn vai mới là chuỗi con của nhãn đang có (một bảng chính sách thêm
    // "DevOps" cạnh "DevOps cấp 2" là đủ), phép chờ cũ trả về ngay lập tức và
    // lượt kế đo trên vai cũ.
    const chip_truoc = (await page.textContent("[data-chip-vai]")) ?? "";
    await page.click("[data-nut-xem-nhu]");
    await page.waitForSelector("[data-menu-vai]");
    if ((await page.locator(`[data-muc-vai="${vai}"]`).count()) === 0) {
      const co = await page
        .locator("[data-muc-vai]")
        .evaluateAll((cac) => cac.map((e) => e.getAttribute("data-muc-vai")));
      throw new Error(`bảng chính sách đang chạy không có vai ${vai}; nó có ${co.join(", ")}`);
    }
    await page.click(`[data-muc-vai="${vai}"]`);
    await page.waitForFunction(
      ([v, truoc]) => {
        const chu = document.querySelector("[data-chip-vai]")?.textContent ?? "";
        return chu !== truoc && chu.includes(v);
      },
      [nhan(vai), chip_truoc],
      { timeout: 60000 },
    );
    return (Date.now() - bat_dau) / 1000;
  }

  async function thoat_xem_nhu() {
    const chip_truoc = (await page.textContent("[data-chip-vai]")) ?? "";
    await page.click("[data-nut-xem-nhu]");
    await page.waitForSelector("[data-menu-vai]");
    await page.click("[data-thoat-xem-nhu]");
    await page.waitForFunction(
      ([v, truoc]) => {
        const chu = document.querySelector("[data-chip-vai]")?.textContent ?? "";
        return chu !== truoc && chu.includes(v);
      },
      [nhan(vai_that), chip_truoc],
      { timeout: 60000 },
    );
  }

  /** Đếm ba thứ trên một envelope, cộng dồn vào bảng tần suất.
   *
   *  `bi_chan` khai lượt ấy thuộc một vai mà bảng chính sách chặn sạch (nhịp
   *  3): nó ra khỏi **cả** tử số lẫn mẫu số của cột từ chối. */
  function dem(env, { bi_chan = false } = {}) {
    tan_suat.luot += 1;
    // `tu_khoa_rong` **không** đọc được từ response (AD-8: lý do chỉ nằm trong
    // audit). Dấu duy nhất nhìn thấy được từ ngoài là một lượt từ chối mà vai
    // ấy đáng lẽ trả lời được; ta đếm mọi lượt từ chối **của vai không bị
    // chặn** rồi nói ra rằng con số này là một cận trên, và `docker compose
    // logs api` cộng `audit_log` là chỗ tách ba lý do.
    const tu_choi_bat_thuong = !bi_chan && env.refused === true;
    if (!bi_chan) {
      tan_suat.luot_dang_le_tra_loi_duoc += 1;
      if (tu_choi_bat_thuong) tan_suat.tu_choi_bat_thuong += 1;
    }
    const ans = typeof env.answer === "string" ? env.answer : "";
    const co_dau_che_la = HO_DAU_CHE_NGOAI_VAI.some((mau) => mau.test(ans));
    if (co_dau_che_la) tan_suat.dau_che_ngoai_vai += 1;
    // Ghép mảnh: lượt có **ít nhất một** citation L1 che một vai ngoài `owner`,
    // mà `answer` lại không mang dấu che nào - tức câu trả lời nói trọn vẹn
    // trong khi dòng hạn chế ngay dưới khẳng định một phần bị hạn chế. Đây là
    // một **dấu hiệu** đọc bằng máy, không một phép chứng minh; nó nêu đúng
    // lượt để người soát đọc bằng mắt.
    const che_ngoai_owner = (env.citations ?? []).some(
      (c) => c.level === "L1" && (c.masked_slots ?? []).some((s) => s !== "owner"),
    );
    const co_slab = /\[[a-z_]+:[^\]]+\]/.test(ans);
    if (che_ngoai_owner && !co_slab) tan_suat.ghep_manh += 1;
    return { tu_choi_bat_thuong, co_dau_che_la, ghep_manh: che_ngoai_owner && !co_slab };
  }

  for (let lan = 1; lan <= ts.lan; lan += 1) {
    console.log(`--- lần ${lan}/${ts.lan}`);

    // --- Nhịp 1 -------------------------------------------------------------
    const n1 = await hoi(ts.cau);
    dem(n1.envelope);
    const mo = Date.now();
    await page.click("[data-nut-do-thi]");
    await page.waitForSelector('[data-vung-do-thi][data-da-ve="1"], [data-do-thi-trong]', {
      timeout: 120000,
    });
    const giay_1 = n1.giay + (Date.now() - mo) / 1000;
    console.log(
      `  nhịp 1 (${nhan(vai_that)}): ${giay_1.toFixed(1)}s · ` +
        `${n1.envelope.citations.length} citation · từ chối=${n1.envelope.refused}`,
    );
    ghi(
      "nhịp 1 trả lời được và có ít nhất một nguồn",
      n1.envelope.refused === false && n1.envelope.citations.length > 0,
      `refused=${n1.envelope.refused} citations=${n1.envelope.citations.length}`,
    );

    // --- Nhịp 2 -------------------------------------------------------------
    const doi_2 = await doi_vai(VAI_NHIP_2);
    const n2 = await hoi(ts.cau);
    const d2 = dem(n2.envelope);
    const giay_2 = doi_2 + n2.giay;
    const so_han_che = await page.locator("[data-han-che]").count();
    const so_slab = await page.locator("[data-slab]").count();
    console.log(
      `  nhịp 2 (${nhan(VAI_NHIP_2)}): ${giay_2.toFixed(1)}s · ` +
        `${n2.envelope.citations.length} citation · ${so_slab} slab · ${so_han_che} dòng hạn chế`,
    );
    ghi(
      "nhịp 2 chèn divider và giữ nguyên lượt trước",
      (await page.locator("[data-moc-doi-vai]").count()) >= 1 &&
        (await page.locator("[data-luot]").count()) === 2,
      `mốc=${await page.locator("[data-moc-doi-vai]").count()} lượt=${await page.locator("[data-luot]").count()}`,
    );
    // Nhịp 2 là climax của bài demo, và đúng chỗ một lượt `tu_khoa_rong` giết
    // buổi diễn: vai này **phải** trả lời được, và câu trả lời phải mang slab
    // cùng đúng một dòng hạn chế. Không có mệnh đề này thì một nhịp 2 bị từ
    // chối chỉ hiện ra thành một dòng log, không một FAIL.
    ghi(
      "nhịp 2 trả lời được, có slab bôi đen và đúng một dòng hạn chế",
      n2.envelope.refused === false && so_slab > 0 && so_han_che === 1,
      `refused=${n2.envelope.refused} slab=${so_slab} dòng hạn chế=${so_han_che}`,
    );
    if (d2.ghep_manh) {
      canh_bao(
        "nhịp 2: có citation L1 che một vai ngoài `owner` mà `answer` không mang dấu che nào" +
          " - đọc lại câu trả lời bằng mắt, đây là hình dạng của hiện tượng ghép mảnh",
      );
    }

    // --- Nhịp 3 -------------------------------------------------------------
    const doi_3 = await doi_vai(VAI_NHIP_3);
    const n3 = await hoi(ts.cau);
    dem(n3.envelope, { bi_chan: true });
    const giay_3 = doi_3 + n3.giay;
    console.log(`  nhịp 3 (${nhan(VAI_NHIP_3)}): ${giay_3.toFixed(1)}s · từ chối=${n3.envelope.refused}`);
    ghi(
      "nhịp 3 là lượt từ chối, 0 trích dẫn, drawer về empty-state",
      n3.envelope.refused === true &&
        n3.envelope.citations.length === 0 &&
        (await page.locator("[data-do-thi-trong]").count()) === 1,
      `refused=${n3.envelope.refused} citations=${n3.envelope.citations.length}`,
    );
    ghi(
      "lịch sử ba lượt và hai divider còn nguyên trên màn ở nhịp cuối",
      (await page.locator("[data-luot]").count()) === 3 &&
        (await page.locator("[data-moc-doi-vai]").count()) === 2,
      `lượt=${await page.locator("[data-luot]").count()} mốc=${await page.locator("[data-moc-doi-vai]").count()}`,
    );

    const tong = giay_1 + giay_2 + giay_3;
    cac_lan.push({ lan, giay_1, giay_2, giay_3, tong });
    console.log(`  tổng: ${tong.toFixed(1)}s / quỹ ${ts.quy}s`);
    if (tong > ts.quy) {
      canh_bao(`lần ${lan} quá quỹ ${ts.quy}s: ${tong.toFixed(1)}s (NFR-08 không đặt SLA, đây là quỹ demo)`);
    }

    if (lan < ts.lan) {
      // Về vai thật và tải lại trang: mỗi lần chạy phải bắt đầu từ một chat
      // trống, nếu không lần thứ hai đo trên một màn đã có sáu lượt.
      await thoat_xem_nhu();
      await page.reload();
      await page.waitForSelector("[data-chip-vai]");
    }
  }

  await page.screenshot({
    path: resolve(GOC_REPO, "eval", "anh_bang_chung", "kiem-tay-4-7-dien-tap.png"),
  });

  // --- Bảng thời gian và bảng tần suất ---------------------------------------

  console.log(`\n# thời gian từng nhịp (giây)`);
  console.log(`  lần   nhịp 1   nhịp 2   nhịp 3    tổng`);
  for (const l of cac_lan) {
    console.log(
      `  ${String(l.lan).padStart(3)}   ${l.giay_1.toFixed(1).padStart(6)}   ` +
        `${l.giay_2.toFixed(1).padStart(6)}   ${l.giay_3.toFixed(1).padStart(6)}   ` +
        `${l.tong.toFixed(1).padStart(5)}`,
    );
  }
  const tong_cac_lan = cac_lan.map((l) => l.tong);
  const tb = tong_cac_lan.reduce((a, b) => a + b, 0) / tong_cac_lan.length;
  console.log(
    `  trung bình ${tb.toFixed(1)}s · thấp nhất ${Math.min(...tong_cac_lan).toFixed(1)}s` +
      ` · cao nhất ${Math.max(...tong_cac_lan).toFixed(1)}s · quỹ ${ts.quy}s`,
  );

  console.log(`\n# tần suất trên ${tan_suat.luot} lượt hỏi`);
  console.log(
    `  lượt từ chối của vai đáng lẽ trả lời được:` +
      ` ${tan_suat.tu_choi_bat_thuong}/${tan_suat.luot_dang_le_tra_loi_duoc}` +
      ` (nhịp 1 và 2; nhịp 3 luôn bị chặn theo thiết kế nên nó ngoài cả tử số` +
      ` lẫn mẫu số). Đây là cận trên của tu_khoa_rong: ba lý do chỉ tách được` +
      ` trong audit_log, xem kiem-tay-4-7.md muc 1.`,
  );
  console.log(
    `  \`answer\` mang dấu che ngoài vai slot: ${tan_suat.dau_che_ngoai_vai}` +
      ` (hai họ [description:l2_only] / [neighbor_id:no_key], khoản sổ nợ 4-7)`,
  );
  console.log(`  dấu hiệu ghép mảnh nhìn thấy được: ${tan_suat.ghep_manh}`);
} catch (loi) {
  // Một exception là một lần chạy **hỏng**, không một lần chạy 0 FAIL.
  hong = loi;
  console.log(`  FAIL  lần chạy dội: ${loi instanceof Error ? loi.message : String(loi)}`);
  so_fail += 1;
} finally {
  await trinh_duyet.close();
  console.log(`\n${so_pass} PASS · ${so_fail} FAIL · ${so_canh_bao} WARN`);
  if (hong !== null) console.error(hong);
  process.exit(so_fail === 0 && hong === null ? 0 : 1);
}
