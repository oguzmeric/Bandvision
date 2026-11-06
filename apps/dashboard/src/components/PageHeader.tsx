/**
 * Panel sayfalarının düz başlık satırı: başlık ve (varsa) kısa açıklama; logo ve rozet yok (sade arayüz). `children`:
 * başlığın sağındaki düğmeler (ör. Canlı izlemede "Kısayollar").
 */
export default function PageHeader({ title, text, children }: { title: string; text?: string; children?: React.ReactNode }) {
  const heading = <h1 className="min-w-0 flex-1 text-xl font-semibold text-pl-ink">{title}</h1>;
  return (
    <div className="mb-4 border-b border-pl-line pb-2">
      {children ? <div className="flex flex-wrap items-center gap-2">{heading}{children}</div> : heading}
      {text && <p className="mt-0.5 max-w-3xl text-[13px] text-pl-muted">{text}</p>}
    </div>
  );
}
