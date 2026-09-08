// Cửa duy nhất của tuyến đồ thị phía `web/` (story 4.6, FR-19, ADR-018).
//
// **Module duy nhất của `web/` thấy id hyperedge thật.** Thân `POST /do-thi`
// mang `he-` + 24 hex ở `graph.nodes[].id` và ở id của node che
// (`<id_hyperedge>#<slot>`); `web/src/app/do_thi_khung.ts` đổi trọn chúng sang
// mã hiển thị **trước** khi bất kỳ thứ gì chạm React hay Cytoscape, nên id thật
// không tồn tại ở tầng dưới và không ai lỡ tay render nó. Đó là luật "id
// hyperedge thật không vào DOM" của 4.4 dựng thành **cơ chế** thay vì một phép
// quét trên từng chỗ chèn JSX.
//
// Hợp đồng với `api/` khai thành hằng ở đây rồi `tests/test_web_khung.py` nhóm
// (13) ghim từng cái với chính nguồn `api/do_thi.py`, `api/hoi_dap.py`,
// `api/main.py` và `adapters/do_thi.py` - cùng khuôn mà 4.2 ghim ba trường đăng
// nhập và 4.3 ghim envelope, và vì cùng một lý do: e2e mock trọn tuyến nên nó
// xanh với bất kỳ tên nào, còn phía `api/` không biết `web/` gửi gì.

import { VAI_SLOT } from "@/nhan";

import { goi, LoiApi } from "./goi";
import { MUC_TRICH_DAN, type MucTietLo, type TrichDan } from "./hoi_dap";

/** Mã của **client** cho một thân 200 sai lược đồ đồ thị; không phải mã của
 *  `api/` (cùng họ với `MA_ENVELOPE_LA` của `hoi_dap.ts` và `MA_MANG` của
 *  `goi.ts`).
 *
 *  Mã riêng chứ không dùng lại `ENVELOPE_LA`: hai tuyến khác nhau và người đọc
 *  `data-ma-loi` trong drawer phải biết tuyến nào đã trôi hợp đồng. Và một đồ
 *  thị sai hình là **hộp đỏ**, không phải một empty-state: empty-state nói
 *  "không có gì để vẽ" và nó phải giữ đúng một nghĩa, nếu không nó thành chỗ
 *  một lỗi hệ thống nấp sau một câu trung tính (NFR-10). */
export const MA_DO_THI_LA = "DO_THI_LA";

/** Mã của **client** cho một lần **vẽ** hỏng: chunk Cytoscape không tải được,
 *  hay constructor dội vì dữ liệu hỏng.
 *
 *  Khác `DO_THI_LA` là thân sai hình, và khác cả hai là quan trọng khi đọc
 *  `data-ma-loi`: một cái nói "máy chủ trả sai lược đồ", cái kia nói "thân
 *  đúng mà trình duyệt không vẽ được". Không có mã này thì một lần vẽ hỏng là
 *  một unhandled rejection cộng một canvas trắng, tức đúng chỗ NFR-10 đòi
 *  phân biệt được lỗi hệ thống với "không có gì để vẽ". */
export const MA_DO_THI_VE_HONG = "DO_THI_VE_HONG";

/** Tuyến đồ thị theo quyền (`@cua_dong.post` của `api/main.py`), cần Bearer. */
export const TUYEN_DO_THI = "/do-thi";

/** Trường **duy nhất** của thân request. `ThanDoThi` khai `extra="forbid"`, nên
 *  một tên lệch là 400 `THAN_YEU_CAU_LA` cho mọi lượt mở drawer. */
export const TRUONG_HYPEREDGE_IDS = "hyperedge_ids";

/** Trần số id của một lượt, **bản chép của `api.hoi_dap.SO_ID_TOI_DA`**.
 *
 *  `web/` **không** cắt danh sách theo trần này, và đó là chủ ý: cắt là một
 *  phép lọc thứ hai đứng ngoài cửa quyền, đúng thứ mà cả 4.4 lẫn story này
 *  cấm. Hằng ở đây để `tests/test_web_khung.py` ghim hai chiều với `api/`, và
 *  để người đọc biết một lượt hơn trần sẽ ra 400 `DANH_SACH_ID_QUA_DAI` (hộp
 *  đỏ trong drawer) chứ không ra một đồ thị thiếu vòng mà không ai nói gì. */
export const SO_ID_TOI_DA = 200;

/** Hai khóa của `graph`, tập đóng (`api.hoi_dap.KHOA_GRAPH`). */
export const KHOA_GRAPH = ["nodes", "edges"] as const;

/** Sáu khóa đóng của một node hyperedge (`adapters.do_thi.KHOA_NODE_HYPEREDGE`). */
export const KHOA_NODE_HYPEREDGE = [
  "id",
  "kind",
  "label",
  "level",
  "scope",
  "content_type",
] as const;

/** Bốn khóa đóng của một node entity (`adapters.do_thi.KHOA_NODE_ENTITY`). */
export const KHOA_NODE_ENTITY = ["id", "kind", "label", "masked"] as const;

/** Ba khóa đóng của một cạnh (`adapters.do_thi.KHOA_CANH`). */
export const KHOA_CANH = ["source", "target", "slot"] as const;

/** Hai giá trị của `kind` (`adapters.do_thi.KIND_HYPEREDGE`/`KIND_ENTITY`).
 *  Client phân biệt hai loại node bằng đúng trường này, không bằng hình id. */
export const KIND_HYPEREDGE = "hyperedge";
export const KIND_ENTITY = "entity";

/** Dấu nối giữa id hyperedge và tên vai trong id một node che
 *  (`adapters.do_thi.DAU_NOI_NODE_CHE`). */
export const DAU_NOI_NODE_CHE = "#";

export type NodeHyperedge = {
  id: string;
  kind: typeof KIND_HYPEREDGE;
  /** `core.facts.cau_fact` dựng từ **đúng** giá trị đã che và đã lọc của vòng
   *  này (ADR-018). Dạng "chủ thể: App01; nguyên nhân: [cause:masked]" - dài,
   *  nên nó là chữ của legend chứ không phải chữ trong vòng. */
  label: string;
  level: MucTietLo;
  scope: string;
  content_type: string;
};

export type NodeEntity = {
  id: string;
  kind: typeof KIND_ENTITY;
  /** Tên thật, hoặc một dấu che do `core.masking` sinh. `masked` nói là cái
   *  nào; `web/` **không** parse dấu che ở đây (một bộ đọc ngược dấu che là bản
   *  thứ hai của cùng một luật, ADR-018 quyết định 2). */
  label: string;
  masked: boolean;
};

export type NodeDoThi = NodeHyperedge | NodeEntity;

export type CanhDoThi = {
  source: string;
  target: string;
  slot: string;
};

/** `graph` của envelope: hai mảng, hình dạng đóng của AD-8. */
export type DoThiThan = {
  nodes: NodeDoThi[];
  edges: CanhDoThi[];
};

function chuoi_that(gia_tri: unknown): boolean {
  return typeof gia_tri === "string" && gia_tri.trim() !== "";
}

function du_khoa(muc: Record<string, unknown>, khoa: readonly string[]): boolean {
  return khoa.every((k) => k in muc);
}

/** Một node hyperedge có đúng sáu khóa và đúng kiểu từng trường không. */
function la_node_hyperedge(n: Record<string, unknown>): boolean {
  if (!du_khoa(n, KHOA_NODE_HYPEREDGE)) return false;
  if (!chuoi_that(n.id) || !chuoi_that(n.label)) return false;
  if (!MUC_TRICH_DAN.includes(n.level as MucTietLo)) return false;
  return chuoi_that(n.scope) && chuoi_that(n.content_type);
}

/** Một node entity có đúng bốn khóa và đúng kiểu từng trường không. */
function la_node_entity(n: Record<string, unknown>): boolean {
  if (!du_khoa(n, KHOA_NODE_ENTITY)) return false;
  if (!chuoi_that(n.id) || !chuoi_that(n.label)) return false;
  return typeof n.masked === "boolean";
}

function la_node(muc: unknown): boolean {
  if (typeof muc !== "object" || muc === null) return false;
  const n = muc as Record<string, unknown>;
  if (n.kind === KIND_HYPEREDGE) return la_node_hyperedge(n);
  if (n.kind === KIND_ENTITY) return la_node_entity(n);
  return false;
}

function la_canh(muc: unknown): boolean {
  if (typeof muc !== "object" || muc === null) return false;
  const c = muc as Record<string, unknown>;
  if (!du_khoa(c, KHOA_CANH)) return false;
  if (!chuoi_that(c.source) || !chuoi_that(c.target)) return false;
  return typeof c.slot === "string" && VAI_SLOT.includes(c.slot);
}

/** `graph` của thân trả về có đúng hình không.
 *
 *  Khuôn `la_envelope` của 4.3, và vì cùng một lý do: một thân sai hình là
 *  **lỗi hệ thống**, không phải một đồ thị rỗng. Vẽ nửa vời một đồ thị thiếu
 *  khóa là vẽ một hình mà không ai nói được nó thiếu gì, và ở một màn hình dựng
 *  ra để đọc phân quyền thì đó là chỗ tệ nhất để đoán.
 *
 *  Bốn phép kiểm, mỗi phép chặn một ca:
 *  - đủ hai khóa `KHOA_GRAPH` và cả hai là mảng;
 *  - mỗi node mang `kind` thuộc tập đóng hai giá trị, rồi đủ khóa của **loại
 *    đó** - `level` lạ là một vòng nói sai về quyền, `masked` không phải bool
 *    là một đỉnh che vẽ thành đỉnh thường (`"false"` truthy trong JS);
 *  - mỗi cạnh mang `slot` nằm trong danh mục 8 vai - nhãn dọc mũi tên đi qua
 *    `nhan_slot`, và một vai lạ hiện nguyên khóa snake_case trên máy chiếu;
 *  - **mọi cạnh nối hai node có mặt**, và đúng chiều hyperedge -> entity.
 *    `api.hoi_dap.dung_envelope` đã kiểm điều này bằng cách dựng lại
 *    `adapters.do_thi.DoThi`, nhưng Cytoscape **dội** khi một cạnh trỏ vào một
 *    node không tồn tại, nên phép kiểm ở đây là chỗ lỗi ấy thành một hộp đỏ có
 *    mã thay vì một exception giữa `useEffect`. */
export function la_do_thi(than: unknown): than is DoThiThan {
  if (typeof than !== "object" || than === null) return false;
  const t = than as Record<string, unknown>;
  if (!du_khoa(t, KHOA_GRAPH)) return false;
  if (!Array.isArray(t.nodes) || !Array.isArray(t.edges)) return false;
  if (!t.nodes.every(la_node)) return false;
  if (!t.edges.every(la_canh)) return false;
  const vong = new Set<string>();
  const dinh = new Set<string>();
  for (const n of t.nodes as NodeDoThi[]) {
    const dich = n.kind === KIND_HYPEREDGE ? vong : dinh;
    dich.add(n.id);
  }
  return (t.edges as CanhDoThi[]).every((c) => vong.has(c.source) && dinh.has(c.target));
}

/** Danh sách id hyperedge thật của một lượt, đúng thứ tự citation.
 *
 *  Ở đây chứ không ở drawer: đọc `citations[].id` là chạm id thật, và luật của
 *  story là id thật chỉ sống trong file này cùng `app/do_thi_khung.ts`. Một
 *  dòng `map` ở `DrawerDoThi.tsx` là một dòng đủ để id thật đi vào một
 *  component React, tức đi vào tầm với của một chỗ chèn JSX. */
export function ids_cua(citations: TrichDan[]): string[] {
  return citations.map((c) => c.id);
}

/** Lấy đồ thị của một danh sách id hyperedge. Trả `graph` đã kiểm hình; ném
 *  `LoiApi` cho mọi ca hỏng.
 *
 *  Server **lọc lại toàn bộ** theo token hiện tại (ADR-018), nên đổi vai là gọi
 *  lại đúng danh sách id ấy chứ không lọc lại phía client: một client tự vẽ là
 *  một client tự quyết đỉnh nào ngoài quyền. Danh sách rỗng vẫn là một request
 *  hợp lệ về phía `api/` (đồ thị rỗng, không chạm kho), nhưng drawer không gọi
 *  tới đây khi lượt không có citation nào - xem `DrawerDoThi`.
 *
 *  **Không trần thời gian** (NFR-08 không đặt SLA): luật cấm
 *  `setTimeout`/`AbortSignal` của 4.3 phủ cả file này. */
export async function lay_do_thi(hyperedge_ids: string[]): Promise<DoThiThan> {
  const than = await goi<unknown>(TUYEN_DO_THI, {
    than: { [TRUONG_HYPEREDGE_IDS]: hyperedge_ids },
  });
  const graph = (than as { graph?: unknown } | null)?.graph;
  if (!la_do_thi(graph)) throw new LoiApi(MA_DO_THI_LA, 200);
  return graph;
}
