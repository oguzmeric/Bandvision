"""Şerit tarama (line-scan) sayımı — docs/03-algorithm.md §4.9.

Tek sıra gelen hacimli ürünler (torba, koli, kasa) için: boş bant öğrenmeye gerek yoktur, bitişik ya da üst üste
binmiş ürünler aralarındaki ek yerinden ayrılır. Sayım çizgisi çevresinde bandın kare başına kayması ölçülür ve çizgiden
geçen her satırın parlaklığı "geçen mesafe" ekseninde bir sinyale eklenir (sanal çizgi-tarama kamerası). Sinyaldeki
çukurlar ürün aralarıdır; iki çukur arası ürün(ler)dir. Ürün boyu otomatik öğrenilir ya da profilden (`productLength`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .profile import Profile
from .segmenter import roi_mask, roi_pixels

MIN_ROI_LEN = 8          # akış ekseninde en az bu kadar işleme pikseli
MIN_CONTRAST = 6.0       # sinyalde bundan düşük kontrast: bant boş/dokusuz, ek yeri aranmaz
SEAM_PROMINENCE = 0.25   # çukur derinliği ≥ bu × kontrast
LOW_LEVEL = 0.25         # ürün kısmı: lo + bu × kontrast üstü
CONF_MIN = 0.05          # kayma eşleşmesi bundan belirsizse hız değişmedi sayılır
RELIABLE_SEGMENTS = 4    # erken öğrenmenin kabulü için gereken tam ürün (parça) sayısı
LO_Q = 0.02              # kontrastın alt ucu: ince ek yerleri (koli kenarı) pencerenin küçük bir kısmıdır
ACTIVE_FRAMES = 10       # hareketli sütun seçimi için gereken hareketli kare sayısı (§4.9.0)
ACTIVE_FRACTION = 0.25   # konum hareketli ⇔ ortalama farkı ≥ bu × en hareketli konumunki
MOTION_MIN = 1.0         # bir kare "hareketli" ⇔ ROI'de akışa dik en hareketli konumun ortalama |farkı| ≥ bu


@dataclass
class ScanEvent:
    seg_id: int
    delta: int


@dataclass
class ScanMarker:
    id: int
    x: float          # normalize görüntü koordinatı
    y: float
    counted: bool


@dataclass
class _Seg:
    id: int
    centers: list[float]      # mutlak sinyal indeksleri
    counted: int


def percentile_lower(values: np.ndarray, q: float) -> float:
    """İnterpolasyonsuz yüzdelik: sıralı dizide floor(q·(n−1)) indeksli eleman (Swift ile birebir)."""
    s = np.sort(values)
    return float(s[math.floor(q * (len(s) - 1))])


def flow_profile(small: np.ndarray, profile: Profile, mask: np.ndarray | None = None,
                 bounds: tuple[int, int, int, int] | None = None) -> tuple[np.ndarray, int] | None:
    """§4.9.1 Akış eksenine göre sıralı profil (3×n: alt çeyrek, alt medyan, üst çeyrek) ve çizgi indeksi.
    ROI akış boyunca çok kısaysa None. Kayma ölçümü medyanla; sayım sinyali ürün açıksa üst, koyuysa alt çeyrekle
    (ürün üstündeki etiket/bant gibi küçük alanlar satırı "boş bant" gibi göstermesin)."""
    h, w = small.shape
    x0, y0, x1, y1 = bounds or roi_pixels(profile.roi, w, h)
    if mask is None:
        mask = roi_mask(profile.roi, profile.roiPolygon, w, h)
    vertical = profile.vertical
    lo, hi = (y0, y1) if vertical else (x0, x1)
    n = hi - lo
    if n < MIN_ROI_LEN:
        return None
    vals = np.zeros((3, n), dtype=np.float64)
    last = (0.0, 0.0, 0.0)
    for i in range(n):
        if vertical:
            line_px = small[lo + i, x0:x1][mask[lo + i, x0:x1]]
        else:
            line_px = small[y0:y1, lo + i][mask[y0:y1, lo + i]]
        if len(line_px):
            s = np.sort(line_px)
            m = len(s) - 1
            last = (float(s[m // 4]), float(s[m // 2]), float(s[(3 * m) // 4]))
        vals[:, i] = last
    forward = profile.direction in ("down", "right")
    prof = vals if forward else vals[:, ::-1].copy()
    b = math.floor(profile.linePosition * (h if vertical else w) + 0.5)   # çizgi: satır/sütun sınırı
    line = b - lo if forward else hi - b
    line = min(max(line, 2), n - 2)
    return prof, line


def match_shift(key: np.ndarray, cur: np.ndarray, line: int) -> tuple[float, int] | None:
    """§4.9.2 cur[k] ≈ key[k − s], s ∈ [0, smax] (kare toplamı farkı, alt piksel parabol).
    (s, smax) ya da eşleşme belirsizse None."""
    n = len(cur)
    win = max(4, n // 8)
    smax = max(2, n // 6)
    ka, kb = max(smax, line - win), min(n, line + win)
    if kb - ka < 4:
        return None
    seg = cur[ka:kb]
    errs = np.array([float(np.mean((seg - key[ka - s:kb - s]) ** 2)) for s in range(smax + 1)])
    k = int(np.argmin(errs))
    mean_e = float(np.mean(errs))
    if (mean_e - errs[k]) / (mean_e + 1e-6) < CONF_MIN:
        return None
    s = float(k)
    if 0 < k < smax:
        a, b, c = errs[k - 1], errs[k], errs[k + 1]
        d = a - 2 * b + c
        if d > 1e-9:
            s = k + 0.5 * (a - c) / d
    return s, smax


def motion_map(small: np.ndarray, prev: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """§4.9.0 |kare − önceki kare|, ROI maskesi dışı 0 (float64, h×w)."""
    return np.abs(small.astype(np.int16) - prev.astype(np.int16)).astype(np.float64) * mask


def frame_moving(motion: np.ndarray, profile: Profile) -> bool:
    """Kare hareketli mi: ROI içinde akışa dik en hareketli konumun ortalama farkı ≥ MOTION_MIN."""
    h, w = motion.shape
    x0, y0, x1, y1 = roi_pixels(profile.roi, w, h)
    sub = motion[y0:y1, x0:x1]
    axis = 0 if profile.vertical else 1
    return float((sub.sum(axis=axis) / max(1, sub.shape[axis])).max()) >= MOTION_MIN


def active_region(motion: np.ndarray, profile: Profile, mask: np.ndarray
                  ) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
    """§4.9.0 Hareketli bölge: ROI içinde akışa dik eksende (dikey akışta sütunlar) ortalama hareketi en
    hareketlinin ACTIVE_FRACTION'ı kadar olan konumlar — bant. Menüler, raylar, yerde duran nesneler hareket etmez;
    alan bandın yanlarına taşsa da yalnızca bant kullanılır. Akış ekseninde kırpılmaz (tek renk ürün içi kareler
    arasında değişmez, satır hareketi güvenilir değil). (maske, sınırlar) ya da hareket yoksa None."""
    h, w = mask.shape
    x0, y0, x1, y1 = roi_pixels(profile.roi, w, h)
    m = mask[y0:y1, x0:x1]
    sub = motion[y0:y1, x0:x1]
    vertical = profile.vertical
    axis = 0 if vertical else 1
    cnt = m.sum(axis=axis)
    cross = np.where(cnt > 0, sub.sum(axis=axis) / np.maximum(cnt, 1), 0.0)
    if cross.max() <= 0:
        return None
    sel = cross >= ACTIVE_FRACTION * float(cross.max())
    idx = np.nonzero(sel)[0]
    c0, c1 = int(idx[0]), int(idx[-1]) + 1
    out = np.zeros_like(mask)
    if vertical:
        out[y0:y1, x0:x1] = m & sel[None, :]
        return out, (x0 + c0, y0, x0 + c1, y1)
    out[y0:y1, x0:x1] = m & sel[:, None]
    return out, (x0, y0 + c0, x1, y0 + c1)


def levels(window: np.ndarray) -> tuple[float, float, float]:
    """§4.9.6 (lo, kontrast, ürün eşiği): lo = %2'lik, kontrast = %90'lık − lo, eşik = lo + 0,25·kontrast."""
    lo = percentile_lower(window, LO_Q)
    contrast = percentile_lower(window, 0.90) - lo
    return lo, contrast, lo + LOW_LEVEL * contrast


def lower_median(values: np.ndarray) -> float:
    s = np.sort(values)
    return float(s[(len(s) - 1) // 2])


def polarity_vote(small: np.ndarray, profile: Profile, mask: np.ndarray, line: int,
                  bounds: tuple[int, int, int, int] | None = None) -> int:
    """§4.9.4 Ürün banttan açık mı (+1) koyu mu (−1)? Çizgi çevresinde ROI'nin ortası ile kenarları karşılaştırılır
    (ürün genelde banttan dardır, kenarlarda bant görünür). Fark ≤ 15 gri seviye ise oy yok (0)."""
    h, w = small.shape
    x0, y0, x1, y1 = bounds or roi_pixels(profile.roi, w, h)
    forward = profile.direction in ("down", "right")
    if profile.vertical:
        c = (y0 + line) if forward else (y1 - 1 - line)
        r0, r1 = max(y0, c - 2), min(y1, c + 3)
        band, mband = small[r0:r1, x0:x1], mask[r0:r1, x0:x1]
    else:
        c = (x0 + line) if forward else (x1 - 1 - line)
        r0, r1 = max(x0, c - 2), min(x1, c + 3)
        band, mband = small[y0:y1, r0:r1].T, mask[y0:y1, r0:r1].T
    wd = band.shape[1]
    side = max(1, (15 * wd) // 100)
    c0, c1 = (3 * wd) // 10, wd - (3 * wd) // 10
    if c1 <= c0:
        return 0
    center = band[:, c0:c1][mband[:, c0:c1]]
    sides = np.concatenate([band[:, :side][mband[:, :side]], band[:, wd - side:][mband[:, wd - side:]]])
    if len(center) == 0 or len(sides) == 0:
        return 0
    diff = lower_median(center) - lower_median(sides)
    return 0 if abs(diff) <= 15 else (1 if diff > 0 else -1)


class LineScanCounter:
    def __init__(self) -> None:
        self._mask_key: tuple[object, ...] | None = None
        self._mask: np.ndarray | None = None
        self.reset()

    def reset(self) -> None:
        """Tam sıfırlama: hareketli sütunlar da yeniden seçilir (§4.9.0)."""
        self._active: np.ndarray | None = None
        self._bounds: tuple[int, int, int, int] | None = None
        self._w_prev: np.ndarray | None = None
        self._w_maps: list[np.ndarray] = []      # hareketli karelerin fark haritaları (en çok ACTIVE_FRAMES)
        self._w_frames: list[np.ndarray] = []    # ilk kare + hareketli kareler (bölge bulununca yeniden işlenir)
        self._reset_scan()

    def _reset_scan(self) -> None:
        self._prev: np.ndarray | None = None
        self._line = 0
        self._n = 0                       # ROI akış uzunluğu (işleme pikseli)
        self._acc = 0.0
        self._key: np.ndarray | None = None   # kayma ölçümünün referans profili (anahtar kare)
        self._base = 0.0                      # anahtar karenin konumu (geçen mesafe)
        self._dist = 0.0                      # toplam geçen mesafe
        self._vel = 0.0                       # son artış (eşleşme belirsizse sürdürülür)
        self._sig: list[float] = []       # mutlak indeks = self._off + liste indeksi
        self._pend: list[tuple[float, float]] = []   # yön (ürün açık/koyu) kararından önce (alt, üst çeyrek)
        self._prev_stats: np.ndarray | None = None
        # Bekletilen kısa parça: (sol ek yeri, sağ ek yeri, ürün başı, ürün sonu, kimlik, ön sayılan)
        self._carry: tuple[int | None, int, int, int, int, int] | None = None
        # Açık parça (son ek yerinden beri): kimlik, ürün başı/sonu, ön sayılan ürün adedi
        self._o_id = 0
        self._o_ia: int | None = None
        self._o_ib = 0
        self._o_k = 0
        self._low: float | None = None    # ürün kısmı eşiği (son kontrast ölçümünden)
        self._off = 0
        self._start = 0                   # bundan önceki merkezler başlangıçta zaten geçmişti
        self._end: int | None = None      # flush sonrası: bundan sonraki merkezler henüz geçmedi
        self._scan = 0                    # sıradaki çukur adayı (mutlak)
        self._last_seam: int | None = None
        self._p_pitch = 0.0
        self._p_len = 0.0
        self._learn_at = 0                # öğrenme denemesi için gereken sinyal uzunluğu
        self._try_at = 0                  # erken (güvenilirse kabul) öğrenme denemesi
        self._next_id = 1
        self._segs: list[_Seg] = []       # ekrandaki işaretler için son ürünler
        self.failed = False               # flush'ta ürün boyu öğrenilemediyse
        self._polarity = 0                # 0 = henüz karar yok, +1 ürün açık, −1 ürün koyu (sinyal ters çevrilir)
        self._votes = 0
        self.shifts: list[float] = []

    # ---- dış arayüz ----
    @property
    def product_length(self) -> float:
        """Öğrenilen/kullanılan ürün boyu (hareketli bölgenin akış uzunluğuna oranla; 0 = henüz yok)."""
        return self._p_len / self._n if self._n and self._p_len > 0 else 0.0

    def process(self, small: np.ndarray, profile: Profile) -> list[ScanEvent]:
        h, w = small.shape
        key = (profile.roi.x, profile.roi.y, profile.roi.width, profile.roi.height,
               tuple(profile.roiPolygon or ()), w, h, profile.vertical)
        if key != self._mask_key:
            self._mask_key, self._mask = key, roi_mask(profile.roi, profile.roiPolygon, w, h)
            self.reset()
        assert self._mask is not None
        if self._active is not None:
            return self._process_active(small, profile)
        # §4.9.0 Önce hangi sütunların hareket ettiğini öğren. İlk kare ve hareketli kareler saklanır; bölge
        # bulununca baştan işlenir (öğrenme sırasında çizgiyi geçen ürün kaçmaz). Hareketsiz/tekrarlanan kare
        # kayma 0 verdiği için atlanması sonucu değiştirmez.
        if self._w_prev is None:
            self._w_frames.append(small.copy())
        elif self._w_prev.shape == small.shape:
            mm = motion_map(small, self._w_prev, self._mask)
            if frame_moving(mm, profile):
                self._w_maps.append(mm)
                self._w_frames.append(small.copy())
        self._w_prev = small.copy()
        if len(self._w_maps) < ACTIVE_FRAMES:
            return []
        # Piksel başına alt medyan: siyah kare, sahne geçişi gibi tek tük kareler seçimi bozmasın
        region = active_region(np.sort(np.stack(self._w_maps), axis=0)[(ACTIVE_FRAMES - 1) // 2],
                               profile, self._mask)
        if region is None:
            self._w_maps.clear()
            self._w_frames = [small.copy()]
            return []
        self._active, self._bounds = region
        frames, self._w_frames, self._w_maps = self._w_frames, [], []
        events: list[ScanEvent] = []
        for f in frames:
            events += self._process_active(f, profile)
        return events

    def _process_active(self, small: np.ndarray, profile: Profile) -> list[ScanEvent]:
        assert self._active is not None
        fp = flow_profile(small, profile, self._active, self._bounds)
        if fp is None:
            return []
        stats, line = fp
        prof = stats[1]
        if self._polarity == 0:
            self._votes += polarity_vote(small, profile, self._active, line, self._bounds)
        if self._prev is None or len(self._prev) != len(prof) or line != self._line:
            self._begin(stats, line, profile)
            return []
        # Anahtar kareye göre ölç: kare kare yuvarlama hataları birikmez (tekrarlanan karelerde artış 0)
        m = match_shift(self._key, prof, line) if self._key is not None else None
        if m is None:
            d = self._dist + self._vel
            self._key, self._base = prof, d
        else:
            d = self._base + m[0]
            if m[0] >= m[1] / 2:
                self._key, self._base = prof, d
        inc = max(0.0, d - self._dist)
        self._vel = inc
        self._dist = max(self._dist, d)
        self.shifts.append(inc)
        self._acc += inc
        k = math.floor(self._acc)
        self._acc -= k
        k = min(k, self._n - line)
        for j in range(k):                # bu karede çizgiyi geçen k satır, önce geçen önce
            self._push(stats[0, line + k - 1 - j], stats[2, line + k - 1 - j])
        self._prev, self._prev_stats = prof, stats
        return self._advance(profile, final=False)

    def flush(self, profile: Profile) -> list[ScanEvent]:
        """Video sonu: son karede çizgiye henüz varmamış kısım eklenir, merkezi geçmiş ürünler sayılır."""
        if self._prev is None or self._end is not None:
            return []
        self._end = self._total()
        st = self._prev_stats
        for k in range(self._line - 1, -1, -1):
            self._push(st[0, k], st[2, k])
        return self._advance(profile, final=True)

    def markers(self, small_shape: tuple[int, int], profile: Profile) -> list[ScanMarker]:
        """Son sayılan ürünlerin şimdiki konumu (çizgiden geçtikleri mesafe kadar ileride)."""
        if self._prev is None:
            return []
        h, w = small_shape
        x0, y0, x1, y1 = self._bounds or roi_pixels(profile.roi, w, h)
        emitted = self._end if self._end is not None else self._total()
        out: list[ScanMarker] = []
        forward = profile.direction in ("down", "right")
        items: list[tuple[int, float, bool]] = [
            (seg.id * 16 + q, c, self._in_range(c)) for seg in self._segs for q, c in enumerate(seg.centers)]
        plen = self._p_len
        if self._carry is not None:
            cid, cia, ck = self._carry[4], self._carry[2], self._carry[5]
            items += [(cid * 16 + q, cia + (q + 0.5) * plen, True) for q in range(ck)]
        if self._o_ia is not None:
            items += [(self._o_id * 16 + q, self._o_ia + (q + 0.5) * plen, True) for q in range(self._o_k)]
        for mid, c, counted in items:
            k = self._line + (emitted - c)
            if not 0 <= k < self._n:
                continue
            if profile.vertical:
                yy = (y0 + k + 0.5) if forward else (y1 - 1 - k + 0.5)
                out.append(ScanMarker(mid, (x0 + x1) / 2 / w, yy / h, counted))
            else:
                xx = (x0 + k + 0.5) if forward else (x1 - 1 - k + 0.5)
                out.append(ScanMarker(mid, xx / w, (y0 + y1) / 2 / h, counted))
        return out

    @property
    def moving(self) -> bool:
        """Son karede bant hareket etti mi (§8 çalışıyor/durdu)."""
        return bool(self.shifts) and self.shifts[-1] > 0.05

    def _in_range(self, c: float) -> bool:
        return c >= self._start and (self._end is None or c < self._end)

    # ---- iç işler ----
    def _begin(self, stats: np.ndarray, line: int, profile: Profile) -> None:
        n = stats.shape[1]
        keep = (self._p_len, self._polarity) if self._n == n else (0.0, 0)
        self._reset_scan()
        self._prev, self._prev_stats, self._line, self._n = stats[1], stats, line, n
        self._key = stats[1]
        if keep[0] > 0 and profile.productLength <= 0:
            self._p_len = self._p_pitch = keep[0]
        self._polarity = keep[1]
        # Başlangıçta çizgiyi zaten geçmiş kısım (en uzaktaki en önce geçmiştir)
        for k in range(n - 1, line - 1, -1):
            self._push(stats[0, k], stats[2, k])
        self._start = self._total()
        self._learn_at = self._start + 2 * self._n

    def _push(self, lo: float, hi: float) -> None:
        if self._polarity == 0:
            self._pend.append((float(lo), float(hi)))
        else:
            self._sig.append(float(hi) if self._polarity > 0 else 255.0 - float(lo))

    def _total(self) -> int:
        return self._off + len(self._sig) + len(self._pend)

    def _sm(self, i: int, r: int) -> float:
        a = max(self._off, i - r) - self._off
        b = min(self._off + len(self._sig), i + r + 1) - self._off
        return float(np.mean(self._sig[a:b]))

    def _ensure_period(self, profile: Profile, final: bool) -> bool:
        total = self._total()
        if self._polarity == 0:
            # Açık/koyu kararı ve (boy bilinmiyorsa) boy öğrenme: en erken bir alan boyu bant aktıktan sonra.
            # Boy bilinmiyorsa iki alan boyuna kadar yalnızca güvenilir sonuç kabul edilir (≥ 4 tam ürün, tutarlı
            # boylar); sayılar gecikip topluca gelmesin ama erken ve yanlış bir boy da kalıcı olmasın.
            if total < self._start + self._n and not final:
                return False
            if profile.productLength > 0 or final or total >= self._start + 2 * self._n:
                self._decide_polarity(profile)
            else:
                if total < self._try_at:
                    return False
                self._try_at = total + max(4, self._n // 2)
                if not self._decide_polarity(profile, strict=True):
                    return False
        if profile.productLength > 0:
            self._p_len = self._p_pitch = profile.productLength * self._n
            return True
        if self._p_len > 0:
            return True
        if total < self._learn_at and not final:
            return False
        r = self._learn()
        if r is None:
            self._learn_at = total + self._n
            if final:
                self.failed = True
            return False
        self._p_len = self._p_pitch = r[0]
        return True

    def _decide_polarity(self, profile: Profile, strict: bool = False) -> bool:
        """§4.9.4 Ürün banttan açık mı koyu mu: iki yorumla da parçalara ayır; parça boylarını ürün boyunun
        katlarıyla daha tutarlı açıklayan (kalan hatası küçük olan) doğrudur. Yanlış yorumda "ürünler" aslında
        boşluklardır, boyları tutarsızdır. Fark belirsizse (< 0,03) kenar/orta oyları karar verir."""
        pend, self._pend = self._pend, []

        def reliable(r: tuple[float, float, int] | None) -> bool:
            return r is not None and r[2] >= RELIABLE_SEGMENTS and r[1] <= 0.15

        def rollback() -> bool:
            self._pend, self._sig, self._polarity = pend, [], 0
            return False

        forced = _spread_polarity(pend)
        if forced != 0:
            # Kesin ipucu: ürün satırında kenarlarda bant görünür (satır içi yayılım büyük), boş bant satırı düzdür
            self._sig = [hi if forced > 0 else 255.0 - lo for lo, hi in pend]
            if profile.productLength <= 0:
                r = self._learn()
                if strict and not reliable(r):
                    return rollback()
                if r is not None:
                    self._p_len = self._p_pitch = r[0]
            self._polarity = forced
            return True
        best: tuple[float, int, float, int] | None = None   # (kalan hata, yön, boy, tam parça sayısı)
        for pol in (1, -1):
            self._sig = [hi if pol > 0 else 255.0 - lo for lo, hi in pend]
            r: tuple[float, float, int] | None
            if profile.productLength > 0:
                plen = profile.productLength * self._n
                res = self._residual(max(4, round(plen)), self._off + len(self._sig))
                r = (plen, res, 0) if res is not None else None
            else:
                r = self._learn()
            if r is None:
                continue
            if best is None or r[1] < best[0] - 0.03:
                best = (r[1], pol, r[0], r[2])
            elif abs(r[1] - best[0]) <= 0.03:                # belirsiz: oylar
                vote_pol = -1 if self._votes < 0 else 1
                if pol == vote_pol:
                    best = (r[1], pol, r[0], r[2])
        if strict and (best is None or not reliable((best[2], best[0], best[3]))):
            return rollback()
        self._polarity = best[1] if best is not None else (-1 if self._votes < 0 else 1)
        self._sig = [hi if self._polarity > 0 else 255.0 - lo for lo, hi in pend]
        if best is not None and profile.productLength <= 0:
            self._p_len = self._p_pitch = best[2]
        return True

    def _residual(self, pp: int, total: int) -> float | None:
        """Parça boylarının pp'nin tam katlarına ortalama uzaklığı (en az 2 tam parça yoksa None)."""
        lens = self._seg_lengths(pp, total)
        if len(lens) < 2:
            return None
        return float(np.mean([abs(v / pp - max(1, round(v / pp))) for v in lens]))

    def _learn(self) -> tuple[float, float, int] | None:
        """§4.9.5 Tek ürün boyu: (a) öz-ilinti aralığı (ham ve yüksek geçiren sinyalde, güçlü olanı),
        (b) parlak koşuların medyanı; adaylar ve parça taramasıyla inceltilmiş halleri arasından parça boylarını
        en iyi açıklayan (oran tam sayıya yakın) EN BÜYÜK boy. P/2 de tam sayılar verir (2'şer), bu yüzden büyükten
        küçüğe bakılır; 2P oranları 0,5 yapar, elenir. (boy, kalan hata, tam parça sayısı) ya da None."""
        x = np.asarray(self._sig, dtype=np.float64)
        n = len(x)
        pmin = max(4, self._n // 10)
        pmax = min(self._n, n // 2)
        cands: list[float] = []
        best_ac: tuple[float, float] | None = None
        for sig in (x - x.mean(), _highpass(x, max(2, pmin // 2))):
            r = _autocorr_peak(sig, pmin, pmax)
            if r is not None and (best_ac is None or r[1] > best_ac[1]):
                best_ac = r
        if best_ac is not None:
            cands.append(best_ac[0])
        run = _run_median(x, pmin)
        if run is not None:
            cands.append(run)
        if not cands:
            return None
        total = self._off + n
        for c in list(cands):
            lens = self._seg_lengths(max(4, round(c)), total)
            if len(lens) >= 2:
                cands.append(float(lens[(len(lens) - 1) // 2]))
        scored: dict[int, float] = {}
        for c in cands:
            q = max(4, round(c))
            if q < pmin:                    # alanın onda birinden kısa "ürün" kıvrım/etiket parçasıdır
                continue
            if q not in scored:
                res = self._residual(q, total)
                scored[q] = 1.0 if res is None else res
        if not scored:
            return None
        good = [q for q, r in scored.items() if r <= 0.15]
        q = max(good) if good else min(scored, key=lambda k: (scored[k], k))
        return float(q), scored[q], len(self._seg_lengths(q, total))

    def _seg_lengths(self, pp: int, total: int) -> list[int]:
        """Tamamlanmış (ilk/son hariç) parçaların ürün kısmı uzunlukları (≥ 0,3·pp)."""
        _, segs = self._detect(pp, self._off, total)
        return sorted(ib - ia for (_a, _b, ia, ib) in segs[1:-1] if ib - ia >= 0.3 * pp)

    def _seam_at(self, i: int, pp: int, total: int, final: bool) -> tuple[bool, float, float] | None:
        """§4.9.6 i ek yeri mi? (karar, ürün eşiği, kontrast). Yeterli ileri veri yoksa None.
        İki tür: (a) dar çukur — yerel en küçük ve derinliği ≥ 0,25·kontrast (bitişik ürün arası, gölge);
        (b) düşen kenar — sinyal ürün eşiğinin (lo + 0,25·kontrast) altına iner (aralıklı ürünlerde uzun boş bant;
        düz boşlukta çukur derinliği ölçülemez)."""
        r = pp // 50
        half = max(1, pp // 3)
        hp = max(1, pp // 2)
        if not final and i + hp + r >= total:
            return None
        v = self._sm(i, r)
        v_prev = self._sm(i - 1, r) if i - 1 >= self._off else None
        lo_i = max(self._off, i - half)
        hi_i = min(total - 1, i + half)
        local_min = True
        for j in range(lo_i, hi_i + 1):
            sj = self._sm(j, r)
            if sj < v or (j < i and sj <= v):
                local_min = False
                break
        if not local_min and (v_prev is None or v >= v_prev):
            return False, 0.0, 0.0
        wa, wb = max(self._off, i - 4 * pp), min(total, i + hp + 1)
        window = np.array([self._sm(j, r) for j in range(wa, wb)])
        _, contrast, low = levels(window)
        if contrast < MIN_CONTRAST:
            return False, low, contrast
        if v_prev is not None and v <= low < v_prev:
            return True, low, contrast                       # (b) düşen kenar
        if not local_min:
            return False, low, contrast
        lmax = max(self._sm(j, r) for j in range(max(self._off, i - hp), i + 1))
        rmax = max(self._sm(j, r) for j in range(i, min(total - 1, i + hp) + 1))
        return min(lmax, rmax) - v >= SEAM_PROMINENCE * contrast, low, contrast

    def _detect(self, pp: int, a0: int, total: int) -> tuple[list[int], list[tuple[int, int, int, int]]]:
        """Çevrimdışı tarama (öğrenme için): çukurlar ve parçalar (a, b, ürün_başı, ürün_sonu)."""
        half = max(1, pp // 3)
        seams: list[int] = []
        segs: list[tuple[int, int, int, int]] = []
        prev = a0
        for i in range(a0, total):
            res = self._seam_at(i, pp, total, final=True)
            if res is None or not res[0]:
                continue
            if seams and i - seams[-1] < half:
                continue
            seg = self._bright(prev, i, pp, res[1])
            if seg is not None:
                segs.append((prev, i, *seg))
            seams.append(i)
            prev = i
        return seams, segs

    def _bright(self, a: int, b: int, pp: int, low: float) -> tuple[int, int] | None:
        """Ürün kısmı: [a, b) içinde eşiğin üstündeki, en az max(2, 0,15·pp) uzunluktaki koşuların ilk ve son
        indeksi (boş bant eşiğe yakınsa gürültüyle oluşan kısa kırıntılar ürüne katılmasın)."""
        r = pp // 50
        min_run = max(2, round(0.15 * pp))
        first: int | None = None
        last = 0
        run_start: int | None = None
        for j in range(a, b + 1):
            above = j < b and self._sm(j, r) > low
            if above and run_start is None:
                run_start = j
            elif not above and run_start is not None:
                if j - run_start >= min_run:
                    if first is None:
                        first = run_start
                    last = j
                run_start = None
        if first is None:
            return None
        return first, last

    def _advance(self, profile: Profile, final: bool) -> list[ScanEvent]:
        if not self._ensure_period(profile, final):
            return []
        pp = max(4, round(self._p_pitch))
        half = max(1, pp // 3)
        r = pp // 50
        total = self._off + len(self._sig)
        events: list[ScanEvent] = []
        last_low, last_c = 0.0, 0.0
        while self._scan < total:
            i = self._scan
            res = self._seam_at(i, pp, total, final)
            if res is None:
                break
            self._scan += 1
            ok, low, contrast = res
            if contrast > 0:
                last_low, last_c = low, contrast
                self._low = low
            if ok and (self._last_seam is None or i - self._last_seam >= half):
                events += self._close(self._last_seam, i, pp, low, profile)
                self._last_seam = i
                self._o_ia, self._o_k = None, 0
            elif self._low is not None and self._sm(i, r) > self._low:
                if self._o_ia is None:
                    self._o_ia, self._o_id = i, self._next_id
                    self._next_id += 1
                self._o_ib = i + 1
                events += self._provisional(profile)
        if final:
            a = self._last_seam if self._last_seam is not None else self._off
            if last_c <= 0:
                window = np.array([self._sm(j, r) for j in range(max(self._off, total - 4 * pp), total)])
                _, last_c, last_low = levels(window)
            if last_c >= MIN_CONTRAST:
                events += self._close(a if self._last_seam is not None else None, total, pp,
                                      last_low, profile, right_seam=False)
            events += self._flush_carry(profile)
            self._o_ia, self._o_k = None, 0
        self._trim(pp)
        return events

    def _provisional(self, profile: Profile) -> list[ScanEvent]:
        """§4.9.7 Ön sayım: açık parçanın ürün kısmı 0,5·P'yi geçince ilk ürünün merkezi çizgiyi geçmiştir,
        hemen sayılır (numara ürün çizgideyken görünsün). Kesin karar parça kapanınca: eksik kalan eklenir,
        fazla sayılan geri alınmaz. Başlangıçtan önce başlamış parçada ve bekletilen kısa parçaya bitişikken
        (birleşebilir) ön sayım yapılmaz."""
        assert self._o_ia is not None
        if self._o_ia < self._start:
            return []
        plen = self._p_len
        a = self._last_seam if self._last_seam is not None else self._off
        if (self._carry is not None and self._o_ia - a <= 0.15 * plen
                and self._o_ib - self._carry[2] <= 1.35 * plen):
            return []
        # Yalnızca parçanın ilk ürünü: açık parçanın uzunluğu kapanıştakinden uzun ölçülebilir (eşik henüz
        # oturmamış); ikinci ve sonraki ürünler kapanışta kesin olarak eklenir (fazla sayım geri alınamaz)
        target = min(1, math.floor((self._o_ib - self._o_ia) / plen + 0.5))
        out: list[ScanEvent] = []
        while self._o_k < target:
            c = self._o_ia + (self._o_k + 0.5) * plen
            if self._end is not None and c >= self._end:
                break
            out.append(ScanEvent(self._o_id * 16 + self._o_k, 1))
            self._o_k += 1
        return out

    def _close(self, a: int | None, b: int, pp: int, low: float, profile: Profile,
               right_seam: bool = True) -> list[ScanEvent]:
        """§4.9.6 Parçayı kapat. Kısa parça (< 0,75·P) sağ komşusuna bitişikse bekletilir: sonraki parçayla
        birleşince ≤ 1,35·P oluyorsa aradaki çukur ürün içi kıvrımdır, tek ürün sayılır."""
        out: list[ScanEvent] = []
        start = a if a is not None else self._off
        sid = self._o_id if self._o_ia is not None else 0
        k = self._o_k if self._o_ia is not None else 0
        br = self._bright(start, b, pp, low)
        if br is None:                                   # yalnızca boş bant
            out += self._flush_carry(profile)
            return out
        if sid == 0:
            sid = self._next_id
            self._next_id += 1
        ia, ib = br
        plen = self._p_len
        tight = 0.15 * plen
        isolated = a is None or ia - start > tight          # önünde gerçek boşluk (boş bant) var
        if self._carry is not None:
            c_a, _cb, c_ia, _cib, c_id, c_k = self._carry
            if ia - start <= tight and ib - c_ia <= 1.35 * plen:
                a, ia, sid, k = c_a, c_ia, c_id, c_k + k
                self._carry = None
                isolated = False
            else:
                out += self._flush_carry(profile)
        if ib - ia < 0.75 * plen and right_seam and b - ib <= tight and self._sm(b, pp // 50) > low:
            self._carry = (a, b, ia, ib, sid, k)
            return out
        out += self._emit(a, b, ia, ib, right_seam, profile, sid, k, isolated)
        return out

    def _flush_carry(self, profile: Profile) -> list[ScanEvent]:
        if self._carry is None:
            return []
        a, b, ia, ib, sid, k = self._carry
        self._carry = None
        return self._emit(a, b, ia, ib, True, profile, sid, k)

    def _emit(self, a: int | None, b: int, ia: int, ib: int, right_seam: bool, profile: Profile,
              sid: int, k: int, isolated: bool = False) -> list[ScanEvent]:
        """Kesin karar: n ürün; ilk k'sı ön sayımla zaten sayıldı (fazlası geri alınmaz). Önünde boşluk olan tek
        başına parça ≥ 0,25·P ise bir üründür (perspektifte uzak/sivri görünen torba; parlak kısmı kısa kalır)."""
        n = min(profile.maxMultiplicity, math.floor((ib - ia) / self._p_len + 0.5))
        if n == 0 and isolated and ib - ia >= 0.25 * self._p_len:
            n = 1
        if n <= 0:
            return []
        # Merkez: ek yerleri arası; ürün ile ek yeri arasında boşluk (boş bant) varsa ürün kısmının biraz dışı.
        # (Gölgeli uçlar ürün kısmını kısaltır; bitişikte ek yeri, aralıklıda ürünün kendisi esas alınır.)
        e = 0.1 * self._p_len
        ca = max(a, ia - e) if a is not None else ia - e
        cb = min(b, ib + e) if right_seam else ib + e
        centers = [ca + (q + 0.5) * (cb - ca) / n for q in range(n)]
        seg = _Seg(sid, centers, max(k, sum(1 for c in centers if self._in_range(c))))
        self._segs = [*self._segs[-7:], seg]
        return [ScanEvent(sid * 16 + q, 1) for q in range(k, n) if self._in_range(centers[q])]

    def _trim(self, pp: int) -> None:
        """Bir daha okunmayacak eski sinyali at (sonucu değiştirmez)."""
        keep_from = min(self._scan - 4 * pp - pp, self._last_seam if self._last_seam is not None else self._off)
        drop = keep_from - self._off - pp // 50 - 2
        if drop > 4096:
            del self._sig[:drop]
            self._off += drop


def _highpass(x: np.ndarray, w: int) -> np.ndarray:
    """x − kayan ortalama (pencere 2w+1, uçlarda kırpılır): ince ek yerlerini öne çıkarır."""
    c = np.concatenate([[0.0], np.cumsum(x)])
    i = np.arange(len(x))
    a, b = np.maximum(0, i - w), np.minimum(len(x), i + w + 1)
    return x - (c[b] - c[a]) / (b - a)


def _autocorr_peak(x: np.ndarray, pmin: int, pmax: int) -> tuple[float, float] | None:
    """Öz-ilintinin [pmin, pmax) tepeleri; en güçlüsü ≥ 0.1 ise gücü onun %60'ından az olmayan en kısa gecikme
    (2P, 3P de tepe verir). (gecikme, güç) ya da None."""
    n = len(x)
    den = float(np.dot(x, x))
    if pmax <= pmin + 1 or den <= 1e-9:
        return None
    ac = np.array([float(np.dot(x[: n - lag], x[lag:])) / den for lag in range(pmax + 1)])
    peaks = [lag for lag in range(pmin, pmax) if ac[lag] > ac[lag - 1] and ac[lag] >= ac[lag + 1]]
    if not peaks:
        return None
    best = max(float(ac[lag]) for lag in peaks)
    if best < 0.1:
        return None
    return float(next(lag for lag in peaks if ac[lag] >= 0.6 * best)), best


def _run_median(x: np.ndarray, pmin: int) -> float | None:
    """Orta seviyenin üstündeki koşuların (uçlara değmeyen, ≥ pmin) medyanı; en az 2 koşu yoksa None."""
    r = max(1, pmin // 8)
    c = np.concatenate([[0.0], np.cumsum(x)])
    i = np.arange(len(x))
    a, b = np.maximum(0, i - r), np.minimum(len(x), i + r + 1)
    sm = (c[b] - c[a]) / (b - a)
    lo = percentile_lower(sm, 0.05)
    mid = lo + 0.5 * (percentile_lower(sm, 0.90) - lo)
    runs: list[int] = []
    k = 0
    while k < len(sm):
        if sm[k] > mid:
            j = k
            while j < len(sm) and sm[j] > mid:
                j += 1
            if k > 0 and j < len(sm) and j - k >= pmin:
                runs.append(j - k)
            k = j
        else:
            k += 1
    if len(runs) < 2:
        return None
    runs.sort()
    return float(runs[(len(runs) - 1) // 2])


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    da, db = a - a.mean(), b - b.mean()
    den = float(np.sqrt(float(np.dot(da, da)) * float(np.dot(db, db))))
    return float(np.dot(da, db)) / den if den > 1e-9 else 0.0


def _spread_polarity(pend: list[tuple[float, float]]) -> int:
    """§4.9.4 Yayılım ipucu: satır içi yayılım s = üst − alt çeyrek. Ürün banttan dar ise ürün satırlarında s büyür;
    açık üründe parlaklık (üst çeyrek) s ile pozitif, koyu ürün yorumu (255 − alt çeyrek) negatif ilişkilidir.
    Biri > 0,3 ve diğeri < 0 ise kesin (+1/−1); değilse 0 (bitişik akışta gölgeli ek yerleri de yayılım verir)."""
    if len(pend) < 8:
        return 0
    arr = np.asarray(pend, dtype=np.float64)
    lo, hi = arr[:, 0], arr[:, 1]
    spread = hi - lo
    cn, ci = _pearson(hi, spread), _pearson(255.0 - lo, spread)
    if cn > 0.3 and ci < 0:
        return 1
    if ci > 0.3 and cn < 0:
        return -1
    return 0
