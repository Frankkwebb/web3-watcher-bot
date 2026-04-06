"""
Web3 Watcher Bot v7 — justFranknftbot
- X feeds check every 30 mins (separate schedule)
- OpenSea: trending + minting now sections
- /etherscan command
- Fixed /opensea command to show actual drops
"""

import time
import hashlib
import logging
import json
import os
import re
import schedule
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# ─── CONFIG ───────────────────────────────────────────────
BOT_TOKEN              = "8680806881:AAGf2HGf0_EdjehNOtDie0ZVBNp6W_ksxNE"
CHAT_ID                = "1836559698"
CHECK_INTERVAL_MINUTES = 15
X_CHECK_INTERVAL       = 30   # X feeds checked every 30 mins
SEEN_FILE              = "seen_cache.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ─── KEYWORDS ─────────────────────────────────────────────
NFT_KEYWORDS = [
    "nft drop", "nft launch", "nft mint", "new nft", "nft collection",
    "pfp drop", "free mint", "mint is live", "minting now", "nft release"
]
WHITELIST_KEYWORDS = [
    "whitelist", "allowlist", "wl drop", "og list", "presale open",
    "wl open", "wl spots", "allowlist open", "mint pass",
    "collab open", "collabs open", "grab wl", "wl available",
    "spots open", "wl for", "free wl", "wl giveaway"
]
JOB_KEYWORDS = [
    "web3 job", "crypto job", "solidity developer", "nft developer",
    "blockchain engineer", "dao contributor", "remote web3", "hiring web3",
]
PROJECT_KEYWORDS = [
    "stealth launch", "just deployed", "new collection dropping",
    "new nft project", "launching today", "drop today"
]

# ─── RSS FEEDS (no X feeds here — handled separately) ─────
RSS_FEEDS = [
    ("NFT Evening", "https://nftevening.com/feed/"),
    ("NFT Now",     "https://nftnow.com/feed/"),
    ("Decrypt",     "https://decrypt.co/feed"),
    ("BeInCrypto",  "https://beincrypto.com/feed/"),
]

# ─── X FEEDS (checked every 30 mins) ──────────────────────
X_FEEDS = [
    ("X: WL/Collab Alerts", "https://rss.app/feeds/ZF8us3eIdkhMU7bF.xml"),
    ("X: Free Mint ETH",    "https://rss.app/feeds/nUafp1OUmSQhuLqX.xml"),
    ("X: Early NFT Alpha",  "https://rss.app/feeds/knbtLb0iKoYYLcjw.xml"),
]

# ─── NITTER KOL ACCOUNTS ──────────────────────────────────
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.pussthecat.org",
]
TWITTER_ACCOUNTS = [
    "NFTdrop", "NFTDropAlert", "WhitelistAlerts", "nftcalendar",
    "beaniemaxi", "punk6529", "NFT_GOD", "garyvee", "Zeneca_33",
    "iamDCinvestor", "web3jobs", "cryptojobslist",
]

# ─── SEEN CACHE ───────────────────────────────────────────
def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except:
            pass
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-3000:], f)

seen = load_seen()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("web3_bot.log"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─── HELPERS ──────────────────────────────────────────────
def is_new(text):
    h = hashlib.md5(text.encode()).hexdigest()
    if h in seen:
        return False
    seen.add(h)
    save_seen(seen)
    return True

def is_fresh(entry):
    for field in ["published", "updated"]:
        val = entry.get(field)
        if val:
            try:
                pub = parsedate_to_datetime(val)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
                return age_hours <= 24
            except:
                pass
    return True

def matches_strict(text, keywords):
    return any(k in text.lower() for k in keywords)

def categorize(title, summary=""):
    full = f"{title} {summary}".lower()
    if matches_strict(full, WHITELIST_KEYWORDS): return "whitelist"
    if matches_strict(full, JOB_KEYWORDS):       return "job"
    if matches_strict(full, NFT_KEYWORDS):       return "nft"
    if matches_strict(full, PROJECT_KEYWORDS):   return "project"
    return None

CATEGORY_META = {
    "whitelist":   ("🎯", "WHITELIST / ALLOWLIST"),
    "job":         ("💼", "WEB3 JOB"),
    "nft":         ("🖼", "NFT DROP"),
    "project":     ("🚀", "NEW PROJECT"),
    "opensea":     ("🌊", "OPENSEA DROP"),
    "mover":       ("📈", "FLOOR PRICE MOVER"),
    "newcontract": ("⚡", "NEW ETH NFT CONTRACT"),
    "upcoming":    ("📅", "UPCOMING MINT"),
    "blur":        ("🔥", "BLUR TRENDING"),
    "x_alert":     ("🐦", "X ALERT"),
}

def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }, timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Send error: {e}")

def shorten(url):
    try:
        r = requests.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=5)
        if r.status_code == 200 and r.text.startswith("http"):
            return r.text.strip()
    except:
        pass
    return url

# ─── CYCLE ALERT TRACKER ──────────────────────────────────
cycle_alerts = []

def alert(category, title, url, source, snippet=""):
    emoji, label = CATEGORY_META.get(category, ("📢", "ALERT"))
    short_url    = shorten(url)
    snip         = f"\n📝 _{snippet[:160]}..._" if snippet else ""
    now          = datetime.now().strftime("%H:%M • %d %b %Y")
    msg = (
        f"{emoji} *{label}*\n"
        f"{'━' * 18}\n"
        f"📌 *{title[:110]}*"
        f"{snip}\n\n"
        f"🔗 {short_url}\n"
        f"📡 `{source}`  •  ⏰ `{now}`\n"
        f"{'─' * 18}"
    )
    send(msg)
    cycle_alerts.append({"category": category, "label": label, "title": title, "source": source, "url": short_url})
    log.info(f"Alerted [{category}] {title[:60]}")

def send_cycle_summary(cycle_name="Scan"):
    now = datetime.now().strftime("%H:%M • %d %b %Y")
    if not cycle_alerts:
        send(
            f"📋 *{cycle_name} Complete — {now}*\n"
            f"{'━' * 18}\n"
            "No new alerts this cycle. Watching all NFT sources closely — will notify you the moment something drops. Stay ready! 👀\n"
            f"{'─' * 18}"
        )
        cycle_alerts.clear()
        return

    total  = len(cycle_alerts)
    counts = {}
    for a in cycle_alerts:
        counts[a["label"]] = counts.get(a["label"], 0) + 1

    breakdown  = " | ".join([f"{v}x {k}" for k, v in counts.items()])
    highlights = ""
    for i, a in enumerate(cycle_alerts[:5], 1):
        highlights += f"\n*{i}.* {a['title'][:65]}\n   _{a['source']}_ — {a['url']}\n"
    more = f"\n_...and {total - 5} more alerts above._" if total > 5 else ""

    paragraph = f"This scan found *{total} new alert(s)*. "
    if "WHITELIST / ALLOWLIST" in counts:
        paragraph += f"*{counts['WHITELIST / ALLOWLIST']} WL/collab spot(s)* are open — act immediately as these fill fast. "
    if "NFT DROP" in counts:
        paragraph += f"*{counts['NFT DROP']} NFT drop(s)* detected — verify details before minting. "
    if "OPENSEA DROP" in counts:
        paragraph += f"*{counts['OPENSEA DROP']} OpenSea drop(s)* found — some may be minting right now. "
    if "FLOOR PRICE MOVER" in counts:
        paragraph += f"*{counts['FLOOR PRICE MOVER']} collection(s)* had major floor moves — watch for flip opportunities. "
    if "NEW ETH NFT CONTRACT" in counts:
        paragraph += f"*{counts['NEW ETH NFT CONTRACT']} new ETH contract(s)* — potential stealth launches. "

    summary = (
        f"📋 *{cycle_name} Summary — {now}*\n"
        f"{'━' * 18}\n"
        f"🗂 *{breakdown}*\n\n"
        f"{paragraph}\n\n"
        f"*Top Picks:*{highlights}{more}\n"
        f"{'─' * 18}\n"
        f"_Move fast — in NFTs, minutes matter!_ 🚀"
    )
    send(summary)
    cycle_alerts.clear()


# ─── MONITOR 1: RSS NEWS FEEDS ────────────────────────────
def check_rss():
    log.info("Checking RSS news feeds...")
    for name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:10]:
                title   = e.get("title", "")
                link    = e.get("link", "")
                summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text()
                if not is_new(link or title): continue
                if not is_fresh(e): continue
                cat = categorize(title, summary)
                if cat:
                    alert(cat, title, link, name, summary[:200])
        except Exception as ex:
            log.warning(f"RSS error ({name}): {ex}")

# ─── MONITOR 2: X FEEDS (every 30 mins) ───────────────────
def check_x_feeds():
    log.info("Checking X RSS feeds...")
    for name, url in X_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:15]:
                title   = e.get("title", "")
                link    = e.get("link", "")
                summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text()
                if not is_new(link or title): continue
                if not is_fresh(e): continue
                # For X feeds, send everything — no strict categorize filter
                cat = categorize(title, summary) or "x_alert"
                alert(cat, title, link, name, summary[:200])
        except Exception as ex:
            log.warning(f"X feed error ({name}): {ex}")

# ─── MONITOR 3: NITTER KOLs ───────────────────────────────
def check_nitter():
    log.info("Checking Nitter KOLs...")
    for account in TWITTER_ACCOUNTS:
        for instance in NITTER_INSTANCES:
            try:
                feed = feedparser.parse(f"{instance}/{account}/rss", request_headers=HEADERS)
                if not feed.entries:
                    continue
                for e in feed.entries[:5]:
                    title = e.get("title", "")
                    link  = e.get("link", "").replace(instance, "https://twitter.com")
                    if not is_new(account + title): continue
                    if not is_fresh(e): continue
                    cat = categorize(title)
                    if cat:
                        alert(cat, f"@{account}: {title[:80]}", link, f"X/@{account}")
                break
            except Exception as ex:
                log.warning(f"Nitter error ({instance}/{account}): {ex}")

# ─── MONITOR 4: OPENSEA MINTING NOW ──────────────────────
def check_opensea_minting_now():
    log.info("Checking OpenSea — Minting Now...")
    try:
        r = requests.get("https://opensea.io/drops", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        seen_slugs = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/collection/" not in href or "/overview" not in href:
                continue
            slug = href.split("/collection/")[-1].replace("/overview", "")
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            parent_text = a.parent.get_text(separator=" ", strip=True).lower() if a.parent else ""
            if "minting now" not in parent_text:
                continue
            text  = a.get_text(separator=" ", strip=True)
            title = text[:120] if text else slug
            link  = f"https://opensea.io/collection/{slug}/overview"
            if is_new(f"os_minting_{slug}"):
                alert("opensea", f"🟢 MINTING NOW — {title}", link, "OpenSea")
    except Exception as ex:
        log.warning(f"OpenSea minting now error: {ex}")

# ─── MONITOR 5: OPENSEA TRENDING ─────────────────────────
def check_opensea_trending():
    log.info("Checking OpenSea — Trending...")
    try:
        r = requests.get("https://opensea.io/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        seen_slugs = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/collection/" not in href:
                continue
            slug = href.split("/collection/")[-1].split("/")[0]
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            text = a.get_text(separator=" ", strip=True)
            # Only pick entries with price/volume info
            if "ETH" not in text and "USDC" not in text:
                continue
            title = f"Trending: {slug.replace('-', ' ').title()} — {text[:60]}"
            link  = f"https://opensea.io/collection/{slug}"
            key   = f"os_trending_{slug}_{datetime.now().strftime('%Y-%m-%d')}"
            if is_new(key):
                alert("opensea", title, link, "OpenSea Trending")
                if len(seen_slugs) >= 5:
                    break
    except Exception as ex:
        log.warning(f"OpenSea trending error: {ex}")

# ─── MONITOR 6: OPENSEA FLOOR MOVERS ─────────────────────
def check_opensea_movers():
    log.info("Checking OpenSea floor movers...")
    try:
        r = requests.get("https://opensea.io/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/collection/" not in href:
                continue
            text = a.get_text(separator=" ", strip=True)
            matches = re.findall(r'([+-]\d+\.?\d*)%', text)
            for m in matches:
                pct = float(m)
                if abs(pct) >= 50:
                    slug  = href.split("/collection/")[-1].split("/")[0]
                    title = f"{slug.replace('-', ' ').title()} floor moved {m}% today"
                    link  = f"https://opensea.io/collection/{slug}"
                    if is_new(f"mover_{slug}_{m}"):
                        alert("mover", title, link, "OpenSea Trending")
    except Exception as ex:
        log.warning(f"OpenSea movers error: {ex}")

# ─── MONITOR 7: ETHERSCAN NEW NFT CONTRACTS ───────────────
def check_new_eth_contracts():
    log.info("Checking Etherscan for new NFT contracts...")
    try:
        r = requests.get(
            "https://etherscan.io/tokens?q=nft&t=1",
            headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("table tbody tr")
        for row in rows[:10]:
            name_el = row.find("a", href=True)
            if not name_el:
                continue
            name     = name_el.get_text(strip=True)
            href     = name_el.get("href", "")
            contract = href.split("/token/")[-1].split("?")[0] if "/token/" in href else ""
            if not contract or not is_new(f"ethcontract_{contract}"):
                continue
            link = f"https://etherscan.io/token/{contract}"
            alert("newcontract", f"New ETH NFT: {name}", link, "Etherscan", f"Contract: {contract[:20]}...")
    except Exception as ex:
        log.warning(f"Etherscan error: {ex}")

# ─── MONITOR 8: BLUR TRENDING ─────────────────────────────
def check_blur_trending():
    log.info("Checking Blur.io trending...")
    try:
        r = requests.get(
            "https://core-api.prod.blur.io/v1/collections/?filters=%7B%22sort%22%3A%22VOLUME_ONE_DAY%22%2C%22order%22%3A%22DESC%22%7D",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=15
        )
        data = r.json()
        for col in data.get("collections", [])[:8]:
            name   = col.get("name", "")
            slug   = col.get("collectionSlug", "")
            floor  = col.get("floorPrice", {}).get("amount", "?")
            volume = col.get("volumeOneDay", {}).get("amount", "?")
            link   = f"https://blur.io/collection/{slug}"
            key    = f"blur_{slug}_{datetime.now().strftime('%Y-%m-%d')}"
            if name and is_new(key):
                alert("blur", f"{name} — Floor: {floor} ETH | 24h Vol: {volume} ETH", link, "Blur.io")
    except Exception as ex:
        log.warning(f"Blur error: {ex}")

# ─── MONITOR 9: MINTYSCORE ────────────────────────────────
def check_mintyscore():
    log.info("Checking MINTYscore...")
    try:
        r = requests.get("https://mintyscore.com/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("a[href]")[:20]:
            href = card.get("href", "")
            if not href or href == "#":
                continue
            text = card.get_text(separator=" ", strip=True)
            if len(text) < 5:
                continue
            full_url = href if href.startswith("http") else f"https://mintyscore.com{href}"
            if is_new(f"minty_{text[:60]}"):
                alert("upcoming", f"Upcoming Mint: {text[:80]}", full_url, "MINTYscore")
    except Exception as ex:
        log.warning(f"MINTYscore error: {ex}")

# ─── COMMAND HANDLER ──────────────────────────────────────
last_update_id = None

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 5}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=10)
        return r.json().get("result", [])
    except:
        return []

def handle_commands():
    global last_update_id
    updates = get_updates(offset=last_update_id + 1 if last_update_id else None)
    for update in updates:
        last_update_id = update["update_id"]
        msg     = update.get("message", {})
        text    = msg.get("text", "").strip().lower()
        user_id = str(msg.get("chat", {}).get("id", ""))

        if user_id != CHAT_ID:
            continue

        if text == "/run":
            send("⚡ *Manual scan triggered!* Running now...")
            run_cycle()
            send("✅ Scan complete!")

        elif text == "/status":
            send(
                "🟢 *Bot Status: ONLINE*\n\n"
                f"⏰ Time: `{datetime.now().strftime('%H:%M • %d %b %Y')}`\n"
                f"📦 Seen cache: `{len(seen)} entries`\n"
                f"⏱ Auto-scan: every `{CHECK_INTERVAL_MINUTES} mins`\n"
                f"🐦 X scan: every `{X_CHECK_INTERVAL} mins`\n"
                "🔁 GitHub Actions: every 6hrs"
            )

        elif text == "/opensea":
            send("🌊 *Fetching OpenSea — Minting Now & Trending...*")
            check_opensea_minting_now()
            check_opensea_trending()
            send("✅ OpenSea check done! See alerts above.")

        elif text == "/etherscan":
            send("⚡ *Fetching latest NFT contracts on Etherscan...*")
            check_new_eth_contracts()
            send("✅ Etherscan check done! See alerts above.")

        elif text == "/xstatus":
            send("🐦 *Checking X feeds...*")
            results = []
            for name, url in X_FEEDS:
                try:
                    feed  = feedparser.parse(url)
                    count = len(feed.entries)
                    latest = feed.entries[0].get("title", "N/A")[:50] if feed.entries else "N/A"
                    results.append(f"✅ *{name}*: `{count} posts`\n   Latest: _{latest}_")
                except:
                    results.append(f"❌ *{name}*: unreachable")
            send("🐦 *X Feed Status:*\n\n" + "\n\n".join(results))

        elif text == "/help":
            send(
                "🤖 *Commands:*\n\n"
                "/run — Full manual scan\n"
                "/status — Bot health & stats\n"
                "/opensea — OpenSea minting now + trending\n"
                "/etherscan — New NFT contracts on ETH\n"
                "/xstatus — X feed status & latest posts\n"
                "/help — This menu"
            )

# ─── SET BOT COMMANDS ─────────────────────────────────────
def set_bot_commands():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
    commands = [
        {"command": "run",        "description": "Full manual scan now"},
        {"command": "status",     "description": "Bot health & stats"},
        {"command": "opensea",    "description": "OpenSea minting now + trending"},
        {"command": "etherscan",  "description": "New NFT contracts on Etherscan"},
        {"command": "xstatus",    "description": "X feed status & latest posts"},
        {"command": "help",       "description": "Show all commands"},
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=10)
        log.info("Bot commands set.")
    except Exception as e:
        log.warning(f"Could not set commands: {e}")

# ─── MAIN CYCLES ──────────────────────────────────────────
def run_cycle():
    log.info("=" * 40)
    log.info("Running main cycle v7...")
    check_rss()
    check_nitter()
    check_opensea_minting_now()
    check_opensea_trending()
    check_opensea_movers()
    check_new_eth_contracts()
    check_blur_trending()
    check_mintyscore()
    send_cycle_summary()
    log.info("Main cycle complete.")

def run_x_cycle():
    log.info("Running X feed cycle...")
    check_x_feeds()
    send_cycle_summary()
    log.info("X cycle complete.")

def main():
    log.info("Bot v7 starting...")
    set_bot_commands()
    send(
        "🤖 *Web3 Watcher Bot v8 is online!*\n\n"
        "Monitoring:\n"
        "🐦 X: WL/Collab/Free Mint alerts (every 30 mins)\n"
        "🌊 OpenSea: Minting Now + Trending + Movers\n"
        "⚡ New ETH NFT contracts (Etherscan)\n"
        "📅 Upcoming mints (MINTYscore)\n"
        "🔥 Blur.io trending\n"
        "🧠 NFT KOL tweets\n\n"
        "Commands: /run /opensea /etherscan /xstatus /status /help"
    )
    run_cycle()
    run_x_cycle()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_cycle)
    schedule.every(X_CHECK_INTERVAL).minutes.do(run_x_cycle)
    schedule.every(1).minutes.do(handle_commands)

    while True:
        schedule.run_pending()
        time.sleep(10)

if __name__ == "__main__":
    main()
