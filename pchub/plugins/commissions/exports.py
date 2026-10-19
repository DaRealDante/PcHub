"""Complete, localized commission exports without optional dependencies."""
import csv
import datetime
import html
import io
import json
import os
from pathlib import Path
import tempfile
import unicodedata

from . import logic


def _translate(italian, english, lang):
    return italian if lang == "it" else english


def _status(commission, lang):
    return logic.statusInfo(commission.get("status", "todo"))[1][lang]


def _client(commission, clients):
    client = dict(clients.get(commission.get("clientId")) or {})
    client["name"] = client.get("name") or commission.get("clientName") or ""
    return client


def _received(commission):
    if commission.get("status") == "paid" and not commission.get("payments"):
        return logic.workPrice(commission)
    return logic.paidAmount(commission)


def _csvText(value):
    """Keep spreadsheet imports from interpreting user text as a formula."""
    text = str(value or "")
    first = next((character for character in text
                  if not character.isspace() and unicodedata.category(character) not in ("Cc", "Cf")), "")
    return "'" + text if first in ("=", "+", "-", "@") else text


def exportCsv(commissions, clientsById, rates, lang="it"):
    """Return semicolon CSV; the original thirteen columns keep their order."""
    lang = "it" if lang == "it" else "en"
    t = lambda it, en: _translate(it, en, lang)
    yes = lambda value: t("Sì", "Yes") if value else t("No", "No")
    number = lambda value: f"{float(value or 0):.2f}".replace(".", ",") if lang == "it" else f"{float(value or 0):.2f}"
    columns = [
        ("Creata", "Created"), ("Cliente", "Client"), ("Piattaforma", "Platform"),
        ("Commissione", "Commission"), ("Stato", "Status"), ("Prezzo", "Price"), ("Valuta", "Currency"),
        ("Prezzo €", "Price €"), ("Incassato €", "Received €"), ("Metodo", "Method"),
        ("Scadenza", "Deadline"), ("Consegnata", "Delivered"), ("Pagata", "Paid"),
        ("ID", "ID"), ("ID cliente", "Client ID"), ("Contatto cliente", "Client contact"),
        ("Piattaforma cliente", "Client platform"), ("Note cliente", "Client notes"),
        ("Cliente temporaneo", "Temporary client"), ("Compenso", "Billing"),
        ("Tariffa oraria", "Hourly rate"), ("Secondi lavorati", "Tracked seconds"),
        ("Tempo lavorato", "Time worked"), ("Incassato nella valuta", "Received in currency"),
        ("Da incassare", "Outstanding"), ("Creata (data e ora)", "Created (date and time)"),
        ("Ultimo cambio stato", "Status changed"), ("Consegnata (data e ora)", "Delivered (date and time)"),
        ("Pagata (data e ora)", "Paid (date and time)"), ("Scadenza (data e ora)", "Deadline (date and time)"),
        ("Preavviso scadenza (ore)", "Deadline alert (hours)"), ("Archiviata", "Archived"),
        ("Descrizione", "Description"), ("Note", "Notes"), ("Attività", "Tasks"), ("Pagamenti", "Payments"),
        ("Compenso base", "Base amount"), ("Totale costi aggiuntivi", "Extra costs total"),
        ("Costi aggiuntivi", "Extra costs"), ("Totale", "Total"),
    ]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([t(*column) for column in columns])
    for commission in commissions:
        client = _client(commission, clientsById)
        price = logic.workPrice(commission)
        financial = commission
        earned = logic.earnedInRange([financial], rates, datetime.datetime(1970, 1, 1), datetime.datetime(3000, 1, 1))
        row = [
            (commission.get("createdAt") or "")[:10], client["name"], commission.get("platform", ""),
            commission.get("title", ""), _status(commission, lang), number(price), commission.get("currency", "EUR"),
            number(logic.toEuro(price, commission.get("currency", "EUR"), rates)), number(earned),
            commission.get("paymentMethod", ""), (commission.get("deadline") or "")[:16],
            (commission.get("deliveredAt") or "")[:10], (commission.get("paidAt") or "")[:10],
            commission.get("id", ""), commission.get("clientId") or "", client.get("contact", ""),
            client.get("platform", ""), client.get("notes", ""), yes(commission.get("temporaryClient")),
            t("A ore", "Hourly") if commission.get("billingMode") == "hourly" else t("Prezzo fisso", "Fixed price"),
            number(commission.get("hourlyRate")), str(commission.get("trackedSeconds") or 0),
            logic.formatWorkTime(commission.get("trackedSeconds")), number(_received(financial)),
            number(logic.outstanding(financial)), commission.get("createdAt") or "",
            commission.get("statusChangedAt") or "", commission.get("deliveredAt") or "", commission.get("paidAt") or "",
            commission.get("deadline") or "", commission.get("deadlineAlertHours"), yes(commission.get("archived")),
            commission.get("description", ""), commission.get("notes", ""),
            json.dumps(commission.get("tasks") or [], ensure_ascii=False),
            json.dumps(commission.get("payments") or [], ensure_ascii=False),
            number(logic.basePrice(commission)), number(logic.extraCostsTotal(commission)),
            json.dumps(commission.get("extraCosts") or [], ensure_ascii=False), number(price),
        ]
        numericColumns = {"Price", "Price €", "Received €", "Hourly rate", "Tracked seconds",
                          "Received in currency", "Outstanding", "Deadline alert (hours)",
                          "Base amount", "Extra costs total", "Total"}
        writer.writerow([value if column[1] in numericColumns else _csvText(value)
                         for column, value in zip(columns, row)])
    return buffer.getvalue()


def _pdfHtml(commissions, clientsById, rates, lang):
    """Build only escaped, self-contained rich text for Qt's paginated renderer."""
    t = lambda it, en: _translate(it, en, lang)
    yes = lambda value: t("Sì", "Yes") if value else t("No", "No")
    escape = lambda value: html.escape(str(value if value is not None and value != "" else "—"), quote=True).replace("\n", "<br/>")
    money = lambda value, currency: logic.formatMoney(value, currency, lang)
    date = lambda value: str(value or "—").replace("T", " ")

    def details(rows):
        return '<table width="100%" cellspacing="0" cellpadding="6">' + "".join(
            f'<tr><td width="31%" bgcolor="#F5F3FF"><b>{escape(label)}</b></td>'
            f'<td width="69%">{escape(value)}</td></tr>' for label, value in rows) + "</table>"

    def section(title, content):
        return f"<h2>{escape(title)}</h2>{content}"

    chunks = ['''<html><head><meta charset="utf-8"/><style>
        body { font-family: Poppins; font-size: 9pt; color: #263044; }
        h1 { font-size: 23pt; color: #6951BD; margin-bottom: 5pt; }
        h2 { font-size: 12pt; color: #6951BD; margin-top: 18pt; margin-bottom: 7pt; }
        p { margin-top: 5pt; margin-bottom: 7pt; line-height: 135%; }
        td { vertical-align: top; }
        .brand { color: #756B8E; font-size: 9pt; }
        .muted { color: #756B8E; font-size: 9pt; }
        </style></head><body>''']
    commissions = list(commissions)
    if not commissions:
        chunks.append(f'<h1>PC Hub · {t("Commissioni", "Commissions")}</h1><p>{t("Nessuna commissione", "No commissions")}</p>')
    for index, commission in enumerate(commissions):
        currency = commission.get("currency", "EUR")
        price = logic.workPrice(commission)
        financial = commission
        client = _client(commission, clientsById)
        hourly = commission.get("billingMode") == "hourly"
        page = ' style="page-break-before: always"' if index else ""
        chunks.append(f'<p class="brand"{page}>PC HUB / {t("COMMISSIONI", "COMMISSIONS")} · {index + 1}/{len(commissions)}</p>')
        chunks.append(f'<h1>{escape(commission.get("title"))}</h1><p class="muted">ID {escape(commission.get("id"))}</p>')
        chunks.append(details([
            (t("Stato", "Status"), _status(commission, lang)),
            (t("Piattaforma", "Platform"), commission.get("platform")),
            (t("Archiviata", "Archived"), yes(commission.get("archived"))),
        ]))
        chunks.append(section(t("Cliente", "Client"), details([
            (t("Nome", "Name"), client["name"]), (t("Temporaneo", "Temporary"), yes(commission.get("temporaryClient"))),
            (t("ID cliente", "Client ID"), commission.get("clientId")),
            (t("Contatto", "Contact"), client.get("contact")), (t("Piattaforma", "Platform"), client.get("platform")),
        ])))
        if client.get("notes"):
            chunks.append(f'<p><b>{t("Note cliente", "Client notes")}</b><br/>{escape(client["notes"])}</p>')
        chunks.append(section(t("Compenso", "Billing"), details([
            (t("Tipo", "Type"), t("A ore", "Hourly") if hourly else t("Prezzo fisso", "Fixed price")),
            (t("Valuta", "Currency"), currency),
            (t("Maturato" if hourly else "Prezzo", "Accrued" if hourly else "Price"), money(price, currency)),
            (t("Compenso base", "Base amount"), money(logic.basePrice(commission), currency)),
            (t("Totale costi aggiuntivi", "Extra costs total"), money(logic.extraCostsTotal(commission), currency)),
            (t("Totale", "Total"), money(price, currency)),
            (t("Tariffa oraria", "Hourly rate"), money(commission.get("hourlyRate"), currency) + "/h"),
            (t("Tempo lavorato", "Time worked"), logic.formatWorkTime(commission.get("trackedSeconds"))),
            (t("Secondi lavorati", "Tracked seconds"), commission.get("trackedSeconds") or 0),
            (t("Incassato nella valuta", "Received in currency"), money(_received(financial), currency)),
            (t("Da incassare", "Outstanding"), money(logic.outstanding(financial), currency)),
            (t("Equivalente in euro", "Euro equivalent"), money(logic.toEuro(price, currency, rates), "EUR")),
            (t("Metodo di pagamento", "Payment method"), commission.get("paymentMethod")),
        ])))
        costRows = [(cost.get("description") or t("Costo", "Cost"), money(cost.get("amount"), currency))
                    for cost in commission.get("extraCosts") or []]
        chunks.append(section(t("Costi aggiuntivi", "Extra costs"),
                              details(costRows) if costRows else f'<p>{t("Nessun costo aggiuntivo", "No extra costs")}</p>'))
        chunks.append(section(t("Date e scadenza", "Dates and deadline"), details([
            (t("Creata", "Created"), date(commission.get("createdAt"))),
            (t("Ultimo cambio stato", "Status changed"), date(commission.get("statusChangedAt"))),
            (t("Consegnata", "Delivered"), date(commission.get("deliveredAt"))),
            (t("Pagata", "Paid"), date(commission.get("paidAt"))),
            (t("Scadenza", "Deadline"), date(commission.get("deadline"))),
            (t("Preavviso scadenza", "Deadline alert"),
             f'{commission["deadlineAlertHours"]} {t("ore", "hours")}' if commission.get("deadlineAlertHours") is not None else t("Disattivato", "Disabled")),
        ])))
        for key, title in (("description", t("Descrizione", "Description")), ("notes", t("Note", "Notes"))):
            chunks.append(section(title, f'<p>{escape(commission.get(key))}</p>'))
        tasks = commission.get("tasks") or []
        taskHtml = "".join(f'<p><b>{t("Fatta", "Done") if task.get("done") else t("Da fare", "To do")}</b> · {escape(task.get("text"))}</p>' for task in tasks)
        chunks.append(section(t("Attività", "Tasks"), taskHtml or f'<p>{t("Nessuna attività", "No tasks")}</p>'))
        payments = commission.get("payments") or []
        chunks.append(f'<h2>{t("Pagamenti", "Payments")} ({len(payments)})</h2>')
        if not payments:
            message = (t("Già pagata senza registrazioni dei singoli pagamenti", "Paid without individual payment records")
                       if commission.get("status") == "paid"
                       else t("Nessun pagamento registrato", "No recorded payments"))
            chunks.append(f'<p>{message}</p>')
        for paymentIndex, payment in enumerate(payments, 1):
            paymentCurrency = payment.get("currency") or currency
            chunks.append(f'<p><b>{paymentIndex}. {escape(money(payment.get("amount"), paymentCurrency))}</b> · {escape(paymentCurrency)}</p>')
            chunks.append(details([
                (t("Data", "Date"), date(payment.get("date"))),
                (t("Metodo", "Method"), payment.get("method")), ("ID", payment.get("id")),
            ]))
            if payment.get("note"):
                chunks.append(f'<p><b>{t("Nota pagamento", "Payment note")}</b><br/>{escape(payment["note"])}</p>')
    chunks.append("</body></html>")
    return "".join(chunks)


def exportPdf(path, commissions, clientsById, rates, lang="it"):
    """Write an A4 PDF with automatic pagination; requires the app's QApplication."""
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
    from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextDocument
    from pchub.ui.fonts import loadFonts

    path = Path(path)
    lang = "it" if lang == "it" else "en"
    loadFonts()
    document = QTextDocument()
    document.setDefaultFont(QFont("Poppins", 9))
    document.setHtml(_pdfHtml(commissions, clientsById, rates, lang))
    descriptor, temporary = tempfile.mkstemp(prefix=".pchub-export-", suffix=".pdf", dir=path.parent)
    os.close(descriptor)
    writer = painter = None
    try:
        writer = QPdfWriter(temporary)
        writer.setResolution(300)
        writer.setTitle("PC Hub · " + _translate("Commissioni", "Commissions", lang))
        writer.setCreator("PC Hub")
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Unit.Millimeter)
        page = writer.pageLayout().paintRectPixels(writer.resolution())
        footerHeight = round(writer.resolution() * 8 / 25.4)
        width, height = page.width(), page.height() - footerHeight
        document.documentLayout().setPaintDevice(writer)
        document.setDocumentMargin(0)
        document.setPageSize(QSizeF(width, height))
        painter = QPainter(writer)
        if not painter.isActive():
            raise OSError(_translate("Impossibile creare il PDF", "Could not create PDF", lang))
        for index in range(document.pageCount()):
            if index and not writer.newPage():
                raise OSError(_translate("Impossibile creare il PDF", "Could not create PDF", lang))
            painter.save()
            painter.setClipRect(QRectF(0, 0, width, height))
            painter.translate(0, -index * height)
            document.drawContents(painter, QRectF(0, index * height, width, height))
            painter.restore()
            painter.setFont(QFont("Poppins", 8))
            painter.setPen(QColor("#756B8E"))
            painter.drawText(QRectF(0, height + 6, width, footerHeight - 6),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(index + 1))
        painter.end()
        painter = writer = None  # Release the Windows file handle before atomic replacement.
        if Path(temporary).stat().st_size < 100:
            raise OSError(_translate("Impossibile creare il PDF", "Could not create PDF", lang))
        os.replace(temporary, path)
    finally:
        if painter is not None and painter.isActive():
            painter.end()
        painter = writer = None
        if os.path.exists(temporary):
            os.remove(temporary)
