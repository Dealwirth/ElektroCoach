import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { basePath } from "./basePath";
import { applyTheme } from "./theme";
import "./index.css";

// Themeneinstellung von Home Assistant sofort übernehmen, noch vor dem ersten
// Zeichnen. Das verhindert ein kurzes Aufblitzen der hellen Betriebsart.
applyTheme();

// basename kommt aus basePath: hinter dem Ingress ist das der wechselnde
// Ingress-Pfad, bei direktem Aufruf leer. So stimmen Deep-Links und
// Aktualisieren (F5) in beiden Faellen.
createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <BrowserRouter basename={basePath || undefined}>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
