import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin", "latin-ext"] });

export const metadata: Metadata = {
  title: { default: "BandVision", template: "%s · BandVision" },
  description: "Banttan geçen ürünleri sayma ve kalite kontrol paneli",
  // Başlatıcı (tools/panel_baslat.bat) bu işaretle paneli tanır: durum dosyasının yazdığı portta (3300 ya da sıradaki boş port) başka bir uygulama olabilir, o panel sanılmasın
  other: { "bv-panel": "1" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="tr">
      <body className={`${inter.variable} font-sans antialiased`}>{children}</body>
    </html>
  );
}
