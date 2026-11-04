/**
 * Antwortfeld mit Umschalter zwischen Tippen und Schreiben (Stift).
 *
 * Beim Schreiben wird das Bild an den Server geschickt und dort in Text
 * umgewandelt. Der erkannte Text erscheint direkt im Textfeld und kann vor dem
 * Absenden noch korrigiert werden. So bleibt die Bewertung nachvollziehbar.
 */

import { useRef, useState } from "react";
import { api, ApiError } from "../api";
import { Alert, Spinner } from "./ui";
import {
  HandwritingCanvas,
  type HandwritingCanvasHandle,
} from "./HandwritingCanvas";

export function AnswerField({
  value,
  onChange,
  examId,
  questionId,
  handwritingAvailable,
}: {
  value: string;
  onChange: (value: string) => void;
  examId: string;
  questionId: string;
  handwritingAvailable: boolean;
}) {
  const [mode, setMode] = useState<"tippen" | "schreiben">("tippen");
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const handleRef = useRef<HandwritingCanvasHandle | null>(null);

  const recognize = async () => {
    const handle = handleRef.current;
    if (!handle || handle.isEmpty()) {
      setError("Bitte zuerst schreiben.");
      return;
    }
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const browserText = await handle.browserText();
      const result = await api.transcribeHandwriting(
        examId,
        questionId,
        handle.toDataUrl(),
        browserText,
        false,
      );
      if (result.ok && result.text) {
        onChange(result.text);
        const how =
          result.method === "browser"
            ? "im Browser"
            : result.method === "gemini"
              ? "mit Bildanalyse"
              : "";
        setInfo(
          `Erkannt ${how}${result.unleserlich ? " – einzelne Stellen unklar" : ""}. ` +
            "Bitte prüfen und bei Bedarf korrigieren.",
        );
        setMode("tippen");
      } else {
        setError(result.error ?? "Handschrift konnte nicht erkannt werden.");
        if (result.hint) setInfo(result.hint);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg bg-ink-100 p-0.5">
          {(["tippen", "schreiben"] as const).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setMode(item)}
              className={`rounded-md px-3 py-1 text-xs font-medium ${
                mode === item ? "bg-white text-brand-700 shadow-card" : "text-ink-600"
              }`}
            >
              {item === "tippen" ? "Tippen" : "Mit Stift schreiben"}
            </button>
          ))}
        </div>
        {!handwritingAvailable && mode === "schreiben" && (
          <span className="text-[11px] text-amber-700">
            Handschrifterkennung nicht aktiv (Bildfreigabe in den Einstellungen).
          </span>
        )}
      </div>

      {mode === "tippen" ? (
        <textarea
          className="input min-h-[100px]"
          placeholder="Antwort …"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <div className="space-y-3">
          <HandwritingCanvas onReady={(handle) => (handleRef.current = handle)} />
          <button type="button" className="btn-primary" onClick={recognize} disabled={busy}>
            {busy ? "Wird erkannt …" : "Handschrift in Text umwandeln"}
          </button>
        </div>
      )}

      {busy && <Spinner label="Handschrift wird gelesen …" />}
      {info && <Alert tone="info">{info}</Alert>}
      {error && <Alert tone="warning" title="Handschrift">{error}</Alert>}
    </div>
  );
}
