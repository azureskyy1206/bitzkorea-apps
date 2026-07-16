import type { Metadata, Viewport } from "next";
import TableMobileEnhancer from "@/components/TableMobileEnhancer";
import "./globals.css";

export const metadata: Metadata = {
  title: "Adobe School Portal",
  description: "서울시교육청 산하 학교 Adobe Named License 셀프서비스 포털",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen min-w-0 antialiased">
        <TableMobileEnhancer />
        {children}
      </body>
    </html>
  );
}
