import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Adobe School Portal",
  description: "서울시교육청 산하 학교 Adobe Named License 셀프서비스 포털",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">{children}</body>
    </html>
  );
}
