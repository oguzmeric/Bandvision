import Image from "next/image";

/** Panel sayfalarının ortak başlığı (BandVision kimliği, rozet, başlık, açıklama) */
export default function PageHeader({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return (
    <>
      <div className="mb-4 flex items-center gap-2.5">
        <Image src="/brand/logo-mark.png" alt="" width={34} height={26} />
        <span className="text-[17px] font-semibold">Band<span className="text-brand-500">Vision</span></span>
      </div>
      <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-2.5 py-1 text-[11px] font-semibold tracking-wider text-brand-500">
        <i className="h-1.5 w-1.5 rounded-full bg-brand-500" />{eyebrow}
      </span>
      <h1 className="mt-2.5 text-2xl font-semibold">{title}</h1>
      <p className="mb-6 mt-1 max-w-3xl text-sm text-muted">{text}</p>
    </>
  );
}
