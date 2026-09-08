// Bố cục đồ thị: hàm thuần, **tất định**, chỉ số học (story 4.6).
//
// Cytoscape có `cose` và `random`; cả hai cho hai hình khác nhau giữa buổi diễn
// tập và buổi thật, đúng thứ AC thứ ba của story cấm. Nên vị trí từng node tính
// ở đây rồi Cytoscape chạy `layout: {name: "preset"}` - nó chỉ đặt node vào chỗ
// đã cho và fit khung nhìn, không mô phỏng lực, không gieo số ngẫu nhiên nào.
//
// Phép canh là hai phép quét nguồn của `tests/test_web_khung.py` nhóm (13):
// `web/src` không được chứa `Math.random`/`Date.now`/`crypto.getRandomValues`,
// và `VungDoThi.tsx` chỉ được khai đúng tên layout `preset`. Rẻ hơn một phép so
// ảnh, và nó bắt được cả lần sửa "chỉ thêm một layout cho đẹp" ở story sau.

import type { Khung } from "./do_thi_khung";

/** Bán kính vòng hyperedge, đơn vị của không gian bố cục. Số của mockup
 *  (`r=74` cho vòng đang hover, `r=52` cho vòng thường); ở đây mọi vòng cùng
 *  cỡ vì cỡ không được mã hóa một trạng thái quyền nào. */
export const BAN_KINH_VONG = 74;

/** Khoảng cách từ tâm vòng tới đỉnh riêng của nó. */
export const BAN_KINH_DINH = 152;

/** Khoảng cách tối thiểu giữa tâm hai vòng cạnh nhau. Bằng hai lần
 *  `BAN_KINH_DINH` trừ một phần chồng lấn chấp nhận được: hai vành đỉnh chạm
 *  nhau ở rìa thì vẫn đọc được, hai vòng chồng nhau thì không. */
export const CACH_HAI_VONG = 300;

/** Bước lệch của hai đỉnh dùng chung cùng một cặp vòng. */
export const LECH_DINH_CHUNG = 58;

/** Bước so le bán kính giữa hai đỉnh cạnh nhau, để nhãn dài không đè nhau. */
export const SO_LE_DINH = 46;

/** Cung mà các đỉnh riêng của một vòng trải ra khi đồ thị có nhiều vòng: hướng
 *  ra ngoài, tránh phía tâm đồ thị nơi các vòng khác đứng. */
const CUNG_RA_NGOAI = Math.PI * 1.5;

export type ViTri = { x: number; y: number };

/** Vị trí theo **mã hiển thị**: `HE-nn` cho vòng, `en-k` hay `HE-nn#slot` cho
 *  đỉnh. Không id thật nào đi tới đây. */
export type BoCuc = Record<string, ViTri>;

function lam_tron(v: number): number {
  return Math.round(v * 100) / 100;
}

/** Bán kính của đường tròn xếp các tâm vòng. Một vòng thì tâm ở gốc. */
export function ban_kinh_vanh_vong(so_vong: number): number {
  if (so_vong <= 1) return 0;
  if (so_vong === 2) return CACH_HAI_VONG / 2;
  return CACH_HAI_VONG / 2 / Math.sin(Math.PI / so_vong);
}

/** Các góc đặt đỉnh quanh một tâm vòng.
 *
 *  Một vòng duy nhất thì đỉnh trải đủ 360 độ; nhiều vòng thì trải trên một
 *  cung hướng **ra ngoài** (tâm cung là hướng từ tâm đồ thị tới tâm vòng), để
 *  đỉnh riêng không chui vào giữa đám vòng. */
function goc_quanh_vong(huong: number, so_dinh: number, day_du: boolean): number[] {
  if (so_dinh <= 0) return [];
  if (so_dinh === 1) return [huong];
  if (day_du) {
    return Array.from({ length: so_dinh }, (_, j) => huong + (2 * Math.PI * j) / so_dinh);
  }
  return Array.from(
    { length: so_dinh },
    (_, j) => huong - CUNG_RA_NGOAI / 2 + (CUNG_RA_NGOAI * j) / (so_dinh - 1),
  );
}

/** Vị trí mọi node của một khung, tất định theo đúng nội dung khung.
 *
 *  Vòng xếp đều trên một đường tròn theo thứ tự `HE-nn`, bắt đầu từ 12 giờ.
 *  Đỉnh **riêng** của một vòng tỏa quanh chính vòng ấy; đỉnh **dùng chung**
 *  giữa nhiều vòng nằm ở trọng tâm các vòng nối vào nó, tức nằm giữa chúng -
 *  đó là chỗ nó nói được điều duy nhất nó có để nói, rằng hai fact chạm cùng
 *  một thực thể. */
export function bo_cuc(khung: Khung): BoCuc {
  const ra: BoCuc = {};
  const so_vong = khung.vong.length;
  const ban_kinh = ban_kinh_vanh_vong(so_vong);
  const tam: Record<string, ViTri> = {};
  khung.vong.forEach((v, i) => {
    const goc = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(so_vong, 1);
    const diem = {
      x: ban_kinh * Math.cos(goc),
      y: ban_kinh * Math.sin(goc),
    };
    tam[v.ma] = diem;
    ra[v.ma] = { x: lam_tron(diem.x), y: lam_tron(diem.y) };
  });

  // Vòng nào nối vào đỉnh nào, theo thứ tự cạnh (đã tất định).
  const vong_cua_dinh = new Map<string, string[]>();
  for (const c of khung.canh) {
    const cu = vong_cua_dinh.get(c.den) ?? [];
    if (!cu.includes(c.tu)) cu.push(c.tu);
    vong_cua_dinh.set(c.den, cu);
  }

  const rieng = new Map<string, string[]>();
  const chung: string[] = [];
  for (const d of khung.dinh) {
    const cac_vong = vong_cua_dinh.get(d.ma) ?? [];
    if (cac_vong.length === 1) {
      const ds = rieng.get(cac_vong[0]) ?? [];
      ds.push(d.ma);
      rieng.set(cac_vong[0], ds);
      continue;
    }
    if (cac_vong.length > 1) chung.push(d.ma);
  }

  khung.vong.forEach((v, i) => {
    const ds = rieng.get(v.ma) ?? [];
    const goc_vong = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(so_vong, 1);
    const cac_goc = goc_quanh_vong(goc_vong, ds.length, so_vong <= 1);
    ds.forEach((ma, j) => {
      const r = BAN_KINH_DINH + (j % 2) * SO_LE_DINH;
      ra[ma] = {
        x: lam_tron(tam[v.ma].x + r * Math.cos(cac_goc[j])),
        y: lam_tron(tam[v.ma].y + r * Math.sin(cac_goc[j])),
      };
    });
  });

  // Đỉnh dùng chung: trọng tâm các vòng nối vào nó, lệch dần theo phương vuông
  // góc khi nhiều đỉnh rơi vào **cùng một chỗ** (nếu không chúng chồng khít
  // lên nhau thành một chấm).
  //
  // Bộ đếm lệch keyed theo **trọng tâm đã làm tròn**, không theo tập vòng. Với
  // bốn vòng xếp đều trên một đường tròn, một đỉnh chung của vòng 1&3 và một
  // đỉnh chung của vòng 2&4 là **hai nhóm khác nhau** nhưng có **cùng** trọng
  // tâm là tâm hình: keyed theo tập vòng thì cả hai đều `k = 0` và hai node vẽ
  // chồng khít. Keyed theo chỗ đứng thì phép lệch làm đúng việc nó sinh ra để
  // làm - tách hai thứ ở cùng một chỗ.
  const dem_cho = new Map<string, number>();
  for (const ma of chung) {
    const cac_vong = vong_cua_dinh.get(ma) ?? [];
    let x = 0;
    let y = 0;
    for (const mv of cac_vong) {
      x += tam[mv].x;
      y += tam[mv].y;
    }
    x /= cac_vong.length;
    y /= cac_vong.length;
    const khoa = `${lam_tron(x)}|${lam_tron(y)}`;
    const k = dem_cho.get(khoa) ?? 0;
    dem_cho.set(khoa, k + 1);
    // Phương vuông góc với đoạn nối hai vòng đầu tiên của nhóm.
    const a = tam[cac_vong[0]];
    const b = tam[cac_vong[1]];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dai = Math.hypot(dx, dy) || 1;
    const lech = k * LECH_DINH_CHUNG;
    ra[ma] = {
      x: lam_tron(x + (-dy / dai) * lech),
      y: lam_tron(y + (dx / dai) * lech),
    };
  }

  return ra;
}
