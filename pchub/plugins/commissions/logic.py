"""Commission tracking model (pure, unit tested): statuses, money in several currencies, payments, deadlines,
yearly totals for the 'prestazione occasionale' threshold, CSV export."""
import csv
import datetime
import io
import json
import uuid

from pchub.core.dates import parseDateTime, toIso
from pchub.core.i18n import T

STATUSES = [
    ("lead", T("Da confermare", "To confirm"), "#94A3B8"),
    ("todo", T("Da iniziare", "To start"), "#38BDF8"),
    ("progress", T("In corso", "In progress"), "#8B7CF6"),
    ("review", T("In revisione", "In review"), "#FBBF24"),
    ("delivered", T("Consegnata", "Delivered"), "#34D399"),
    ("paid", T("Pagato", "Paid"), "#22C55E"),
    ("cancelled", T("Annullata", "Cancelled"), "#F87171"),
]
STATUS_IDS = [status[0] for status in STATUSES]
ACTIVE_STATUSES = {"lead", "todo", "progress", "review"}
CURRENCIES = [("EUR", "€"), ("ROBUX", "R$"), ("USD", "$")]
PAYMENT_METHODS = ["Stripe", "PayPal", "Revolut", "Robux", "Bonifico", "Contanti", "Altro"]
PLATFORMS = ["Discord", "BuiltByBit", "Fiverr", "Roblox", "Nourity", "Altro"]


def statusInfo(statusId):
    return next((status for status in STATUSES if status[0] == statusId), STATUSES[1])


def currencySymbol(currency):
    return dict(CURRENCIES).get(currency, currency)


def toEuro(amount, currency, rates):
    """rates: {'ROBUX': € per 1000 Robux, 'USD': € per 1 $}."""
    amount = float(amount or 0)
    if currency == "EUR":
        return amount
    if currency == "ROBUX":
        return amount / 1000.0 * float(rates.get("ROBUX", 0) or 0)
    if currency == "USD":
        return amount * float(rates.get("USD", 0) or 0)
    return 0.0


def formatMoney(amount, currency, language="it"):
    amount = float(amount or 0)
    if currency == "ROBUX":
        text = f"{int(round(amount)):,}"
        text = text.replace(",", ".") if language == "it" else text
        return f"R$ {text}"
    text = f"{amount:,.2f}"
    if language == "it":
        text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    if text.endswith(",00") or text.endswith(".00"):
        text = text[:-3]
    return f"{text} {currencySymbol(currency)}" if currency == "EUR" else f"{currencySymbol(currency)}{text}"


def newClient(name, platform="Discord", contact="", notes=""):
    return {"id": uuid.uuid4().hex[:10], "name": name.strip(), "platform": platform, "contact": contact, "notes": notes,
            "createdAt": toIso(datetime.datetime.now())}


def basePrice(commission):
    """Work alone; legacy fixed prices become the base before extras are added."""
    if commission.get("billingMode") == "hourly":
        return max(0.0, float(commission.get("trackedSeconds") or 0)) * max(
            0.0, float(commission.get("hourlyRate") or 0)) / 3600
    return float(commission.get("basePrice", commission.get("price")) or 0)


def extraCostsTotal(commission):
    return sum(float(cost.get("amount") or 0) for cost in commission.get("extraCosts") or [])


def workPrice(commission):
    return basePrice(commission) + extraCostsTotal(commission)


def formatWorkTime(seconds):
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def newCommission(title, clientId=None, price=0.0, currency="EUR", status="todo", deadline=None, platform="Discord",
                  paymentMethod="Stripe", description="", now=None):
    now = now or datetime.datetime.now()
    return {"id": uuid.uuid4().hex[:10], "title": title.strip(), "clientId": clientId, "platform": platform,
            "description": description, "status": status, "price": float(price or 0), "currency": currency,
            "paymentMethod": paymentMethod, "payments": [], "deadline": toIso(deadline) if deadline else None,
            "deadlineAlertHours": 24, "tasks": [], "notes": "", "createdAt": toIso(now), "statusChangedAt": toIso(now),
            "deliveredAt": None, "paidAt": None, "archived": False, "alertedKeys": [],
            "billingMode": "fixed", "basePrice": float(price or 0), "extraCosts": [],
            "hourlyRate": 0.0, "trackedSeconds": 0.0,
            "clientName": "", "temporaryClient": False}


def setStatus(commission, status, now=None):
    now = now or datetime.datetime.now()
    if commission.get("status") == status:
        return
    commission["status"] = status
    commission["statusChangedAt"] = toIso(now)
    if status in ("delivered", "paid") and not commission.get("deliveredAt"):
        commission["deliveredAt"] = toIso(now)
    if status == "paid" and not commission.get("paidAt"):
        commission["paidAt"] = toIso(now)


def paidAmount(commission):
    """Total paid in the commission's own currency (payments in other currencies are ignored here)."""
    return sum(float(payment.get("amount") or 0) for payment in commission.get("payments", [])
               if payment.get("currency", commission["currency"]) == commission["currency"])


def outstanding(commission):
    if commission.get("status") in ("cancelled",):
        return 0.0
    if commission.get("status") == "paid" and not commission.get("payments"):
        return 0.0
    return max(0.0, workPrice(commission) - paidAmount(commission))


def addPayment(commission, amount, currency=None, method=None, date=None, note=""):
    commission.setdefault("payments", []).append({
        "id": uuid.uuid4().hex[:8], "amount": float(amount), "currency": currency or commission["currency"],
        "method": method or commission.get("paymentMethod"), "date": toIso(date or datetime.datetime.now()), "note": note})
    if workPrice(commission) > 0 and outstanding(commission) <= 0.0001 and commission.get("status") != "cancelled":
        setStatus(commission, "paid", date)


def removePayment(commission, paymentId):
    commission["payments"] = [payment for payment in commission.get("payments", []) if payment.get("id") != paymentId]


def progress(commission):
    tasks = commission.get("tasks") or []
    if tasks:
        return sum(1 for task in tasks if task.get("done")) / len(tasks)
    return {"lead": 0, "todo": 0, "progress": 0.4, "review": 0.8, "delivered": 1, "paid": 1, "cancelled": 0}.get(
        commission.get("status"), 0)


def deadlineOf(commission):
    return parseDateTime(commission.get("deadline"))


def isOverdue(commission, now=None):
    now = now or datetime.datetime.now()
    deadline = deadlineOf(commission)
    return bool(deadline and commission.get("status") in ACTIVE_STATUSES and deadline < now)


def dueSoon(commission, now=None, hours=48):
    now = now or datetime.datetime.now()
    deadline = deadlineOf(commission)
    return bool(deadline and commission.get("status") in ACTIVE_STATUSES and now <= deadline <= now + datetime.timedelta(hours=hours))


def earnedInRange(commissions, rates, start, end):
    """Money actually received (payments, plus 'paid' commissions without payment records) in [start, end), in €."""
    total = 0.0
    for commission in commissions:
        payments = commission.get("payments") or []
        if payments:
            for payment in payments:
                when = parseDateTime(payment.get("date"))
                if when and start <= when < end:
                    total += toEuro(payment.get("amount"), payment.get("currency", commission["currency"]), rates)
        elif commission.get("status") == "paid":
            when = parseDateTime(commission.get("paidAt") or commission.get("statusChangedAt"))
            if when and start <= when < end:
                total += toEuro(workPrice(commission), commission["currency"], rates)
    return total


def earnedInYear(commissions, rates, year):
    return earnedInRange(commissions, rates, datetime.datetime(year, 1, 1), datetime.datetime(year + 1, 1, 1))


def monthlyEarnings(commissions, rates, months=12, today=None):
    """[(year, month, €)] for the last `months` months, oldest first."""
    today = today or datetime.date.today()
    results = []
    for offset in range(months - 1, -1, -1):
        monthIndex = today.year * 12 + today.month - 1 - offset
        year, month = monthIndex // 12, monthIndex % 12 + 1
        start = datetime.datetime(year, month, 1)
        nextIndex = monthIndex + 1
        end = datetime.datetime(nextIndex // 12, nextIndex % 12 + 1, 1)
        results.append((year, month, earnedInRange(commissions, rates, start, end)))
    return results


def outstandingTotal(commissions, rates):
    return sum(toEuro(outstanding(commission), commission["currency"], rates) for commission in commissions
               if commission.get("status") not in ("lead", "cancelled") and not commission.get("archived"))


def clientStats(clientId, commissions, rates):
    owned = [commission for commission in commissions if commission.get("clientId") == clientId]
    earned = sum(earnedInRange([commission], rates, datetime.datetime(1970, 1, 1), datetime.datetime(3000, 1, 1))
                 for commission in owned)
    return {"count": len(owned), "active": sum(1 for commission in owned if commission.get("status") in ACTIVE_STATUSES),
            "earned": earned}


def exportCsv(commissions, clientsById, rates, statusName):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Creata", "Cliente", "Piattaforma", "Commissione", "Stato", "Prezzo", "Valuta", "Prezzo €",
                     "Incassato €", "Metodo", "Scadenza", "Consegnata", "Pagata",
                     "Compenso base", "Totale costi aggiuntivi", "Costi aggiuntivi", "Totale"])
    for commission in commissions:
        client = clientsById.get(commission.get("clientId")) or {}
        earned = earnedInRange([commission], rates, datetime.datetime(1970, 1, 1), datetime.datetime(3000, 1, 1))
        price = workPrice(commission)
        writer.writerow([
            (commission.get("createdAt") or "")[:10], client.get("name", ""), commission.get("platform", ""),
            commission["title"], statusName(commission["status"]), f"{price:.2f}".replace(".", ","),
            commission["currency"], f"{toEuro(price, commission['currency'], rates):.2f}".replace(".", ","),
            f"{earned:.2f}".replace(".", ","), commission.get("paymentMethod", ""), (commission.get("deadline") or "")[:16],
            (commission.get("deliveredAt") or "")[:10], (commission.get("paidAt") or "")[:10],
            f"{basePrice(commission):.2f}".replace(".", ","), f"{extraCostsTotal(commission):.2f}".replace(".", ","),
            json.dumps(commission.get("extraCosts") or [], ensure_ascii=False), f"{price:.2f}".replace(".", ",")])
    return buffer.getvalue()
