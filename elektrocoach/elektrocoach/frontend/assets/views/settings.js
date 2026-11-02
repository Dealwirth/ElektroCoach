/** Settings: runtime options, learning goals, notifications and secrets. */

import { api } from '../api.js';
import {
  el, card, badge, button, spinner, errorBox, toast, field, input, select,
  checkbox, infoBox, table, formatDate, formatBytes,
} from '../ui.js';

export async function renderSettings(container, { navigate }) {
  container.appendChild(el('div', { className: 'view-header' }, [
    el('h1', { text: 'Einstellungen' }),
    el('p', { text:
      'Änderungen wirken sofort. Ihr Gemini-API-Schlüssel wird sicher im Backend gespeichert und niemals an den Browser gesendet.' }),
  ]));

  const host = el('div');
  container.appendChild(host);

  const learningHost = el('div');
  const aiHost = el('div');
  const notifyHost = el('div');
  const infoHost = el('div');
  host.appendChild(el('div', { className: 'grid grid-2' }, [learningHost, notifyHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [aiHost]));
  host.appendChild(el('div', { style: { marginTop: '16px' } }, [infoHost]));

  let settings = {};
  try {
    settings = await api.get('api/settings');
  } catch (error) {
    host.replaceChildren(errorBox(error));
    return;
  }

  const stored = settings.settings || {};
  const runtime = settings.runtime || {};

  // -- learning --------------------------------------------------------------
  const goalMinutes = input({ type: 'number', value: String(stored['learning.daily_goal_minutes'] || 30), min: '5', max: '480' });
  const examDate = input({ type: 'date', value: stored['learning.exam_date'] || '' });
  const reminderTime = input({ type: 'time', value: stored['notifications.reminder_time'] || '18:00' });

  learningHost.appendChild(card('Lernen', [
    field('Tägliches Lernziel in Minuten', goalMinutes),
    field('Prüfungstermin', examDate, 'Wird für den Lernplan verwendet.'),
    el('div', { className: 'btn-row' }, [
      button('Speichern', {
        variant: 'primary',
        onClick: async () => {
          try {
            await api.patch('api/settings', {
              values: {
                'learning.daily_goal_minutes': Number(goalMinutes.value) || 30,
                'learning.exam_date': examDate.value || '',
              },
            });
            toast('Die Lerneinstellungen wurden gespeichert.', 'success');
          } catch (error) {
            toast(error.message, 'error');
          }
        },
      }),
    ]),
  ]));

  // -- notifications ---------------------------------------------------------
  const dailyReminder = el('input', {
    attrs: { type: 'checkbox', checked: stored['notifications.daily_reminder'] !== false ? true : undefined },
  });
  const notifyService = input({ value: runtime.notify_service || '', placeholder: 'z. B. notify.mobile_app_mein_handy' });
  const notifyEnabled = el('input', {
    attrs: { type: 'checkbox', checked: runtime.notifications_enabled ? true : undefined },
  });
  const autoRepair = el('input', {
    attrs: { type: 'checkbox', checked: runtime.auto_repair_enabled ? true : undefined },
  });

  notifyHost.appendChild(card('Benachrichtigungen und Reparatur', [
    el('label', { className: 'checkbox' }, [notifyEnabled, el('span', { text: 'Benachrichtigungen an Home Assistant senden' })]),
    el('label', { className: 'checkbox' }, [dailyReminder, el('span', { text: 'Tägliche Lernempfehlung senden' })]),
    field('Uhrzeit der Erinnerung', reminderTime),
    field('Benachrichtigungsdienst', notifyService,
      'Leer lassen für dauerhafte Benachrichtigungen in Home Assistant. Für die App auf dem Smartphone z. B. „notify.mobile_app_mein_handy“ eintragen.'),
    el('label', { className: 'checkbox' }, [autoRepair, el('span', { text: 'Sichere automatische Reparaturen ausführen' })]),
    el('p', { className: 'muted small', text:
      'Automatische Reparaturen führen ausschließlich risikoarme Schritte aus (Worker neu starten, Aufgabe erneut einreihen, Index neu aufbauen). Alles, was Daten verändert, erfordert immer Ihre Bestätigung.' }),
    el('div', { className: 'btn-row' }, [
      button('Speichern', {
        variant: 'primary',
        onClick: async () => {
          try {
            await api.patch('api/settings', {
              values: {
                'notifications.daily_reminder': dailyReminder.checked,
                'notifications.reminder_time': reminderTime.value || '18:00',
              },
            });
            await api.patch('api/settings/runtime', {
              notify_service: notifyService.value || '',
              notifications_enabled: notifyEnabled.checked,
              auto_repair_enabled: autoRepair.checked,
            });
            toast('Die Benachrichtigungseinstellungen wurden gespeichert.', 'success');
          } catch (error) {
            toast(error.message, 'error');
          }
        },
      }),
      button('Testbenachrichtigung senden', {
        onClick: async () => {
          try {
            const response = await api.post('api/homeassistant/notify-test');
            toast(response.message, response.ok ? 'success' : 'warning', 9000);
          } catch (error) {
            toast(error.message, 'error');
          }
        },
      }),
    ]),
  ]));

  // -- AI --------------------------------------------------------------------
  const ollamaModel = input({ value: runtime.ollama_model || '' });
  const geminiModel = input({ value: runtime.gemini_model || '' });
  const geminiKey = input({ type: 'password', placeholder: runtime.gemini_api_key_set ? '•••••• (bereits gespeichert)' : 'API-Schlüssel eintragen' });
  const geminiEnabled = el('input', {
    attrs: { type: 'checkbox', checked: runtime.gemini_enabled ? true : undefined },
  });
  const aiFeedback = el('div');

  aiHost.appendChild(card('Künstliche Intelligenz', [
    el('div', { className: 'grid grid-2' }, [
      el('div', {}, [
        el('h4', { text: 'Lokale KI (Ollama)' }),
        el('p', { className: 'muted small', text:
          `Adresse: ${runtime.ollama_url} (wird in der Add-on-Konfiguration geändert)` }),
        field('Modell', ollamaModel, 'Empfohlen für den Raspberry Pi 4: qwen2.5:1.5b. Für bessere Qualität: qwen2.5:3b (langsamer).'),
        el('div', { className: 'btn-row' }, [
          button('Verbindung prüfen', {
            className: 'btn-sm',
            onClick: async () => {
              aiFeedback.replaceChildren(spinner('Prüfung läuft …'));
              try {
                const response = await api.post('api/settings/ollama/test');
                aiFeedback.replaceChildren(infoBox(response.message, response.ok ? 'success' : 'warning'));
              } catch (error) {
                aiFeedback.replaceChildren(errorBox(error));
              }
            },
          }),
        ]),
      ]),
      el('div', {}, [
        el('h4', { text: 'Google Gemini (kostenlos)' }),
        el('p', { className: 'muted small', text:
          'Wird für Handschrifterkennung und schwierige Fachfragen verwendet. Es ist ausschließlich die kostenlose Nutzung vorgesehen. Ist das Kontingent erschöpft, wird die Aufgabe pausiert – es erfolgt keine kostenpflichtige Anfrage.' }),
        el('label', { className: 'checkbox' }, [geminiEnabled, el('span', { text: 'Gemini verwenden' })]),
        field('API-Schlüssel', geminiKey, 'Wird verschlüsselt gespeichert und nie angezeigt. Erstellen Sie einen kostenlosen Schlüssel unter https://aistudio.google.com/app/apikey'),
        field('Modell', geminiModel, 'Die Modellliste wird live geladen. Wählen Sie ein Modell mit „flash“ im Namen für schnelle Antworten.'),
        el('div', { className: 'btn-row' }, [
          button('Schlüssel und Modell prüfen', {
            className: 'btn-sm',
            onClick: async () => {
              aiFeedback.replaceChildren(spinner('Gemini wird geprüft …'));
              try {
                const response = await api.post('api/settings/gemini/test');
                aiFeedback.replaceChildren(infoBox(response.message, response.ok ? 'success' : 'warning'));
              } catch (error) {
                aiFeedback.replaceChildren(errorBox(error));
              }
            },
          }),
        ]),
      ]),
    ]),
    el('div', { className: 'btn-row', style: { marginTop: '12px' } }, [
      button('KI-Einstellungen speichern', {
        variant: 'primary',
        onClick: async () => {
          const payload = {
            ollama_model: ollamaModel.value || undefined,
            gemini_model: geminiModel.value || undefined,
            gemini_enabled: geminiEnabled.checked,
          };
          if (geminiKey.value) payload.gemini_api_key = geminiKey.value;
          try {
            await api.patch('api/settings/runtime', payload);
            geminiKey.value = '';
            toast('Die KI-Einstellungen wurden gespeichert.', 'success');
          } catch (error) {
            toast(error.message, 'error');
          }
        },
      }),
    ]),
    aiFeedback,
  ]));

  // -- read-only info --------------------------------------------------------
  infoHost.appendChild(card('Systemwerte (nur Anzeige)', [
    table(
      ['Einstellung', 'Wert'],
      [
        ['Backup-Intervall', `${runtime.backup_interval_hours} Stunden`],
        ['Aufbewahrte Backups', String(runtime.backup_keep)],
        ['Speicherwarnung ab', `${runtime.storage_warning_percent} %`],
        ['Speicher kritisch ab', `${runtime.storage_critical_percent} %`],
        ['Überwachungsintervall', `${runtime.monitoring_interval_seconds} Sekunden`],
        ['Sprachen der Texterkennung', runtime.ocr_language || '–'],
        ['Gemini-Tageslimit', String(runtime.gemini_daily_request_budget)],
      ],
    ),
    infoBox(settings.addon_options_note),
    el('div', { className: 'btn-row' }, [
      button('Zum Einrichtungsassistenten', { onClick: () => navigate('setup') }),
      button('Backups verwalten', { onClick: () => navigate('system') }),
    ]),
  ]));
}
