"use client";

import { useRouter } from "next/navigation";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type UIEvent,
} from "react";

import { LoiApi, MA_MANG } from "@/api/goi";
import { DAI_CAU_HOI_TOI_DA, hoi, type Envelope, type TrichDan } from "@/api/hoi_dap";
import { duong_het_phien, la_het_phien, nhan_vai, xoa_token } from "@/api/phien";
import { HopLoi } from "@/khung/HopLoi";
import { useCacLanDoiVai, usePhien } from "@/khung/KhungApp";
import { cac_manh, dien, MICROCOPY, type KhoaMicrocopy } from "@/microcopy";

import { DongHanChe } from "./DongHanChe";
import { DrawerDoThi, type LuotDrawer } from "./DrawerDoThi";
import { HoverDoThiProvider } from "./hover_do_thi";
import { KhoiNguon } from "./KhoiNguon";
import { nhom_cua, ThanCoSlab } from "./ThanCoSlab";

/** Bốn nấc của một lượt. Ba nấc kết thúc phải khác nhau về **cấu trúc DOM**,
 *  không chỉ khác màu: lượt trả lời mang `data-tra-loi`, lượt từ chối mang
 *  `data-tu-choi` và bỏ hẳn vế số trích dẫn, lượt lỗi là một `HopLoi` mang
 *  `data-ma-loi`. Một phép phân biệt chỉ bằng màu là phép phân biệt mất khi ai
 *  đó sửa CSS, và đây đúng là chỗ NFR-10 đòi nhìn thấy được. */
/** Khoảng cách tới đáy (px) mà dưới nó thì một lượt mới vẫn tự cuộn xuống. */
const NGUONG_DAY = 48;

/** Từ số ký tự này trở đi thì hiện bộ đếm dưới ô hỏi (90% trần). */
const NGUONG_DEM_KY_TU = Math.floor(DAI_CAU_HOI_TOI_DA * 0.9);

type KetCuc =
  | { loai: "dang_cho" }
  | { loai: "tra_loi"; envelope: Envelope }
  | { loai: "tu_choi"; envelope: Envelope }
  | { loai: "loi"; ma: string };

type Luot = {
  id: number;
  cau_hoi: string;
  /** Vai của **phiên lúc gửi**, ghi lại ngay khi gửi. Lượt đang chờ và lượt lỗi
   *  chưa có envelope nên dòng meta của chúng dùng vai này; lượt đã trả lời thì
   *  dùng `meta.role` của chính envelope (thứ server đã phân giải). Ghi lại lúc
   *  gửi để "xem như" của 4.5 không phải viết lại lượt cũ. */
  vai_gui: string;
  ket_cuc: KetCuc;
  /** Người dùng đã tự đặt khối nguồn của lượt này mở hay thu gọn chưa.
   *
   *  `null` là "chưa đặt": khi đó khối theo luật mặc định của EXPERIENCE.md -
   *  lượt trả lời **mới nhất** mở, lượt cũ thu gọn. Một `boolean` là lựa chọn
   *  của người dùng và nó **giữ nguyên** qua các lượt sau; nếu không, mở lại
   *  một lượt cũ rồi hỏi câu tiếp là nó tự đóng lại ngay dưới tay họ. */
  mo_nguon: boolean | null;
};

/** Mốc đổi vai: một **mục thật** trong danh sách, không một thứ suy ra từ hai
 *  lượt cạnh nhau.
 *
 *  EXPERIENCE.md nói "mỗi lần đổi vai chèn một divider", nên đổi hai lần liên
 *  tiếp mà không hỏi câu nào phải ra **hai** divider, đổi đi rồi đổi về cũng
 *  vậy, và bấm lại đúng vai đang mang cũng vậy. Suy từ chênh lệch `vai_gui`
 *  giữa hai lượt nuốt cả ba ca. `vai_gui` giữ nguyên vai trò 4.3 đặt cho nó và
 *  story này không viết lại nó. */
type MocDoiVai = {
  id: number;
  /** Vai **mới**, ghi lại lúc chèn: mốc là một dòng lịch sử, nên nó không được
   *  đọc lại vai hiện tại ở lần render sau. */
  vai: string;
};

/** Một mục của danh sách: một lượt hỏi, hay một mốc đổi vai. */
type Muc = { loai: "luot"; luot: Luot } | { loai: "moc"; moc: MocDoiVai };

/** Dòng meta của một lượt trả lời, tên vai in đậm.
 *
 *  Câu ở `microcopy.json` nguyên vẹn (bảng Voice and Tone còn đối chiếu được),
 *  `cac_manh` tách nó theo chỗ trống lúc render để bọc `<b>` quanh `{vai}`.
 *  Màu là `ink-muted` cho **cả dòng** kể cả phần in đậm (DESIGN.md: một màu cố
 *  định cho mọi lượt, kể cả lượt từ chối FR-16). */
function DongMeta({ khoa, vai, n }: { khoa: KhoaMicrocopy; vai: string; n?: number }) {
  const gia_tri: Record<string, string | number> = { vai: nhan_vai(vai) };
  if (n !== undefined) gia_tri.n = n;
  return (
    <div className="luot__meta" data-luot-meta>
      {cac_manh(khoa, gia_tri).map((manh, i) =>
        manh.ten === "vai" ? <b key={i}>{manh.van_ban}</b> : <span key={i}>{manh.van_ban}</span>,
      )}
    </div>
  );
}

/** Bong bóng trả lời của một lượt, bốn nấc.
 *
 *  Lượt lỗi **không** dùng bong bóng: hộp đỏ đứng ở đúng vị trí lượt để nó khác
 *  hẳn template từ chối chữ đen (NFR-10 fail-closed nhìn thấy được). */
function BongBongTraLoi({
  luot,
  mo_nguon,
  dat_mo_nguon,
}: {
  luot: Luot;
  mo_nguon: boolean;
  dat_mo_nguon: (mo: boolean) => void;
}) {
  const id_luot = luot.id;
  // Hai nấc chưa có câu trả lời nào **không** mang dòng meta: câu ấy nói "trả
  // lời theo quyền X" và chưa có lượt trả lời nào để nói thế. Vai của phiên lúc
  // gửi vẫn được ghi vào `luot.vai_gui` (4.5 đọc nó), chỉ là không render.
  if (luot.ket_cuc.loai === "loi") {
    return (
      <div className="luot_loi" data-ma-loi={luot.ket_cuc.ma}>
        <HopLoi>{MICROCOPY.loi_he_thong}</HopLoi>
      </div>
    );
  }

  if (luot.ket_cuc.loai === "dang_cho") {
    return (
      <div className="luot_tra_loi" data-dang-cho>
        <div className="luot__cho">
          <span className="ba_cham" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          {MICROCOPY.dang_truy_van}
        </div>
      </div>
    );
  }

  const envelope = luot.ket_cuc.envelope;

  // Lượt từ chối (FR-16): câu lấy từ `MICROCOPY.tu_choi` theo cờ `refused` chứ
  // không tự soạn (`answer` là `null` trên dây, AD-8), dòng meta **bỏ vế "· n
  // trích dẫn"**, và hai lượt từ chối vì hai lý do khác nhau ra DOM giống hệt
  // nhau - lý do chỉ có trong audit, response không mang nó.
  if (luot.ket_cuc.loai === "tu_choi") {
    return (
      <div className="luot_tra_loi" data-tu-choi>
        <DongMeta khoa="meta_luot_tu_choi" vai={envelope.meta.role} />
        <p className="luot__than">{MICROCOPY.tu_choi}</p>
      </div>
    );
  }

  // Lượt trả lời, ba khối của story 4.4 (`graph` vẫn bỏ qua, drawer là 4.6).
  // Cả ba đọc envelope **đã lọc và đã che** của server, không suy diễn thêm:
  // không lọc bớt citation nào, không sắp lại, không suy mức từ `masked_slots`,
  // không dựng lại câu trả lời.
  return (
    <div className="luot_tra_loi" data-tra-loi>
      <DongMeta khoa="meta_luot" vai={envelope.meta.role} n={envelope.citations.length} />
      <p className="luot__than">
        <ThanCoSlab van_ban={envelope.answer ?? ""} cac_nhom={nhom_cua(envelope.citations)} />
      </p>
      {/* Khối nguồn đứng **ngoài** vùng `aria-live` của lượt, dù nó nằm trong
          cùng bong bóng. Vùng live bọc ô trả lời, và mọi lần bấm mở hay thu
          gọn khối nguồn là một lần đổi DOM bên trong vùng ấy, tức trình đọc
          màn hình đọc lại cả câu trả lời cho một cú bấm chỉ hiện thêm vài
          hàng - đúng thứ mà vòng review 4.3 thu hẹp vùng live để chặn (bọc cả
          khối cuộn thì mỗi lượt mới đọc lại chính câu người dùng vừa gõ).
          `aria-live="off"` trên tổ tiên gần nhất thắng, nên toggle im lặng;
          số nguồn vẫn tới trình đọc qua vế "· n trích dẫn" của dòng meta, thứ
          nằm trong vùng live và có mặt ngay khi envelope về. */}
      <div aria-live="off">
        <KhoiNguon
          citations={envelope.citations}
          mo={mo_nguon}
          dat_mo={dat_mo_nguon}
          id_luot={id_luot}
        />
      </div>
      <DongHanChe citations={envelope.citations} />
    </div>
  );
}

/** Một lượt trong danh sách: câu hỏi lệch phải, ô trả lời lệch trái.
 *
 *  Vùng `aria-live` là **đúng ô trả lời**, không cả khối cuộn: bọc cả khối thì
 *  mỗi lượt mới đọc lại chính câu người dùng vừa gõ. Ô này có mặt từ lúc lượt
 *  được tạo (nấc chờ) và chỉ nội dung bên trong đổi, nên trình đọc màn hình đọc
 *  đúng phần mới. Mốc đổi vai của 4.5 đứng ở cấp danh sách, tức **ngoài** ô
 *  này, nên chèn một mốc không làm đọc lại lượt trước nó. */
function LuotChat({
  luot,
  mo_nguon,
  dat_mo_nguon,
}: {
  luot: Luot;
  mo_nguon: boolean;
  dat_mo_nguon: (mo: boolean) => void;
}) {
  return (
    <div className="luot" data-luot>
      <div className="luot_hoi" data-luot-hoi>
        {luot.cau_hoi}
      </div>
      <div className="luot__o_tra_loi" aria-live="polite">
        <BongBongTraLoi luot={luot} mo_nguon={mo_nguon} dat_mo_nguon={dat_mo_nguon} />
      </div>
    </div>
  );
}

/** Divider hổ phách giữa hai lượt: "Đã đổi sang xem như <vai> · câu hỏi giữ nguyên".
 *
 *  Đứng ở cấp **danh sách**, ngoài mọi `.luot`, nên nó nằm ngoài vùng
 *  `aria-live` của từng lượt: một mốc chèn vào không được làm trình đọc màn
 *  hình đọc lại câu trả lời của lượt trước nó.
 *
 *  Câu ở `microcopy.json` nguyên vẹn (bảng Voice and Tone còn đối chiếu nguyên
 *  văn được), tên vai đi qua `nhan_vai` như mọi chỗ khác. */
function DongMocDoiVai({ moc }: { moc: MocDoiVai }) {
  return (
    <div className="moc_doi_vai" data-moc-doi-vai={moc.vai}>
      <span>{dien("divider_doi_vai", { vai: nhan_vai(moc.vai) })}</span>
    </div>
  );
}

/** Màn chat: danh sách lượt cuộn phía trên, composer luôn ở đáy.
 *
 *  Trống lần đầu thì **chỉ có composer**: không màn chào, không câu mồi
 *  (EXPERIENCE.md State Patterns). Không stream ở M3, câu trả lời hiện trọn một
 *  lần khi envelope về. Lịch sử sống trong bộ nhớ trang và chỉ ở đó - ghi ra
 *  `sessionStorage` hay backend là Ask First của spec 4.3.
 *
 *  **Không trần thời gian cho một lượt** (NFR-08 không đặt SLA): không
 *  `setTimeout`, không `AbortSignal.timeout`, và `tests/test_web_khung.py` quét
 *  cả `web/src` để giữ luật đó. */
export function ManChat({ tieu_de }: { tieu_de: string }) {
  const router = useRouter();
  const phien = usePhien();
  const o_hoi = useRef<HTMLTextAreaElement>(null);
  const khoi_cuon = useRef<HTMLDivElement>(null);
  // Chốt chống gửi hai lần nằm ở **ref**, không ở state: hai lần bấm trong cùng
  // một tick đọc cùng một giá trị state cũ nên cả hai đều lọt (cùng lý lẽ với
  // màn đăng nhập 4.2). State `dang_cho` chỉ để vẽ nút.
  const dang_cho_ref = useRef(false);
  const dem_ref = useRef(0);
  // Người đọc có đang ở gần đáy khối cuộn không (mặc định có: chat trống).
  const o_day = useRef(true);
  const [dang_cho, dat_dang_cho] = useState(false);
  // Số ký tự đã gõ, **chỉ để vẽ bộ đếm**. Câu hỏi vẫn đọc bằng ref lúc gửi
  // (`o_hoi.current.value`), nên nó không vào state React và một lần gõ không
  // render lại cả danh sách lượt.
  const [so_ky_tu, dat_so_ky_tu] = useState(0);
  const [cac_muc, dat_cac_muc] = useState<Muc[]>([]);
  // Drawer đồ thị (story 4.6). Ba mẩu state, và cả ba sống ở đây vì hai đầu của
  // sợi dây hover đều nằm dưới màn này: cite-row phát mã, drawer nhận mã.
  const [mo_do_thi, dat_mo_do_thi] = useState(false);
  const [ma_chon, dat_ma_chon] = useState<string | null>(null);
  const [ma_hover, dat_ma_hover] = useState<string | null>(null);
  // Dãy vai của mọi lần đổi vai đã xảy ra (khung giữ). Mỗi phần tử **chưa
  // thấy** là một mốc được chèn, mang đúng tên vai của lần đổi ấy.
  const cac_lan_doi = useCacLanDoiVai();
  const da_chen = useRef(cac_lan_doi.length);

  // Cuộn xuống đáy **chỉ khi người đọc đang ở gần đáy**: đọc lại một lượt cũ
  // trong lúc lượt mới về mà bị kéo tuột xuống là mất chỗ đang đọc. Vị trí cuộn
  // theo dõi bằng ref trong `onScroll` chứ không đo trong effect - effect chạy
  // **sau** khi DOM đã có lượt mới nên lúc đó khoảng cách tới đáy đã đổi.
  useEffect(() => {
    const el = khoi_cuon.current;
    if (el && o_day.current) el.scrollTop = el.scrollHeight;
  }, [cac_muc]);

  // Chèn một mốc cho **mỗi** phần tử mới của dãy, kể cả nhiều lần đổi liên
  // tiếp mà không có lượt nào ở giữa và kể cả hai lần đổi chồng nhau (lần đọc
  // phiên thứ nhất bị hủy). Tên vai lấy từ chính phần tử ấy, không từ
  // `phien.vai` - phiên còn là vai cũ cho tới khi `/auth/toi` trả về.
  //
  // **Lịch sử lượt cũ không đổi một byte** ở đây: mốc chỉ được *thêm vào cuối*,
  // không lượt nào bị render lại theo vai mới (NFR-09: đổi vai có hiệu lực từ
  // truy vấn kế tiếp).
  useEffect(() => {
    if (cac_lan_doi.length === da_chen.current) return;
    const moi = cac_lan_doi.slice(da_chen.current);
    da_chen.current = cac_lan_doi.length;
    o_day.current = true;
    const them: Muc[] = moi.map((vai) => {
      dem_ref.current += 1;
      return { loai: "moc", moc: { id: dem_ref.current, vai } };
    });
    dat_cac_muc((cu) => [...cu, ...them]);
  }, [cac_lan_doi]);

  function theo_doi_cuon(su_kien: UIEvent<HTMLDivElement>) {
    const el = su_kien.currentTarget;
    o_day.current = el.scrollHeight - el.scrollTop - el.clientHeight <= NGUONG_DAY;
  }

  // Id của lượt **trả lời** mới nhất. Khối nguồn của nó mở mặc định, mọi lượt
  // trả lời cũ thu gọn thành "Nguồn (n) ▸" (EXPERIENCE.md Component Patterns).
  // Tính lúc render chứ không giữ trong state: một lượt mới về là mặc định của
  // lượt cũ đổi theo, và hai state phải đồng bộ tay là hai state lệch nhau.
  const id_tra_loi_moi_nhat = cac_muc.reduce<number | null>(
    (moi_nhat, m) =>
      m.loai === "luot" && m.luot.ket_cuc.loai === "tra_loi" ? m.luot.id : moi_nhat,
    null,
  );

  // Lượt mà drawer đang vẽ: lượt mới nhất **có envelope**, tức trả lời **hoặc**
  // từ chối. Không phải `id_tra_loi_moi_nhat` của 4.4 - nó cố ý bỏ qua lượt từ
  // chối (đúng cho khối nguồn), và dùng lại nó ở đây làm nhịp 3 của demo hỏng
  // theo cách tệ nhất: `sale_ba` bị chặn, chat hiện template từ chối, mà drawer
  // vẫn đứng nguyên đồ thị của Tech Support ở lượt trước - dữ liệu của **một
  // vai khác** còn trên màn sau khi người dùng đã đổi vai, đúng thứ
  // EXPERIENCE.md trạng thái C cấm. Lượt từ chối có `citations: []` nên nó rơi
  // vào đúng nhánh empty-state của drawer, không cần một nhánh riêng và không
  // request nào bay đi.
  const luot_drawer = cac_muc.reduce<LuotDrawer | null>((moi_nhat, m) => {
    if (m.loai !== "luot") return moi_nhat;
    const kc = m.luot.ket_cuc;
    if (kc.loai !== "tra_loi" && kc.loai !== "tu_choi") return moi_nhat;
    const so = m.luot.id;
    return { id: so, citations: kc.envelope.citations };
  }, null);
  const id_luot_drawer = luot_drawer === null ? null : luot_drawer.id;
  const vai_phien = phien?.vai ?? "";

  // Lượt mới hay đổi vai: **mọi highlight cũ bỏ**. Một mã `HE-02` chọn ở lượt
  // trước trỏ vào một citation khác ở lượt sau, nên giữ nó lại là làm sáng một
  // vòng nói sai về nguồn.
  useEffect(() => {
    dat_ma_chon(null);
    dat_ma_hover(null);
  }, [id_luot_drawer, vai_phien]);

  /** Bấm ô số của một cite-row: mở drawer **và** chọn vòng ấy, và nó giữ sáng
   *  sau khi rời chuột (khác hover, thứ tắt ngay). */
  function chon_vong(ma: string) {
    dat_mo_do_thi(true);
    dat_ma_chon(ma);
  }

  /** Người dùng tự mở hay thu gọn khối nguồn của một lượt. Từ đây `mo_nguon`
   *  của lượt ấy không còn là `null`, nên nó thôi theo mặc định và giữ nguyên
   *  lựa chọn ấy qua các lượt sau. */
  /** Sửa đúng một lượt trong danh sách, giữ nguyên mọi mục khác từng byte. */
  function sua_luot(id: number, sua: (luot: Luot) => Luot) {
    dat_cac_muc((cu) =>
      cu.map((m) =>
        m.loai === "luot" && m.luot.id === id ? { loai: "luot", luot: sua(m.luot) } : m,
      ),
    );
  }

  function dat_mo_nguon(id: number, mo: boolean) {
    sua_luot(id, (l) => ({ ...l, mo_nguon: mo }));
  }

  /** Kết thúc một lượt: ghi kết cục và mở khóa composer cho lượt sau. */
  function ket_thuc(id: number, ket_cuc: KetCuc) {
    sua_luot(id, (l) => ({ ...l, ket_cuc }));
    dat_dang_cho(false);
    dang_cho_ref.current = false;
  }

  async function gui() {
    if (dang_cho_ref.current) return;
    // Câu rỗng hay toàn khoảng trắng không gửi: không request nào, không lượt nào.
    const cau_hoi = (o_hoi.current?.value ?? "").trim();
    if (cau_hoi === "") return;

    dang_cho_ref.current = true;
    dat_dang_cho(true);
    // Tự gửi một câu là một ý định muốn thấy lượt của nó, kể cả khi đang đọc
    // lượt cũ ở trên.
    o_day.current = true;
    const id = dem_ref.current + 1;
    dem_ref.current = id;
    dat_cac_muc((cu) => [
      ...cu,
      {
        loai: "luot",
        luot: {
          id,
          cau_hoi,
          vai_gui: phien?.vai ?? "",
          ket_cuc: { loai: "dang_cho" },
          mo_nguon: null,
        },
      },
    ]);
    if (o_hoi.current) o_hoi.current.value = "";
    dat_so_ky_tu(0);

    try {
      const envelope = await hoi(cau_hoi);
      ket_thuc(id, envelope.refused ? { loai: "tu_choi", envelope } : { loai: "tra_loi", envelope });
    } catch (that_bai: unknown) {
      // Luật phân loại lỗi khai một chỗ (`phien.ts`): 401 giữa một lượt là hết
      // phiên, và đây là **nhánh duy nhất** của màn chat được điều hướng. Mọi mã
      // khác (400, 5xx, `MANG`) báo tại chỗ bằng hộp đỏ và giữ nguyên URL - đá
      // người dùng ra ngoài vì máy chủ chết là mất câu hỏi của họ và nói sai
      // nguyên nhân. Không mở khóa composer ở nhánh này: `router.replace` còn bay.
      if (la_het_phien(that_bai)) {
        xoa_token();
        router.replace(duong_het_phien());
        return;
      }
      const l = that_bai instanceof LoiApi ? that_bai : new LoiApi(MA_MANG, 0);
      ket_thuc(id, { loai: "loi", ma: l.code });
      // Trả câu hỏi về composer để người dùng bấm gửi lại chứ không gõ lại cả
      // câu. Chỉ ở nhánh lỗi (lượt trả lời và lượt từ chối là một lượt đã xong),
      // và chỉ khi ô đang trống - họ có thể đã gõ câu kế trong lúc chờ.
      if (o_hoi.current && o_hoi.current.value.trim() === "") {
        o_hoi.current.value = cau_hoi;
        dat_so_ky_tu(cau_hoi.length);
      }
    }
  }

  function nop(su_kien: FormEvent<HTMLFormElement>) {
    su_kien.preventDefault();
    void gui();
  }

  function phim(su_kien: KeyboardEvent<HTMLTextAreaElement>) {
    if (su_kien.key !== "Enter" || su_kien.shiftKey) return;
    // Enter giữa một tổ hợp gõ tiếng Việt (Telex, VNI, IME) là chốt chữ chứ
    // không phải gửi câu; gửi ở đó là cắt câu hỏi giữa chừng.
    if (su_kien.nativeEvent.isComposing) return;
    // Đang chờ thì **không** chặn phím: `gui()` sẽ thoát ngay ở chốt ref, nên
    // một `preventDefault()` ở đây nuốt phím im lặng - người dùng gõ Enter mà
    // không có gì xảy ra, cả gửi lẫn xuống dòng. Để nó rơi về hành vi mặc định
    // của textarea (xuống dòng).
    if (dang_cho_ref.current) return;
    su_kien.preventDefault();
    void gui();
  }

  return (
    <>
      {/* Header chat là **một hàng**: tiêu đề trang bên trái, nút "Đồ thị" bên
          phải. Tiêu đề đến từ `dieu_huong.json` qua prop, nên nhãn của sidebar
          và của trang vẫn là **một** chuỗi (luật của 4.1). */}
      <div className="man_chat__dau">
        <h1 className="tieu_de_trang">{tieu_de}</h1>
        <button
          type="button"
          className="nut_do_thi"
          data-nut-do-thi
          data-active={mo_do_thi ? "1" : undefined}
          aria-pressed={mo_do_thi}
          onClick={() => dat_mo_do_thi(!mo_do_thi)}
        >
          {MICROCOPY.nut_do_thi}
        </button>
      </div>

      {/* Vùng neo của drawer: nó trượt từ phải **trong** vùng hội thoại, nên
          header chat không bao giờ bị che và nút "Đồ thị" luôn bấm lại được. */}
      <div className="man_chat__vung">
        {/* Cột hội thoại. Drawer là **anh em flex** của nó chứ không một tấm
            phủ lên trên: một drawer `position: absolute` che mất composer, tức
            mở đồ thị ra là không hỏi được câu tiếp - đúng nhịp mà buổi demo
            cần nhất (hỏi, xem đồ thị, đổi vai, hỏi lại). */}
        <div className="man_chat__cot">
          <HoverDoThiProvider
            value={{ ma_hover, ma_chon, id_luot_drawer, dat_ma_hover, chon_vong }}
          >
            <div
              className="man_chat__cuon"
              ref={khoi_cuon}
              data-danh-sach-luot
              onScroll={theo_doi_cuon}
            >
              {cac_muc.map((muc) =>
                muc.loai === "moc" ? (
                  <DongMocDoiVai key={muc.moc.id} moc={muc.moc} />
                ) : (
                  <LuotChat
                    key={muc.luot.id}
                    luot={muc.luot}
                    mo_nguon={muc.luot.mo_nguon ?? muc.luot.id === id_tra_loi_moi_nhat}
                    dat_mo_nguon={(mo) => dat_mo_nguon(muc.luot.id, mo)}
                  />
                ),
              )}
            </div>
          </HoverDoThiProvider>

          <form className="composer" onSubmit={nop}>
            <label htmlFor="o_hoi" className="sr-only">
              {MICROCOPY.nhan_o_hoi}
            </label>
            <textarea
              id="o_hoi"
              className="o_hoi"
              ref={o_hoi}
              rows={2}
              data-o-hoi
              maxLength={DAI_CAU_HOI_TOI_DA}
              placeholder={MICROCOPY.placeholder_o_hoi}
              onKeyDown={phim}
              onChange={(e) => dat_so_ky_tu(e.currentTarget.value.length)}
            />
            {/* Bộ đếm chỉ hiện khi **gần trần**. `maxLength` chặn trước một câu quá
                dài (đóng khoản ledger `CAU_HOI_QUA_DAI`), nhưng nó cắt **lặng lẽ**:
                dán một câu 5000 ký tự thì mất 1000 ký tự cuối, không đếm, không
                nhắc, và câu cụt vẫn gửi đi được. Một con số hiện ra ở đúng lúc là
                phần còn thiếu của phép chặn ấy.
                Ngưỡng chứ không luôn hiện: một bộ đếm trên mọi câu là nhiễu cho
                99% lượt, và nó kéo mắt khỏi chính ô đang gõ. */}
            {so_ky_tu >= NGUONG_DEM_KY_TU && (
              <span
                className="o_hoi__dem"
                data-dem-ky-tu={so_ky_tu}
                data-cham-tran={so_ky_tu >= DAI_CAU_HOI_TOI_DA ? "1" : undefined}
                aria-live="polite"
              >
                {dien("dem_ky_tu", { da: so_ky_tu, tran: DAI_CAU_HOI_TOI_DA })}
              </span>
            )}
            <button type="submit" className="nut_chinh" disabled={dang_cho} data-nut-gui>
              {MICROCOPY.nut_gui}
            </button>
          </form>
        </div>

        {/* Vòng đang sáng: mã đang hover thắng mã đã chọn, vì hover là thao tác
            vừa xảy ra. Rời hover thì mã đã chọn sáng lại - đúng ca "bấm ô số
            rồi rê chuột đi" của I/O Matrix. */}
        <DrawerDoThi
          mo={mo_do_thi}
          dong={() => dat_mo_do_thi(false)}
          luot={luot_drawer}
          vai={vai_phien}
          ma_sang={ma_hover ?? ma_chon}
        />
      </div>
    </>
  );
}
