/** Panel sayfalarının düz başlık satırı: başlık ve (varsa) kısa açıklama; logo ve rozet yok (sade arayüz). */
export default function PageHeader({ title, text }: { title: string; text?: string }) {
  return (
    <div className="mb-4 border-b border-pl-line pb-2">
      <h1 className="text-xl font-semibold text-pl-ink">{title}</h1>
      {text && <p className="mt-0.5 max-w-3xl text-[13px] text-pl-muted">{text}</p>}
    </div>
  );
}
