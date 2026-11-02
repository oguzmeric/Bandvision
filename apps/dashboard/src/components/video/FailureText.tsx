"use client";

import ConnectionProblem from "@/components/watch/ConnectionProblem";
import type { Failure } from "@/lib/failure";

/** `Failure` metni: panelin oturumu dolduysa diğer sayfalardaki gibi `AUTH_TEXT` + "Giriş yap" bağlantısı, değilse düz metin */
export default function FailureText({ failure }: { failure: Failure }) {
  return typeof failure === "string" ? <>{failure}</> : <ConnectionProblem problem="auth" />;
}
