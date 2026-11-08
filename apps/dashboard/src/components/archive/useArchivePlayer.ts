"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/live";
import {
  createPlayer, deletePlayer, getPlayer, playerAction, type ArchiveCamera, type PlayerAction, type PlayerView,
} from "@/lib/archive";
import { POLL_MS } from "@/lib/archiveTime.mjs";

/** Yoklama 404 aldı: oynatıcı sunucuda yok (analiz sunucusu yeniden başladı ya da boşta kaldığı için kapandı) */
export const VANISHED_NOTICE = "Oynatıcı kapanmış (analiz sunucusu yeniden başlamış olabilir); sonraki işlemde yeniden açılır.";
/** Kaybolan oynatıcı bir işlemde yeniden açıldı */
export const REOPENED_NOTICE = "Oynatıcı yeniden açıldı.";
/** Ardışık iki yoklama 404 dışı bir hatayla düştü (analiz sunucusu ya da vekil yanıt vermiyor) */
export const OFFLINE_NOTICE = "Analiz sunucusuna ulaşılamıyor; yeniden deneniyor…";
const OFFLINE_AFTER = 2;

const ACTIVE = new Set(["connecting", "playing"]);
export const isActive = (v: PlayerView | null) => !!v && ACTIVE.has(v.state);

const message = (e: unknown) => (e instanceof Error ? e.message : "İstek başarısız.");
const missing = (e: unknown) => e instanceof ApiError && e.status === 404;

export interface ArchivePlayerApi {
  view: PlayerView | null;
  /** Son geçiş bir sarma ya da hız değişimi: `connecting` "Sarılıyor…" diye yazılır */
  seeking: boolean;
  /** İsteğin reddi (ör. 429 "En çok 2 kayıt aynı anda izlenebilir.") */
  error: string | null;
  notice: string | null;
  /** Oynatıcı açılıyor (POST yanıtı bekleniyor) */
  opening: boolean;
  /** Akış `<img>`'inin anahtarı: yalnız oynatıcı değişince ya da hatadan sonra sürdürülünce artar */
  streamKey: number;
  /** Seçili hız (oynatıcı yokken yeni oynatıcının hızı) */
  speed: number;
  toggle: (cam: ArchiveCamera, at: number) => void;
  seek: (cam: ArchiveCamera, at: number) => void;
  setSpeed: (cam: ArchiveCamera, speed: number, at: number) => void;
  close: () => void;
}

/**
 * Tek kayıt oynatıcısının yaşam döngüsü: ilk oynatmada `POST players`, 1 sn'de bir durum yoklaması, kumandalar
 * (`actions`), kamera/gün değişince, sayfadan çıkışta (`pagehide`, bileşen kalkınca) `DELETE` (keepalive). Yanıtlar
 * gönderiliş sırasıyla uygulanır: bir işlemden önce gönderilmiş yoklamanın eski yanıtı yeni durumu ezmez. Sunucuda kaybolan
 * oynatıcı (404) sonraki işlemde aynı konumdan yeniden açılır.
 */
export function useArchivePlayer(): ArchivePlayerApi {
  const [view, setView] = useState<PlayerView | null>(null);
  const [seeking, setSeeking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [streamKey, setStreamKey] = useState(0);
  const [speed, setSpeedState] = useState(1);
  const [offline, setOffline] = useState(false);

  const idRef = useRef<string | null>(null);
  const viewRef = useRef<PlayerView | null>(null);
  const speedRef = useRef(1);
  /** Kamera/gün değişince artar: eski isteklerin yanıtları atılır */
  const epochRef = useRef(0);
  /** İstek sırası ve uygulanan son istek */
  const seqRef = useRef(0);
  const appliedRef = useRef(0);
  const openingRef = useRef<object | null>(null);
  /** Açılış uçuştayken istenen son konum: POST bitince oraya sarılır */
  const pendingRef = useRef<number | null>(null);
  /** Ardışık başarısız (404 dışı) yoklama sayısı */
  const failsRef = useRef(0);
  const show = useCallback((v: PlayerView | null) => {
    viewRef.current = v;
    idRef.current = v?.id ?? null;
    setView(v);
    if (v) {
      speedRef.current = v.speed;
      setSpeedState(v.speed);
      if (v.state !== "connecting") setSeeking(false);
    }
  }, []);

  const open = useCallback((cam: ArchiveCamera, at: number, reopened: boolean) => {
    if (openingRef.current) return;
    const token = {};
    openingRef.current = token;
    const epoch = epochRef.current;
    const seq = ++seqRef.current;
    setOpening(true);
    setError(null);
    setSeeking(false);
    createPlayer(cam, at, speedRef.current)
      .then((v) => {
        if (epoch !== epochRef.current) { deletePlayer(v.id); return; }   // bu arada kamera/gün değişti
        appliedRef.current = seq;
        show(v);
        setStreamKey((k) => k + 1);
        setNotice(reopened ? REOPENED_NOTICE : null);
      })
      .catch((e: unknown) => { if (epoch === epochRef.current) { pendingRef.current = null; setError(message(e)); } })
      .finally(() => {
        if (openingRef.current !== token) return;
        openingRef.current = null;
        setOpening(false);
        // açılış sürerken başka ana tıklandıysa (çizelge, kısayol) şimdi oraya sarılır
        const next = pendingRef.current;
        pendingRef.current = null;
        if (next !== null && epoch === epochRef.current && idRef.current && next !== at) seekRef.current(cam, next);
      });
  }, [show]);

  /** Kumanda; oynatıcı sunucuda yoksa (404) duraklatma dışındaki işler `at`tan yeni oynatıcıyla sürer */
  const act = useCallback((cam: ArchiveCamera, body: PlayerAction, at: number) => {
    const id = idRef.current;
    if (!id) { if (body.action !== "pause") open(cam, at, false); return; }
    const epoch = epochRef.current;
    const seq = ++seqRef.current;
    appliedRef.current = seq;                       // daha önce gönderilmiş yoklamaların yanıtı artık uygulanmaz
    const wasError = viewRef.current?.state === "error";
    setSeeking(body.action === "seek" || body.action === "speed");
    if (body.action === "seek") {
      const cur = viewRef.current;
      if (cur) show({ ...cur, state: "connecting", at: body.at, message: "" });
    }
    playerAction(id, body)
      .then((v) => {
        if (epoch !== epochRef.current || idRef.current !== id || seq < appliedRef.current) return;
        setError(null);
        show(v);
        if (wasError && v.state !== "error") setStreamKey((k) => k + 1);   // hatadan sonra akış baştan açılır
      })
      .catch((e: unknown) => {
        if (epoch !== epochRef.current || idRef.current !== id) return;
        if (missing(e)) {
          show(null);
          if (body.action === "pause") setNotice(VANISHED_NOTICE);
          else open(cam, at, true);
          return;
        }
        setError(message(e));
      });
  }, [open, show]);

  const toggle = useCallback((cam: ArchiveCamera, at: number) => {
    const v = viewRef.current;
    if (!v) open(cam, at, notice === VANISHED_NOTICE);
    else act(cam, isActive(v) ? { action: "pause" } : { action: "resume" }, at);
  }, [act, open, notice]);

  const seek = useCallback((cam: ArchiveCamera, at: number) => {
    if (openingRef.current) pendingRef.current = at;          // açılış bitince bu konuma sarılır
    else if (!idRef.current) open(cam, at, notice === VANISHED_NOTICE);
    else act(cam, { action: "seek", at }, at);
  }, [act, open, notice]);
  const seekRef = useRef(seek);
  seekRef.current = seek;

  const setSpeed = useCallback((cam: ArchiveCamera, s: number, at: number) => {
    speedRef.current = s;
    setSpeedState(s);
    if (idRef.current) act(cam, { action: "speed", speed: s }, at);
  }, [act]);

  const close = useCallback(() => {
    epochRef.current += 1;
    openingRef.current = null;
    pendingRef.current = null;
    failsRef.current = 0;
    if (idRef.current) deletePlayer(idRef.current);
    show(null);
    setOpening(false);
    setError(null);
    setNotice(null);
    setOffline(false);
    setSeeking(false);
  }, [show]);

  // Durum yoklaması (1 sn): oynatıcı varken. 404 → oynatıcı kayboldu; başka hata iki kez üst üste → "ulaşılamıyor" notu
  // (ilk başarılı yoklamada kalkar; başarılı yoklama son işlemin hatasını da siler)
  const id = view?.id ?? null;
  useEffect(() => {
    failsRef.current = 0;
    setOffline(false);
    if (!id) return;
    let busy = false;
    const timer = setInterval(() => {
      if (busy) return;
      busy = true;
      const epoch = epochRef.current;
      const seq = ++seqRef.current;
      getPlayer(id)
        .then((v) => {
          if (epoch !== epochRef.current || idRef.current !== id) return;
          failsRef.current = 0;
          setOffline(false);
          setError(null);
          if (seq < appliedRef.current) return;
          appliedRef.current = seq;
          show(v);
        })
        .catch((e: unknown) => {
          if (epoch !== epochRef.current || idRef.current !== id) return;
          if (!missing(e)) {
            failsRef.current += 1;
            if (failsRef.current >= OFFLINE_AFTER) setOffline(true);
            return;
          }
          show(null);
          setNotice(VANISHED_NOTICE);
        })
        .finally(() => { busy = false; });
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [id, show]);

  // Sayfadan çıkış: sekme kapanır/başka siteye gidilir (`pagehide`) ya da panelde başka sayfaya geçilir (bileşen kalkar).
  // Hook tamamen sıfırlanır: uçuştaki açılış geçersiz (yanıtı gelince oynatıcı silinir), açılış kilidi ve bekleyen konum
  // temizlenir. Böylece React StrictMode'un (`next dev`) bağla → kaldır → yeniden bağla sınamasında ikinci bağlamada yeni
  // oynatıcı açılabilir (ArchiveView derin bağlantıyı aynı nedenle yeniden koşar). Sayfa geri/ileri önbelleğinden dönerse
  // oynatıcı durmuş görünür; Oynat yenisini açar.
  useEffect(() => {
    const leave = () => {
      epochRef.current += 1;
      openingRef.current = null;
      pendingRef.current = null;
      if (idRef.current) deletePlayer(idRef.current);
      show(null);
      setOpening(false);
    };
    window.addEventListener("pagehide", leave);
    return () => {
      window.removeEventListener("pagehide", leave);
      leave();
    };
  }, [show]);

  return { view, seeking, error, notice: offline ? OFFLINE_NOTICE : notice, opening, streamKey, speed, toggle, seek, setSpeed, close };
}
