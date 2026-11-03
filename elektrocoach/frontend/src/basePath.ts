/**
 * Basispfad-Berechnung fuer Home-Assistant-Ingress.
 *
 * Home Assistant liefert die Oberflaeche unter einem wechselnden Pfad aus,
 * zum Beispiel /api/hassio_ingress/Xs3V.../. Dieser Pfad ist pro Installation
 * und pro Neustart anders. Er laesst sich nicht fest verdrahten.
 *
 * Der Pfad wird deshalb zur Laufzeit aus der aktuellen Adresse gelesen:
 *   * /api/hassio_ingress/<token>/...  -> /api/hassio_ingress/<token>
 *   * direkt aufgerufen (Docker, Tests) -> ""
 *
 * Sowohl der Router (basename) als auch der API-Client nutzen diesen Wert,
 * damit Links und Aufrufe auch auf verschachtelten Seiten stimmen.
 */

const INGRESS_PATTERN = /^(.*?\/hassio_ingress\/[^/]+)/;

function detectBasePath(): string {
  if (typeof window === "undefined") return "";
  const match = window.location.pathname.match(INGRESS_PATTERN);
  if (match) return match[1];
  return "";
}

export const basePath = detectBasePath();

/** Absoluter API-Pfad inklusive Ingress-Praefix. */
export const apiBase = `${basePath}/api`;

/** Pfad fuer ausgelieferte Dateien (Seitenbilder, Exporte). */
export function assetPath(path: string): string {
  return `${apiBase}/${path.replace(/^\//, "")}`;
}
