/** Einstellungen: KI, Home Assistant, Lernen, Import und Sicherheit. */

import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import {
  Alert,
  Card,
  PageHeader,
  SectionTitle,
  Spinner,
  Tabs,
  useAsync,
} from "../components/ui";
import { getThemeMode, setThemeMode, type ThemeMode } from "../theme";

type TabId = "ki" | "homeassistant" | "darstellung" | "lernen" | "import" | "sicherheit";

export default function SettingsPage() {
  const [tab, setTab] = useState<TabId>("ki");
  const settings = useAsync(() => api.settings(), []);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [message, setMessage] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (settings.data) setValues(settings.data);
  }, [settings.data]);

  const set = (key: string, value: unknown) => setValues((current) => ({ ...current, [key]: value }));

  const save = async (keys: string[]) => {
    setBusy(true);
    setMessage(null);
    try {
      const payload: Record<string, unknown> = {};
      keys.forEach((key) => {
        payload[key] = values[key];
      });
      const result = await api.updateSettings(payload);
      setMessage({
        tone: "success",
        text: result.changed.length
          ? `${result.changed.length} Einstellung(en) gespeichert.`
          : "Keine Änderungen erkannt.",
      });
      settings.reload();
    } catch (error) {
      setMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  };

  if (settings.loading) return <Spinner label="Einstellungen werden geladen …" />;
  if (settings.error) return <Alert tone="danger">{settings.error}</Alert>;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Einstellungen"
        subtitle="KI-Dienste, Home-Assistant-Anbindung, Lernziele und Sicherheit."
      />

      {message && (
        <Alert tone={message.tone} onClose={() => setMessage(null)}>
          {message.text}
        </Alert>
      )}

      <Tabs<TabId>
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "ki", label: "KI-Dienste" },
          { id: "homeassistant", label: "Home Assistant" },
          { id: "darstellung", label: "Darstellung" },
          { id: "lernen", label: "Lernen" },
          { id: "import", label: "Import & OCR" },
          { id: "sicherheit", label: "Sicherheit" },
        ]}
      />

      {tab === "ki" && (
        <KiSettings values={values} set={set} save={save} busy={busy} />
      )}
      {tab === "homeassistant" && (
        <HaSettings values={values} set={set} save={save} busy={busy} />
      )}
      {tab === "darstellung" && <AppearanceSettings />}
      {tab === "lernen" && <LearnSettings values={values} set={set} save={save} busy={busy} />}
      {tab === "import" && <ImportSettings values={values} set={set} save={save} busy={busy} />}
      {tab === "sicherheit" && <SecuritySettings values={values} set={set} save={save} busy={busy} />}
    </div>
  );
}

interface TabProps {
  values: Record<string, unknown>;
  set: (key: string, value: unknown) => void;
  save: (keys: string[]) => void;
  busy: boolean;
}

/**
 * Darstellung: Hell/Dunkel.
 *
 * Standard ist "automatisch": die Oberfläche folgt der Einstellung von Home
 * Assistant. Wer Home Assistant im hellen Design nutzt, aber diese Oberfläche
 * dunkel möchte, kann hier ausdrücklich umschalten.
 */
function AppearanceSettings() {
  const [mode, setMode] = useState<ThemeMode>(() => getThemeMode());

  const choose = (value: ThemeMode) => {
    setMode(value);
    setThemeMode(value);
  };

  const options: Array<{ id: ThemeMode; label: string; hint: string }> = [
    { id: "auto", label: "Automatisch", hint: "Übernimmt die Einstellung von Home Assistant." },
    { id: "light", label: "Immer hell", hint: "Unabhängig von Home Assistant." },
    { id: "dark", label: "Immer dunkel", hint: "Unabhängig von Home Assistant." },
  ];

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <SectionTitle
          title="Farbdarstellung"
          subtitle="Die Oberfläche kann dem hellen oder dunklen Design von Home Assistant folgen."
        />
        <div className="space-y-2">
          {options.map((option) => (
            <label
              key={option.id}
              className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-colors ${
                mode === option.id
                  ? "border-brand-500 bg-brand-50"
                  : "border-ink-200 hover:bg-ink-50"
              }`}
            >
              <input
                type="radio"
                name="theme-mode"
                className="mt-0.5 h-4 w-4"
                checked={mode === option.id}
                onChange={() => choose(option.id)}
              />
              <span>
                <span className="block text-sm font-medium text-ink-900">{option.label}</span>
                <span className="mt-0.5 block text-xs text-ink-500">{option.hint}</span>
              </span>
            </label>
          ))}
        </div>
        <p className="mt-4 text-xs text-ink-500">
          Die Einstellung gilt für dieses Gerät und diesen Browser. Beim Umschalten in Home
          Assistant ändert sich die Darstellung hier automatisch mit.
        </p>
      </Card>

      <Card>
        <SectionTitle title="Vorschau" subtitle="So sehen die Bausteine in der aktuellen Betriebsart aus." />
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <span className="badge-brand">Thema</span>
            <span className="badge-success">Richtig</span>
            <span className="badge-warning">Zu prüfen</span>
            <span className="badge-danger">Fehler</span>
            <span className="badge-neutral">Neutral</span>
          </div>
          <div className="rounded-xl border border-ink-200 bg-white p-3.5">
            <p className="text-sm font-semibold text-ink-900">Karte mit Text</p>
            <p className="mt-1 text-sm text-ink-500">
              Fließtext in der Nebenschriftfarbe, gut lesbar in beiden Betriebsarten.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary btn-sm">
              Hauptaktion
            </button>
            <button type="button" className="btn-secondary btn-sm">
              Nebenaktion
            </button>
            <button type="button" className="btn-ghost btn-sm">
              Leise
            </button>
          </div>
          <Alert tone="info" title="Hinweis">
            Meldungen passen sich ebenfalls automatisch an.
          </Alert>
        </div>
      </Card>
    </div>
  );
}

function Text({ id, label, value, onChange, hint, type = "text" }: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  type?: string;
}) {
  return (
    <div>
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type={type}
        className="input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

function NumberField({ id, label, value, onChange, hint, min, max }: {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
  hint?: string;
  min?: number;
  max?: number;
}) {
  return (
    <div>
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type="number"
        className="input"
        value={value}
        min={min}
        max={max}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

function Toggle({ id, label, checked, onChange, hint }: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  hint?: string;
}) {
  return (
    <div>
      <label className="flex items-center gap-2.5 text-sm font-medium text-ink-800" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          className="h-4 w-4 rounded border-ink-300"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
        />
        {label}
      </label>
      {hint && <p className="mt-1 pl-7 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

function KiSettings({ values, set, save, busy }: TabProps) {
  const [status, setStatus] = useState<import("../types").AiStatus | null>(null);
  const [models, setModels] = useState<Record<string, unknown> | null>(null);
  const [addon, setAddon] = useState<import("../types").OllamaAddonStatus | null>(null);
  const [addonBusy, setAddonBusy] = useState(false);
  const [pullModel, setPullModel] = useState("");
  const [pullBusy, setPullBusy] = useState(false);
  const [addonMessage, setAddonMessage] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);

  const loadAddon = () => {
    api.ollamaAddon().then(setAddon).catch(() => undefined);
    api.ollamaInstalled().then((result) => setModels({ models: result.models })).catch(() => undefined);
  };

  useEffect(() => {
    api.aiStatus().then(setStatus).catch(() => undefined);
    api.ollamaModels().then(setModels).catch(() => undefined);
    loadAddon();
  }, []);

  const setupAddon = async () => {
    setAddonBusy(true);
    setAddonMessage(null);
    try {
      const result = await api.ollamaAddonEnsure();
      if (result.reachable) {
        setAddonMessage({
          tone: "success",
          text: result.created
            ? "Ollama-Add-on installiert und gestartet. Adresse wurde übernommen."
            : "Ollama-Add-on läuft. Adresse wurde übernommen.",
        });
      } else {
        setAddonMessage({
          tone: "warning",
          text: result.error || "Add-on läuft, antwortet aber noch nicht. Bitte kurz warten.",
        });
      }
      loadAddon();
      set("ollama_enabled", true);
      if (result.url) set("ollama_url", result.url);
    } catch (error) {
      setAddonMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setAddonBusy(false);
    }
  };

  const doPull = async () => {
    const model = pullModel.trim();
    if (!model) return;
    setPullBusy(true);
    setAddonMessage(null);
    try {
      await api.ollamaPull(model);
      setAddonMessage({ tone: "success", text: `Modell ${model} geladen.` });
      setPullModel("");
      loadAddon();
    } catch (error) {
      setAddonMessage({ tone: "danger", text: error instanceof ApiError ? error.message : String(error) });
    } finally {
      setPullBusy(false);
    }
  };

  const addonInstalled = Boolean(addon?.installed);

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="lg:col-span-2">
        <SectionTitle
          title="Ollama automatisch einrichten"
          subtitle="Installiert und startet das Ollama-Add-on und übernimmt die richtige Adresse."
        />
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="badge-neutral">Supervisor: {addon?.supervisor ? "verfügbar" : "nicht verfügbar"}</span>
            <span className="badge-neutral">Add-on: {addonInstalled ? "installiert" : "nicht installiert"}</span>
            {addon?.state && <span className="badge-neutral">Status: {addon.state}</span>}
            {addon?.suggested_url && <span className="badge-neutral font-mono">{addon.suggested_url}</span>}
          </div>
          <p className="text-xs text-ink-500">
            Die Einrichtung lädt ein kostenloses, lokales Modell über das Ollama-Add-on. Es entstehen keine Kosten
            und es wird keine Abrechnung aktiviert.
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary" onClick={setupAddon} disabled={addonBusy || !addon?.supervisor}>
              {addonBusy ? "Einrichten …" : addonInstalled ? "Add-on prüfen & Adresse übernehmen" : "Ollama installieren & starten"}
            </button>
            <button type="button" className="btn-ghost" onClick={loadAddon} disabled={addonBusy}>
              Status aktualisieren
            </button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[220px] flex-1">
              <Text
                id="pull_model"
                label="Modell herunterladen"
                value={pullModel}
                onChange={setPullModel}
                hint="Beispiel: llama3.2:3b, phi4-mini:3.8b oder qwen2.5:3b."
              />
            </div>
            <button type="button" className="btn-secondary" onClick={doPull} disabled={pullBusy || !pullModel.trim()}>
              {pullBusy ? "Lädt …" : "Herunterladen"}
            </button>
          </div>
          {addonMessage && <Alert tone={addonMessage.tone}>{addonMessage.text}</Alert>}
        </div>
      </Card>

      <Card>
        <SectionTitle
          title="Lokales Modell (Ollama)"
          subtitle="Kostenlos, offline, empfohlen für einfache Aufgaben auf dem Raspberry Pi."
        />
        <div className="space-y-4">
          <Toggle
            id="ollama_enabled"
            label="Ollama verwenden"
            checked={Boolean(values.ollama_enabled)}
            onChange={(value) => set("ollama_enabled", value)}
            hint="Ohne Ollama bleiben Bibliothek, Lernen und Schaltplan-Editor vollständig nutzbar."
          />
          <Text
            id="ollama_url"
            label="Ollama-Adresse"
            value={String(values.ollama_url ?? "")}
            onChange={(value) => set("ollama_url", value)}
            hint="Standard: http://homeassistant.local:11434 oder der Name des Ollama-Add-ons."
          />
          <Text
            id="ollama_model"
            label="Modell"
            value={String(values.ollama_model ?? "")}
            onChange={(value) => set("ollama_model", value)}
            hint="Empfohlen für 8 GB RAM: llama3.2:3b, phi4-mini:3.8b oder qwen2.5:3b."
          />
          {models && Array.isArray(models.models) && (models.models as string[]).length > 0 && (
            <div>
              <p className="text-xs font-medium text-ink-600">Installierte Modelle</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {(models.models as string[]).map((model) => (
                  <button
                    key={model}
                    type="button"
                    className="badge-neutral"
                    onClick={() => set("ollama_model", model)}
                  >
                    {model}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="rounded-xl bg-ink-50 p-3 text-xs text-ink-600">
            <p className="font-semibold text-ink-700">Empfohlene Modelle für 8 GB RAM</p>
            <ul className="mt-1.5 space-y-1">
              {(status?.ollama.recommended ?? []).map((model) => (
                <li key={model.name}>
                  <button type="button" className="text-left hover:underline" onClick={() => set("ollama_model", model.name)}>
                    <span className="font-mono">{model.name}</span> · {model.size_gb} GB · {model.note}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <button type="button" className="btn-primary" onClick={() => save(["ollama_enabled", "ollama_url", "ollama_model"])} disabled={busy}>
            Speichern
          </button>
        </div>
      </Card>

      <Card>
        <SectionTitle
          title="Cloud (Gemini Free Tier)"
          subtitle="Für anspruchsvolle Handschrift, Bilder und schwierige Fachfragen."
        />
        <div className="space-y-4">
          <Toggle
            id="gemini_enabled"
            label="Gemini verwenden"
            checked={Boolean(values.gemini_enabled)}
            onChange={(value) => set("gemini_enabled", value)}
          />
          <div>
            <label className="label" htmlFor="gemini_api_key">
              API-Schlüssel
            </label>
            <input
              id="gemini_api_key"
              type="password"
              className="input"
              placeholder={values.gemini_api_key_set ? "bereits gesetzt" : "AIza…"}
              value={String(values.gemini_api_key ?? "")}
              onChange={(event) => set("gemini_api_key", event.target.value)}
            />
            <p className="mt-1 text-xs text-ink-500">
              Der Schlüssel wird verschlüsselt in der Datenbank gespeichert und nie an das Frontend
              ausgeliefert. Erzeugen: aistudio.google.com → API key.
            </p>
          </div>
          <Text
            id="gemini_text_model"
            label="Textmodell"
            value={String(values.gemini_text_model ?? "")}
            onChange={(value) => set("gemini_text_model", value)}
            hint="Kostenloses Kontingent: gemini-2.5-flash oder gemini-2.5-flash-lite."
          />
          <Text
            id="gemini_vision_model"
            label="Bild-/OCR-Modell"
            value={String(values.gemini_vision_model ?? "")}
            onChange={(value) => set("gemini_vision_model", value)}
          />
          <Toggle
            id="gemini_allow_images"
            label="Bilder an die Cloud senden"
            checked={Boolean(values.gemini_allow_images)}
            onChange={(value) => set("gemini_allow_images", value)}
            hint="Aus: es werden nur Texte übertragen. Empfohlen, wenn Schaltpläne vertraulich sind."
          />
          <Toggle
            id="allow_external_ai"
            label="Externe KI grundsätzlich erlauben"
            checked={Boolean(values.allow_external_ai)}
            onChange={(value) => set("allow_external_ai", value)}
            hint="Abschalten erzwingt rein lokalen Betrieb."
          />
          {status?.gemini.quota && (
            <p className="text-xs text-ink-500">
              Kontingent heute: {status.gemini.quota.used} von {status.gemini.quota.limit}
              {status.gemini.quota.exhausted ? " (aufgebraucht)" : ""}
            </p>
          )}
          <button
            type="button"
            className="btn-primary"
            onClick={() =>
              save([
                "gemini_enabled",
                "gemini_api_key",
                "gemini_text_model",
                "gemini_vision_model",
                "gemini_allow_images",
                "allow_external_ai",
              ])
            }
            disabled={busy}
          >
            Speichern
          </button>
        </div>
      </Card>

      <Card className="lg:col-span-2">
        <SectionTitle title="Verhalten bei Ausfall" subtitle="Die Anwendung arbeitet immer weiter." />
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="ai_mode">
              KI-Modus
            </label>
            <select
              id="ai_mode"
              className="input"
              value={String(values.ai_mode ?? "auto")}
              onChange={(event) => set("ai_mode", event.target.value)}
            >
              <option value="auto">Automatisch (lokal bevorzugt)</option>
              <option value="local">Nur lokal (Ollama)</option>
              <option value="cloud">Nur Cloud (Gemini)</option>
              <option value="off">Aus (keine KI)</option>
            </select>
          </div>
          <NumberField
            id="ai_timeout_seconds"
            label="Zeitlimit je Anfrage (Sekunden)"
            value={Number(values.ai_timeout_seconds ?? 60)}
            onChange={(value) => set("ai_timeout_seconds", value)}
            min={5}
            max={300}
            hint="Kurze Zeitlimits verhindern blockierte Anfragen auf schwacher Hardware."
          />
          <NumberField
            id="ai_max_retries"
            label="Wiederholungsversuche"
            value={Number(values.ai_max_retries ?? 1)}
            onChange={(value) => set("ai_max_retries", value)}
            min={0}
            max={5}
          />
          <NumberField
            id="gemini_daily_limit"
            label="Tageslimit Gemini (Anfragen)"
            value={Number(values.gemini_daily_limit ?? 200)}
            onChange={(value) => set("gemini_daily_limit", value)}
            min={0}
            max={10000}
            hint="Sicherheitsgrenze, damit keine kostenpflichtigen Aufrufe entstehen."
          />
        </div>
        <button
          type="button"
          className="btn-primary mt-5"
          onClick={() => save(["ai_mode", "ai_timeout_seconds", "ai_max_retries", "gemini_daily_limit"])}
          disabled={busy}
        >
          Speichern
        </button>
      </Card>
    </div>
  );
}

function HaSettings({ values, set, save, busy }: TabProps) {
  const status = useAsync(() => api.haStatus(), []);
  const [notifyMessage, setNotifyMessage] = useState("");
  const [testResult, setTestResult] = useState<string | null>(null);

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <SectionTitle
          title="MQTT-Sensoren"
          subtitle="Lernfortschritt, Lernzeit und offene Wiederholungen als Home-Assistant-Sensoren."
        />
        <div className="space-y-4">
          <Toggle
            id="mqtt_enabled"
            label="MQTT veröffentlichen"
            checked={Boolean(values.mqtt_enabled)}
            onChange={(value) => set("mqtt_enabled", value)}
            hint="Nutzt den Mosquitto-Broker von Home Assistant. Ohne MQTT bleibt alles andere nutzbar."
          />
          <Text
            id="mqtt_host"
            label="Broker-Adresse"
            value={String(values.mqtt_host ?? "")}
            onChange={(value) => set("mqtt_host", value)}
            hint="Standard im Home-Assistant-Betrieb: core-mosquitto."
          />
          <NumberField
            id="mqtt_port"
            label="Port"
            value={Number(values.mqtt_port ?? 1883)}
            onChange={(value) => set("mqtt_port", value)}
            min={1}
            max={65535}
          />
          <Text
            id="mqtt_username"
            label="Benutzername"
            value={String(values.mqtt_username ?? "")}
            onChange={(value) => set("mqtt_username", value)}
          />
          <div>
            <label className="label" htmlFor="mqtt_password">
              Passwort
            </label>
            <input
              id="mqtt_password"
              type="password"
              className="input"
              placeholder={values.mqtt_password_set ? "bereits gesetzt" : ""}
              value={String(values.mqtt_password ?? "")}
              onChange={(event) => set("mqtt_password", event.target.value)}
            />
          </div>
          <NumberField
            id="sensor_update_interval"
            label="Aktualisierungsintervall (Sekunden)"
            value={Number(values.sensor_update_interval ?? 300)}
            onChange={(value) => set("sensor_update_interval", value)}
            min={30}
            max={3600}
            hint="Mindestens 30 Sekunden, um den Home-Assistant-Event-Bus zu schonen. Empfohlen: 300."
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-primary"
              onClick={() => save(["mqtt_enabled", "mqtt_host", "mqtt_port", "mqtt_username", "mqtt_password", "sensor_update_interval"])}
              disabled={busy}
            >
              Speichern
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={async () => {
                const result = await api.haPublish();
                setTestResult(result.ok ? "Sensoren veröffentlicht." : "Veröffentlichung fehlgeschlagen.");
                status.reload();
              }}
            >
              Sensoren jetzt senden
            </button>
          </div>
          {testResult && <p className="text-xs text-ink-500">{testResult}</p>}
        </div>
      </Card>

      <div className="space-y-5">
        <Card>
          <SectionTitle title="Status" />
          {status.loading && <Spinner />}
          {status.data && (
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-600">MQTT aktiv</dt>
                <dd>{status.data.mqtt_enabled ? "ja" : "nein"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-600">Verbindung</dt>
                <dd>{status.data.mqtt_connected ? "verbunden" : "nicht verbunden"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-600">Supervisor-Zugriff</dt>
                <dd>{status.data.supervisor_token ? "vorhanden" : "nicht vorhanden"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-600">Hintergrunddienst</dt>
                <dd>{status.data.scheduler_running ? "läuft" : "gestoppt"}</dd>
              </div>
            </dl>
          )}
        </Card>

        <Card>
          <SectionTitle title="Benachrichtigungen" subtitle="Erinnerungen über die Home-Assistant-App." />
          <div className="space-y-4">
            <Text
              id="ha_notify_service"
              label="Benachrichtigungsdienst"
              value={String(values.ha_notify_service ?? "")}
              onChange={(value) => set("ha_notify_service", value)}
              hint="Zum Beispiel notify.mobile_app_mein_handy. Leer lassen: dann erscheint die Meldung als dauerhafte Benachrichtigung in Home Assistant."
            />
            <NumberField
              id="notify_hour"
              label="Erinnerungszeit (Stunde)"
              value={Number(values.notify_hour ?? 18)}
              onChange={(value) => set("notify_hour", value)}
              min={0}
              max={23}
            />
            <Toggle
              id="notify_enabled"
              label="Tägliche Erinnerung senden"
              checked={Boolean(values.notify_enabled)}
              onChange={(value) => set("notify_enabled", value)}
            />
            <button type="button" className="btn-primary" onClick={() => save(["ha_notify_service", "notify_hour", "notify_enabled"])} disabled={busy}>
              Speichern
            </button>
            <div className="border-t border-ink-100 pt-4">
              <label className="label" htmlFor="notify-test">
                Testnachricht
              </label>
              <div className="flex gap-2">
                <input
                  id="notify-test"
                  className="input flex-1"
                  value={notifyMessage}
                  onChange={(event) => setNotifyMessage(event.target.value)}
                  placeholder="Text der Testnachricht"
                />
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={async () => {
                    try {
                      await api.haNotify(notifyMessage || "Testnachricht von ElektroCoach");
                      setTestResult("Benachrichtigung gesendet.");
                    } catch (error) {
                      setTestResult(error instanceof ApiError ? error.message : String(error));
                    }
                  }}
                >
                  Senden
                </button>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function LearnSettings({ values, set, save, busy }: TabProps) {
  return (
    <Card>
      <SectionTitle title="Lernen" subtitle="Tagesziel, Wiederholungen und Fragengenerierung." />
      <div className="grid gap-4 sm:grid-cols-2">
        <NumberField
          id="daily_goal_minutes"
          label="Tägliches Lernziel (Minuten)"
          value={Number(values.daily_goal_minutes ?? 30)}
          onChange={(value) => set("daily_goal_minutes", value)}
          min={5}
          max={480}
        />
        <NumberField
          id="exam_pass_percent"
          label="Bestehensgrenze (%)"
          value={Number(values.exam_pass_percent ?? 50)}
          onChange={(value) => set("exam_pass_percent", value)}
          min={30}
          max={90}
        />
        <NumberField
          id="srs_new_per_day"
          label="Neue Aufgaben pro Tag"
          value={Number(values.srs_new_per_day ?? 15)}
          onChange={(value) => set("srs_new_per_day", value)}
          min={0}
          max={100}
        />
        <NumberField
          id="srs_max_reviews"
          label="Maximale Wiederholungen pro Tag"
          value={Number(values.srs_max_reviews ?? 60)}
          onChange={(value) => set("srs_max_reviews", value)}
          min={5}
          max={300}
        />
        <NumberField
          id="question_default_count"
          label="Aufgaben je Generierung"
          value={Number(values.question_default_count ?? 5)}
          onChange={(value) => set("question_default_count", value)}
          min={1}
          max={30}
        />
        <NumberField
          id="question_default_difficulty"
          label="Standardschwierigkeit"
          value={Number(values.question_default_difficulty ?? 3)}
          onChange={(value) => set("question_default_difficulty", value)}
          min={1}
          max={5}
        />
        <Toggle
          id="mark_unverified"
          label="Unsichere KI-Inhalte kennzeichnen"
          checked={values.mark_unverified === undefined ? true : Boolean(values.mark_unverified)}
          onChange={(value) => set("mark_unverified", value)}
          hint="Empfohlen: automatisch erzeugte Fragen werden als prüfbedürftig markiert."
        />
        <Toggle
          id="auto_analyze_after_import"
          label="Themen nach Import automatisch analysieren"
          checked={values.auto_analyze_after_import === undefined ? true : Boolean(values.auto_analyze_after_import)}
          onChange={(value) => set("auto_analyze_after_import", value)}
        />
      </div>
      <button
        type="button"
        className="btn-primary mt-5"
        onClick={() =>
          save([
            "daily_goal_minutes",
            "exam_pass_percent",
            "srs_new_per_day",
            "srs_max_reviews",
            "question_default_count",
            "question_default_difficulty",
            "mark_unverified",
            "auto_analyze_after_import",
          ])
        }
        disabled={busy}
      >
        Speichern
      </button>
    </Card>
  );
}

function ImportSettings({ values, set, save, busy }: TabProps) {
  return (
    <Card>
      <SectionTitle title="Import und Texterkennung" subtitle="OCR, Handschrift und Ressourcenschutz." />
      <div className="grid gap-4 sm:grid-cols-2">
        <Text
          id="ocr_languages"
          label="OCR-Sprachen"
          value={String(values.ocr_languages ?? "deu+eng")}
          onChange={(value) => set("ocr_languages", value)}
          hint="Tesseract-Sprachkürzel, mit + verbunden. deu+eng für deutsche Aufzeichnungen."
        />
        <NumberField
          id="ocr_dpi"
          label="Auflösung für OCR (DPI)"
          value={Number(values.ocr_dpi ?? 300)}
          onChange={(value) => set("ocr_dpi", value)}
          min={150}
          max={600}
          hint="150 DPI ist der Standard. Höhere Werte erkennen Handschrift besser, brauchen aber mehr Speicher und Zeit."
        />
        <Toggle
          id="use_ai_for_ocr"
          label="KI für schwierige Handschrift verwenden"
          checked={Boolean(values.use_ai_for_ocr)}
          onChange={(value) => set("use_ai_for_ocr", value)}
          hint="Nur bei unsicherer Erkennung. Benötigt Gemini mit Bildfreigabe."
        />
        <Toggle
          id="keep_page_images"
          label="Seitenbilder aufbewahren"
          checked={values.keep_page_images === undefined ? true : Boolean(values.keep_page_images)}
          onChange={(value) => set("keep_page_images", value)}
          hint="Aus spart Speicherplatz, dann sind Originalausschnitte nicht mehr sichtbar."
        />
        <NumberField
          id="import_max_parallel"
          label="Gleichzeitige Dateien"
          value={Number(values.import_max_parallel ?? 1)}
          onChange={(value) => set("import_max_parallel", value)}
          min={1}
          max={4}
          hint="Auf dem Raspberry Pi 4 bei 1 belassen."
        />
        <NumberField
          id="import_memory_guard_mb"
          label="Speicherreserve (MB)"
          value={Number(values.import_memory_guard_mb ?? 400)}
          onChange={(value) => set("import_memory_guard_mb", value)}
          min={100}
          max={2000}
          hint="Unterhalb dieser Reserve pausiert der Import automatisch."
        />
        <NumberField
          id="dedupe_threshold"
          label="Duplikatschwelle"
          value={Number(values.dedupe_threshold ?? 0.9)}
          onChange={(value) => set("dedupe_threshold", value)}
          min={0.5}
          max={1}
          hint="Ähnlichkeit ab der Inhalte als Duplikat gelten (0,5 bis 1,0)."
        />
        <Toggle
          id="refine_after_import"
          label="Nach dem Import automatisch nachbearbeiten"
          checked={Boolean(values.refine_after_import)}
          onChange={(value) => set("refine_after_import", value)}
          hint="Startet die KI-Nachbearbeitung, sobald eine KI erreichbar ist."
        />
        <Toggle
          id="refine_use_cloud"
          label="Nachbearbeitung darf Gemini nutzen"
          checked={Boolean(values.refine_use_cloud)}
          onChange={(value) => set("refine_use_cloud", value)}
          hint="Standard aus: Nachbearbeitung läuft dann nur lokal über Ollama."
        />
      </div>
      <button
        type="button"
        className="btn-primary mt-5"
        onClick={() =>
          save([
            "ocr_languages",
            "ocr_dpi",
            "use_ai_for_ocr",
            "keep_page_images",
            "import_max_parallel",
            "import_memory_guard_mb",
            "dedupe_threshold",
            "refine_after_import",
            "refine_use_cloud",
          ])
        }
        disabled={busy}
      >
        Speichern
      </button>
    </Card>
  );
}

function SecuritySettings({ values, set, save, busy }: TabProps) {
  const storage = useAsync(() => api.storage(), []);
  const backups = useAsync(() => api.backups(), []);
  const [result, setResult] = useState<string | null>(null);

  return (
    <div className="space-y-5">
      <Card>
        <SectionTitle title="Zugangsschutz" subtitle="Zusätzliche Absicherung der Oberfläche." />
        <div className="grid gap-4 sm:grid-cols-2">
          <Toggle
            id="require_auth"
            label="Passwortschutz aktivieren"
            checked={Boolean(values.require_auth)}
            onChange={(value) => set("require_auth", value)}
            hint="Empfohlen, wenn Home Assistant aus dem Internet erreichbar ist."
          />
          <Text
            id="auth_password"
            label="Passwort"
            type="password"
            value={String(values.auth_password ?? "")}
            onChange={(value) => set("auth_password", value)}
            hint="Wird verschlüsselt gespeichert."
          />
          <Toggle
            id="audit_log_enabled"
            label="Änderungen protokollieren"
            checked={values.audit_log_enabled === undefined ? true : Boolean(values.audit_log_enabled)}
            onChange={(value) => set("audit_log_enabled", value)}
          />
          <Toggle
            id="allow_external_ai_strict"
            label="Keine Inhalte nach außen senden"
            checked={Boolean(values.allow_external_ai_strict)}
            onChange={(value) => set("allow_external_ai_strict", value)}
            hint="Erzwingt lokalen Betrieb, auch wenn ein Gemini-Schlüssel hinterlegt ist."
          />
        </div>
        <button type="button" className="btn-primary mt-5" onClick={() => save(["require_auth", "auth_password", "audit_log_enabled", "allow_external_ai_strict"])} disabled={busy}>
          Speichern
        </button>
      </Card>

      <Card>
        <SectionTitle title="Speicher" subtitle="Verbrauch und verfügbarer Platz." />
        {storage.data && (
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-500">Frei</dt>
              <dd className="text-lg font-semibold text-ink-900">
                {Math.round(storage.data.disk_free_mb)} MB
              </dd>
            </div>
            <div>
              <dt className="text-ink-500">Datenbank</dt>
              <dd className="text-lg font-semibold text-ink-900">
                {storage.data.database_mb.toFixed(1)} MB
              </dd>
            </div>
            <div>
              <dt className="text-ink-500">Dokumente</dt>
              <dd className="text-lg font-semibold text-ink-900">
                {storage.data.documents_mb.toFixed(1)} MB
              </dd>
            </div>
          </dl>
        )}
        {storage.data?.low_space_warning && (
          <div className="mt-3">
            <Alert tone="warning" title="Wenig Speicherplatz">
              Bitte Speicher freigeben oder auf eine SSD umsteigen.
            </Alert>
          </div>
        )}
      </Card>

      <Card>
        <SectionTitle title="Sicherungen" subtitle="Manuelle Sicherung und Wiederherstellung." />
        <div className="mb-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            onClick={async () => {
              const created = await api.createBackup("manuell", true);
              setResult(`Sicherung erstellt: ${created.name}`);
              backups.reload();
            }}
          >
            Sicherung erstellen
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={async () => {
              const maintenance = await api.maintenance();
              setResult(
                `Wartung abgeschlossen. Integrität: ${maintenance.integrity}. Größe: ${maintenance.size_before_mb} → ${maintenance.size_after_mb} MB.`,
              );
              storage.reload();
            }}
          >
            Datenbank optimieren
          </button>
        </div>
        {result && <p className="mb-3 text-xs text-ink-600">{result}</p>}
        {backups.data && backups.data.items.length === 0 && (
          <p className="text-sm text-ink-500">Noch keine Sicherungen vorhanden.</p>
        )}
        {backups.data && backups.data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="table-base min-w-[520px]">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Größe</th>
                  <th>Erstellt</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {backups.data.items.map((item) => (
                  <tr key={item.name}>
                    <td className="font-mono text-xs text-ink-700">{item.name}</td>
                    <td className="text-ink-600">{item.size_mb} MB</td>
                    <td className="text-ink-500">{item.created_at}</td>
                    <td className="text-right">
                      <button
                        type="button"
                        className="btn-secondary btn-sm"
                        onClick={async () => {
                          if (!window.confirm("Diese Sicherung wiederherstellen? Die aktuelle Datenbank wird ersetzt.")) return;
                          const restored = await api.restoreBackup(item.name, true);
                          setResult(
                            restored.ok
                              ? "Sicherung wiederhergestellt. Bitte die Anwendung neu starten."
                              : "Wiederherstellung fehlgeschlagen.",
                          );
                        }}
                      >
                        Wiederherstellen
                      </button>
                      <button
                        type="button"
                        className="btn-ghost btn-sm text-red-600"
                        onClick={async () => {
                          await api.deleteBackup(item.name);
                          backups.reload();
                        }}
                      >
                        Löschen
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
