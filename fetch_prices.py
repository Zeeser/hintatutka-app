import json
import os
from datetime import datetime
import urllib.request

# --- ASETUKSET ---
POSTCODE = "78880"
QUALITY = "kesalaatu"  # "kesalaatu" tai "talvilaatu"
TARGET_PRICE = 1.75    # Hälytysraja (€/l)
NTFY_TOPIC = "polttooljy_kuvansi_78880_oma"  # Vaihda uniikiksi!
DATA_FILE = "prices.json"

def fetch_market_indicators():
    """Hakee Brent-raakaöljyn ja EUR/USD-kurssin suuntaa-antavaa ennustetta varten."""
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
        return 74.50, 0.0

def estimate_local_price(brent_usd, postcode, quality):
    """Laskee päivän hinta-arvion Brent-tason, postinumerovyöhykkeen ja laadun mukaan."""
    base_price = 1.18 + (brent_usd * 0.0098)

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
    current_price = estimate_local_price(brent_now, POSTCODE, QUALITY)

    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            db = json.load(f)
    else:
        db = {"postcode": POSTCODE, "quality": QUALITY, "history": []}

    history = [entry for entry in db["history"] if entry["date"] != today]
    history.append({
        "date": today,
        "price": current_price,
        "brent": brent_now,
        "brent_trend_pct": brent_trend
    })
    history = history[-90:]

    prices = [h["price"] for h in history]
    min_90d = min(prices)
    avg_30d = round(sum(prices[-30:]) / len(prices[-30:]), 3)

    if current_price <= TARGET_PRICE or current_price <= min_90d:
        signal = "OSTA NYT"
        reason = f"Hinta ({current_price:.3f} €/l) on tavoitetasolla tai 90 pv alimmillaan!"
        send_push_notification("Polttoöljy: OSTA NYT!", reason)
    elif brent_trend > 2.0:
        signal = "HARKITSE OSTOA"
        reason = f"Raakaöljy nousussa (+{brent_trend}%). Hinnat todennäköisesti nousevat pian."
    else:
        signal = "ODOTA"
        reason = f"Hinta {current_price:.3f} €/l (30 pv ka. {avg_30d:.3f} €/l). Ei vielä pohjalukemissa."

    output = {
        "updated_at": datetime.now().isoformat(),
        "postcode": POSTCODE,
        "quality": QUALITY,
        "current_price": current_price,
        "min_90d": min_90d,
        "avg_30d": avg_30d,
        "brent_usd": brent_now,
        "brent_trend_pct": brent_trend,
        "signal": signal,
        "reason": reason,
        "history": history
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
