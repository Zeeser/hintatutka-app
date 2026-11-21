import json
import os
from datetime import datetime
import urllib.request

# --- ASETUKSET ---
POSTCODE = "78880"
QUALITY = "kesalaatu"  # "kesalaatu" tai "talvilaatu"
TARGET_PRICE = 1.75    # Hälytysraja (€/l)
NTFY_TOPIC = "polttooljy_halytys_oma_kuvansi"  # Vaihda uniikiksi!
DATA_FILE = "prices.json"

# Toimittajakohtaiset marginaali- ja rahtierot suhteessa perusindeksiin (78880 alue)
SUPPLIERS_CONFIG = [
    {"id": "neste", "name": "Neste", "offset": 0.015, "url": "https://www.neste.fi/lammitysoljy"},
    {"id": "st1", "name": "St1", "offset": 0.005, "url": "https://www.st1.fi/lammitysoljy"},
    {"id": "seo", "name": "SEO", "offset": -0.005, "url": "https://www.seo.fi/polttooljy"},
    {"id": "osuuskauppa", "name": "Alueen Osuuskauppa / Paikallinen", "offset": 0.000, "url": "https://www.s-kaupat.fi"}
]

def fetch_market_indicators():
    """Hakee Brent-raakaöljyn hinnan ja 5 pv trendin."""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?interval=1d&range=5d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode())
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            brent_now = round(closes[-1], 2)
            brent_prev = round(closes[-2], 2) if len(closes) > 1 else brent_now
            trend_pct = round(((brent_now - brent_prev) / brent_prev) * 100, 2)
            return brent_now, trend_pct
    except Exception as e:
        print(f"Markkinadatan haku epäonnistui: {e}")
        return 73.50, 0.0

def estimate_base_price(brent_usd, postcode, quality):
    """Kalibroitu perushinta-arvio postinumerolle ja laadulle."""
    base_price = 1.08 + (brent_usd * 0.0095)
    prefix = int(postcode[:2])
    freight = 0.00 if prefix < 40 else (0.05 if prefix >= 84 else 0.02)
    quality_add = 0.07 if quality == "talvilaatu" else 0.00
    return round(base_price + freight + quality_add, 3)

def send_push_notification(title, message):
    """Lähettää ilmaisen push-ilmoituksen Android-puhelimeen ntfy.sh-palvelun kautta."""
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Priority": "high",
                "Tags": "fuelpump,chart_with_downwards_trend"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
        print("Push-ilmoitus lähetetty!")
    except Exception as e:
        print(f"Ilmoituksen lähetys epäonnistui: {e}")

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    brent_now, brent_trend = fetch_market_indicators()
    base_price = estimate_base_price(brent_now, POSTCODE, QUALITY)

    suppliers = []
    for s in SUPPLIERS_CONFIG:
        est = round(base_price + s["offset"], 3)
        suppliers.append({
            "id": s["id"],
            "name": s["name"],
            "price": est,
            "url": s["url"],
            "is_estimate": True
        })

    suppliers.sort(key=lambda x: x["price"])
    cheapest = suppliers[0]
    current_price = cheapest["price"]

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            db = json.load(f)
    else:
        db = {"postcode": POSTCODE, "quality": QUALITY, "history": []}

    history = [entry for entry in db["history"] if entry["date"] != today]
    history.append({
        "date": today,
        "price": current_price,
        "cheapest_supplier": cheapest["name"],
        "brent": brent_now,
        "brent_trend_pct": brent_trend
    })
    history = history[-90:]

    prices = [h["price"] for h in history]
    min_90d = min(prices)
    avg_30d = round(sum(prices[-30:]) / len(prices[-30:]), 3)

    if current_price <= TARGET_PRICE or current_price <= min_90d:
        signal = "OSTA NYT"
        reason = f"Halvin ({cheapest['name']}: {current_price:.3f} €/l) on tavoitetasolla tai 90 pv pohjalla!"
        send_push_notification("Polttoöljy: OSTA NYT!", reason)
    elif brent_trend > 2.0:
        signal = "HARKITSE OSTOA"
        reason = f"Raakaöljy nousussa (+{brent_trend}%). Edullisin nyt: {cheapest['name']} ({current_price:.3f} €/l)."
    else:
        signal = "ODOTA"
        reason = f"Edullisin {cheapest['name']} ({current_price:.3f} €/l), 30 pv ka. {avg_30d:.3f} €/l."

    output = {
        "updated_at": datetime.now().isoformat(),
        "postcode": POSTCODE,
        "quality": QUALITY,
        "current_price": current_price,
        "cheapest_supplier": cheapest["name"],
        "min_90d": min_90d,
        "avg_30d": avg_30d,
        "brent_usd": brent_now,
        "brent_trend_pct": brent_trend,
        "signal": signal,
        "reason": reason,
        "suppliers": suppliers,
        "history": history
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
