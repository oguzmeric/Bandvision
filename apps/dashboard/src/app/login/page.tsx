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
    <main className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm rounded-2xl border border-line bg-white p-7 shadow-[0_12px_32px_rgba(29,26,46,0.06)]">
        <div className="mb-6 flex items-center gap-3">
          <Image src="/brand/logo-mark.png" alt="" width={46} height={36} priority />
          <div>
            <h1 className="text-lg font-semibold">BandVision</h1>
            <p className="text-sm text-muted">Panele giriş</p>
          </div>
        </div>
        <LoginForm next={safeNext(next)} />
      </div>
    </main>
  );
}
