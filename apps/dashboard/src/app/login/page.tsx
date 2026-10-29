import type { Metadata } from "next";
import Image from "next/image";
import { redirect } from "next/navigation";
import { authMode, safeNext } from "@/lib/session";
import LoginForm from "./LoginForm";

export const metadata: Metadata = { title: "Giriş" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  if (!authMode()) redirect(safeNext(next));            // şifre kipi kapalı: giriş gerekmez
  return (
    // Sade görünüm: gri zeminde tek kenarlıklı bölüm; başlık satırı .pl-section > h2 görünümünde
    <main className="grid min-h-screen place-items-center bg-pl-side px-4">
      <section className="pl-section mb-0 w-full max-w-sm pb-4">
        <div className="-mx-2.5 mb-4 flex items-center gap-3 rounded-t-[3px] border-b border-pl-line bg-pl-head px-2.5 py-2">
          <Image src="/brand/logo-mark.png" alt="" width={32} height={25} priority />
          <div>
            <h1 className="text-[15px] font-semibold">BandVision</h1>
            <p className="text-[12.5px] text-pl-muted">Panele giriş</p>
          </div>
        </div>
        <LoginForm next={safeNext(next)} />
      </section>
    </main>
  );
}
