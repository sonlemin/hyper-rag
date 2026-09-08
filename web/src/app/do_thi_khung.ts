// Đổi đồ thị của `POST /do-thi` sang **mã hiển thị** (story 4.6). Hàm thuần,
// không React, không Cytoscape, không kho.
//
// **Đây là biên giới, không phải một phép làm đẹp.** Id thật dừng ở file này:
//
//     he-3f9c…  (citation thứ 2)      -> HE-02
//     ent-a71…  (App01, gặp lần đầu)  -> en-1        (dùng chung giữa các vòng)
//     he-3f9c…#cause                  -> HE-02#cause (node che, không gộp)
//
// Ba lý do. Một, luật "id hyperedge thật không vào DOM" của 4.4 thành **cơ
// chế**: id thật không tồn tại ở tầng dưới, nên không ai lỡ tay render nó.
// Hai, `HE-nn` đã là ngôn ngữ chung của cite-row nên hover chỉ là một phép so
// chuỗi, không một bảng tra thứ hai. Ba, id trả về mà không có citation tương
// ứng (không xảy ra theo hợp đồng, nhưng một hàm thuần phải quyết) bị **bỏ**,
// và số bị bỏ đi ra ở `bi_bo`, thứ `VungDoThi` phơi thành `data-so-bo` để
// hai ca e2e khẳng định nó bằng 0 ở lượt thường và bằng 1 ở lượt dựng sẵn.
//
// Node che **không gộp** giữa hai vòng, đúng ADR-018 quyết định 2: gộp là kể
// rằng hai fact chung một thực thể bị che, và tên thứ đó đã che thì cái chung
// vẫn là nội dung.

import {
  DAU_NOI_NODE_CHE,
  KIND_HYPEREDGE,
  type DoThiThan,
  type NodeEntity,
  type NodeHyperedge,
} from "@/api/do_thi";
import { ma_hien_thi, type MucTietLo, type TrichDan } from "@/api/hoi_dap";

/** Nhãn của một đỉnh bị che. Đúng chuỗi mà `components.graph-entity-masked`
 *  khai, và **không** phải dấu che của server: `[cause:masked]` là chữ của
 *  ngữ cảnh LLM, còn trên màn thì EXPERIENCE.md chốt "KHÔNG hiện tên (nhãn
 *  ngoài thay bằng •••)". */
export const NHAN_DINH_CHE = "•••";

/** Số màu của dải vòng (`--mau-graph-ring-1..5`). Vòng thứ sáu quay vòng lại. */
export const SO_MAU_VONG = 5;

/** Tiền tố mã hiển thị của một đỉnh entity. Chữ thường để mắt phân biệt ngay
 *  với `HE-` của vòng, kể cả khi hai mã đứng cạnh nhau trong một tooltip. */
export const TIEN_TO_MA_DINH = "en-";

/** Trần ký tự của nhãn ngắn viết **trong** vòng. Chữ trong vòng và chữ ở legend
 *  là hai thứ khác nhau: `label` của node hyperedge là `core.facts.cau_fact`
 *  ("chủ thể: App01; triệu chứng: lỗi 502; nguyên nhân: [cause:masked]"), đúng
 *  thứ ADR-018 chốt và đúng thứ **không** nhét vừa một vòng tròn. */
export const DAI_NHAN_NGAN = 22;

/** Vai slot mà nhãn ngắn trong vòng rút ra từ đó. */
export const VAI_NHAN_NGAN = "subject";

export type VongKhung = {
  /** Mã hiển thị `HE-nn`, đánh theo thứ tự citation của **chính lượt này**. */
  ma: string;
  /** Chữ viết trong vòng dưới mã, rút từ đỉnh nối bằng vai `subject`; rỗng khi
   *  vòng không có đỉnh ấy (vai bị lọc, hay hyperedge không mang vai đó). */
  nhan_ngan: string;
  /** Câu fact đã che và đã lọc, chữ của **legend** chứ không của vòng. */
  label: string;
  level: MucTietLo;
  scope: string;
  content_type: string;
  /** Chỉ số màu trong dải `graph-ring-1..5` (1-based). */
  mau: number;
};

export type DinhKhung = {
  /** `en-k` cho đỉnh thấy được, `HE-nn#slot` cho đỉnh bị che. */
  ma: string;
  nhan: string;
  che: boolean;
};

export type CanhKhung = {
  /** Mã vòng. */
  tu: string;
  /** Mã đỉnh. */
  den: string;
  slot: string;
  che: boolean;
};

export type Khung = {
  vong: VongKhung[];
  dinh: DinhKhung[];
  canh: CanhKhung[];
  /** Số node hyperedge của thân trả về mà lượt này không có citation tương
   *  ứng. Theo hợp đồng nó luôn bằng 0; một hàm thuần vẫn phải quyết, và test
   *  khẳng định con số ấy thay vì tin vào lời hứa. */
  bi_bo: number;
};

/** Cắt một nhãn dài về `dai` ký tự, thêm dấu lược. Không cắt giữa khoảng trắng
 *  đầu cuối: nhãn đã `trim` trước khi vào đây. */
export function rut_ngan(van_ban: string, dai = DAI_NHAN_NGAN): string {
  const s = van_ban.trim();
  return s.length <= dai ? s : `${s.slice(0, dai - 1)}…`;
}

/** Tách id một node che thành (id hyperedge, vai). `null` khi không phải dạng
 *  ấy. Cắt ở dấu nối **cuối cùng** vì id hyperedge không chứa nó còn tên vai
 *  thì chắc chắn không. */
function tach_node_che(ma_node: string): { goc: string; slot: string } | null {
  const vi_tri = ma_node.lastIndexOf(DAU_NOI_NODE_CHE);
  if (vi_tri <= 0 || vi_tri === ma_node.length - 1) return null;
  return {
    goc: ma_node.slice(0, vi_tri),
    slot: ma_node.slice(vi_tri + 1),
  };
}

/** Đổi trọn một đồ thị sang mã hiển thị.
 *
 *  Thứ tự tất định ở cả ba mảng: vòng theo thứ tự citation của lượt (tức theo
 *  `HE-nn`), đỉnh theo lần xuất hiện đầu trong `nodes` của thân trả về, cạnh
 *  theo thứ tự `edges` của thân trả về - cả hai thứ tự sau đã tất định ở
 *  server (ADR-018, mục "Hình dạng"). Không sắp lại, không gộp, không bỏ một
 *  node nào ngoài ca "không có citation" nói ở trên. */
export function dung_khung(than: DoThiThan, citations: TrichDan[]): Khung {
  const ma_vong = new Map<string, string>();
  const mau_vong = new Map<string, number>();
  const thu_tu = new Map<string, number>();
  citations.forEach((c, i) => {
    const that = c.id;
    ma_vong.set(that, ma_hien_thi(i));
    mau_vong.set(that, (i % SO_MAU_VONG) + 1);
    thu_tu.set(that, i);
  });

  const vong: VongKhung[] = [];
  const goc_cua_vong = new Map<string, string>();
  let bi_bo = 0;
  for (const n of than.nodes) {
    if (n.kind !== KIND_HYPEREDGE) continue;
    const h = n as NodeHyperedge;
    const that = h.id;
    const ma = ma_vong.get(that);
    if (ma === undefined) {
      bi_bo += 1;
      continue;
    }
    goc_cua_vong.set(ma, that);
    vong.push({
      ma,
      nhan_ngan: "",
      label: h.label,
      level: h.level,
      scope: h.scope,
      content_type: h.content_type,
      mau: mau_vong.get(that) ?? 1,
    });
  }
  vong.sort((a, b) => (thu_tu.get(goc_cua_vong.get(a.ma) ?? "") ?? 0)
    - (thu_tu.get(goc_cua_vong.get(b.ma) ?? "") ?? 0));

  // Cạnh giữ lại là cạnh của một vòng còn giữ. Một cạnh trỏ từ một vòng đã bỏ
  // là một cạnh không còn đầu nào để vẽ, và Cytoscape dội khi gặp nó.
  const canh_giu = than.edges.filter((c) => ma_vong.has(c.source));

  // Đỉnh giữ lại là đỉnh có ít nhất một cạnh còn giữ trỏ tới. Đỉnh mồ côi
  // (chỉ nối vào một vòng đã bỏ) biến mất cùng vòng ấy.
  const dinh_can = new Set<string>();
  for (const c of canh_giu) {
    dinh_can.add(c.target);
  }

  const ma_dinh = new Map<string, string>();
  const dinh: DinhKhung[] = [];
  let dem_dinh = 0;
  for (const n of than.nodes) {
    if (n.kind === KIND_HYPEREDGE) continue;
    const e = n as NodeEntity;
    const that = e.id;
    if (!dinh_can.has(that) || ma_dinh.has(that)) continue;
    const che = e.masked;
    const tach = che ? tach_node_che(that) : null;
    const ma_goc = tach === null ? undefined : ma_vong.get(tach.goc);
    let ma: string;
    if (tach !== null && ma_goc !== undefined) {
      ma = `${ma_goc}${DAU_NOI_NODE_CHE}${tach.slot}`;
    } else {
      dem_dinh += 1;
      ma = `${TIEN_TO_MA_DINH}${dem_dinh}`;
    }
    ma_dinh.set(that, ma);
    dinh.push({ ma, nhan: che ? NHAN_DINH_CHE : e.label, che });
  }

  const che_cua_dinh = new Map<string, boolean>();
  for (const d of dinh) {
    che_cua_dinh.set(d.ma, d.che);
  }

  const canh: CanhKhung[] = [];
  for (const c of canh_giu) {
    const tu = ma_vong.get(c.source);
    const den = ma_dinh.get(c.target);
    if (tu === undefined || den === undefined) continue;
    canh.push({ tu, den, slot: c.slot, che: che_cua_dinh.get(den) === true });
  }

  // Nhãn ngắn trong vòng: rút từ đỉnh nối bằng vai `subject`, đã qua tầng che
  // nên một `subject` bị che ra `•••` chứ không ra tên thật.
  const nhan_theo_ma = new Map<string, string>();
  for (const d of dinh) {
    nhan_theo_ma.set(d.ma, d.nhan);
  }
  for (const c of canh) {
    if (c.slot !== VAI_NHAN_NGAN) continue;
    const v = vong.find((x) => x.ma === c.tu);
    if (v === undefined || v.nhan_ngan !== "") continue;
    v.nhan_ngan = rut_ngan(nhan_theo_ma.get(c.den) ?? "");
  }

  return { vong, dinh, canh, bi_bo };
}
