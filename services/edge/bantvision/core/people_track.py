"""Kişi/araç/hayvan takibi ve çizgi geçiş sayımı — docs/03-algorithm.md §4.10.

Bant izleyicisi (§4) tek yönlü akış ve birleşen/ayrılan lekeler içindir. İnsanlar durur, geri döner, kalabalıkta
birbirinin önünden geçer; tanıma bazı karelerde kişiyi kaçırır. Bu yüzden ayrı bir izleyici (ByteTrack tarzı):

- **Tahmin:** her iz sabit hızla (kutu değişimi/kare) ilerletilir; eşleşmeyen iz `maxAge` kare boyunca tahminle
  yaşar (kısa kayıp ve örtüşmede kimlik korunur). Hız uzun tabanlıdır: şimdiki gözlem ile `velWindow` kare
  önceki gözlem arasındaki değişim / kare (tek karelik sıçrama ya da yer değiştirme hızı bozmaz). Eşleşme hem
  tahmin edilen hem son görülen kutuya karşı denenir (yürümeye devam eden de, kayıpken duran da yakalanır).
  Kayıptaki izin merkez kapısı her kayıp karede `gateGrow` kadar büyür (`gateMax`'a kadar): öndeki kişinin
  arkasında kalıp yeniden çıkan kişi eski kimliğine bağlanır.
- **Tek turda eşleştirme (yan yana gruplar için):** tüm iz–tespit çiftleri örtüşmeye (IoU) göre, sonra merkez
  yakınlığına göre sıralanıp açgözlü eşlenir. Yüksek güvenli tespit IoU ya da merkez kapısıyla, düşük güvenli tespit
  yalnızca daha sıkı IoU ile aday olur. Böylece kişinin kendi silik tespiti, yanındakinin güçlü tespitinden önce
  gelir (iki aşamalı ByteTrack'te iz komşuya atlıyordu). Merkez kapısı kutu boyuna göre ölçeklenir: |dx|/en ve
  |dy|/boy elipsi — yana bir kişi eninden az, kişinin kendi hareketine yeterli. Düşük güvenli tespit yeni iz
  başlatmaz → yanlış iz yok, ama mevcut kişi silikleşse de izlenir.
- **Parça kutu bastırma:** başka bir kutunun neredeyse tamamen içinde kalan kutu (aynı kişinin üst gövdesi/yarısı)
  ayrı kişi değildir: atılır, güveni kapsayan kutuya aktarılır. Yan yana grupta mükerrer iz/sayım bundan doğar.
  Yalnızca belirgin küçük kutular (alan ≤ %75) atılır: aynı boyda üst üste binen kutu arkadaki gerçek kişidir.
- **Hareket desteği (tepeden kamera):** hazır tanıyıcı kameranın tam altındaki kişiyi (yalnızca kafa/omuz görünür)
  çoğu zaman bulamaz. Tanımanın eşleşmediği iz, yakınındaki hareket lekesiyle sürer (leke tek kişiden büyükse —
  birleşmiş grup — iz kendi tahmini konumunda lekenin içine kısıtlanır; yan yana kişiler tek ize çökmez). Hiçbir izin
  açıklamadığı leke "doğrulanmamış" iz başlatır: geçişleri bekletilir ve iz en az bir kez yüksek güvenli tanımayla
  eşleşince sayılır; hiç eşleşmezse (kapı, gölge, ışık, araba) hiç sayılmaz. Doğrulanmış bir izle örtüşen
  doğrulanmamış iz silinir (aynı kişinin iki izden iki kez sayılması önlenir).
- **Alandan çıkan iz silinir:** tahmini merkezi sayım alanının (ROI) dışına çıkan iz hemen silinir. Yoksa kadrajın
  kenarından çıkan kişinin tahminle yaşayan izi aynı kenardan giren yeni kişiye bağlanıyor, ters yönde geçip ikinci
  kez sayılıyordu (yeni kişinin kendi izi de sayılır → mükerrer).
- **Onay:** iz doğrulanmış ve `minHits` gözlemli olunca sayılabilir olur; onaydan önceki geçiş onayla birlikte sayılır.
- **Tampon bantlı çizgi:** çapa noktasının çizgiye işaretli uzaklığı s; bant = max(band, band_rel × kutu boyu);
  s > +bant → bir yan, s < −bant → öbür yan, arası "çizgi üstü" (yan değişmez). Yeni yan art arda `side_frames`
  gözlemde görülmeden geçiş sayılmaz (kutu kenarının tek karelik zıplaması giriş/çıkış üretmez). Yan −1'den +1'e geçince giriş, tersinde çıkış. Çizgide bekleyen/sallanan
  kişi sayılmaz; girip geri dönen bir giriş + bir çıkış sayılır (doğrusu bu). Yalnızca gerçek gözlemler (tahmin
  değil) yan belirler: hayalet geçiş olmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

Box = tuple[float, float, float, float]          # x1, y1, x2, y2 (normalize)


@dataclass
class MotParams:
    high: float = 0.45          # yeni iz başlatabilen tespit güveni
    low: float = 0.15           # yalnızca mevcut izi sürdürebilen en düşük güven
    iou_match: float = 0.2      # 1. aşama IoU eşiği
    iou_low: float = 0.3        # 2. aşama (düşük güven) IoU eşiği
    center_gate: float = 0.8    # IoU yetmezse: hypot(dx/en, dy/boy) < bu (komşu kişi ≈ 0,9+ uzakta)
    tentative_age: int = 2      # onaysız iz bu kadar ardışık kayba dayanır
    gate_grow: float = 0.5      # kayıp kare başına kapı büyümesi × izin hızı (kutu boyuna göre; duran iz büyümez)
    gate_max: float = 1.6
    vel_window: int = 10        # hız tabanı (kare)
    min_hits: int = 3
    max_age: int = 30           # tahminle yaşama (kare)
    band: float = 0.02          # çizgi tampon bandı (yarı genişlik, normalize) …
    band_rel: float = 0.1       # … en az kutu boyunun bu kadarı (yakındaki büyük kişide kutu kenarı daha çok titrer)
    side_frames: int = 2        # yeni yan art arda bu kadar gözlemde görülünce geçiş sayılır (tek karelik zıplama değil)
    contain: float = 0.85       # kesişim/küçük kutu alanı ≥ bu → parça kutu, atılır …
    part_area: float = 0.75     # … ve küçük kutu alanı ≤ bu × büyük (eş boy kutu: arkadaki gerçek kişi, atılmaz)
    motion_gate: float = 1.0    # hareket lekesi kapısı (izin en/boyuna göre)
    group_area: float = 1.8     # leke alanı > bu × iz alanı → birleşmiş grup lekesi
    group_margin: float = 1.0   # grup lekesinde tahmini merkez lekeye en fazla kutu boyunun bu kadarı uzaksa kısıtlanır
    dup_iou: float = 0.3        # doğrulanmamış iz bu örtüşmeyle doğrulanmış ize binerse silinir
    motion_life: float = 1.5    # doğrulanmış iz son tanımadan sonra en fazla max_age × bu kadar kare lekeyle yaşar
    unverified_life: float = 3.0  # hiç tanınmamış (lekeden doğan) iz en fazla max_age × bu kadar kare yaşar


@dataclass
class MotTrack:
    id: int
    box: np.ndarray                                 # tahmin edilen (gözlenen karede: gözlenen) kutu
    vel: np.ndarray
    last: np.ndarray                                # son gözlenen kutu
    score: float
    hits: int = 1
    misses: int = 0
    confirmed: bool = False
    side: int = 0                                   # son kesin yan: −1, +1; 0 bilinmiyor
    cand: int = 0                                   # aday yeni yan ve art arda görülme sayısı (yan teyidi)
    cand_n: int = 0
    pending: list[int] = field(default_factory=list)    # onaydan önce olan geçişler (+1 giriş, −1 çıkış)
    trail: list[tuple[float, float]] = field(default_factory=list)
    hist: list[tuple[int, np.ndarray]] = field(default_factory=list)   # (kare, gözlenen kutu), hız tabanı
    entries: int = 0
    exits: int = 0
    verified: bool = True                           # en az bir yüksek güvenli tanımayla eşleşti (hareket izi: False)
    born: int = 0                                   # doğduğu kare
    last_det: int = 0                               # son tanımayla eşleştiği kare


def iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def anchor(box: np.ndarray, mode: str) -> tuple[float, float]:
    """Çizgiye göre konum noktası: kutu merkezi ya da alt orta (yatık kamerada ayak, zemindeki çizgiyle tutarlı)."""
    cx = float(box[0] + box[2]) / 2
    return (cx, float(box[3])) if mode == "bottom" else (cx, float(box[1] + box[3]) / 2)


def suppress_parts(dets: list[tuple[Box, float]], contain: float, part_area: float) -> list[tuple[Box, float]]:
    """Başka bir kutunun içinde kalan parça kutuları atar; kapsayan kutu ikisinin yüksek güvenini alır."""
    order = sorted(range(len(dets)), key=lambda i: -_area(dets[i][0]))
    kept: list[list] = []
    for i in order:
        b, s = dets[i]
        a = _area(b)
        for k in kept:
            c = k[0]
            inter = max(0.0, min(b[2], c[2]) - max(b[0], c[0])) * max(0.0, min(b[3], c[3]) - max(b[1], c[1]))
            if a > 0 and inter / a >= contain and a <= part_area * _area(c):
                k[1] = max(k[1], s)
                break
        else:
            kept.append([b, s])
    return [(b, s) for b, s in kept]


def _area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _center(b: np.ndarray) -> tuple[float, float]:
    return float(b[0] + b[2]) / 2, float(b[1] + b[3]) / 2


def _center_in(b: np.ndarray, c: np.ndarray) -> bool:
    """`b` kutusunun merkezi `c` kutusunun içinde mi?"""
    x, y = _center(b)
    return bool(c[0] <= x <= c[2] and c[1] <= y <= c[3])


def _box_at(size: np.ndarray, c: tuple[float, float]) -> np.ndarray:
    """`size` boyunda, merkezi `c` olan kutu."""
    hw, hh = float(size[2] - size[0]) / 2, float(size[3] - size[1]) / 2
    return np.array([c[0] - hw, c[1] - hh, c[0] + hw, c[1] + hh])


def _gate_dist(a: np.ndarray, size: np.ndarray, b: np.ndarray) -> float:
    """Merkezler arası uzaklık, `size` kutusunun en ve boyuna göre normalize (elips kapı)."""
    w = max(float(size[2] - size[0]), 1e-6)
    h = max(float(size[3] - size[1]), 1e-6)
    return float(np.hypot((a[0] + a[2] - b[0] - b[2]) / 2 / w, (a[1] + a[3] - b[1] - b[3]) / 2 / h))


class MotTracker:
    def __init__(self, params: MotParams | None = None) -> None:
        self.p = params or MotParams()
        self.tracks: list[MotTrack] = []
        self.next_id = 1
        self.frame = 0

    def reset(self) -> None:
        self.tracks.clear()

    def update(self, dets: list[tuple[Box, float]], side_of: object, anchor_mode: str = "center",
               motion: list[Box] | None = None, bounds: Box = (0.0, 0.0, 1.0, 1.0)
               ) -> tuple[list[MotTrack], list[MotTrack]]:
        """Bir kare. `side_of(x, y) -> s` çizgiye işaretli uzaklık (giriş yönü pozitif); `motion`: hareket lekeleri
        (isteğe bağlı); `bounds`: sayım alanı (ROI) — tahmini merkezi dışına çıkan iz silinir. (girenler, çıkanlar)."""
        p = self.p
        for t in self.tracks:                                     # tahmin
            t.box = t.box + t.vel
        dets = suppress_parts(dets, p.contain, p.part_area)
        boxes = [np.asarray(b, np.float64) for b, _ in dets]
        scores = [s for _, s in dets]
        high = [i for i, s in enumerate(scores) if s >= p.high]
        low = [i for i, s in enumerate(scores) if p.low <= s < p.high]

        matched_t: set[int] = set()
        matched_d: dict[int, int] = {}                            # iz indeksi → tespit indeksi
        used_d: set[int] = set()

        pairs: list[tuple[float, float, int, int]] = []
        for ti, t in enumerate(self.tracks):
            for di in high + low:
                b = boxes[di]
                ov = max(iou(t.box, b), iou(t.last, b))
                dc = min(_gate_dist(t.box, t.last, b), _gate_dist(t.last, t.last, b))
                gate = min(p.gate_max, p.center_gate + self._grow(t))
                ok = (ov >= p.iou_match or dc < gate) if scores[di] >= p.high else ov >= p.iou_low
                if ok:
                    pairs.append((-ov, dc, ti, di))
        pairs.sort()
        for _, _, ti, di in pairs:                                # açgözlü: en iyi örtüşen önce
            if ti in matched_t or di in used_d:
                continue
            matched_t.add(ti)
            used_d.add(di)
            matched_d[ti] = di

        # hareket desteği: tanımayla eşleşmeyen izler lekeyle sürer (leke birden çok ize paylaşılabilir: grup)
        mboxes = [np.asarray(b, np.float64) for b in (motion or [])]
        claim: dict[int, int] = {}                                # iz indeksi → leke indeksi
        for ti, t in enumerate(self.tracks):
            # Tanımadan doğmuş onaysız iz lekeyle sürmez: birleşik/yarım kutudan doğan hayali iz grubun lekesiyle
            # yaşayıp onaylanıyor ve sayılıyordu. Gerçek kişi birkaç karede tanımayla onaylanır.
            if ti in matched_d or not mboxes or (t.verified and not t.confirmed):
                continue
            # Yaşam sınırı: kapı, ekran yazısı, gölge gibi hareketlerle süresiz yaşayan hayalet iz başka kişilerin
            # geçişini sayıyordu. Doğrulanmış iz son tanımadan sonra, hiç tanınmamış iz doğumundan sonra sınırlı.
            if t.verified and self.frame - t.last_det > p.motion_life * p.max_age:
                continue
            if not t.verified and self.frame - t.born > p.unverified_life * p.max_age:
                continue
            gate = min(p.gate_max, p.motion_gate + self._grow(t))
            best: tuple[float, int] | None = None
            for mi, m in enumerate(mboxes):
                dc = _gate_dist(t.box, t.last, m)
                if (dc < gate or _center_in(t.box, m)) and (best is None or dc < best[0]):
                    best = (dc, mi)
            if best is not None:
                claim[ti] = best[1]
        # Lekeyi kaç kişi açıklıyor: onu talep eden izler + tanıma kutusunun merkezi lekede olan izler. Birden çoksa
        # (ya da leke tek kişiden büyükse) grup lekesidir: iz yalnızca tahmini merkezi lekeye yakınsa (`group_margin`)
        # teyit alır ve konumu lekeye kısıtlanır; uzaklaşan iz sürüklenmez (yoksa yanından ters yönde geçen grubun
        # lekesi, işi bitmiş bir izi sürükleyip çizgiyi ters geçirerek ikinci kez saydırıyordu). Yalnızca lekeyi tek
        # başına açıklayan iz lekenin merkezine taşınır (yoksa üst üste iki kişi tek noktaya çöker).
        owners = [0] * len(mboxes)
        for mi in claim.values():
            owners[mi] += 1
        for di in matched_d.values():
            for mi, m in enumerate(mboxes):
                if _center_in(boxes[di], m):
                    owners[mi] += 1
        matched_m: dict[int, np.ndarray] = {}                     # iz indeksi → gözlenen kutu (lekeden)
        for ti, mi in claim.items():
            t, m = self.tracks[ti], mboxes[mi]
            if owners[mi] > 1 or _area(m) > p.group_area * _area(t.last):
                pc = _center(t.box)
                hw, hh = p.group_margin * (t.last[2] - t.last[0]), p.group_margin * (t.last[3] - t.last[1])
                if m[0] - hw <= pc[0] <= m[2] + hw and m[1] - hh <= pc[1] <= m[3] + hh:
                    c = (min(max(pc[0], m[0]), m[2]), min(max(pc[1], m[1]), m[3]))
                    matched_m[ti] = _box_at(t.last, c)
            else:
                matched_m[ti] = _box_at(t.last, _center(m))

        entered: list[MotTrack] = []
        exited: list[MotTrack] = []
        for ti, t in enumerate(self.tracks):
            if ti in matched_d:
                di = matched_d[ti]
                t.score = scores[di]
                if scores[di] >= p.high and not t.verified:
                    t.verified = True
                    t.hist = []                                   # hız artık tanıma gözlemlerinden
                t.last_det = self.frame
                self._update(t, boxes[di], True, side_of, anchor_mode, entered, exited)
            elif ti in matched_m:
                self._update(t, matched_m[ti], False, side_of, anchor_mode, entered, exited)
            else:
                t.misses += 1
        used = set(matched_d.values())
        for di in high:
            if di not in used:
                self._new(boxes[di], scores[di], True, side_of, anchor_mode, entered, exited)
        for m in mboxes:                                          # hiçbir izin açıklamadığı leke: doğrulanmamış iz
            if not any(iou(t.box, m) > 0 or _center_in(m, t.box) for t in self.tracks):
                self._new(m, 0.0, False, side_of, anchor_mode, entered, exited)
        verified = [t for t in self.tracks if t.verified]
        self.tracks = [t for t in self.tracks
                       if t.misses <= (p.max_age if t.confirmed else p.tentative_age)
                       and _center_in(t.box, np.asarray(bounds))      # alandan çıktı: kimliği yeni gelene geçmesin
                       and (t.verified or not any(iou(t.box, v.box) >= p.dup_iou or _center_in(t.box, v.box)
                                                  for v in verified))]
        self.frame += 1
        return entered, exited

    def _grow(self, t: MotTrack) -> float:
        """Kayıptaki izin kapı büyümesi: kayıp kare × hız (kutu en/boyuna göre). Yürüyen kişinin konum belirsizliği
        zamanla artar, duranın artmaz: kapıda durup karanlığa giren kişinin izi aşağıda yeni beliren kişiye
        atlayıp ters geçiş saymıyor."""
        w = max(float(t.last[2] - t.last[0]), 1e-6)
        h = max(float(t.last[3] - t.last[1]), 1e-6)
        return self.p.gate_grow * t.misses * float(np.hypot(t.vel[0] / w, t.vel[1] / h))

    def _new(self, box: np.ndarray, score: float, verified: bool, side_of: object, anchor_mode: str,
             entered: list[MotTrack], exited: list[MotTrack]) -> None:
        t = MotTrack(self.next_id, box, np.zeros(4), box, score, verified=verified, born=self.frame,
                     last_det=self.frame)
        t.hist.append((self.frame, box))
        self.next_id += 1
        self.tracks.append(t)
        self._observe(t, side_of, anchor_mode, entered, exited)

    def _update(self, t: MotTrack, box: np.ndarray, from_det: bool, side_of: object, anchor_mode: str,
                entered: list[MotTrack], exited: list[MotTrack]) -> None:
        p = self.p
        if from_det or not t.verified:
            # Doğrulanmış izin hızı yalnızca tanıma gözlemlerinden: birleşik grup lekesinde konum lekeye kısıtlanır,
            # hızı bozmasın (kör bölgede arkadaki kişinin izi geride kalıp çıkışta eşleşmiyordu).
            t.hist = [h for h in t.hist if h[0] >= self.frame - p.vel_window]
            if t.hist:                                            # uzun tabanlı hız (merkezden: boy değişimi hız sayılmaz)
                f0, b0 = t.hist[0]
                c, c0 = _center(box), _center(b0)
                vx, vy = (c[0] - c0[0]) / (self.frame - f0), (c[1] - c0[1]) / (self.frame - f0)
                t.vel = np.array([vx, vy, vx, vy])
            t.hist.append((self.frame, box))
        t.box = box
        t.last = box
        t.hits += 1
        t.misses = 0
        self._observe(t, side_of, anchor_mode, entered, exited)

    def _observe(self, t: MotTrack, side_of: object, anchor_mode: str,
                 entered: list[MotTrack], exited: list[MotTrack]) -> None:
        ax, ay = anchor(t.box, anchor_mode)
        t.trail = [*t.trail[-29:], (ax, ay)]
        s = side_of(ax, ay)  # type: ignore[operator]
        band = max(self.p.band, self.p.band_rel * float(t.box[3] - t.box[1]))
        d = 1 if s > band else (-1 if s < -band else 0)
        if d != 0:
            if t.side == 0 or d == t.side:
                t.side = d
                t.cand, t.cand_n = 0, 0
            else:                                                # yan teyidi: art arda side_frames gözlem
                t.cand_n = t.cand_n + 1 if t.cand == d else 1
                t.cand = d
                if t.cand_n >= self.p.side_frames:
                    t.pending.append(d)                          # −1→+1 giriş (+1), +1→−1 çıkış (−1)
                    t.side = d
                    t.cand, t.cand_n = 0, 0
        if not t.confirmed and t.verified and t.hits >= self.p.min_hits:
            t.confirmed = True
        if t.confirmed and t.pending:
            for x in t.pending:
                if x > 0:
                    t.entries += 1
                    entered.append(t)
                else:
                    t.exits += 1
                    exited.append(t)
            t.pending = []
