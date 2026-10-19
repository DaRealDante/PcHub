import datetime
import time
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit,
                               QMenu, QPlainTextEdit, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from pchub.core.dates import formatCountdown, formatWhen, parseDateTime, toIso
from pchub.core.i18n import T, language, tr
from pchub.core.plugin_api import ActiveItem, CalendarItem, HomeWidgetSpec, PluginBase, TrayEntry
from pchub.core.settings_schema import Choice, NumberInput, Section, Slider, Toggle
from pchub.plugins.commissions import logic
from pchub.ui.calendar_widgets import DateTimeField
from pchub.ui.dialogs import ThemedDialog, askText, confirm, showMessage
from pchub.ui.theme import theme
from pchub.ui.widgets import (BarChart, Card, EmptyState, IconTile, IconWidget, MeterBar, clearLayout, divider,
                              iconButton, makeButton, makeLabel, setRole, setThemedIcon)

MIME_TYPE = "application/x-pchub-commission"
TEXT = {
    "new": T("Nuova commissione", "New commission"),
    "edit": T("Commissione", "Commission"),
    "board": T("Bacheca", "Board"),
    "list": T("Lista", "List"),
    "clients": T("Clienti", "Clients"),
    "export": T("Esporta", "Export"),
    "exportAll": T("Esporta tutte", "Export all"),
    "exportError": T("Esportazione non riuscita", "Export failed"),
    "replaceExport": T("Sostituire il file esistente?", "Replace the existing file?"),
    "replace": T("Sostituisci", "Replace"),
    "search": T("Cerca commissioni o clienti…", "Search commissions or clients…"),
    "allClients": T("Tutti i clienti", "All clients"),
    "active": T("In corso", "Active"),
    "dueWeek": T("Scadenze 7 giorni", "Due in 7 days"),
    "overdueCount": T("{count} in ritardo", "{count} overdue"),
    "toCollect": T("Da incassare", "To collect"),
    "earnedYear": T("Incassato {year}", "Earned {year}"),
    "threshold": T("{earned} di {limit}", "{earned} of {limit}"),
    "earningsChart": T("Incassi ultimi 12 mesi", "Earnings, last 12 months"),
    "title": T("Titolo", "Title"),
    "client": T("Cliente", "Client"),
    "noClient": T("Nessun cliente", "No client"),
    "newClient": T("Nuovo cliente", "New client"),
    "clientName": T("Nome del cliente (es. nick Discord)", "Client name (e.g. Discord nick)"),
    "platform": T("Piattaforma", "Platform"),
    "status": T("Stato", "Status"),
    "price": T("Prezzo", "Price"),
    "extraCosts": T("Costi aggiuntivi", "Extra costs"),
    "addExtraCost": T("Aggiungi costo", "Add cost"),
    "costDescription": T("Descrizione del costo", "Cost description"),
    "baseAmount": T("Compenso base", "Base amount"),
    "baseInput": T("Prezzo base", "Base price"),
    "total": T("Totale", "Total"),
    "method": T("Pagamento", "Payment"),
    "deadline": T("Scadenza", "Deadline"),
    "alertBefore": T("Avvisami", "Alert me"),
    "noAlert": T("Nessun avviso", "No alert"),
    "hoursBefore": T("{count} ore prima", "{count} hours before"),
    "daysBefore": T("{count} giorni prima", "{count} days before"),
    "dayBefore": T("1 giorno prima", "1 day before"),
    "tasks": T("Checklist", "Checklist"),
    "addTask": T("Aggiungi un passaggio e premi Invio", "Add a step and press Enter"),
    "payments": T("Pagamenti", "Payments"),
    "addPayment": T("Registra pagamento", "Record payment"),
    "paidOf": T("Pagato {paid} di {price}", "Paid {paid} of {price}"),
    "notes": T("Note (richieste del cliente, link, accordi…)", "Notes (client requests, links, agreements…)"),
    "description": T("Descrizione", "Description"),
    "save": T("Salva", "Save"),
    "cancel": T("Annulla", "Cancel"),
    "delete": T("Elimina", "Delete"),
    "archive": T("Archivia", "Archive"),
    "unarchive": T("Ripristina", "Restore"),
    "deleteTitle": T("Eliminare la commissione?", "Delete the commission?"),
    "deleteMessage": T("Verranno eliminati anche i pagamenti registrati.", "Recorded payments will be deleted too."),
    "empty": T("Nessuna commissione", "No commissions"),
    "emptyText": T("Premi Nuova commissione per iniziare a tenere traccia di lavori, scadenze e pagamenti.",
                   "Press New commission to start tracking jobs, deadlines and payments."),
    "dropHere": T("Trascina qui", "Drop here"),
    "deadlineSoonTitle": T("Scadenza vicina: {title}", "Deadline soon: {title}"),
    "deadlineNowTitle": T("Scadenza: {title}", "Deadline: {title}"),
    "open": T("Apri", "Open"),
    "ok": T("Ok", "OK"),
    "markDelivered": T("Consegnata", "Delivered"),
    "overdue": T("in ritardo", "overdue"),
    "noDeadline": T("Senza scadenza", "No deadline"),
    "clientsTitle": T("Clienti", "Clients"),
    "clientCommissions": T("{count} commissioni · {active} attive · incassato {earned}", "{count} commissions · {active} active · earned {earned}"),
    "rename": T("Rinomina", "Rename"),
    "deleteClient": T("Rimuovere il cliente dalla lista?", "Remove client from the directory?"),
    "deleteClientMessage": T("Il nome resta nelle sue commissioni. Il cliente non sarà più nella lista.",
                             "Their name stays on existing commissions. They will no longer be in the directory."),
    "temporaryClient": T("Cliente temporaneo", "Temporary client"),
    "temporaryHint": T("Il nome resta solo in questa commissione e non viene aggiunto alla lista clienti.",
                       "The name stays only in this commission and is not added to the client directory."),
    "markPaid": T("Pagata", "Paid"),
    "manualPayment": T("Pagamento manuale", "Manual payment"),
    "exported": T("Esportate {count} commissioni", "Exported {count} commissions"),
    "paidLabel": T("pagata", "paid"),
    "unpaid": T("da pagare", "unpaid"),
    "archived": T("Mostra archiviate", "Show archived"),
    "nextDeadline": T("Prossima scadenza", "Next deadline"),
    "noneActive": T("Nessuna commissione attiva", "No active commissions"),
    "paymentAmount": T("Importo", "Amount"),
    "paymentRecorded": T("Pagamento registrato", "Payment recorded"),
    "quickStatus": T("Sposta in", "Move to"),
    "billing": T("Compenso", "Billing"),
    "fixed": T("Prezzo fisso", "Fixed price"),
    "hourly": T("A ore", "Hourly"),
    "work": T("Tempo di lavoro", "Work time"),
    "rate": T("Tariffa oraria", "Hourly rate"),
    "worked": T("Tempo lavorato", "Time worked"),
    "accrued": T("Guadagno maturato", "Accrued earnings"),
    "accruedShort": T("Maturato", "Earned"),
    "defaultHourlyRate": T("Tariffa oraria predefinita", "Default hourly rate"),
    "defaultRateHint": T("Nella valuta della commissione. Si applica alle nuove commissioni; puoi cambiarla per ogni lavoro.",
                         "In the commission's currency. Applies to new commissions; you can change it for each job."),
    "startWork": T("Avvia", "Start"),
    "pauseWork": T("Pausa", "Pause"),
    "resumeWork": T("Riprendi", "Resume"),
    "resetWork": T("Azzera", "Reset"),
    "editTime": T("Correggi tempo", "Adjust time"),
    "resetTitle": T("Azzerare il tempo lavorato?", "Reset tracked time?"),
    "resetMessage": T("Il tempo e il guadagno maturato torneranno a zero. I pagamenti registrati restano.",
                      "Tracked time and accrued earnings will return to zero. Recorded payments are kept."),
    "trackingHint": T("I comandi del cronometro salvano subito. Continua in background; all’uscita dall’app va in pausa.",
                      "Timer commands save immediately. Runs in the background; pauses when you quit the app."),
    "rateHint": T("La tariffa si applica a tutto il tempo lavorato. Il maturato non è ancora un incasso.",
                  "The rate applies to all tracked time. Accrued earnings are not received payments."),
    "runningWork": T("In registrazione", "Tracking"),
    "pausedWork": T("In pausa", "Paused"),
    "hours": T("Ore", "Hours"),
    "minutes": T("Minuti", "Minutes"),
    "seconds": T("Secondi", "Seconds"),
}
ALERT_OPTIONS = [None, 2, 6, 24, 48, 168]


def alertLabel(hours):
    if hours is None:
        return tr(TEXT["noAlert"])
    if hours == 24:
        return tr(TEXT["dayBefore"])
    if hours % 24 == 0:
        return tr(TEXT["daysBefore"], count=hours // 24)
    return tr(TEXT["hoursBefore"], count=hours)


def statusName(statusId):
    return tr(logic.statusInfo(statusId)[1])


class CommissionsPlugin(PluginBase):
    pluginId = "commissions"
    name = T("Commissioni", "Commissions")
    description = T("Lavori dei clienti: stato, scadenze, prezzi in € o Robux, pagamenti e incassi dell'anno.",
                    "Client jobs: status, deadlines, prices in € or Robux, payments and yearly earnings.")
    icon = "briefcase"
    version = "1.4.0"
    author = "Ken"
    settingsSchema = [
        Section(T("Predefiniti", "Defaults")),
        Choice("defaultCurrency", T("Valuta predefinita", "Default currency"), [("EUR", "Euro (€)"), ("ROBUX", "Robux (R$)"),
                                                                              ("USD", "Dollari ($)")], "EUR", icon="tag",
               pinnable=False),
        NumberInput("defaultHourlyRate", TEXT["defaultHourlyRate"], 0, 10_000_000, 0, decimals=2,
                    suffix=T(" /ora", " /hour"), icon="timer", pinnable=False, description=TEXT["defaultRateHint"]),
        Choice("defaultMethod", T("Pagamento predefinito", "Default payment"), [(method, method) for method in logic.PAYMENT_METHODS],
               "Stripe", icon="package", pinnable=False),
        Choice("defaultPlatform", T("Piattaforma predefinita", "Default platform"),
               [(platform, platform) for platform in logic.PLATFORMS], "Discord", icon="users", pinnable=False),
        Section(T("Valute", "Currencies"), description=T("Servono solo per i totali in euro.", "Only used for the euro totals.")),
        NumberInput("robuxRate", T("Valore di 1.000 Robux in €", "Value of 1,000 Robux in €"), 0, 100, 3.2, decimals=2,
                    step=0.1, suffix=" €", icon="gem",
                    description=T("Il DevEx paga circa 3,50 $ ogni 1.000 Robux: metti quanto prendi davvero tu.",
                                  "DevEx pays about $3.50 per 1,000 Robux: put what you actually get.")),
        NumberInput("usdRate", T("Valore di 1 $ in €", "Value of $1 in €"), 0, 10, 0.92, decimals=2, step=0.01,
                    suffix=" €", icon="globe"),
        Section(T("Soglia annua", "Yearly limit")),
        Toggle("showThreshold", T("Mostra la soglia annua", "Show the yearly limit"), True, icon="gauge",
               description=T("Una barra con quanto hai incassato quest'anno rispetto al limite che vuoi tenere d'occhio.",
                             "A bar with how much you earned this year against the limit you want to watch.")),
        NumberInput("yearlyThreshold", T("Soglia (es. prestazione occasionale)", "Limit (e.g. occasional work)"), 0, 1000000,
                    5000, suffix=" €", visibleIf=("showThreshold", True), icon="flag",
                    description=T("Solo un promemoria visivo: per i conti veri chiedi al commercialista.",
                                  "Just a visual reminder: ask an accountant for the real numbers.")),
        Section(T("Avvisi", "Alerts")),
        Toggle("deadlineAlerts", T("Avvisi per le scadenze", "Deadline alerts"), True, icon="bell-ring"),
        Choice("defaultAlert", T("Avviso predefinito", "Default alert"),
               [(str(hours), alertLabel(hours)) for hours in ALERT_OPTIONS if hours], "24", icon="hourglass", pinnable=False,
               visibleIf=("deadlineAlerts", True)),
        Toggle("sound", T("Suono", "Sound"), True, icon="volume-2", visibleIf=("deadlineAlerts", True)),
        Section(T("Bacheca", "Board")),
        Toggle("showCancelled", T("Mostra la colonna Annullate", "Show the Cancelled column"), False, icon="x",
               pinnable=False),
        Slider("hidePaidAfterDays", T("Nascondi le pagate dopo", "Hide paid ones after"), 0, 120, 30, suffix=T(" giorni", " days"),
               icon="eye-off", pinnable=False,
               description=T("Restano nella lista e nei totali. 0 = non nasconderle mai.",
                             "They stay in the list and totals. 0 = never hide.")),
    ]

    commissionsChanged = Signal()
    workChanged = Signal()

    def __init__(self, context):
        super().__init__(context)
        self.clock = datetime.datetime.now
        self.commissions = list(context.getData("commissions", []) or [])
        for commission in self.commissions:
            commission.setdefault("basePrice", float(commission.get("price") or 0))
            commission.setdefault("extraCosts", [])
            commission["price"] = logic.workPrice(commission)
        self.clients = list(context.getData("clients", []) or [])
        self.workClock = time.monotonic
        self.runningCommissionId = None
        self.lastWorkTick = None
        self.lastWorkSave = 0
        self.workTimer = QTimer(self)
        self.workTimer.setInterval(1000)
        self.workTimer.timeout.connect(self._tickWork)
        self.checkTimer = QTimer(self)
        self.checkTimer.setInterval(60000)
        self.checkTimer.timeout.connect(self.check)

    def start(self):
        self.checkTimer.start()
        QTimer.singleShot(2500, self.check)

    def stop(self):
        self.pauseWork()
        self.checkTimer.stop()
        self.save()

    def save(self):
        self.context.setData("commissions", self.commissions)
        self.context.setData("clients", self.clients)

    def _changed(self):
        self.save()
        self.refreshActive()
        self.commissionsChanged.emit()
        self.context.notifyCalendarChanged()

    def onSettingChanged(self, key, value):
        self.commissionsChanged.emit()

    def rates(self):
        return {"ROBUX": self.setting("robuxRate") or 0, "USD": self.setting("usdRate") or 0}

    def money(self, amount, currency):
        return logic.formatMoney(amount, currency, language())

    def euro(self, amount):
        return logic.formatMoney(amount, "EUR", language())

    # clients ------------------------------------------------------------------
    def client(self, clientId):
        return next((client for client in self.clients if client["id"] == clientId), None)

    def clientName(self, clientId, fallback=""):
        client = self.client(clientId)
        return client["name"] if client else fallback

    def _prepareClientFields(self, fields):
        if not any(key in fields for key in ("clientId", "clientName", "temporaryClient")):
            return
        client = self.client(fields.get("clientId"))
        name = (fields.get("clientName") or (client or {}).get("name") or "").strip()
        if fields.get("temporaryClient"):
            fields.update(clientId=None, clientName=name, temporaryClient=True)
        elif name:
            client = client or next((entry for entry in self.clients if entry["name"].casefold() == name.casefold()), None)
            if client is None:
                client = logic.newClient(name, fields.get("platform") or self.setting("defaultPlatform") or "Discord")
                self.clients.append(client)
            fields.update(clientId=client["id"], clientName=client["name"], temporaryClient=False)
        else:
            fields.update(clientId=None, clientName="", temporaryClient=False)

    def addClient(self, name, platform=None):
        client = logic.newClient(name, platform or self.setting("defaultPlatform") or "Discord")
        self.clients.append(client)
        self._changed()
        return client

    def renameClient(self, clientId, name):
        client = self.client(clientId)
        if client and name:
            client["name"] = name
            self._changed()

    def deleteClient(self, clientId):
        name = self.clientName(clientId)
        self.clients = [client for client in self.clients if client["id"] != clientId]
        for commission in self.commissions:
            if commission.get("clientId") == clientId:
                commission.update(clientId=None, clientName=name or commission.get("clientName", ""), temporaryClient=True)
        self._changed()

    # commissions ------------------------------------------------------------------
    def find(self, commissionId):
        return next((commission for commission in self.commissions if commission["id"] == commissionId), None)

    def add(self, title, **fields):
        self._prepareClientFields(fields)
        commission = logic.newCommission(title, fields.pop("clientId", None), fields.pop("price", 0),
                                         fields.pop("currency", self.setting("defaultCurrency") or "EUR"),
                                         fields.pop("status", "todo"), fields.pop("deadline", None),
                                         fields.pop("platform", self.setting("defaultPlatform") or "Discord"),
                                         fields.pop("paymentMethod", self.setting("defaultMethod") or "Stripe"),
                                         now=self.clock())
        defaultAlert = self.setting("defaultAlert")
        commission["deadlineAlertHours"] = int(defaultAlert) if defaultAlert not in (None, "", "none") else None
        commission["hourlyRate"] = float(self.setting("defaultHourlyRate") or 0)
        commission.update(fields)
        commission["extraCosts"] = [dict(cost) for cost in commission.get("extraCosts") or []]
        commission["price"] = logic.workPrice(commission)
        self.commissions.append(commission)
        self._changed()
        return commission

    def update(self, commissionId, **fields):
        commission = self.find(commissionId)
        if commission is None:
            return
        self._prepareClientFields(fields)
        if self.runningCommissionId == commissionId:
            self._tickWork()
            if (fields.get("billingMode", commission.get("billingMode")) != "hourly"
                    or float(fields.get("hourlyRate", commission.get("hourlyRate")) or 0) <= 0
                    or fields.get("status", commission["status"]) not in logic.ACTIVE_STATUSES):
                self.pauseWork()
        newStatus = fields.pop("status", None)
        if "deadline" in fields:
            newDeadline = toIso(fields["deadline"]) if isinstance(fields["deadline"], datetime.datetime) else fields["deadline"]
            if newDeadline != commission.get("deadline"):
                commission["alertedKeys"] = []
            fields["deadline"] = newDeadline
        # The public price argument still edits the fixed quote. The editor sends
        # basePrice explicitly because its price is already the calculated total.
        commission.setdefault("basePrice", float(commission.get("price") or 0))
        if "price" in fields and "basePrice" not in fields:
            fields["basePrice"] = float(fields["price"] or 0)
        if "extraCosts" in fields:
            fields["extraCosts"] = [dict(cost) for cost in fields["extraCosts"] or []]
        commission.update(fields)
        commission["price"] = logic.workPrice(commission)
        if newStatus:
            logic.setStatus(commission, newStatus, self.clock())
        self._changed()

    def setStatus(self, commissionId, status):
        if self.runningCommissionId == commissionId and status not in logic.ACTIVE_STATUSES:
            self.pauseWork()
        commission = self.find(commissionId)
        if commission:
            logic.setStatus(commission, status, self.clock())
            self._changed()

    def delete(self, commissionId):
        if self.runningCommissionId == commissionId:
            self.pauseWork()
        self.commissions = [commission for commission in self.commissions if commission["id"] != commissionId]
        self.context.removeActive(commissionId)
        self._changed()

    def setArchived(self, commissionId, archived):
        if archived and self.runningCommissionId == commissionId:
            self.pauseWork()
        commission = self.find(commissionId)
        if commission:
            commission["archived"] = archived
            self._changed()

    def recordPayment(self, commissionId, amount, currency=None, method=None):
        self._tickWork()
        commission = self.find(commissionId)
        if commission and amount:
            logic.addPayment(commission, amount, currency, method, self.clock())
            if commission["status"] == "paid" and self.runningCommissionId == commissionId:
                self.pauseWork()
            self._changed()

    def markPaid(self, commissionId, **fields):
        commission = self.find(commissionId)
        if not commission or fields.get("status", commission["status"]) == "cancelled":
            return
        if self.runningCommissionId == commissionId:
            self.pauseWork()
        # A paid legacy commission without receipts already counts as received.
        if commission["status"] == "paid" and not commission.get("payments"):
            return
        if fields:
            fields.pop("status", None)
            self.update(commissionId, **fields)
        balance = max(0.0, float(commission.get("price") or 0) - logic.paidAmount(commission))
        if balance > 0:
            logic.addPayment(commission, balance, date=self.clock())
        logic.setStatus(commission, "paid", self.clock())
        self._changed()

    # work timer: runtime ownership keeps closing an editor independent of tracking.
    def toggleCardWork(self, commissionId, parent=None):
        if self.runningCommissionId == commissionId:
            self.pauseWork()
            return
        commission = self.find(commissionId)
        if (not commission or commission.get("billingMode") != "hourly" or commission.get("archived")
                or commission["status"] not in logic.ACTIVE_STATUSES):
            return
        if float(commission.get("hourlyRate") or 0) <= 0:
            dialog = ThemedDialog(parent, 380)
            dialog.addHeader(tr(TEXT["rate"]), "timer", message=commission["title"])
            rate = QDoubleSpinBox()
            rate.setRange(0, 10_000_000)
            rate.setDecimals(2)
            rate.setSuffix(f" {logic.currencySymbol(commission['currency'])}/h")
            rate.setValue(float(self.setting("defaultHourlyRate") or 0))
            dialog.bodyLayout.addWidget(rate)
            cancel = makeButton(tr(TEXT["cancel"]))
            cancel.clicked.connect(dialog.reject)
            start = makeButton(tr(TEXT["startWork"]), "play", "primary")
            start.setEnabled(rate.value() > 0)
            rate.valueChanged.connect(lambda value: start.setEnabled(value > 0))
            start.clicked.connect(dialog.accept)
            dialog.addButtons([cancel, start])
            rate.setFocus()
            if not dialog.exec() or rate.value() <= 0:
                dialog.deleteLater()
                return
            self.update(commissionId, hourlyRate=rate.value())
            dialog.deleteLater()
        self.startWork(commissionId)

    def startWork(self, commissionId):
        commission = self.find(commissionId)
        if (not commission or commission.get("billingMode") != "hourly" or commission.get("archived")
                or commission["status"] not in logic.ACTIVE_STATUSES or not commission.get("hourlyRate")):
            return
        if self.runningCommissionId == commissionId:
            return
        self.pauseWork()
        self.runningCommissionId = commissionId
        self.lastWorkTick = self.lastWorkSave = self.workClock()
        self.workTimer.start()
        self.workChanged.emit()
        self._changed()

    def _tickWork(self):
        commission = self.find(self.runningCommissionId)
        if commission is None:
            return
        now = self.workClock()
        elapsed = max(0.0, now - self.lastWorkTick)
        self.lastWorkTick = now
        commission["trackedSeconds"] = float(commission.get("trackedSeconds") or 0) + elapsed
        commission["price"] = logic.workPrice(commission)
        if now - self.lastWorkSave >= 15:
            self.save()
            self.lastWorkSave = now
        self.workChanged.emit()

    def pauseWork(self):
        if self.runningCommissionId is None:
            return
        self._tickWork()
        self.runningCommissionId = None
        self.lastWorkTick = None
        self.workTimer.stop()
        self.workChanged.emit()
        self._changed()

    def setWorkSeconds(self, commissionId, seconds):
        commission = self.find(commissionId)
        if commission is None:
            return
        if self.runningCommissionId == commissionId:
            self.pauseWork()
        commission["trackedSeconds"] = max(0.0, float(seconds))
        commission["price"] = logic.workPrice(commission)
        self._changed()
        self.workChanged.emit()

    def visible(self, includeArchived=False):
        return [commission for commission in self.commissions if includeArchived or not commission.get("archived")]

    # stats -------------------------------------------------------------------------
    def stats(self):
        now = self.clock()
        visible = self.visible()
        active = [commission for commission in visible if commission["status"] in logic.ACTIVE_STATUSES]
        dueWeek = [commission for commission in active if logic.dueSoon(commission, now, 24 * 7)]
        overdue = [commission for commission in active if logic.isOverdue(commission, now)]
        rates = self.rates()
        upcoming = sorted([commission for commission in active if logic.deadlineOf(commission)],
                          key=lambda commission: logic.deadlineOf(commission))
        return {"active": len(active), "dueWeek": len(dueWeek), "overdue": len(overdue),
                "outstanding": logic.outstandingTotal(self.commissions, rates),
                "earnedYear": logic.earnedInYear(self.commissions, rates, now.year),
                "nextDeadline": upcoming[0] if upcoming else None, "year": now.year}

    # alerts --------------------------------------------------------------------------
    def check(self):
        now = self.clock()
        changed = False
        if self.setting("deadlineAlerts"):
            for commission in self.commissions:
                deadline = logic.deadlineOf(commission)
                if deadline is None or commission["status"] not in logic.ACTIVE_STATUSES or commission.get("archived"):
                    continue
                alerted = commission.setdefault("alertedKeys", [])
                hours = commission.get("deadlineAlertHours")
                if hours and deadline - datetime.timedelta(hours=hours) <= now < deadline and "soon" not in alerted:
                    alerted.append("soon")
                    changed = True
                    self._alert(commission, tr(TEXT["deadlineSoonTitle"], title=commission["title"]), deadline, now)
                if now >= deadline and "due" not in alerted and now - deadline < datetime.timedelta(days=2):
                    alerted.append("due")
                    changed = True
                    self._alert(commission, tr(TEXT["deadlineNowTitle"], title=commission["title"]), deadline, now)
        if changed:
            self.save()
        self.refreshActive()

    def _alert(self, commission, title, deadline, now):
        commissionId = commission["id"]
        clientText = self.clientName(commission.get("clientId"), commission.get("clientName", ""))
        message = " · ".join(part for part in (clientText, f"{formatWhen(deadline)} ({formatCountdown(deadline, now)})") if part)
        self.context.alert(title, message, "briefcase",
                           [(tr(TEXT["open"]), lambda: self.openEditor(commissionId), "external-link"),
                            (tr(TEXT["markDelivered"]), lambda: self.setStatus(commissionId, "delivered"), "check")],
                           accent=logic.statusInfo(commission["status"])[2], sound="notify" if self.setting("sound") else None)
        self.context.emit("deadline", commissionId=commissionId, title=commission["title"])

    def refreshActive(self):
        now = self.clock()
        for commission in self.commissions:
            urgent = (commission["status"] in logic.ACTIVE_STATUSES and not commission.get("archived")
                      and (logic.isOverdue(commission, now) or logic.dueSoon(commission, now, 24)))
            if urgent:
                deadline = logic.deadlineOf(commission)
                overdue = deadline < now
                self.context.setActive(ActiveItem(
                    commission["id"], commission["title"],
                    f"{formatWhen(deadline)} · {tr(TEXT['overdue']) if overdue else formatCountdown(deadline, now)}",
                    icon="briefcase", progress=logic.progress(commission), accent=theme().danger if overdue else None,
                    actions=[(TEXT["open"], "external-link", lambda commissionId=commission["id"]: self.openEditor(commissionId)),
                             (TEXT["markDelivered"], "check",
                              lambda commissionId=commission["id"]: self.setStatus(commissionId, "delivered"))]))
            else:
                self.context.removeActive(commission["id"])

    # export -------------------------------------------------------------------------
    def exportCsv(self, path, commissionId=None):
        from pchub.plugins.commissions import exports
        self._tickWork()
        clientsById = {client["id"]: client for client in self.clients}
        commissions = [self.find(commissionId)] if commissionId else self.commissions
        commissions = [commission for commission in commissions if commission is not None]
        text = exports.exportCsv(commissions, clientsById, self.rates(), language())
        with open(path, "w", encoding="utf-8-sig", newline="") as fileHandle:
            fileHandle.write(text)
        return len(commissions)

    def chooseExportPath(self, parent=None, commissionId=None):
        name = f"commissione-{commissionId}" if commissionId else f"commissioni-{self.clock().date().isoformat()}"
        path, selected = QFileDialog.getSaveFileName(parent, tr(TEXT["export"]), name, "PDF (*.pdf);;CSV (*.csv)")
        if path and Path(path).suffix.lower() not in (".pdf", ".csv"):
            path += ".csv" if "*.csv" in selected else ".pdf"
            if Path(path).exists() and not confirm(parent, tr(TEXT["replaceExport"]), Path(path).name,
                                                   confirmText=tr(TEXT["replace"])):
                return ""
        return path

    def exportReport(self, path, commissionId=None, parent=None):
        from pchub.plugins.commissions import exports
        try:
            if Path(path).suffix.lower() == ".csv":
                count = self.exportCsv(path, commissionId)
            else:
                self._tickWork()
                commissions = [self.find(commissionId)] if commissionId else self.commissions
                commissions = [commission for commission in commissions if commission is not None]
                exports.exportPdf(path, commissions, {client["id"]: client for client in self.clients}, self.rates(), language())
                count = len(commissions)
        except (OSError, ValueError, RuntimeError) as error:
            showMessage(parent, tr(TEXT["exportError"]), str(error), "circle-alert")
            return False
        self.context.notify(tr(TEXT["export"]), tr(TEXT["exported"], count=count))
        return True

    def openExport(self, commissionId=None, parent=None):
        path = self.chooseExportPath(parent, commissionId)
        if path:
            self.exportReport(path, commissionId, parent)

    # integrations ---------------------------------------------------------------------
    def openEditor(self, commissionId=None, parent=None, presetStatus=None):
        self.context.openPage()
        CommissionEditor(self, self.find(commissionId) if commissionId else None, parent, presetStatus).exec()

    def calendarItems(self, startDate, endDate):
        items = []
        for commission in self.commissions:
            deadline = logic.deadlineOf(commission)
            if deadline is None or commission.get("archived") or commission["status"] == "cancelled":
                continue
            if startDate <= deadline.date() <= endDate:
                clientText = self.clientName(commission.get("clientId"), commission.get("clientName", ""))
                items.append(CalendarItem(commission["id"], f"⏰ {commission['title']}", deadline,
                                          allDay=deadline.time() == datetime.time(), icon="briefcase",
                                          color=logic.statusInfo(commission["status"])[2],
                                          subtitle=" · ".join(part for part in (clientText, statusName(commission["status"])) if part),
                                          done=commission["status"] in ("delivered", "paid"),
                                          onOpen=lambda commissionId=commission["id"]: self.openEditor(commissionId),
                                          kind="deadline"))
        return items

    def createPage(self):
        return CommissionsPage(self)

    def homeWidgets(self):
        return [HomeWidgetSpec("commissions.overview", T("Commissioni", "Commissions"), lambda: CommissionsHomeWidget(self),
                               T("Attive, prossima scadenza, da incassare e incassi dell'anno.",
                                 "Active, next deadline, to collect and yearly earnings."), "briefcase", "wide",
                               ["wide", "large", "small", "full"]),
                HomeWidgetSpec("commissions.deadlines", T("Scadenze commissioni", "Commission deadlines"),
                               lambda: DeadlinesHomeWidget(self), T("Le prossime consegne.", "Upcoming deliveries."),
                               "hourglass", "wide", ["wide", "tall", "large"])]

    def trayEntries(self):
        return [TrayEntry("new", TEXT["new"], lambda: self.openEditor(), icon="briefcase")]


Plugin = CommissionsPlugin


class CommissionEditor(ThemedDialog):
    def __init__(self, plugin, commission=None, parent=None, presetStatus=None):
        super().__init__(parent, 660)
        self.plugin = plugin
        self.commission = commission
        commission = commission or {}
        statusColor = logic.statusInfo(commission.get("status", presetStatus or "todo"))[2]
        self.addHeader(commission.get("title") or tr(TEXT["new"]), "briefcase", statusColor)
        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setFrameShape(QFrame.NoFrame)
        scrollArea.setMaximumHeight(560)
        scrollArea.setMinimumHeight(460)
        bodyHost = QWidget()
        self.form = QVBoxLayout(bodyHost)
        self.form.setContentsMargins(0, 0, 8, 0)
        self.form.setSpacing(10)
        scrollArea.setWidget(bodyHost)
        self.bodyLayout.addWidget(scrollArea)

        self.titleEdit = QLineEdit(commission.get("title", ""))
        self.titleEdit.setPlaceholderText(tr(TEXT["title"]))
        self.form.addWidget(self.titleEdit)

        clientRow = QHBoxLayout()
        clientRow.setSpacing(6)
        self.clientCombo = QComboBox()
        self.clientCombo.setEditable(True)
        self.clientCombo.setInsertPolicy(QComboBox.NoInsert)
        self.clientCombo.lineEdit().setPlaceholderText(tr(TEXT["clientName"]))
        self._fillClients(commission.get("clientId"))
        clientRow.addWidget(self.clientCombo, 1)
        newClientButton = iconButton("plus", tr(TEXT["newClient"]), "text", 16)
        newClientButton.clicked.connect(self._newClient)
        clientRow.addWidget(newClientButton)
        self.platformCombo = QComboBox()
        for platform in logic.PLATFORMS:
            self.platformCombo.addItem(platform, platform)
        self.platformCombo.setCurrentIndex(max(0, self.platformCombo.findData(
            commission.get("platform") or plugin.setting("defaultPlatform") or "Discord")))
        clientRow.addWidget(self.platformCombo)
        self._row(tr(TEXT["client"]), clientRow)
        self.temporaryClientCheck = QCheckBox(tr(TEXT["temporaryClient"]))
        self.temporaryClientCheck.setChecked(bool(commission.get("temporaryClient")))
        self.temporaryClientCheck.setToolTip(tr(TEXT["temporaryHint"]))
        temporaryRow = QHBoxLayout()
        temporaryRow.addSpacing(102)
        temporaryRow.addWidget(self.temporaryClientCheck)
        temporaryRow.addStretch(1)
        self.form.addLayout(temporaryRow)

        self.statusCombo = QComboBox()
        for statusId, label, color in logic.STATUSES:
            self.statusCombo.addItem(tr(label), statusId)
        self.statusCombo.setCurrentIndex(max(0, self.statusCombo.findData(commission.get("status", presetStatus or "todo"))))
        self._row(tr(TEXT["status"]), self.statusCombo)

        self.billingCombo = QComboBox()
        self.billingCombo.addItem(tr(TEXT["fixed"]), "fixed")
        self.billingCombo.addItem(tr(TEXT["hourly"]), "hourly")
        self.billingCombo.setCurrentIndex(max(0, self.billingCombo.findData(commission.get("billingMode", "fixed"))))
        self._row(tr(TEXT["billing"]), self.billingCombo)

        priceRow = QHBoxLayout()
        priceRow.setSpacing(6)
        self.priceSpin = QDoubleSpinBox()
        self.priceSpin.setRange(0, 10_000_000)
        self.priceSpin.setDecimals(2)
        self.fixedBasePrice = float(commission.get("basePrice", commission.get("price")) or 0)
        self.priceSpin.setValue(self.fixedBasePrice)
        self.priceSpin.setMinimumWidth(120)
        priceRow.addWidget(self.priceSpin, 1)
        self.currencyCombo = QComboBox()
        for currency, symbol in logic.CURRENCIES:
            self.currencyCombo.addItem(f"{currency} ({symbol})", currency)
        self.currencyCombo.setCurrentIndex(max(0, self.currencyCombo.findData(
            commission.get("currency") or plugin.setting("defaultCurrency") or "EUR")))
        self.currencyCombo.currentIndexChanged.connect(self._onCurrency)
        priceRow.addWidget(self.currencyCombo)
        self.methodCombo = QComboBox()
        for method in logic.PAYMENT_METHODS:
            self.methodCombo.addItem(method, method)
        self.methodCombo.setCurrentIndex(max(0, self.methodCombo.findData(
            commission.get("paymentMethod") or plugin.setting("defaultMethod") or "Stripe")))
        priceRow.addWidget(self.methodCombo)
        self._row(tr(TEXT["baseInput"]), priceRow)
        self._buildWorkCard(commission)
        self._buildExtraCostsCard(commission)

        deadlineRow = QHBoxLayout()
        deadlineRow.setSpacing(6)
        self.deadlineField = DateTimeField(parseDateTime(commission.get("deadline")), allowEmpty=True)
        deadlineRow.addWidget(self.deadlineField, 1)
        self.alertCombo = QComboBox()
        for hours in ALERT_OPTIONS:
            self.alertCombo.addItem(alertLabel(hours), hours)
        defaultAlert = plugin.setting("defaultAlert")
        currentAlert = commission.get("deadlineAlertHours", int(defaultAlert) if defaultAlert not in (None, "none") else None) \
            if commission else (int(defaultAlert) if defaultAlert not in (None, "none") else None)
        self.alertCombo.setCurrentIndex(max(0, self.alertCombo.findData(currentAlert)))
        deadlineRow.addWidget(self.alertCombo)
        self._row(tr(TEXT["deadline"]), deadlineRow)

        self.form.addWidget(makeLabel(tr(TEXT["tasks"]).upper(), "section"))
        self.tasks = [dict(task) for task in commission.get("tasks", [])]
        self.tasksLayout = QVBoxLayout()
        self.tasksLayout.setSpacing(2)
        self.form.addLayout(self.tasksLayout)
        self.taskEdit = QLineEdit()
        self.taskEdit.setPlaceholderText(tr(TEXT["addTask"]))
        self.taskEdit.returnPressed.connect(self._addTask)
        self.form.addWidget(self.taskEdit)
        self._refreshTasks()

        paymentsHeader = QHBoxLayout()
        paymentsHeader.addWidget(makeLabel(tr(TEXT["payments"]).upper(), "section"), 1)
        self.paidButton = makeButton(tr(TEXT["markPaid"]), "check", "primary")
        self.paidButton.clicked.connect(self._markPaid)
        paymentsHeader.addWidget(self.paidButton)
        self.form.addLayout(paymentsHeader)
        self.payments = [dict(payment) for payment in commission.get("payments", [])]
        self.paymentsLayout = QVBoxLayout()
        self.paymentsLayout.setSpacing(2)
        self.form.addLayout(self.paymentsLayout)
        self.manualPaymentButton = makeButton(tr(TEXT["manualPayment"]), "plus", "ghost", checkable=True)
        self.manualPaymentHost = QWidget()
        paymentRow = QHBoxLayout(self.manualPaymentHost)
        paymentRow.setContentsMargins(0, 0, 0, 0)
        paymentRow.setSpacing(6)
        self.paymentSpin = QDoubleSpinBox()
        self.paymentSpin.setRange(0, 10_000_000)
        self.paymentSpin.setDecimals(2)
        self.paymentAmountEdited = False
        self.paymentSpin.valueChanged.connect(self._markPaymentEdited)
        paymentRow.addWidget(self.paymentSpin, 1)
        addPaymentButton = makeButton(tr(TEXT["addPayment"]), "plus")
        addPaymentButton.clicked.connect(self._addPayment)
        paymentRow.addWidget(addPaymentButton)
        self.manualPaymentButton.toggled.connect(self.manualPaymentHost.setVisible)
        self.form.addWidget(self.manualPaymentButton)
        self.form.addWidget(self.manualPaymentHost)
        self.manualPaymentHost.hide()
        self._refreshPayments()
        self.priceSpin.valueChanged.connect(self._fixedPriceChanged)

        self._onCurrency()
        self.billingCombo.currentIndexChanged.connect(self._billingChanged)
        self.hourlyRateSpin.valueChanged.connect(self._refreshWork)
        self.statusCombo.currentIndexChanged.connect(self._refreshWork)
        plugin.workChanged.connect(self._refreshWork)
        self._billingChanged()
        self.notesEdit = QPlainTextEdit(commission.get("notes", ""))
        self.notesEdit.setPlaceholderText(tr(TEXT["notes"]))
        self.notesEdit.setFixedHeight(90)
        self.form.addWidget(self.notesEdit)
        self.form.addStretch(1)

        buttons = []
        exportButton = iconButton("download", tr(TEXT["export"]))
        exportButton.clicked.connect(self._exportCommission)
        buttons.append(exportButton)
        if self.commission:
            deleteButton = makeButton(tr(TEXT["delete"]), "trash-2", "danger")
            deleteButton.clicked.connect(self._delete)
            buttons.append(deleteButton)
            archiveButton = makeButton(tr(TEXT["unarchive"] if self.commission.get("archived") else TEXT["archive"]), "archive", "ghost")
            archiveButton.clicked.connect(self._toggleArchive)
            buttons.append(archiveButton)
        cancelButton = makeButton(tr(TEXT["cancel"]))
        cancelButton.clicked.connect(self.reject)
        saveButton = makeButton(tr(TEXT["save"]), "check", "primary")
        saveButton.clicked.connect(self._save)
        self.addButtons(buttons + [cancelButton, saveButton])

    def _buildWorkCard(self, commission):
        self.workCard = Card(level=1, padding=14, hoverable=False)
        layout = QVBoxLayout(self.workCard)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        heading.addWidget(IconWidget("timer", "accent", 18))
        heading.addWidget(makeLabel(tr(TEXT["work"]), "subtitle"), 1)
        self.workStateLabel = makeLabel("", "chip")
        heading.addWidget(self.workStateLabel)
        layout.addLayout(heading)
        rateRow = QHBoxLayout()
        rateRow.addWidget(makeLabel(tr(TEXT["rate"]), "muted"), 1)
        self.hourlyRateSpin = QDoubleSpinBox()
        self.hourlyRateSpin.setRange(0, 10_000_000)
        self.hourlyRateSpin.setDecimals(2)
        self.hourlyRateSpin.setValue(float((commission.get("hourlyRate") or 0) if commission
                                           else (self.plugin.setting("defaultHourlyRate") or 0)))
        self.hourlyRateSpin.setMinimumWidth(160)
        rateRow.addWidget(self.hourlyRateSpin)
        layout.addLayout(rateRow)
        metrics = QHBoxLayout()
        for key, attribute in (("worked", "workTimeLabel"), ("accrued", "workEarnedLabel")):
            column = QVBoxLayout()
            column.setSpacing(2)
            column.addWidget(makeLabel(tr(TEXT[key]), "faint"))
            label = makeLabel("", "title")
            setattr(self, attribute, label)
            column.addWidget(label)
            metrics.addLayout(column, 1)
        layout.addLayout(metrics)
        controls = QHBoxLayout()
        self.workButton = makeButton("", "play", "primary")
        self.workButton.clicked.connect(self._toggleWork)
        controls.addWidget(self.workButton)
        self.editWorkButton = makeButton(tr(TEXT["editTime"]), "pencil", "ghost")
        self.editWorkButton.clicked.connect(self._editWorkTime)
        controls.addWidget(self.editWorkButton)
        self.resetWorkButton = iconButton("rotate-ccw", tr(TEXT["resetWork"]))
        self.resetWorkButton.clicked.connect(self._resetWork)
        controls.addWidget(self.resetWorkButton)
        controls.addStretch(1)
        layout.addLayout(controls)
        layout.addWidget(makeLabel(tr(TEXT["rateHint"]), "faint", True))
        layout.addWidget(makeLabel(tr(TEXT["trackingHint"]), "faint", True))
        self.form.addWidget(self.workCard)

    def _billingChanged(self, *args):
        hourly = self.billingCombo.currentData() == "hourly"
        self.workCard.setVisible(hourly)
        self.priceSpin.setEnabled(not hourly)
        if not hourly:
            self.priceSpin.setValue(self.fixedBasePrice)
        self._refreshWork()

    def _editorBasePrice(self):
        if self.billingCombo.currentData() == "hourly":
            return float((self.commission or {}).get("trackedSeconds") or 0) * self.hourlyRateSpin.value() / 3600
        return self.priceSpin.value()

    def _editorPrice(self):
        return self._editorBasePrice() + sum(float(cost.get("amount") or 0) for cost in self.extraCosts)

    def _fixedPriceChanged(self, *args):
        if self.billingCombo.currentData() != "hourly":
            self.fixedBasePrice = self.priceSpin.value()
        self._refreshCostSummary()

    def _refreshWork(self, *args):
        commission = self.commission or {}
        seconds = float(commission.get("trackedSeconds") or 0)
        running = bool(self.commission and self.plugin.runningCommissionId == commission["id"])
        self.workTimeLabel.setText(logic.formatWorkTime(seconds))
        self.workEarnedLabel.setText(self.plugin.money(seconds * self.hourlyRateSpin.value() / 3600, self._currency()))
        self.workStateLabel.setText(tr(TEXT["runningWork" if running else "pausedWork"]))
        setRole(self.workStateLabel, "chipSuccess" if running else "chip")
        self.workButton.setText(tr(TEXT["pauseWork" if running else "resumeWork" if seconds else "startWork"]))
        setThemedIcon(self.workButton, "pause" if running else "play", "accentText", 16)
        allowed = not commission.get("archived") and self.statusCombo.currentData() in logic.ACTIVE_STATUSES
        self.workButton.setEnabled(running or (allowed and self.hourlyRateSpin.value() > 0))
        self.resetWorkButton.setEnabled(seconds > 0 or running)
        self.hourlyRateSpin.setSuffix(f" {logic.currencySymbol(self._currency())}/h")
        if self.billingCombo.currentData() == "hourly":
            self.priceSpin.setValue(self._editorBasePrice())
        self._refreshCostSummary()

    def _buildExtraCostsCard(self, commission):
        card = Card(level=1, padding=14, hoverable=False)
        layout = QVBoxLayout(card)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(makeLabel(tr(TEXT["extraCosts"]), "subtitle"), 1)
        self.addExtraCostButton = makeButton(tr(TEXT["addExtraCost"]), "plus", "ghost")
        self.addExtraCostButton.clicked.connect(self._addExtraCost)
        header.addWidget(self.addExtraCostButton)
        layout.addLayout(header)
        self.extraCosts = [dict(cost) for cost in commission.get("extraCosts") or []]
        self.extraCostsLayout = QVBoxLayout()
        self.extraCostsLayout.setSpacing(6)
        layout.addLayout(self.extraCostsLayout)
        layout.addWidget(divider())
        for key, attribute in (("baseAmount", "costBaseLabel"), ("extraCosts", "costExtrasLabel"), ("total", "costTotalLabel")):
            row = QHBoxLayout()
            row.addWidget(makeLabel(tr(TEXT[key]), "muted"), 1)
            label = makeLabel("", "accent" if key == "total" else "text")
            setattr(self, attribute, label)
            row.addWidget(label)
            layout.addLayout(row)
        self.form.addWidget(card)
        self._refreshExtraCosts()

    def _refreshExtraCosts(self):
        clearLayout(self.extraCostsLayout)
        self.extraCostFields = []
        for index, cost in enumerate(self.extraCosts):
            row = QHBoxLayout()
            row.setSpacing(6)
            description = QLineEdit(cost.get("description") or "")
            description.setPlaceholderText(tr(TEXT["costDescription"]))
            description.setMinimumWidth(0)
            description.textChanged.connect(lambda text, entry=cost: entry.update(description=text))
            row.addWidget(description, 1)
            amount = QDoubleSpinBox()
            amount.setRange(0, 10_000_000)
            amount.setDecimals(0 if self._currency() == "ROBUX" else 2)
            amount.setValue(float(cost.get("amount") or 0))
            amount.setSuffix(f" {logic.currencySymbol(self._currency())}")
            amount.setFixedWidth(140)
            amount.valueChanged.connect(lambda value, entry=cost: self._extraCostChanged(entry, value))
            row.addWidget(amount)
            remove = iconButton("x", tr(TEXT["delete"]), "faint", 13)
            remove.clicked.connect(lambda checked=False, costIndex=index: self._removeExtraCost(costIndex))
            row.addWidget(remove)
            self.extraCostsLayout.addLayout(row)
            self.extraCostFields.append((description, amount))
        self._refreshCostSummary()

    def _extraCostChanged(self, cost, value):
        cost["amount"] = value
        self._refreshCostSummary()

    def _addExtraCost(self):
        self.extraCosts.append({"description": "", "amount": 0.0})
        self._refreshExtraCosts()
        self.extraCostFields[-1][0].setFocus()

    def _removeExtraCost(self, index):
        if 0 <= index < len(self.extraCosts):
            del self.extraCosts[index]
            self._refreshExtraCosts()

    def _refreshCostSummary(self):
        currency = self._currency()
        self.costBaseLabel.setText(self.plugin.money(self._editorBasePrice(), currency))
        self.costExtrasLabel.setText(self.plugin.money(sum(float(cost.get("amount") or 0) for cost in self.extraCosts), currency))
        self.costTotalLabel.setText(self.plugin.money(self._editorPrice(), currency))
        self._refreshPaymentSummary()

    def _storeWorkFields(self):
        values = self._values()
        if not values["title"]:
            self.titleEdit.setFocus()
            return False
        if self.commission:
            self.plugin.update(self.commission["id"], **values)
        else:
            title = values.pop("title")
            self.commission = self.plugin.add(title, **values)
        return True

    def _toggleWork(self):
        wasRunning = bool(self.commission and self.plugin.runningCommissionId == self.commission["id"])
        if not self._storeWorkFields():
            return
        if wasRunning:
            self.plugin.pauseWork()
        else:
            self.plugin.startWork(self.commission["id"])
        self._refreshWork()

    def _resetWork(self):
        if confirm(self, tr(TEXT["resetTitle"]), tr(TEXT["resetMessage"]), danger=True,
                   confirmText=tr(TEXT["resetWork"])) and self._storeWorkFields():
            self.plugin.setWorkSeconds(self.commission["id"], 0)

    def _editWorkTime(self):
        dialog = ThemedDialog(self, 400)
        dialog.addHeader(tr(TEXT["editTime"]), "timer")
        seconds = int((self.commission or {}).get("trackedSeconds") or 0)
        row = QHBoxLayout()
        fields = []
        for key, maximum, value in (("hours", 99999, seconds // 3600),
                                     ("minutes", 59, seconds % 3600 // 60), ("seconds", 59, seconds % 60)):
            column = QVBoxLayout()
            column.addWidget(makeLabel(tr(TEXT[key]), "muted"))
            spin = QSpinBox()
            spin.setRange(0, maximum)
            spin.setValue(value)
            fields.append(spin)
            column.addWidget(spin)
            row.addLayout(column)
        dialog.bodyLayout.addLayout(row)
        cancel = makeButton(tr(TEXT["cancel"]))
        cancel.clicked.connect(dialog.reject)
        save = makeButton(tr(TEXT["save"]), "check", "primary")
        save.clicked.connect(dialog.accept)
        dialog.addButtons([cancel, save])
        if dialog.exec() and self._storeWorkFields():
            self.plugin.setWorkSeconds(self.commission["id"],
                                       fields[0].value() * 3600 + fields[1].value() * 60 + fields[2].value())

    def _row(self, label, content):
        rowLayout = QHBoxLayout()
        rowLayout.setSpacing(10)
        labelWidget = makeLabel(label, "muted")
        labelWidget.setFixedWidth(92)
        rowLayout.addWidget(labelWidget)
        if isinstance(content, QWidget):
            rowLayout.addWidget(content, 1)
        else:
            rowLayout.addLayout(content, 1)
        self.form.addLayout(rowLayout)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.commission:
            self.titleEdit.setFocus()

    def _fillClients(self, selectedId):
        self.clientCombo.clear()
        self.clientCombo.addItem("", None)
        for client in sorted(self.plugin.clients, key=lambda client: client["name"].lower()):
            self.clientCombo.addItem(client["name"], client["id"])
        self.clientCombo.setCurrentIndex(max(0, self.clientCombo.findData(selectedId)))
        if not selectedId and self.commission:
            self.clientCombo.setEditText(self.commission.get("clientName", ""))

    def _newClient(self):
        accepted, name = askText(self, tr(TEXT["newClient"]), tr(TEXT["clientName"]))
        if accepted and name:
            self.clientCombo.setEditText(name.strip())

    def _currency(self):
        return self.currencyCombo.currentData()

    def _onCurrency(self, index=None):
        decimals = 0 if self._currency() == "ROBUX" else 2
        self.priceSpin.setDecimals(decimals)
        self.paymentSpin.setDecimals(decimals)
        for description, amount in self.extraCostFields:
            amount.setDecimals(decimals)
            amount.setSuffix(f" {logic.currencySymbol(self._currency())}")
        self._refreshPayments()
        self._refreshWork()

    def _refreshTasks(self):
        clearLayout(self.tasksLayout)
        for index, task in enumerate(self.tasks):
            rowLayout = QHBoxLayout()
            rowLayout.setSpacing(6)
            checkBox = QCheckBox(task["text"])
            checkBox.setChecked(bool(task.get("done")))
            checkBox.toggled.connect(lambda checked, taskIndex=index: self.tasks[taskIndex].update(done=checked))
            rowLayout.addWidget(checkBox, 1)
            removeButton = iconButton("x", None, "faint", 13)
            removeButton.clicked.connect(lambda checked=False, taskIndex=index: self._removeTask(taskIndex))
            rowLayout.addWidget(removeButton)
            self.tasksLayout.addLayout(rowLayout)

    def _addTask(self):
        text = self.taskEdit.text().strip()
        if text:
            self.tasks.append({"text": text, "done": False})
            self.taskEdit.clear()
            self._refreshTasks()

    def _removeTask(self, index):
        if 0 <= index < len(self.tasks):
            del self.tasks[index]
            self._refreshTasks()

    def _refreshPayments(self):
        clearLayout(self.paymentsLayout)
        currency = self._currency()
        for payment in self.payments:
            rowLayout = QHBoxLayout()
            rowLayout.setSpacing(6)
            rowLayout.addWidget(IconWidget("check", "success", 14))
            when = parseDateTime(payment.get("date"))
            rowLayout.addWidget(makeLabel(when.strftime("%d/%m/%Y") if when else "", "faint"))
            rowLayout.addWidget(makeLabel(self.plugin.money(payment["amount"], payment.get("currency", currency))), 1)
            rowLayout.addWidget(makeLabel(payment.get("method") or "", "chip"))
            removeButton = iconButton("x", None, "faint", 13)
            removeButton.clicked.connect(lambda checked=False, paymentId=payment.get("id"): self._removePayment(paymentId))
            rowLayout.addWidget(removeButton)
            self.paymentsLayout.addLayout(rowLayout)
        self.paymentSummaryLabel = makeLabel("", "faint")
        self.paymentsLayout.addWidget(self.paymentSummaryLabel)
        self.paymentAmountEdited = False
        self._refreshPaymentSummary()

    def _markPaymentEdited(self, *args):
        self.paymentAmountEdited = True

    def _refreshPaymentSummary(self):
        if not hasattr(self, "paymentSummaryLabel"):
            return
        currency = self._currency()
        paid = sum(float(payment["amount"]) for payment in self.payments if payment.get("currency", currency) == currency)
        self.paymentSummaryLabel.setText(tr(TEXT["paidOf"], paid=self.plugin.money(paid, currency),
                                           price=self.plugin.money(self._editorPrice(), currency)))
        if not self.paymentAmountEdited:
            self.paymentSpin.blockSignals(True)
            self.paymentSpin.setValue(max(0.0, self._editorPrice() - paid))
            self.paymentSpin.blockSignals(False)
        stored = self.commission or {}
        legacyPaid = stored.get("status") == "paid" and not stored.get("payments")
        complete = stored.get("status") == "paid" and self._editorPrice() - paid <= 0.0001
        self.paidButton.setEnabled(not legacyPaid and not complete and self.statusCombo.currentData() != "cancelled")

    def _markPaid(self):
        values = self._values()
        if not values["title"]:
            self.titleEdit.setFocus()
            return
        if self.commission:
            self.plugin.markPaid(self.commission["id"], **values)
        else:
            title = values.pop("title")
            if values["status"] == "paid":
                values["status"] = "todo"
            self.commission = self.plugin.add(title, **values)
            self.plugin.markPaid(self.commission["id"])
        self.accept()

    def _exportCommission(self):
        if not self.titleEdit.text().strip():
            self.titleEdit.setFocus()
            return
        path = self.plugin.chooseExportPath(self, (self.commission or {}).get("id"))
        if path and self._storeWorkFields():
            self.plugin.exportReport(path, self.commission["id"], self)

    def _addPayment(self):
        amount = self.paymentSpin.value()
        if amount <= 0:
            return
        self.payments.append({"id": datetime.datetime.now().strftime("%H%M%S%f"), "amount": amount,
                              "currency": self._currency(), "method": self.methodCombo.currentData(),
                              "date": toIso(datetime.datetime.now()), "note": ""})
        price = self._editorPrice()
        paid = sum(float(payment["amount"]) for payment in self.payments if payment.get("currency") == self._currency())
        if price and paid >= price and self.statusCombo.currentData() not in ("cancelled",):
            self.statusCombo.setCurrentIndex(self.statusCombo.findData("paid"))
        self._refreshPayments()

    def _removePayment(self, paymentId):
        self.payments = [payment for payment in self.payments if payment.get("id") != paymentId]
        paid = sum(float(payment["amount"]) for payment in self.payments if payment.get("currency", self._currency()) == self._currency())
        if self.statusCombo.currentData() == "paid" and self._editorPrice() - paid > 0.0001:
            self.statusCombo.setCurrentIndex(self.statusCombo.findData("delivered"))
        self._refreshPayments()

    def _values(self):
        clientId = self.clientCombo.currentData() if self.clientCombo.currentText() == self.clientCombo.itemText(
            self.clientCombo.currentIndex()) else None
        return dict(title=self.titleEdit.text().strip(), clientId=clientId,
                    clientName=self.clientCombo.currentText().strip(), temporaryClient=self.temporaryClientCheck.isChecked(),
                    platform=self.platformCombo.currentData(), status=self.statusCombo.currentData(),
                    price=self._editorPrice(), basePrice=self.fixedBasePrice,
                    extraCosts=[dict(cost) for cost in self.extraCosts], billingMode=self.billingCombo.currentData(),
                    hourlyRate=self.hourlyRateSpin.value(), currency=self._currency(), paymentMethod=self.methodCombo.currentData(),
                    deadline=self.deadlineField.value(), deadlineAlertHours=self.alertCombo.currentData(),
                    tasks=[dict(task) for task in self.tasks], payments=[dict(payment) for payment in self.payments],
                    notes=self.notesEdit.toPlainText().strip())

    def _save(self):
        values = self._values()
        if not values["title"]:
            self.titleEdit.setFocus()
            return
        if self.commission:
            self.plugin.update(self.commission["id"], **values)
        else:
            title = values.pop("title")
            status = values.pop("status")
            deadline = values.pop("deadline")
            commission = self.plugin.add(title, status=status, deadline=deadline, **values)
            if status in ("delivered", "paid"):
                logic.setStatus(commission, status)
        self.accept()

    def _delete(self):
        if confirm(self, tr(TEXT["deleteTitle"]), tr(TEXT["deleteMessage"]), [self.commission["title"]], danger=True,
                   confirmText=tr(TEXT["delete"])):
            self.plugin.delete(self.commission["id"])
            self.accept()

    def _toggleArchive(self):
        self.plugin.setArchived(self.commission["id"], not self.commission.get("archived"))
        self.accept()


class CommissionCard(Card):
    def __init__(self, plugin, commission, parent=None, compact=False):
        super().__init__(parent, level=1, padding=12, hoverable=True, clickable=True, radius=14)
        self.plugin = plugin
        self.commissionId = commission["id"]
        self.commission = commission
        self.dragStart = None
        now = datetime.datetime.now()
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        titleLabel = makeLabel(commission["title"], "subtitle" if not compact else None, True)
        layout.addWidget(titleLabel)
        clientText = plugin.clientName(commission.get("clientId"), commission.get("clientName", ""))
        infoParts = [part for part in (clientText, commission.get("platform")) if part]
        if infoParts:
            layout.addWidget(makeLabel(" · ".join(infoParts), "faint", True))
        chipsRow = QHBoxLayout()
        chipsRow.setSpacing(5)
        self.priceLabel = makeLabel("", "chipAccent", True)
        chipsRow.addWidget(self.priceLabel)
        plugin.workChanged.connect(self._refreshPrice)
        self._refreshPrice()
        outstanding = logic.outstanding(commission)
        if commission.get("price") and commission["status"] not in ("lead", "cancelled"):
            if outstanding <= 0.0001:
                chipsRow.addWidget(makeLabel(tr(TEXT["paidLabel"]), "chipSuccess"))
            elif commission["status"] in ("delivered", "review"):
                chipsRow.addWidget(makeLabel(tr(TEXT["unpaid"]), "chipWarning"))
        chipsRow.addStretch(1)
        layout.addLayout(chipsRow)
        if commission.get("billingMode") == "hourly":
            workRow = QHBoxLayout()
            workRow.setSpacing(6)
            self.workChip = makeLabel("", "subtitle")
            workRow.addWidget(self.workChip, 1)
            self.workRateLabel = makeLabel("", "faint", True)
            workRow.addWidget(self.workRateLabel)
            layout.addLayout(workRow)
            self.workButton = makeButton("", "play", "primary")
            self.workButton.clicked.connect(self._toggleCardWork)
            layout.addWidget(self.workButton)
            plugin.workChanged.connect(self._refreshWorkChip)
            self._refreshWorkChip()
        deadline = logic.deadlineOf(commission)
        if deadline:
            overdue = logic.isOverdue(commission, now)
            deadlineRow = QHBoxLayout()
            deadlineRow.setSpacing(5)
            deadlineRow.addWidget(IconWidget("hourglass", "danger" if overdue else "muted", 13))
            deadlineRow.addWidget(makeLabel(f"{formatWhen(deadline)} · {formatCountdown(deadline, now)}",
                                            "error" if overdue else "faint", True), 1)
            layout.addLayout(deadlineRow)
        if commission.get("tasks") or commission["status"] in logic.ACTIVE_STATUSES:
            progressBar = MeterBar(logic.statusInfo(commission["status"])[2], 5)
            progressBar.setValue(logic.progress(commission))
            layout.addWidget(progressBar)
        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.paidButton = makeButton(tr(TEXT["markPaid"]), variant="ghost")
        self.paidButton.setEnabled(commission["status"] != "cancelled" and
                                   (commission["status"] != "paid" or logic.outstanding(commission) > 0.0001))
        self.paidButton.clicked.connect(lambda: plugin.markPaid(self.commissionId))
        actions.addWidget(self.paidButton)
        exportButton = makeButton(tr(TEXT["export"]), variant="ghost")
        exportButton.clicked.connect(lambda: plugin.openExport(self.commissionId, self))
        actions.addWidget(exportButton)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.clicked.connect(lambda: plugin.openEditor(self.commissionId, self))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _refreshPrice(self):
        commission = self.commission
        money = self.plugin.money(commission.get("price", 0), commission["currency"])
        self.priceLabel.setText(f"{tr(TEXT['accruedShort'])}: {money}" if commission.get("billingMode") == "hourly" else money)
        self.priceLabel.setVisible(bool(commission.get("price")) or commission.get("billingMode") == "hourly")

    def _refreshWorkChip(self):
        commission = self.plugin.find(self.commissionId)
        if commission:
            running = self.plugin.runningCommissionId == self.commissionId
            seconds = float(commission.get("trackedSeconds") or 0)
            self.workChip.setText(logic.formatWorkTime(seconds))
            self.workChip.setToolTip(tr(TEXT["runningWork" if running else "pausedWork"]))
            self.workRateLabel.setText(f"{self.plugin.money(commission.get('hourlyRate', 0), commission['currency'])}/h")
            self.workButton.setText(tr(TEXT["pauseWork" if running else "resumeWork" if seconds else "startWork"]))
            setThemedIcon(self.workButton, "pause" if running else "play", "accentText", 16)
            self.workButton.setEnabled(running or (not commission.get("archived")
                                                  and commission["status"] in logic.ACTIVE_STATUSES))

    def _toggleCardWork(self):
        self.plugin.toggleCardWork(self.commissionId, self)

    def _menu(self, point):
        menu = QMenu(self)
        paid = menu.addAction(tr(TEXT["markPaid"]), lambda: self.plugin.markPaid(self.commissionId))
        paid.setEnabled(self.paidButton.isEnabled())
        menu.addAction(tr(TEXT["export"]), lambda: self.plugin.openExport(self.commissionId, self))
        menu.addSeparator()
        for statusId, label, color in logic.STATUSES:
            action = menu.addAction(f"{tr(TEXT['quickStatus'])}: {tr(label)}")
            action.triggered.connect(lambda checked=False, value=statusId: self.plugin.setStatus(self.commissionId, value))
        menu.exec(self.mapToGlobal(point))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragStart = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragStart is not None and event.buttons() & Qt.LeftButton and \
                (event.position().toPoint() - self.dragStart).manhattanLength() > 10:
            self.pressedState = False
            drag = QDrag(self)
            mimeData = QMimeData()
            mimeData.setData(MIME_TYPE, self.commissionId.encode("utf-8"))
            drag.setMimeData(mimeData)
            snapshot = self.grab()
            faded = QPixmap(snapshot.size())
            faded.setDevicePixelRatio(snapshot.devicePixelRatio())
            faded.fill(Qt.transparent)
            painter = QPainter(faded)
            painter.setOpacity(0.8)
            painter.drawPixmap(0, 0, snapshot)
            painter.end()
            drag.setPixmap(faded)
            drag.setHotSpot(self.dragStart)
            self.dragStart = None
            drag.exec(Qt.MoveAction)
            return
        super().mouseMoveEvent(event)


class BoardColumn(Card):
    def __init__(self, plugin, statusId, commissions, parent=None):
        super().__init__(parent, padding=10, hoverable=False, radius=18)
        self.plugin = plugin
        self.statusId = statusId
        self.setAcceptDrops(True)
        self.setFixedWidth(272)
        statusId, label, color = logic.statusInfo(statusId)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        headerRow = QHBoxLayout()
        headerRow.setSpacing(6)
        dot = QWidget()
        dot.setFixedSize(9, 9)
        dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        headerRow.addWidget(dot)
        headerRow.addWidget(makeLabel(tr(label), "subtitle"))
        headerRow.addWidget(makeLabel(str(len(commissions)), "chip"))
        headerRow.addStretch(1)
        addButton = iconButton("plus", tr(TEXT["new"]), "muted", 15)
        addButton.clicked.connect(lambda: plugin.openEditor(None, self, statusId))
        headerRow.addWidget(addButton)
        layout.addLayout(headerRow)
        self.columnCommissions = commissions
        self.totalLabel = makeLabel("", "faint")
        layout.addWidget(self.totalLabel)
        plugin.workChanged.connect(self._refreshTotal)
        self._refreshTotal()
        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setFrameShape(QFrame.NoFrame)
        cardsHost = QWidget()
        cardsLayout = QVBoxLayout(cardsHost)
        cardsLayout.setContentsMargins(0, 0, 4, 0)
        cardsLayout.setSpacing(6)
        for commission in commissions:
            cardsLayout.addWidget(CommissionCard(plugin, commission))
        if not commissions:
            hint = makeLabel(tr(TEXT["dropHere"]), "faint")
            hint.setAlignment(Qt.AlignCenter)
            hint.setMinimumHeight(60)
            cardsLayout.addWidget(hint)
        cardsLayout.addStretch(1)
        scrollArea.setWidget(cardsHost)
        layout.addWidget(scrollArea, 1)

    def _refreshTotal(self):
        total = sum(logic.toEuro(commission.get("price"), commission["currency"], self.plugin.rates())
                    for commission in self.columnCommissions)
        self.totalLabel.setText(self.plugin.euro(total))
        self.totalLabel.setVisible(bool(total))

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE):
            self.setSelected(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setSelected(False)

    def dropEvent(self, event):
        self.setSelected(False)
        commissionId = bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8")
        event.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.plugin.setStatus(commissionId, self.statusId))


class StatTile(Card):
    def __init__(self, iconName, title, parent=None):
        super().__init__(parent, padding=14)
        layout = QHBoxLayout(self)
        layout.setSpacing(12)
        self.tile = IconTile(iconName, 40)
        layout.addWidget(self.tile)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(0)
        self.titleLabel = makeLabel(title, "faint")
        self.valueLabel = makeLabel("", "metricSmall")
        self.subLabel = makeLabel("", "faint")
        textLayout.addWidget(self.titleLabel)
        textLayout.addWidget(self.valueLabel)
        textLayout.addWidget(self.subLabel)
        layout.addLayout(textLayout, 1)
        self.meter = MeterBar(None, 6)
        self.meter.hide()
        textLayout.addWidget(self.meter)


class CommissionsPage(QWidget):
    noScroll = True

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.view = plugin.context.getData("view", "board")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 14)
        layout.setSpacing(6)
        statsRow = QHBoxLayout()
        statsRow.setSpacing(4)
        self.activeTile = StatTile("briefcase", tr(TEXT["active"]))
        self.dueTile = StatTile("hourglass", tr(TEXT["dueWeek"]))
        self.collectTile = StatTile("history", tr(TEXT["toCollect"]))
        self.earnedTile = StatTile("gem", "")
        for tile in (self.activeTile, self.dueTile, self.collectTile, self.earnedTile):
            statsRow.addWidget(tile, 1)
        layout.addLayout(statsRow)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.searchEdit = QLineEdit()
        self.searchEdit.setPlaceholderText(tr(TEXT["search"]))
        self.searchEdit.textChanged.connect(self.refreshBody)
        toolbar.addWidget(self.searchEdit, 2)
        self.clientFilter = QComboBox()
        self.clientFilter.currentIndexChanged.connect(self.refreshBody)
        toolbar.addWidget(self.clientFilter, 1)
        self.boardChip = makeButton(tr(TEXT["board"]), "layout-grid", "chip", checkable=True)
        self.listChip = makeButton(tr(TEXT["list"]), "list-todo", "chip", checkable=True)
        self.boardChip.clicked.connect(lambda: self.setView("board"))
        self.listChip.clicked.connect(lambda: self.setView("list"))
        toolbar.addWidget(self.boardChip)
        toolbar.addWidget(self.listChip)
        self.archivedCheck = QCheckBox(tr(TEXT["archived"]))
        self.archivedCheck.toggled.connect(self.refreshBody)
        toolbar.addWidget(self.archivedCheck)
        moreButton = makeButton("", "ellipsis", "ghost")
        moreButton.clicked.connect(lambda: self._moreMenu(moreButton))
        toolbar.addWidget(moreButton)
        self.exportButton = makeButton(tr(TEXT["exportAll"]), "download", "ghost")
        self.exportButton.clicked.connect(self._export)
        toolbar.addWidget(self.exportButton)
        newButton = makeButton(tr(TEXT["new"]), "plus", "primary")
        newButton.clicked.connect(lambda: plugin.openEditor(None, self))
        toolbar.addWidget(newButton)
        layout.addLayout(toolbar)
        self.workBanner = Card(padding=10, hoverable=False)
        workRow = QHBoxLayout(self.workBanner)
        workRow.addWidget(IconWidget("timer", "accent", 18))
        self.workBannerLabel = makeLabel("", "subtitle", True)
        workRow.addWidget(self.workBannerLabel, 1)
        openWork = makeButton(tr(TEXT["open"]), "external-link", "ghost")
        openWork.clicked.connect(lambda: plugin.openEditor(plugin.runningCommissionId, self)
                                if plugin.runningCommissionId else None)
        workRow.addWidget(openWork)
        pauseWork = makeButton(tr(TEXT["pauseWork"]), "pause", "primary")
        pauseWork.clicked.connect(plugin.pauseWork)
        workRow.addWidget(pauseWork)
        layout.addWidget(self.workBanner)
        plugin.workChanged.connect(self._refreshWorkBanner)
        plugin.workChanged.connect(self._refreshStats)
        self._refreshWorkBanner()
        self.bodyHost = QWidget()
        self.bodyLayout = QVBoxLayout(self.bodyHost)
        self.bodyLayout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.bodyHost, 1)
        plugin.commissionsChanged.connect(self.refresh)
        self.refresh()

    def _refreshWorkBanner(self):
        commission = self.plugin.find(self.plugin.runningCommissionId)
        self.workBanner.setVisible(commission is not None)
        if commission:
            self.workBannerLabel.setText(f"{commission['title']} · {logic.formatWorkTime(commission.get('trackedSeconds', 0))}"
                                         f" · {self.plugin.money(commission.get('price', 0), commission['currency'])}")

    def _moreMenu(self, button):
        menu = QMenu(button)
        menu.addAction(tr(TEXT["clients"]), lambda: ClientsDialog(self.plugin, self).exec())
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _export(self):
        self.plugin.openExport(parent=self)

    def setView(self, view):
        self.view = view
        self.plugin.context.setData("view", view)
        self.refreshBody()

    def refresh(self):
        self.exportButton.setEnabled(bool(self.plugin.commissions))
        self._refreshStats()
        currentClient = self.clientFilter.currentData()
        self.clientFilter.blockSignals(True)
        self.clientFilter.clear()
        self.clientFilter.addItem(tr(TEXT["allClients"]), None)
        for client in sorted(self.plugin.clients, key=lambda client: client["name"].lower()):
            self.clientFilter.addItem(client["name"], client["id"])
        self.clientFilter.setCurrentIndex(max(0, self.clientFilter.findData(currentClient)))
        self.clientFilter.blockSignals(False)
        self.refreshBody()

    def _refreshStats(self):
        plugin = self.plugin
        stats = plugin.stats()
        currentTheme = theme()
        self.activeTile.valueLabel.setText(str(stats["active"]))
        nextDeadline = stats["nextDeadline"]
        self.activeTile.subLabel.setText(
            f"{tr(TEXT['nextDeadline'])}: {formatWhen(logic.deadlineOf(nextDeadline))}" if nextDeadline else "")
        self.dueTile.valueLabel.setText(str(stats["dueWeek"]))
        self.dueTile.subLabel.setText(tr(TEXT["overdueCount"], count=stats["overdue"]) if stats["overdue"] else "")
        setRole(self.dueTile.subLabel, "error" if stats["overdue"] else "faint")
        self.dueTile.tile.setColor(currentTheme.danger if stats["overdue"] else None)
        self.collectTile.valueLabel.setText(plugin.euro(stats["outstanding"]))
        self.earnedTile.titleLabel.setText(tr(TEXT["earnedYear"], year=stats["year"]))
        self.earnedTile.valueLabel.setText(plugin.euro(stats["earnedYear"]))
        limit = float(plugin.setting("yearlyThreshold") or 0)
        if plugin.setting("showThreshold") and limit > 0:
            fraction = stats["earnedYear"] / limit
            self.earnedTile.meter.show()
            self.earnedTile.meter.setValue(fraction)
            self.earnedTile.meter.setColor(currentTheme.danger if fraction >= 0.9 else currentTheme.warning if fraction >= 0.7 else None)
            self.earnedTile.subLabel.setText(tr(TEXT["threshold"], earned=f"{fraction * 100:.0f}%", limit=plugin.euro(limit)))
        else:
            self.earnedTile.meter.hide()
            self.earnedTile.subLabel.setText("")

    def _filtered(self):
        query = self.searchEdit.text().strip().lower()
        clientId = self.clientFilter.currentData()
        result = []
        for commission in self.plugin.visible(self.archivedCheck.isChecked()):
            if clientId and commission.get("clientId") != clientId:
                continue
            if query:
                haystack = " ".join([commission["title"], commission.get("notes", ""), commission.get("platform", ""),
                                     self.plugin.clientName(commission.get("clientId"), commission.get("clientName", ""))]).lower()
                if not all(word in haystack for word in query.split()):
                    continue
            result.append(commission)
        return result

    def refreshBody(self, *args):
        self.boardChip.setChecked(self.view == "board")
        self.listChip.setChecked(self.view == "list")
        clearLayout(self.bodyLayout)
        commissions = self._filtered()
        if not self.plugin.commissions:
            emptyCard = Card(padding=20)
            emptyLayout = QVBoxLayout(emptyCard)
            emptyLayout.addWidget(EmptyState("briefcase", tr(TEXT["empty"]), tr(TEXT["emptyText"])))
            self.bodyLayout.addWidget(emptyCard)
            self.bodyLayout.addStretch(1)
            return
        if self.view == "board":
            self._buildBoard(commissions)
        else:
            self._buildList(commissions)

    def _buildBoard(self, commissions):
        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setFrameShape(QFrame.NoFrame)
        scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        columnsLayout = QHBoxLayout(host)
        columnsLayout.setContentsMargins(0, 0, 0, 6)
        columnsLayout.setSpacing(4)
        hideDays = int(self.plugin.setting("hidePaidAfterDays") or 0)
        now = datetime.datetime.now()
        for statusId, label, color in logic.STATUSES:
            if statusId == "cancelled" and not self.plugin.setting("showCancelled"):
                continue
            items = [commission for commission in commissions if commission["status"] == statusId]
            if statusId == "paid" and hideDays and not self.searchEdit.text().strip():
                items = [commission for commission in items
                         if (now - (parseDateTime(commission.get("paidAt") or commission.get("statusChangedAt")) or now)).days <= hideDays]
            items.sort(key=lambda commission: (logic.deadlineOf(commission) or datetime.datetime.max, commission["createdAt"]))
            columnsLayout.addWidget(BoardColumn(self.plugin, statusId, items))
        columnsLayout.addStretch(1)
        scrollArea.setWidget(host)
        self.bodyLayout.addWidget(scrollArea, 1)

    def _buildList(self, commissions):
        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        listLayout = QVBoxLayout(host)
        listLayout.setContentsMargins(0, 0, 6, 0)
        listLayout.setSpacing(4)
        chartCard = Card(padding=14)
        chartLayout = QVBoxLayout(chartCard)
        chartLayout.addWidget(makeLabel(tr(TEXT["earningsChart"]).upper(), "section"))
        chart = BarChart(valueFormatter=self.plugin.euro)
        monthNames = {"it": "GFMAMGLASOND", "en": "JFMAMJJASOND"}[language()]
        chart.setValues([(monthNames[month - 1], value) for year, month, value in
                         logic.monthlyEarnings(self.plugin.commissions, self.plugin.rates())])
        chart.setFixedHeight(150)
        chartLayout.addWidget(chart)
        listLayout.addWidget(chartCard)
        tableCard = Card(padding=10)
        tableLayout = QVBoxLayout(tableCard)
        tableLayout.setSpacing(0)
        ordered = sorted(commissions, key=lambda commission: (
            logic.STATUS_IDS.index(commission["status"]) if commission["status"] in logic.ACTIVE_STATUSES else 10,
            logic.deadlineOf(commission) or datetime.datetime.max))
        now = datetime.datetime.now()
        for index, commission in enumerate(ordered):
            if index:
                tableLayout.addWidget(divider())
            tableLayout.addWidget(CommissionRow(self.plugin, commission, now))
        listLayout.addWidget(tableCard)
        listLayout.addStretch(1)
        scrollArea.setWidget(host)
        self.bodyLayout.addWidget(scrollArea, 1)


class CommissionRow(QWidget):
    def __init__(self, plugin, commission, now, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.commissionId = commission["id"]
        self.setCursor(Qt.PointingHandCursor)
        statusId, label, color = logic.statusInfo(commission["status"])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 9, 6, 9)
        layout.setSpacing(12)
        dot = QWidget()
        dot.setFixedSize(9, 9)
        dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        layout.addWidget(dot)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(1)
        textLayout.addWidget(makeLabel(commission["title"]))
        clientText = plugin.clientName(commission.get("clientId"), commission.get("clientName", ""))
        textLayout.addWidget(makeLabel(" · ".join(part for part in (clientText, commission.get("platform"), tr(label)) if part), "faint"))
        layout.addLayout(textLayout, 1)
        deadline = logic.deadlineOf(commission)
        deadlineLabel = makeLabel(formatWhen(deadline) if deadline else tr(TEXT["noDeadline"]),
                                  "error" if logic.isOverdue(commission, now) else "faint")
        deadlineLabel.setMinimumWidth(140)
        layout.addWidget(deadlineLabel)
        self.priceLabel = makeLabel("", "accent")
        self.priceLabel.setMinimumWidth(90)
        self.priceLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.priceLabel)
        self.paidButton = makeButton(tr(TEXT["markPaid"]), "check", "ghost")
        self.paidButton.setEnabled(commission["status"] != "cancelled" and
                                   (commission["status"] != "paid" or logic.outstanding(commission) > 0.0001))
        self.paidButton.clicked.connect(lambda: plugin.markPaid(self.commissionId))
        layout.addWidget(self.paidButton)
        exportButton = iconButton("download", tr(TEXT["export"]))
        exportButton.clicked.connect(lambda: plugin.openExport(self.commissionId, self))
        layout.addWidget(exportButton)
        plugin.workChanged.connect(self._refreshPrice)
        self._refreshPrice()

    def _refreshPrice(self):
        commission = self.plugin.find(self.commissionId)
        if commission:
            self.priceLabel.setText(self.plugin.money(commission.get("price"), commission["currency"])
                                    if commission.get("price") else "—")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.plugin.openEditor(self.commissionId, self)


class ClientsDialog(ThemedDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent, 560)
        self.plugin = plugin
        self.addHeader(tr(TEXT["clientsTitle"]), "users")
        self.listLayout = QVBoxLayout()
        self.listLayout.setSpacing(0)
        host = QWidget()
        host.setLayout(self.listLayout)
        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setFrameShape(QFrame.NoFrame)
        scrollArea.setMinimumHeight(320)
        scrollArea.setWidget(host)
        self.bodyLayout.addWidget(scrollArea)
        addButton = makeButton(tr(TEXT["newClient"]), "plus")
        addButton.clicked.connect(self._add)
        closeButton = makeButton(tr("common.close"), variant="primary")
        closeButton.clicked.connect(self.accept)
        self.addButtons([addButton, closeButton])
        self.rebuild()

    def rebuild(self):
        clearLayout(self.listLayout)
        rates = self.plugin.rates()
        clients = sorted(self.plugin.clients, key=lambda client: client["name"].lower())
        if not clients:
            self.listLayout.addWidget(EmptyState("users", tr(TEXT["clientsTitle"]), ""))
        for index, client in enumerate(clients):
            if index:
                self.listLayout.addWidget(divider())
            stats = logic.clientStats(client["id"], self.plugin.commissions, rates)
            rowLayout = QHBoxLayout()
            rowLayout.setContentsMargins(4, 8, 4, 8)
            textLayout = QVBoxLayout()
            textLayout.setSpacing(1)
            textLayout.addWidget(makeLabel(client["name"]))
            textLayout.addWidget(makeLabel(tr(TEXT["clientCommissions"], count=stats["count"], active=stats["active"],
                                              earned=self.plugin.euro(stats["earned"])), "faint"))
            rowLayout.addLayout(textLayout, 1)
            rowLayout.addWidget(makeLabel(client.get("platform") or "", "chip"))
            renameButton = iconButton("pencil", tr(TEXT["rename"]), "muted", 15)
            renameButton.clicked.connect(lambda checked=False, clientId=client["id"], name=client["name"]: self._rename(clientId, name))
            rowLayout.addWidget(renameButton)
            deleteButton = iconButton("trash-2", tr(TEXT["delete"]), "danger", 15)
            deleteButton.clicked.connect(lambda checked=False, clientId=client["id"], name=client["name"]: self._delete(clientId, name))
            rowLayout.addWidget(deleteButton)
            rowWidget = QWidget()
            rowWidget.setLayout(rowLayout)
            self.listLayout.addWidget(rowWidget)
        self.listLayout.addStretch(1)

    def _add(self):
        accepted, name = askText(self, tr(TEXT["newClient"]), tr(TEXT["clientName"]))
        if accepted and name:
            self.plugin.addClient(name)
            self.rebuild()

    def _rename(self, clientId, name):
        accepted, newName = askText(self, tr(TEXT["rename"]), tr(TEXT["clientName"]), name)
        if accepted and newName:
            self.plugin.renameClient(clientId, newName)
            self.rebuild()

    def _delete(self, clientId, name):
        if confirm(self, tr(TEXT["deleteClient"]), tr(TEXT["deleteClientMessage"]), [name], danger=True,
                   confirmText=tr(TEXT["delete"])):
            self.plugin.deleteClient(clientId)
            self.rebuild()


class CommissionsHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        leftLayout = QVBoxLayout()
        leftLayout.setSpacing(2)
        self.activeLabel = makeLabel("", "metric")
        self.activeSub = makeLabel(tr(TEXT["active"]), "faint")
        self.nextLabel = makeLabel("", "faint", True)
        leftLayout.addWidget(self.activeLabel)
        leftLayout.addWidget(self.activeSub)
        leftLayout.addStretch(1)
        leftLayout.addWidget(self.nextLabel)
        layout.addLayout(leftLayout, 1)
        rightLayout = QVBoxLayout()
        rightLayout.setSpacing(2)
        self.collectLabel = makeLabel("", "metricSmall")
        rightLayout.addWidget(self.collectLabel)
        rightLayout.addWidget(makeLabel(tr(TEXT["toCollect"]), "faint"))
        rightLayout.addStretch(1)
        self.earnedLabel = makeLabel("", "faint")
        rightLayout.addWidget(self.earnedLabel)
        self.meter = MeterBar(None, 6)
        rightLayout.addWidget(self.meter)
        self.rightHost = QWidget()
        self.rightHost.setLayout(rightLayout)
        layout.addWidget(self.rightHost, 1)
        plugin.commissionsChanged.connect(self.refresh)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.rightHost.setVisible(self.width() > 300)

    def refresh(self):
        plugin = self.plugin
        stats = plugin.stats()
        self.activeLabel.setText(str(stats["active"]))
        nextDeadline = stats["nextDeadline"]
        if nextDeadline:
            deadline = logic.deadlineOf(nextDeadline)
            self.nextLabel.setText(f"⏰ {nextDeadline['title']} · {formatWhen(deadline)}")
            setRole(self.nextLabel, "error" if deadline < datetime.datetime.now() else "faint")
        else:
            self.nextLabel.setText(tr(TEXT["noneActive"]))
        self.collectLabel.setText(plugin.euro(stats["outstanding"]))
        limit = float(plugin.setting("yearlyThreshold") or 0)
        self.earnedLabel.setText(f"{tr(TEXT['earnedYear'], year=stats['year'])}: {plugin.euro(stats['earnedYear'])}")
        showMeter = bool(plugin.setting("showThreshold") and limit > 0)
        self.meter.setVisible(showMeter)
        if showMeter:
            self.meter.setValue(stats["earnedYear"] / limit)


class DeadlinesHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.rowsLayout = QVBoxLayout(self)
        self.rowsLayout.setContentsMargins(0, 0, 0, 0)
        self.rowsLayout.setSpacing(4)
        plugin.commissionsChanged.connect(self.refresh)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def refresh(self):
        clearLayout(self.rowsLayout)
        now = datetime.datetime.now()
        active = [commission for commission in self.plugin.visible()
                  if commission["status"] in logic.ACTIVE_STATUSES and logic.deadlineOf(commission)]
        active.sort(key=logic.deadlineOf)
        capacity = max(2, self.height() // 26)
        if not active:
            self.rowsLayout.addWidget(makeLabel(tr(TEXT["noneActive"]), "faint"))
        for commission in active[:capacity]:
            deadline = logic.deadlineOf(commission)
            rowLayout = QHBoxLayout()
            rowLayout.setSpacing(8)
            dot = QWidget()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background: {logic.statusInfo(commission['status'])[2]}; border-radius: 4px;")
            rowLayout.addWidget(dot)
            rowLayout.addWidget(makeLabel(commission["title"]), 1)
            rowLayout.addWidget(makeLabel(formatCountdown(deadline, now), "error" if deadline < now else "faint"))
            self.rowsLayout.addLayout(rowLayout)
        self.rowsLayout.addStretch(1)
