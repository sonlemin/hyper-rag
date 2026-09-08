import dieu_huong from "@/khung/dieu_huong.json";

import { ManChat } from "./ManChat";

/** Trang "Hỏi đáp": chat console (story 4.3, drawer đồ thị của 4.6).
 *
 *  Server component mỏng bọc `ManChat`, khuôn của route đăng nhập nhưng **không
 *  cần `Suspense`**: màn chat không đọc `useSearchParams` nên nó prerender tĩnh
 *  được. Tiêu đề đọc từ `dieu_huong.json` để nhãn của sidebar và của trang là
 *  một chuỗi, và từ 4.6 nó đi **qua prop** chứ không render ở đây: header chat
 *  là một hàng chứa cả nút "Đồ thị", và nút ấy là state của client component.
 *  `.man_chat` là cột: header trên, vùng hội thoại ở giữa (drawer neo vào nó),
 *  composer ở đáy. */
export default function TrangHoiDap() {
  return (
    <div className="man_chat">
      <ManChat tieu_de={dieu_huong[0].nhan} />
    </div>
  );
}
