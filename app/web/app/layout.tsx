import type { Viewport } from "next";
import "./globals.css";
import SalesSectionNav from "../components/SalesSectionNav";
import SiteHeader from "../components/SiteHeader";

export const metadata = { title: "Sales Support" };

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen min-w-0 bg-zinc-50 text-zinc-900 antialiased">
        <SiteHeader />
        <main className="mx-auto min-w-0 w-full max-w-[2200px] px-3 py-5 sm:px-6 sm:py-8">
          <SalesSectionNav />
          {children}
        </main>
      </body>
    </html>
  );
}
