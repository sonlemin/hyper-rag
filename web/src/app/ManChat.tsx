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
import { hoi, type Envelope, type TrichDan } from "@/api/hoi_dap";
import { duong_het_phien, la_het_phien, nhan_vai, xoa_token } from "@/api/phien";
import { HopLoi } from "@/khung/HopLoi";
import { usePhien } from "@/khung/KhungApp";
import { cac_manh, dien, MICROCOPY, type KhoaMicrocopy } from "@/microcopy";
import { nhan_slot } from "@/nhan";

import { tach_slab } from "./dau_che";
import { DongHanChe } from "./DongHanChe";
import { KhoiNguon } from "./KhoiNguon";

/** Bốn nấc của một lượt. Ba nấc kết thúc phải khác nhau về **cấu trúc DOM**,
 *  không chỉ khác màu: lượt trả lời mang `data-tra-loi`, lượt từ chối mang
 *  `data-tu-choi` và bỏ hẳn vế số trích dẫn, lượt lỗi là một `HopLoi` mang
 *  `data-ma-loi`. Một phép phân biệt chỉ bằng màu là phép phân biệt mất khi ai
 *  đó sửa CSS, và đây đúng là chỗ NFR-10 đòi nhìn thấy được. */
/** Khoảng cách tới đáy (px) mà dưới nó thì một lượt mới vẫn tự cuộn xuống. */
const NGUONG_DAY = 48;

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
        <ThanCoSlab van_ban={envelope.answer ?? ""} citations={envelope.citations} />
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
        <KhoiNguon citations={envelope.citations} mo={mo_nguon} dat_mo={dat_mo_nguon} />
      </div>
      <DongHanChe citations={envelope.citations} />
    </div>
  );
}

/** Thân câu trả lời với slab bôi đen thay dấu che, ngay tại vị trí của nó.
 *
 *  Slab là **hiển thị best-effort trên `answer`** (chốt brief §6: không test an
 *  ninh nào trên `answer`), nên một chuỗi không nhận ra là chữ thường và giữ
 *  nguyên văn. Tập nhóm để nhận diện `[owner:<nhóm>]` lấy từ `owner_group` của
 *  **chính lượt này**, đúng khuôn `core.masking.la_dau_che`.
 *
 *  `[owner:<nhóm>]` render **giữ tên nhóm** ("[người phụ trách: DevOps]") còn
 *  `[owner:group]` render "[người phụ trách: che]": AD-9 tổng quát hóa `owner`
 *  về mức nhóm chứ không xóa nó, và FR-14 đòi placeholder nói được nhóm nào.
 *  Bôi tên nhóm thành "che" là vứt đi đúng thứ server cố ý cho ra. */
function ThanCoSlab({ van_ban, citations }: { van_ban: string; citations: TrichDan[] }) {
  const cac_nhom = citations
    .map((c) => c.owner_group)
    .filter((n): n is string => n !== null);
  return (
    <>
      {tach_slab(van_ban, cac_nhom).map((manh, i) =>
        manh.loai === "chu" ? (
          <span key={i}>{manh.van_ban}</span>
        ) : (
          <span key={i} className="slab" data-slab={manh.vai}>
            {manh.nhom === null
              ? dien("slab_che", { ten_slot: nhan_slot(manh.vai) })
              : dien("slab_owner", { ten_slot: nhan_slot(manh.vai), nhom: manh.nhom })}
          </span>
        ),
      )}
    </>
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
export function ManChat() {
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
  const [cac_luot, dat_cac_luot] = useState<Luot[]>([]);

  // Cuộn xuống đáy **chỉ khi người đọc đang ở gần đáy**: đọc lại một lượt cũ
  // trong lúc lượt mới về mà bị kéo tuột xuống là mất chỗ đang đọc. Vị trí cuộn
  // theo dõi bằng ref trong `onScroll` chứ không đo trong effect - effect chạy
  // **sau** khi DOM đã có lượt mới nên lúc đó khoảng cách tới đáy đã đổi.
  useEffect(() => {
    const el = khoi_cuon.current;
    if (el && o_day.current) el.scrollTop = el.scrollHeight;
  }, [cac_luot]);

  function theo_doi_cuon(su_kien: UIEvent<HTMLDivElement>) {
    const el = su_kien.currentTarget;
    o_day.current = el.scrollHeight - el.scrollTop - el.clientHeight <= NGUONG_DAY;
  }

  // Id của lượt **trả lời** mới nhất. Khối nguồn của nó mở mặc định, mọi lượt
  // trả lời cũ thu gọn thành "Nguồn (n) ▸" (EXPERIENCE.md Component Patterns).
  // Tính lúc render chứ không giữ trong state: một lượt mới về là mặc định của
  // lượt cũ đổi theo, và hai state phải đồng bộ tay là hai state lệch nhau.
  const id_tra_loi_moi_nhat = cac_luot.reduce<number | null>(
    (moi_nhat, l) => (l.ket_cuc.loai === "tra_loi" ? l.id : moi_nhat),
    null,
  );

  /** Người dùng tự mở hay thu gọn khối nguồn của một lượt. Từ đây `mo_nguon`
   *  của lượt ấy không còn là `null`, nên nó thôi theo mặc định và giữ nguyên
   *  lựa chọn ấy qua các lượt sau. */
  function dat_mo_nguon(id: number, mo: boolean) {
    dat_cac_luot((cu) => cu.map((l) => (l.id === id ? { ...l, mo_nguon: mo } : l)));
  }

  /** Kết thúc một lượt: ghi kết cục và mở khóa composer cho lượt sau. */
  function ket_thuc(id: number, ket_cuc: KetCuc) {
    dat_cac_luot((cu) => cu.map((l) => (l.id === id ? { ...l, ket_cuc } : l)));
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
    dat_cac_luot((cu) => [
      ...cu,
      { id, cau_hoi, vai_gui: phien?.vai ?? "", ket_cuc: { loai: "dang_cho" }, mo_nguon: null },
    ]);
    if (o_hoi.current) o_hoi.current.value = "";

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
      if (o_hoi.current && o_hoi.current.value.trim() === "") o_hoi.current.value = cau_hoi;
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
      <div
        className="man_chat__cuon"
        ref={khoi_cuon}
        data-danh-sach-luot
        onScroll={theo_doi_cuon}
      >
        {cac_luot.map((luot) => (
          <div className="luot" key={luot.id} data-luot>
            <div className="luot_hoi" data-luot-hoi>
              {luot.cau_hoi}
            </div>
            {/* Vùng `aria-live` là **đúng ô trả lời**, không cả khối cuộn: bọc
                cả khối thì mỗi lượt mới đọc lại chính câu người dùng vừa gõ.
                Ô này có mặt từ lúc lượt được tạo (nấc chờ) và chỉ nội dung bên
                trong đổi, nên trình đọc màn hình đọc đúng phần mới. */}
            <div className="luot__o_tra_loi" aria-live="polite">
              <BongBongTraLoi
                luot={luot}
                mo_nguon={luot.mo_nguon ?? luot.id === id_tra_loi_moi_nhat}
                dat_mo_nguon={(mo) => dat_mo_nguon(luot.id, mo)}
              />
            </div>
          </div>
        ))}
      </div>

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
          placeholder={MICROCOPY.placeholder_o_hoi}
          onKeyDown={phim}
        />
        <button type="submit" className="nut_chinh" disabled={dang_cho} data-nut-gui>
          {MICROCOPY.nut_gui}
        </button>
      </form>
    </>
  );
}
