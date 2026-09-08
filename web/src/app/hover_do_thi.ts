"use client";

// Sợi dây giữa cite-row và vòng đồ thị (story 4.6, FR-19 MUST).
//
// Một context chứ không ba tầng prop: `KhoiNguon` nằm dưới `ManChat` ->
// `LuotChat` -> `BongBongTraLoi`, và ba chữ ký mọc thêm hai prop chỉ để chuyển
// tiếp là ba chỗ một story sau quên chuyển tiếp. Context sống ở file riêng
// (không ở `ManChat.tsx`) vì `ManChat` đã nhập `KhoiNguon`, và một vòng nhập
// giữa hai module React là một lỗi lúc chạy chứ không lúc biên dịch.
//
// Giá trị mặc định **inert**: trang mẫu `/mau` dựng `KhoiNguon` ngoài mọi
// provider, và một cite-row ở đó không được nối dây vào một drawer không có.

import { createContext, useContext } from "react";

export type NoiDungHoverDoThi = {
  /** Mã vòng đang được hover từ cite-row, hay `null`. */
  ma_hover: string | null;
  /** Mã vòng đang được chọn (bấm số), giữ sáng cả sau khi rời chuột. */
  ma_chon: string | null;
  /** Id lượt mà drawer đang vẽ. `null` nghĩa là chưa có lượt nào có envelope,
   *  và khi đó **không** cite-row nào được nối dây. */
  id_luot_drawer: number | null;
  dat_ma_hover: (ma: string | null) => void;
  /** Bấm ô số: mở drawer **và** chọn vòng ấy. */
  chon_vong: (ma: string) => void;
};

const INERT: NoiDungHoverDoThi = {
  ma_hover: null,
  ma_chon: null,
  id_luot_drawer: null,
  dat_ma_hover: () => {},
  chon_vong: () => {},
};

const HoverDoThiContext = createContext<NoiDungHoverDoThi>(INERT);

export const HoverDoThiProvider = HoverDoThiContext.Provider;

export function useHoverDoThi(): NoiDungHoverDoThi {
  return useContext(HoverDoThiContext);
}
