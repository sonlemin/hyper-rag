import type { Metadata } from "next";
import type { ReactNode } from "react";

import { bien_css } from "@/design/bien_css";
import { KhungApp } from "@/khung/KhungApp";
import { MICROCOPY } from "@/microcopy";
import "./globals.css";

export const metadata: Metadata = {
  title: MICROCOPY.thuong_hieu,
  description: MICROCOPY.thuong_hieu_phu,
};

// CSS variables sinh **lúc build** từ `src/design/tokens.json` (server
// component, không có file CSS token viết tay). Font hệ thống, không webfont.
const BIEN_TOKEN = bien_css();

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <head>
        <style data-token-thiet-ke>{BIEN_TOKEN}</style>
      </head>
      <body>
        <KhungApp>{children}</KhungApp>
      </body>
    </html>
  );
}
