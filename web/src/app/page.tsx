import dieu_huong from "@/khung/dieu_huong.json";

import { ManChat } from "./ManChat";

/** Trang "Hỏi đáp": chat console (story 4.3).
 *
 *  Server component mỏng bọc `ManChat`, khuôn của route đăng nhập nhưng **không
 *  cần `Suspense`**: màn chat không đọc `useSearchParams` nên nó prerender tĩnh
 *  được. Tiêu đề đọc từ `dieu_huong.json` để nhãn của sidebar và của trang là
 *  một chuỗi. `.man_chat` là cột: tiêu đề trên, danh sách lượt cuộn ở giữa,
 *  composer ở đáy. */
export default function TrangHoiDap() {
  return (
    <div className="man_chat">
      <h1 className="tieu_de_trang">{dieu_huong[0].nhan}</h1>
      <ManChat />
    </div>
  );
}
