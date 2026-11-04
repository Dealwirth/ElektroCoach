/** System: Zustand, Ressourcen, Importdienst, Wartung und Diagnose. */

import { api } from "../api";
import {
  Alert,
  Card,
  PageHeader,
  ProgressBar,
  SectionTitle,
  Spinner,
  StatCard,
  formatBytes,
  formatNumber,
  useAsync,
} from "../components/ui";

export default function SystemPage() {
  const info = useAsync(() => api.systemInfo(), []);
  const usage = useAsync(() => api.aiUsage(), []);

  if (info.loading) return <Spinner label="Systemdaten werden geladen …" />;
  if (info.error) return <Alert tone="danger">{info.error}</Alert>;
  if (!info.data) return null;

  const { storage, tesseract, handwriting, ai, ha } = info.data;
  const counts = storage.counts ?? {};

  return (
    <div className="space-y-6">
      <PageHeader
        title="System"
        subtitle="Ressourcen, Dienste und Wartung. Wichtig für den zuverlässigen Betrieb auf dem Raspberry Pi."
        actions={
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              info.reload();
              usage.reload();
            }}
          >
            Aktualisieren
          </button>
        }
      />

      {storage.low_space_warning && (
        <Alert tone="warning" title="Wenig Speicherplatz">
          Der freie Speicher ist knapp. Bitte Sicherungen oder alte Dokumente entfernen.
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Freier Speicher"
          value={formatNumber(storage.disk_free_mb, 0)}
          unit="MB"
          tone={storage.disk_free_percent < 10 ? "danger" : storage.disk_free_percent < 25 ? "warning" : "success"}
          hint={`${formatNumber(storage.disk_free_percent, 1)} % von ${formatNumber(storage.disk_total_mb, 0)} MB`}
        />
        <StatCard
          label="Datenbank"
          value={formatNumber(storage.database_mb, 1)}
          unit="MB"
          tone="brand"
          hint={`Integrität: ${storage.integrity}`}
        />
        <StatCard
          label="Freier Arbeitsspeicher"
          value={storage.memory_available_mb === null ? "–" : formatNumber(storage.memory_available_mb, 0)}
          unit="MB"
          tone="neutral"
          hint="Verfügbar für Importe und KI"
        />
        <StatCard
          label="Systemlast (1 min)"
          value={storage.load_1min === null ? "–" : formatNumber(storage.load_1min, 2)}
          unit="Load"
          tone={storage.load_1min !== null && storage.load_1min > 4 ? "warning" : "success"}
          hint={`${info.data.cpu_count ?? "?"} Kerne`}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <SectionTitle title="Speicherverbrauch" subtitle="Verteilung der Daten." />
          <div className="space-y-4">
            {[
              ["Datenbank", storage.database_mb],
              ["Seitenbilder", storage.pages_mb],
              ["Importdateien", storage.documents_mb],
              ["Sicherungen", storage.backups_mb],
            ].map(([label, value]) => (
              <div key={String(label)}>
                <div className="mb-1 flex justify-between text-xs text-ink-600">
                  <span>{label}</span>
                  <span>{formatNumber(Number(value), 1)} MB</span>
                </div>
                <ProgressBar
                  value={Number(value)}
                  max={Math.max(
                    storage.database_mb + storage.pages_mb + storage.documents_mb + storage.backups_mb,
                    1,
                  )}
                />
              </div>
            ))}
          </div>
          <div className="mt-5 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            {Object.entries(counts).map(([key, value]) => (
              <div key={key} className="rounded-lg bg-ink-50 px-3 py-2">
                <p className="text-xs text-ink-500">{key}</p>
                <p className="font-semibold text-ink-900">{value}</p>
              </div>
            ))}
          </div>
        </Card>

        <div className="space-y-5">
          <Card>
            <SectionTitle title="Dienste" />
            <dl className="space-y-2.5 text-sm">
              <Row label="Version" value={info.data.version} />
              <Row label="Python" value={info.data.python} />
              <Row label="Plattform" value={`${info.data.platform} / ${info.data.machine}`} />
              <Row
                label="Laufzeit"
                value={`${Math.floor(info.data.uptime_seconds / 3600)} h ${Math.floor((info.data.uptime_seconds % 3600) / 60)} min`}
              />
              <Row label="Import-Warteschlange" value={String(info.data.import_queue)} />
              <Row label="Importdienst" value={info.data.import_worker_alive ? "aktiv" : "inaktiv"} />
              <Row
                label="Texterkennung"
                value={
                  tesseract.available
                    ? `aktiv (${tesseract.languages.slice(0, 4).join(", ") || "keine Sprachen"})`
                    : "nicht installiert"
                }
              />
              <Row
                label="Handschrift"
                value={
                  handwriting.available
                    ? `aktiv (TrOCR${handwriting.engine !== "auto" ? `, ${handwriting.engine}` : ""})`
                    : "nicht verfügbar"
                }
              />
              <Row label="MQTT-Sensoren" value={ha.mqtt_enabled ? "aktiv" : "inaktiv"} />
              <Row label="Sensorintervall" value={`${ha.sensor_update_interval} s`} />
            </dl>
            {!tesseract.available && (
              <div className="mt-3">
                <Alert tone="warning" title="Texterkennung nicht verfügbar">
                  Ohne Tesseract werden nur bereits digitale Texte aus PDF- und Textdateien gelesen.
                  Bilder und Scans benötigen die Texterkennung.
                </Alert>
              </div>
            )}
            {!handwriting.available && (
              <div className="mt-3">
                <Alert tone="warning" title="Handschrift-Modell nicht verfügbar">
                  Ohne das lokale Handschrift-Modell liest nur Tesseract, der bei Handschrift
                  unbrauchbare Ergebnisse liefert. Fehlende Dateien: {handwriting.missing.join(", ") || "unbekannt"}.
                </Alert>
              </div>
            )}
          </Card>

          <Card>
            <SectionTitle title="KI-Verbrauch heute" />
            {usage.loading && <Spinner />}
            {usage.data && (
              <div className="space-y-3 text-sm">
                <Row
                  label="Anfragen gesamt"
                  value={String((usage.data.today as { total?: number })?.total ?? 0)}
                />
                <Row
                  label="Lokal (Ollama)"
                  value={String(
                    ((usage.data.today as Record<string, { calls?: number }>)?.ollama?.calls) ?? 0,
                  )}
                />
                <Row
                  label="Cloud (Gemini)"
                  value={String(
                    ((usage.data.today as Record<string, { calls?: number }>)?.gemini?.calls) ?? 0,
                  )}
                />
                {usage.data.gemini_quota ? (
                  <div>
                    <div className="mb-1 flex justify-between text-xs text-ink-600">
                      <span>Gemini-Kontingent</span>
                      <span>
                        {String((usage.data.gemini_quota as { used: number }).used)} /{" "}
                        {String((usage.data.gemini_quota as { limit: number }).limit)}
                      </span>
                    </div>
                    <ProgressBar
                      value={Number((usage.data.gemini_quota as { used: number }).used)}
                      max={Number((usage.data.gemini_quota as { limit: number }).limit) || 1}
                      tone={
                        (usage.data.gemini_quota as { exhausted: boolean }).exhausted ? "danger" : "brand"
                      }
                    />
                  </div>
                ) : null}
                <p className="text-xs text-ink-500">
                  Modus: {ai.mode} · lokal {ai.ollama.available ? "bereit" : "inaktiv"} · Cloud{" "}
                  {ai.gemini.available ? "bereit" : "inaktiv"}
                </p>
              </div>
            )}
          </Card>
        </div>
      </div>

      <Card>
        <SectionTitle title="Wartung" subtitle="Sichere Vorgänge zur Pflege der Datenbank." />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-primary"
            onClick={async () => {
              const result = await api.maintenance();
              window.alert(
                `Wartung abgeschlossen.\nIntegrität: ${result.integrity}\nGröße: ${result.size_before_mb} MB → ${result.size_after_mb} MB`,
              );
              info.reload();
            }}
          >
            Datenbank optimieren
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={async () => {
              const result = await api.createBackup("systemseite", true);
              window.alert(`Sicherung erstellt: ${result.name} (${result.size_mb} MB)`);
              info.reload();
            }}
          >
            Sicherung erstellen
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={async () => {
              const result = await api.cleanupUploads();
              window.alert(`${result.removed} nicht mehr benötigte Importdateien entfernt.`);
              info.reload();
            }}
          >
            Importdateien aufräumen
          </button>
        </div>
        <p className="mt-3 text-xs text-ink-500">
          Gesamter Datenverbrauch: {formatBytes(
            (storage.database_mb + storage.pages_mb + storage.documents_mb + storage.backups_mb) * 1024 * 1024,
          )}
        </p>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-ink-600">{label}</dt>
      <dd className="text-right font-medium text-ink-900">{value}</dd>
    </div>
  );
}
