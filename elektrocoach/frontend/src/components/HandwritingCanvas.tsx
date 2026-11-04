/**
 * Schreibfeld fuer Stift, Finger und Maus.
 *
 * Der Lernende beantwortet Aufgaben handschriftlich. Das Bild wird an den
 * Server geschickt und dort in Text umgewandelt. Wenn der Browser die
 * Handschrift-Erkennung beherrscht (Handwriting Recognition API), wird der
 * Text direkt mitgesendet. Das spart eine Cloud-Anfrage und funktioniert
 * offline.
 *
 * Wichtig fuer die Bedienung:
 *   * Pointer-Ereignisse decken Maus, Stift und Finger gemeinsam ab.
 *   * touch-action: none verhindert, dass der Browser beim Schreiben scrollt.
 *   * Feste Zeichenflaeche mit hoher Aufloesung, damit die Linien scharf sind.
 */

import { useEffect, useRef, useState } from "react";

interface Stroke {
  points: Array<{ x: number; y: number }>;
}

export interface HandwritingCanvasHandle {
  toDataUrl: () => string;
  browserText: () => Promise<string>;
  clear: () => void;
  isEmpty: () => boolean;
}

const WIDTH = 1000;
const HEIGHT = 620;
const LINE_WIDTH = 3;

// Die Handschrift-Erkennung des Browsers ist noch nicht ueberall vorhanden.
interface HandwritingRecognizer {
  recognize: (input: unknown) => Promise<Array<{ text: string }>>;
  addPointer?: (event: PointerEvent) => void;
  start?: () => void;
}

interface HandwritingApi {
  createHandwritingRecognizer?: (options?: Record<string, unknown>) => Promise<HandwritingRecognizer>;
}

export function HandwritingCanvas({
  onReady,
  disabled = false,
}: {
  onReady?: (handle: HandwritingCanvasHandle) => void;
  disabled?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const strokesRef = useRef<Stroke[]>([]);
  const currentRef = useRef<Stroke | null>(null);
  const [empty, setEmpty] = useState(true);
  const [penWidth, setPenWidth] = useState(LINE_WIDTH);
  const [tool, setTool] = useState<"pen" | "eraser">("pen");

  const redraw = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const stroke of strokesRef.current) {
      ctx.strokeStyle = "#111827";
      ctx.lineWidth = penWidth;
      ctx.beginPath();
      stroke.points.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.stroke();
    }
    if (currentRef.current) {
      ctx.strokeStyle = "#111827";
      ctx.lineWidth = penWidth;
      ctx.beginPath();
      currentRef.current.points.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.stroke();
    }
  };

  useEffect(() => {
    redraw();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [penWidth]);

  useEffect(() => {
    onReady?.({
      toDataUrl: () => canvasRef.current?.toDataURL("image/png") ?? "",
      clear: () => {
        strokesRef.current = [];
        currentRef.current = null;
        setEmpty(true);
        redraw();
      },
      isEmpty: () => strokesRef.current.length === 0,
      browserText: async () => {
        const api = (window as unknown as { Handwriting?: HandwritingApi }).Handwriting;
        if (!api?.createHandwritingRecognizer || !canvasRef.current) return "";
        try {
          const recognizer = await api.createHandwritingRecognizer({ languages: ["de"] });
          recognizer.start?.();
          for (const stroke of strokesRef.current) {
            for (const point of stroke.points) {
              const event = new PointerEvent("pointermove", {
                clientX: point.x,
                clientY: point.y,
                bubbles: true,
              });
              recognizer.addPointer?.(event);
            }
          }
          const results = await recognizer.recognize(undefined);
          return results.map((r) => r.text).join(" ").trim();
        } catch {
          return "";
        }
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const position = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * canvas.width,
      y: ((event.clientY - rect.top) / rect.height) * canvas.height,
    };
  };

  const start = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (disabled) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    if (tool === "eraser") {
      eraseAt(position(event));
      return;
    }
    currentRef.current = { points: [position(event)] };
    setEmpty(false);
  };

  const move = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (disabled) return;
    if (tool === "eraser") {
      if (event.buttons) eraseAt(position(event));
      return;
    }
    if (!currentRef.current) return;
    currentRef.current.points.push(position(event));
    redraw();
  };

  const end = () => {
    if (currentRef.current && currentRef.current.points.length > 1) {
      strokesRef.current.push(currentRef.current);
    }
    currentRef.current = null;
    redraw();
  };

  const eraseAt = (point: { x: number; y: number }) => {
    const radius = 18;
    strokesRef.current = strokesRef.current.filter(
      (stroke) =>
        !stroke.points.some(
          (p) => Math.hypot(p.x - point.x, p.y - point.y) < radius,
        ),
    );
    setEmpty(strokesRef.current.length === 0);
    redraw();
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg bg-ink-100 p-0.5">
          {(["pen", "eraser"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setTool(value)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                tool === value ? "bg-white text-brand-700 shadow-card" : "text-ink-600"
              }`}
            >
              {value === "pen" ? "Stift" : "Radierer"}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5 text-xs text-ink-500">
          <span>Stärke</span>
          <input
            type="range"
            min={1}
            max={8}
            value={penWidth}
            onChange={(event) => setPenWidth(Number(event.target.value))}
            className="h-1.5 w-24 accent-brand-600"
            aria-label="Stiftstärke"
          />
        </div>
        <button
          type="button"
          className="btn-ghost btn-sm"
          onClick={() => {
            strokesRef.current = [];
            currentRef.current = null;
            setEmpty(true);
            redraw();
          }}
        >
          Alles löschen
        </button>
        {empty && <span className="text-xs text-ink-400">Mit Stift, Finger oder Maus schreiben.</span>}
      </div>

      <canvas
        ref={canvasRef}
        width={WIDTH}
        height={HEIGHT}
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={end}
        onPointerLeave={end}
        onPointerCancel={end}
        className={`w-full touch-none rounded-xl border-2 border-dashed border-ink-200 bg-white ${
          disabled ? "opacity-50" : "cursor-crosshair"
        }`}
        style={{ aspectRatio: `${WIDTH} / ${HEIGHT}` }}
      />
    </div>
  );
}
