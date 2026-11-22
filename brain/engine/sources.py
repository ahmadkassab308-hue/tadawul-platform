"""Best-effort free fetches for Saudi official / calendar / commodity data.

Every function returns None or empty on failure. Callers must treat that as NOT FOUND
and must not invent values. Saudi Exchange often returns HTTP 403 from this environment.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

RIYADH = ZoneInfo("Asia/Riyadh")
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; tadawul-brain/1.0; research)",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.8",
}

# After a hard block (403/SSL) on a host, skip further URLs on that host in this process.
_BLOCKED_HOSTS: set[str] = set()


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return ""


def _get(url: str, timeout: int = 6) -> tuple[Optional[int], Optional[str], Optional[str]]:
    host = _host(url)
    if host in _BLOCKED_HOSTS:
        return None, f"skipped, host previously blocked: {host}", url
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.status == 403:
                _BLOCKED_HOSTS.add(host)
            return resp.status, raw, resp.geturl()
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        if "403" in msg or "SSL" in msg or "Forbidden" in msg:
            if host:
                _BLOCKED_HOSTS.add(host)
        return None, msg, url


def try_tadawul_announcements(symbol: str) -> Optional[dict]:
    """Official issuer announcements from Saudi Exchange or Argaam if parseable."""
    code = symbol.split(".")[0]
    urls = [
        f"https://www.saudiexchange.sa/tadawul.eportal.theme.helper/ThemeCompanyProfileAjax/getAnnouncements?symbol={code}&lang=ar",
        f"https://www.saudiexchange.sa/resources/sau-tadawul-product-v2/v1/announcements?symbol={code}",
        f"https://www.saudiexchange.sa/wps/portal/saudiexchange/hidden/company-profile-v2?companySymbol={code}",
        "https://www.argaam.com/en/rss",
    ]
    errors = []
    for url in urls:
        status, body, final = _get(url)
        if status and 200 <= status < 300 and body and not body.startswith("HTTPError") and "<html" not in body[:80].lower():
            # try JSON
            try:
                data = json.loads(body)
                return {"items": data, "source_url": final or url, "source": "JSON " + url}
            except json.JSONDecodeError:
                errors.append(f"{url}: not JSON")
                continue
        errors.append(f"{url}: {status or body}")
    return {"items": None, "error": " | ".join(errors[:4]), "source": "saudiexchange.sa / argaam.com"}


def try_foreign_ownership(symbol: str) -> Optional[dict]:
    code = symbol.split(".")[0]
    urls = [
        f"https://www.saudiexchange.sa/resources/sau-tadawul-product-v2/v1/foreign-ownership?symbol={code}",
        "https://www.saudiexchange.sa/wps/portal/saudiexchange/newsandreports/reports-publications/historical-reports",
    ]
    errors = []
    for url in urls:
        status, body, final = _get(url)
        if status and 200 <= status < 300 and body:
            try:
                data = json.loads(body)
                return {"data": data, "source_url": final or url}
            except json.JSONDecodeError:
                errors.append(f"{url}: HTTP {status} but not parseable JSON")
                continue
        errors.append(f"{url}: {status or body}")
    return {"data": None, "error": " | ".join(errors[:3]), "source": "saudiexchange.sa"}


def try_investor_flows() -> Optional[dict]:
    urls = [
        "https://www.saudiexchange.sa/wps/portal/saudiexchange/newsandreports/reports-publications/historical-reports",
        "https://www.saudiexchange.sa/resources/sau-tadawul-product-v2/v1/trading-activity",
    ]
    errors = []
    for url in urls:
        status, body, _ = _get(url)
        if status and 200 <= status < 300 and body:
            try:
                data = json.loads(body)
                return {"data": data, "source_url": url}
            except json.JSONDecodeError:
                errors.append(f"{url}: HTTP {status} but not parseable JSON")
                continue
        errors.append(f"{url}: {status or body}")
    return {"data": None, "error": " | ".join(errors[:3]), "source": "saudiexchange.sa weekly trading reports"}


def try_petrochem_prices() -> Optional[dict]:
    """Product vs feedstock commodity prices. Equity tickers (MEOH, LYB) are NOT spreads."""
    # FRED / public CSVs sometimes carry chemicals; if missing, return None payload with errors.
    candidates = {
        "naphtha": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WPU0571",  # may not be naphtha
    }
    # We only accept a series if the CSV header/id is clearly a petrochem product or feedstock.
    # The generic PPI code above is not assumed to be a Saudi spread — skip unless we know the series.
    errors = []
    for name, url in candidates.items():
        status, body, _ = _get(url)
        if not status or status >= 400 or not body or "DATE" not in (body.splitlines()[0].upper() if body else ""):
            errors.append(f"{name}: {status or body}")
            continue
        # Even a successful PPI series is not a product-minus-feedstock spread. Do not misuse it.
        errors.append(f"{name}: fetched a series but it is not a documented product/feedstock spread; ignored")
    return {"data": None, "error": " | ".join(errors) if errors else "no series attempted", "source": "no free Saudi product–feedstock spread source"}


def ramadan_windows(around: date, years_back: int = 1, years_fwd: int = 1) -> list[dict]:
    """Umm al-Qura civil dates via hijridate (Saudi calendar used in the library).
    Official moon-sighting may differ by one day. Source must be cited.
    """
    from hijridate import Gregorian, Hijri

    g = Gregorian(around.year, around.month, around.day).to_hijri()
    out = []
    for hy in range(g.year - years_back, g.year + years_fwd + 1):
        start = Hijri(hy, 9, 1).to_gregorian()
        # month length 29 or 30
        try:
            end = Hijri(hy, 9, 30).to_gregorian()
            length = 30
        except Exception:
            end = Hijri(hy, 9, 29).to_gregorian()
            length = 29
        fitr = Hijri(hy, 10, 1).to_gregorian()
        adha = Hijri(hy, 12, 10).to_gregorian()
        out.append(
            {
                "hijri_year": hy,
                "ramadan_start": date(start.year, start.month, start.day),
                "ramadan_end": date(end.year, end.month, end.day),
                "length": length,
                "eid_fitr": date(fitr.year, fitr.month, fitr.day),
                "eid_adha": date(adha.year, adha.month, adha.day),
            }
        )
    return out


def ksa_fixed_holidays(year: int) -> list[tuple[date, str]]:
    return [
        (date(year, 2, 22), "يوم التأسيس"),
        (date(year, 9, 23), "اليوم الوطني"),
    ]


def calendar_context(asof: date, ex_div: Optional[date] = None) -> dict:
    """Build a factual calendar snapshot. MSCI/FTSE exact press-release dates are not assumed."""
    windows = ramadan_windows(asof, 0, 1)
    events = []
    in_ramadan = False
    days_to_ramadan = None
    days_to_ex = None
    days_to_holiday = None
    for w in windows:
        if w["ramadan_start"] <= asof <= w["ramadan_end"]:
            in_ramadan = True
            events.append(f"اليوم ضمن رمضان {w['hijri_year']} (تقويم أم القرى عبر hijridate، قد يختلف يوم عن الرؤية)")
        elif asof < w["ramadan_start"]:
            delta = (w["ramadan_start"] - asof).days
            if days_to_ramadan is None or delta < days_to_ramadan:
                days_to_ramadan = delta
            if delta <= 21:
                events.append(f"رمضان {w['hijri_year']} يبدأ {w['ramadan_start']} بعد {delta} يوماً (أم القرى/hijridate)")
        for label, d in (("عيد الفطر", w["eid_fitr"]), ("عيد الأضحى", w["eid_adha"])):
            if 0 <= (d - asof).days <= 21:
                events.append(f"{label} في {d} بعد {(d - asof).days} يوماً (أم القرى/hijridate)")
    for y in (asof.year, asof.year + 1):
        for d, name in ksa_fixed_holidays(y):
            if 0 <= (d - asof).days <= 14:
                events.append(f"{name} في {d} بعد {(d - asof).days} يوماً")
            if days_to_holiday is None or (d >= asof and (d - asof).days < (days_to_holiday or 999)):
                if d >= asof:
                    days_to_holiday = (d - asof).days
    if ex_div:
        days_to_ex = (ex_div - asof).days
        if -1 <= days_to_ex <= 21:
            events.append(f"تاريخ الاستحقاق/الإكس للتوزيع {ex_div} ({'بعد' if days_to_ex>=0 else 'قبل'} {abs(days_to_ex)} يوم)")
    # MSCI/FTSE: only mention the conventional review months, not a confirmed event date.
    msci_months = {2, 5, 8, 11}
    in_msci_month = asof.month in msci_months
    if in_msci_month:
        events.append(
            f"الشهر {asof.month} من الأشهر المعتادة لمراجعة MSCI/FTSE الربعية "
            "(فبراير/مايو/أغسطس/نوفمبر) دون تأكيد بيان رسمي لهذه الدورة"
        )
    return {
        "asof": asof,
        "in_ramadan": in_ramadan,
        "days_to_ramadan": days_to_ramadan,
        "days_to_ex": days_to_ex,
        "ex_div": ex_div,
        "in_msci_review_month": in_msci_month,
        "events": events,
        "source": "hijridate (Umm al-Qura) + Yahoo ex-dividend إن وُجد + تقويم العطل الرسمية الثابتة",
    }
