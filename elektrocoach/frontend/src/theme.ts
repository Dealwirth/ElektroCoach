/**
 * Themensteuerung: die Oberfläche folgt der Hell-/Dunkel-Einstellung von
 * Home Assistant.
 *
 * Hinter dem Ingress läuft die Oberfläche in einem iframe von Home Assistant.
 * Dieser iframe ist same-origin, deshalb darf das Dokument des Elterndokuments
 * gelesen werden. Daraus wird die Einstellung ermittelt. Reihenfolge:
 *
 *   1. ausdrückliche Auswahl des Nutzers (automatisch / hell / dunkel)
 *   2. Home-Assistant-Oberfläche (Themenobjekt, color-scheme, Hintergrundfarbe)
 *   3. Betriebssystem-Einstellung (prefers-color-scheme)
 *
 * Bei direktem Aufruf (Docker, Tests) gibt es kein Elterndokument; dann gilt
 * die Betriebssystem-Einstellung. Ist nichts davon verfügbar, bleibt es hell.
 */

import { useEffect, useState } from "react";

export type ThemeMode = "auto" | "light" | "dark";

const STORAGE_KEY = "elektrocoach.theme";
const DARK_CLASS = "dark";
// Farbe der Browserleiste, passend zur jeweiligen Betriebsart.
const THEME_COLOR_LIGHT = "#f7f8fa";
const THEME_COLOR_DARK = "#0f141c";

interface Rgb {
  r: number;
  g: number;
  b: number;
}

export function getThemeMode(): ThemeMode {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "auto") return stored;
  } catch {
    /* localStorage kann in manchen Browsern gesperrt sein */
  }
  return "auto";
}

export function setThemeMode(mode: ThemeMode): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    /* nicht kritisch: dann gilt die Auswahl nur für diese Sitzung */
  }
  applyTheme(mode);
}

function parseColor(value: string | null | undefined): Rgb | null {
  if (!value) return null;
  const text = value.trim().toLowerCase();
  const hex = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/);
  if (hex) {
    let body = hex[1];
    if (body.length === 3) {
      body = body
        .split("")
        .map((char) => char + char)
        .join("");
    }
    return {
      r: parseInt(body.slice(0, 2), 16),
      g: parseInt(body.slice(2, 4), 16),
      b: parseInt(body.slice(4, 6), 16),
    };
  }
  const rgb = text.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/);
  if (rgb) {
    return { r: Number(rgb[1]), g: Number(rgb[2]), b: Number(rgb[3]) };
  }
  return null;
}

/** Wahrgenommene Helligkeit (0 = schwarz, 1 = weiß). */
function luminance({ r, g, b }: Rgb): number {
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

/** Dokument des Elterndokuments, wenn es gelesen werden darf. */
function parentDocument(): Document | null {
  try {
    if (typeof window === "undefined") return null;
    const parent = window.parent;
    if (!parent || parent === window) return null;
    // Zugriff wirft bei fremder Herkunft. Das wird bewusst abgefangen.
    return parent.document ?? null;
  } catch {
    return null;
  }
}

/** Liest die Dunkel-Einstellung aus der Home-Assistant-Oberfläche. */
export function haDark(): boolean | null {
  const doc = parentDocument();
  if (!doc) return null;
  try {
    const host = doc.querySelector("home-assistant") as
      | (HTMLElement & { hass?: { themes?: { darkMode?: boolean } } })
      | null;
    const flag = host?.hass?.themes?.darkMode;
    if (typeof flag === "boolean") return flag;

    const meta = doc.querySelector('meta[name="color-scheme"]');
    const scheme = meta?.getAttribute("content");
    if (scheme === "dark") return true;
    if (scheme === "light") return false;

    const root = doc.documentElement;
    const inline = root.style.getPropertyValue("--primary-background-color");
    const computed = window.getComputedStyle(root).getPropertyValue("--primary-background-color");
    const parsed = parseColor(inline || computed);
    if (parsed) return luminance(parsed) < 0.5;

    const bodyBg = parseColor(window.getComputedStyle(doc.body).backgroundColor);
    if (bodyBg) return luminance(bodyBg) < 0.5;
  } catch {
    /* Elterndokument nicht lesbar: dann greift die Betriebssystem-Einstellung */
  }
  return null;
}

function prefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches === true;
  } catch {
    return false;
  }
}

export function resolveDark(mode: ThemeMode = getThemeMode()): boolean {
  if (mode === "dark") return true;
  if (mode === "light") return false;
  const fromHa = haDark();
  if (fromHa !== null) return fromHa;
  return prefersDark();
}

/** Setzt die Klasse `dark` am Wurzelelement. Gibt die Betriebsart zurück. */
export function applyTheme(mode: ThemeMode = getThemeMode()): boolean {
  if (typeof document === "undefined") return false;
  const dark = resolveDark(mode);
  const root = document.documentElement;
  root.classList.toggle(DARK_CLASS, dark);
  root.style.colorScheme = dark ? "dark" : "light";
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", dark ? THEME_COLOR_DARK : THEME_COLOR_LIGHT);
  return dark;
}

/**
 * Beobachtet die Themenquelle und meldet jede Änderung.
 *
 * Home Assistant ändert die Einstellung ohne Neuladen. Deshalb werden das
 * Elterndokument (Änderungen an Klasse und Inline-Stil), die
 * Betriebssystem-Einstellung und zusätzlich ein langsamer Abruf beobachtet.
 * Der Abruf deckt Fälle ab, in denen Home Assistant nur eine CSS-Variable
 * ändert, ohne ein beobachtbares Attribut zu setzen.
 */
export function watchTheme(onChange: (dark: boolean) => void): () => void {
  let last = applyTheme();
  onChange(last);

  const evaluate = () => {
    const dark = applyTheme();
    if (dark !== last) {
      last = dark;
      onChange(dark);
    }
  };

  const mql = (() => {
    try {
      return window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      return null;
    }
  })();
  mql?.addEventListener("change", evaluate);

  const doc = parentDocument();
  const observer = doc ? new MutationObserver(evaluate) : null;
  if (doc && observer) {
    observer.observe(doc.documentElement, { attributes: true, attributeFilter: ["style", "class"] });
    if (doc.body) {
      observer.observe(doc.body, { attributes: true, attributeFilter: ["style", "class"] });
    }
  }

  const timer = window.setInterval(evaluate, 2000);

  return () => {
    mql?.removeEventListener("change", evaluate);
    observer?.disconnect();
    window.clearInterval(timer);
  };
}

/** Reagiert auf Themenwechsel und gibt die aktuelle Betriebsart zurück. */
export function useIsDark(): boolean {
  const [dark, setDark] = useState<boolean>(() => resolveDark());
  useEffect(() => watchTheme(setDark), []);
  return dark;
}
