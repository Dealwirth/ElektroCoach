/**
 * Symbol-Darstellung: zeichnet ein Bauteil als SVG-Gruppe.
 *
 * Die Zeichnung ist bewusst einfach und IEC-nah gehalten. Anschlusspunkte
 * werden immer aus der Symboldefinition abgeleitet, damit Zeichnung und
 * Netzmodell nicht auseinanderlaufen koennen.
 */

import type { Component, SymbolDef } from "../types";
import { componentPins } from "./useEditor";

const STROKE = "var(--canvas-ink)";

function Body({ symbol }: { symbol: SymbolDef }) {
  const { width: w, height: h } = symbol;
  const mid = h / 2;

  switch (symbol.type) {
    case "switch":
    case "pushbutton_no":
      return (
        <g>
          <line x1="0" y1={mid} x2="14" y2={mid} />
          <line x1="14" y1={mid} x2={w - 14} y2={mid - 16} />
          <line x1={w - 14} y1={mid} x2={w} y2={mid} />
          {symbol.type === "pushbutton_no" && (
            <g>
              <line x1={w / 2 - 10} y1={mid - 26} x2={w / 2 + 10} y2={mid - 26} />
              <line x1={w / 2} y1={mid - 26} x2={w / 2} y2={mid - 34} />
            </g>
          )}
          <circle cx="14" cy={mid} r="2.5" fill={STROKE} />
          <circle cx={w - 14} cy={mid} r="2.5" fill={STROKE} />
        </g>
      );
    case "pushbutton_nc":
      return (
        <g>
          <line x1="0" y1={mid} x2="14" y2={mid} />
          <line x1="14" y1={mid} x2={w - 14} y2={mid - 16} />
          <line x1={w - 14} y1={mid} x2={w} y2={mid} />
          <line x1={w - 16} y1={mid - 18} x2={w - 2} y2={mid - 26} />
        </g>
      );
    case "changeover":
      return (
        <g>
          <line x1="0" y1={mid} x2="20" y2={mid} />
          <line x1="20" y1={mid} x2={w - 16} y2="4" />
          <line x1={w - 16} y1="4" x2={w} y2="4" />
          <line x1={w - 16} y1={h - 4} x2={w} y2={h - 4} />
          <circle cx="20" cy={mid} r="2.5" fill={STROKE} />
        </g>
      );
    case "fuse":
      return (
        <g>
          <rect x="16" y={mid - 9} width={w - 32} height="18" rx="4" fill="var(--canvas-bg)" />
          <line x1="0" y1={mid} x2="16" y2={mid} />
          <line x1={w - 16} y1={mid} x2={w} y2={mid} />
        </g>
      );
    case "mcb":
      return (
        <g>
          <rect x="18" y={mid - 20} width={w - 36} height="40" rx="4" fill="var(--canvas-bg)" />
          <line x1="0" y1={mid} x2="18" y2={mid} />
          <line x1={w - 18} y1={mid} x2={w} y2={mid} />
          <line x1={w / 2} y1={mid - 12} x2={w / 2 + 8} y2={mid + 6} />
          <circle cx={w / 2} cy={mid - 14} r="3" fill={STROKE} />
        </g>
      );
    case "rcd":
      return (
        <g>
          <rect x="16" y="12" width={w - 32} height={h - 24} rx="5" fill="var(--canvas-bg)" />
          {[20, 40, 60, 80].map((y) => (
            <g key={y}>
              <line x1="0" y1={y} x2="16" y2={y} />
              <line x1={w - 16} y1={y} x2={w} y2={y} />
              <line x1="26" y1={y} x2="44" y2={y - 6} />
            </g>
          ))}
          <ellipse cx={w / 2} cy={h - 18} rx="14" ry="7" fill="none" />
        </g>
      );
    case "relay":
      return (
        <g>
          <rect x="16" y="8" width={w - 32} height={h - 16} rx="4" fill="var(--canvas-bg)" />
          <line x1="0" y1="20" x2="16" y2="20" />
          <line x1="0" y1="40" x2="16" y2="40" />
          <line x1={w - 16} y1="20" x2={w} y2="20" />
          <line x1={w - 16} y1="40" x2={w} y2="40" />
          <line x1="30" y1="20" x2="30" y2="40" />
        </g>
      );
    case "contactor":
      return (
        <g>
          <rect x="16" y="8" width={w - 32} height={h - 16} rx="4" fill="var(--canvas-bg)" />
          {[20, 60].map((y) => (
            <g key={y}>
              <line x1="0" y1={y} x2="16" y2={y} />
              <line x1={w - 16} y1={y} x2={w} y2={y} />
            </g>
          ))}
          {[10, 30, 50, 70].map((y) => (
            <line key={y} x1={w - 16} y1={y} x2={w} y2={y} />
          ))}
          <line x1="34" y1="20" x2="34" y2="60" />
          <line x1="28" y1="30" x2="40" y2="26" />
        </g>
      );
    case "motor":
      return (
        <g>
          <circle cx={w / 2} cy={h / 2} r={Math.min(w, h) / 2 - 4} fill="var(--canvas-bg)" />
          <text x={w / 2} y={h / 2 + 5} textAnchor="middle" fontSize="14" fill={STROKE}>
            M
          </text>
          {[20, 40, 60].map((y) => (
            <line key={y} x1="0" y1={y} x2={w / 2 - Math.min(w, h) / 2 + 4} y2={y} />
          ))}
        </g>
      );
    case "lamp":
      return (
        <g>
          <circle cx={w / 2} cy={h / 2} r={Math.min(w, h) / 2 - 6} fill="var(--canvas-bg)" />
          <line x1={w / 2 - 12} y1={h / 2 - 12} x2={w / 2 + 12} y2={h / 2 + 12} />
          <line x1={w / 2 - 12} y1={h / 2 + 12} x2={w / 2 + 12} y2={h / 2 - 12} />
          <line x1="0" y1={h / 2} x2={w / 2 - Math.min(w, h) / 2 + 6} y2={h / 2} />
          <line x1={w / 2 + Math.min(w, h) / 2 - 6} y1={h / 2} x2={w} y2={h / 2} />
        </g>
      );
    case "socket":
      return (
        <g>
          <path d={`M2 ${h - 2} A ${w / 2} ${h - 4} 0 0 1 ${w - 2} ${h - 2} Z`} fill="var(--canvas-bg)" />
          <line x1="0" y1="15" x2="12" y2="15" />
          <line x1="0" y1="30" x2="12" y2="30" />
          <line x1="0" y1="45" x2="12" y2="45" />
          <circle cx={w / 2} cy={h - 14} r="3" fill={STROKE} />
        </g>
      );
    case "terminal":
      return (
        <g>
          <circle cx={w / 2} cy={h / 2} r="7" fill="var(--canvas-bg)" />
          <line x1="0" y1={h / 2} x2={w / 2 - 7} y2={h / 2} />
          <line x1={w / 2 + 7} y1={h / 2} x2={w} y2={h / 2} />
        </g>
      );
    case "supply_l1":
    case "supply_n":
    case "supply_pe": {
      const label = symbol.type === "supply_l1" ? "L1" : symbol.type === "supply_n" ? "N" : "PE";
      const color = symbol.type === "supply_l1" ? "#dc2626"
        : symbol.type === "supply_n" ? "#2563eb" : "#16a34a";
      return (
        <g>
          <line x1="0" y1={h / 2} x2={w - 8} y2={h / 2} stroke={color} strokeWidth="3" />
          <circle cx={w - 6} cy={h / 2} r="5" fill={color} />
          <text x={w - 22} y={h / 2 - 8} textAnchor="middle" fontSize="12" fill={color}>
            {label}
          </text>
        </g>
      );
    }
    case "junction":
      return <circle cx={w / 2} cy={h / 2} r="6" fill={STROKE} />;
    case "heater":
      return (
        <g>
          <rect x="14" y={mid - 12} width={w - 28} height="24" rx="3" fill="var(--canvas-bg)" />
          <path
            d={`M20 ${mid - 8} L28 ${mid + 8} L36 ${mid - 8} L44 ${mid + 8} L52 ${mid - 8}`}
            fill="none"
          />
          <line x1="0" y1={mid} x2="14" y2={mid} />
          <line x1={w - 14} y1={mid} x2={w} y2={mid} />
        </g>
      );
    case "temperature_sensor":
      return (
        <g>
          <rect x="16" y={mid - 12} width={w - 32} height="24" rx="3" fill="var(--canvas-bg)" />
          <text x={w / 2} y={mid + 5} textAnchor="middle" fontSize="12" fill={STROKE}>
            T
          </text>
          <line x1="0" y1={mid} x2="16" y2={mid} />
          <line x1={w - 16} y1={mid} x2={w} y2={mid} />
        </g>
      );
    case "text":
      return null;
    default:
      return <rect x="0" y="0" width={w} height={h} rx="4" fill="var(--canvas-bg)" />;
  }
}

export function SymbolShape({
  component,
  symbol,
  selected,
  showPins = true,
  interactive = false,
}: {
  component: Component;
  symbol: SymbolDef;
  selected?: boolean;
  showPins?: boolean;
  interactive?: boolean;
}) {
  const pins = componentPins(component, { [symbol.type]: symbol });
  const isText = symbol.type === "text";

  return (
    <g
      transform={`translate(${component.x} ${component.y})`}
      style={{ cursor: interactive ? "move" : "default" }}
    >
      <g
        transform={`rotate(${component.rotation} ${symbol.width / 2} ${symbol.height / 2})`}
        stroke={STROKE}
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {selected && (
          <rect
            x="-6"
            y="-6"
            width={symbol.width + 12}
            height={symbol.height + 12}
            rx="6"
            fill="rgba(27,111,245,0.08)"
            stroke="#1b6ff5"
            strokeWidth="1.5"
            strokeDasharray="5 4"
          />
        )}
        <Body symbol={symbol} />
      </g>

      {isText ? (
        <text x="4" y="18" fontSize="14" fill={STROKE} fontFamily="Helvetica, Arial, sans-serif">
          {component.label}
        </text>
      ) : (
        component.label && (
          <text
            x={symbol.width / 2}
            y={symbol.height + 15}
            textAnchor="middle"
            fontSize="12"
            fill="var(--canvas-label)"
            fontFamily="Helvetica, Arial, sans-serif"
          >
            {component.label}
          </text>
        )
      )}

      {showPins &&
        pins.map((pin) => (
          <g key={pin.id}>
            <circle
              cx={pin.x - component.x}
              cy={pin.y - component.y}
              r="4.5"
              fill="var(--canvas-bg)"
              stroke={STROKE}
              strokeWidth="1.6"
            />
            <circle
              cx={pin.x - component.x}
              cy={pin.y - component.y}
              r="9"
              fill="transparent"
              data-pin="1"
              data-component={component.id}
              data-pin-id={pin.id}
              className="cursor-crosshair"
            />
          </g>
        ))}
    </g>
  );
}
