import dieu_huong from "@/khung/dieu_huong.json";

/** Trang "Hỏi đáp": hôm nay chỉ có khung, chat console là story 4.3. */
export default function TrangHoiDap() {
  return <h1 className="tieu_de_trang">{dieu_huong[0].nhan}</h1>;
}
