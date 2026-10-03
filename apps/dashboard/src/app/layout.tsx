import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Sidebar from "@/components/Sidebar";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin", "latin-ext"] });

export const metadata: Metadata = {
  title: { default: "BandVision", template: "%s · BandVision" },
  description: "Banttan geçen ürünleri sayma ve kalite kontrol paneli",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="tr">
      <body className={`${inter.variable} font-sans antialiased`}>
        <div className="grid min-h-screen grid-cols-[72px_1fr]">
          <Sidebar />
          <main className="min-w-0 px-5 py-6 md:px-9 md:py-7">{children}</main>
        </div>
      </body>
    </html>
  );
}
