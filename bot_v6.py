"""
Web3 Watcher Bot v4 — justFranknftbot
Added: Etherscan new ERC-721 contracts, Minty Score upcoming mints, Blur.io trending
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
BOT_TOKEN        = "8680806881:AAGf2HGf0_EdjehNOtDie0ZVBNp6W_ksxNE"
CHAT_ID          = "1836559698"
CHECK_INTERVAL_MINUTES = 15
SEEN_FILE        = "seen_cache.json"
ETHERSCAN_API    = "https://api.etherscan.io/api"  # free, no key needed for basic calls

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

# ─── RSS FEEDS ────────────────────────────────────────────
RSS_FEEDS = [
    ("NFT Evening",  "https://nftevening.com/feed/"),
    ("NFT Now",      "https://nftnow.com/feed/"),
    ("Decrypt",      "https://decrypt.co/feed"),
    ("BeInCrypto",   "https://beincrypto.com/feed/"),
    # ── X/Twitter Search Feeds (via rss.app) ──
    ("X: WL/Collab Alerts",  "https://rss.app/feeds/ZF8us3eIdkhMU7bF.xml"),
    ("X: Free Mint ETH",     "https://rss.app/feeds/nUafp1OUmSQhuLqX.xml"),
    ("X: Early NFT Alpha",   "https://rss.app/feeds/knbtLb0iKoYYLcjw.xml"),
]

# ─── NITTER + KOL ACCOUNTS ────────────────────────────────
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
    t = text.lower()
    return any(k in t for k in keywords)

def categorize(title, summary=""):
    full = f"{title} {summary}".lower()
    if matches_strict(full, WHITELIST_KEYWORDS): return "whitelist"
    if matches_strict(full, JOB_KEYWORDS):       return "job"
    if matches_strict(full, NFT_KEYWORDS):       return "nft"
    if matches_strict(full, PROJECT_KEYWORDS):   return "project"
    return None

CATEGORY_META = {
    "whitelist": ("🎯", "WHITELIST / ALLOWLIST"),
    "job":       ("💼", "WEB3 JOB"),
    "nft":       ("🖼", "NFT DROP"),
    "project":   ("🚀", "NEW PROJECT"),
    "opensea":   ("🌊", "OPENSEA DROP"),
    "mover":     ("📈", "FLOOR PRICE MOVER"),
    "newcontract": ("⚡", "NEW ETH NFT CONTRACT"),
    "upcoming":  ("📅", "UPCOMING MINT"),
    "blur":      ("🔥", "BLUR TRENDING"),
}

def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }, timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Send error: {e}")

def alert(category, title, url, source, snippet=""):
    emoji, label = CATEGORY_META.get(category, ("📢", "ALERT"))
    snip = f"\n_{snippet[:180]}..._" if snippet else ""
    msg = (
        f"{emoji} *{label}*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"*{title[:120]}*"
        f"{snip}\n\n"
        f"🔗 [Read more]({url})\n"
        f"📡 `{source}`\n"
        f"⏰ `{datetime.now().strftime('%H:%M • %d %b %Y')}`"
    )
    send(msg)
    log.info(f"Alerted [{category}] {title[:60]}")

# ─── MONITOR 1: RSS ───────────────────────────────────────
def check_rss():
    log.info("Checking RSS feeds...")
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

# ─── MONITOR 2: NITTER KOLs ───────────────────────────────
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

# ─── MONITOR 3: OPENSEA DROPS ─────────────────────────────
def check_opensea_drops():
    log.info("Checking OpenSea Drops...")
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
            text = a.get_text(separator=" ", strip=True)
            title = text[:120] if text else slug
            parent_text = a.parent.get_text(separator=" ", strip=True).lower() if a.parent else ""
            status = "🟢 Minting Now" if "minting now" in parent_text else "🔜 Upcoming"
            link = f"https://opensea.io/collection/{slug}/overview"
            if is_new(f"opensea_{slug}"):
                alert("opensea", f"{status} — {title}", link, "OpenSea Drops")
    except Exception as ex:
        log.warning(f"OpenSea drops error: {ex}")

# ─── MONITOR 4: OPENSEA FLOOR MOVERS ─────────────────────
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
                    slug = href.split("/collection/")[-1].split("/")[0]
                    title = f"{slug.replace('-', ' ').title()} floor moved {m}% today"
                    link  = f"https://opensea.io/collection/{slug}"
                    if is_new(f"mover_{slug}_{m}"):
                        alert("mover", title, link, "OpenSea Trending")
    except Exception as ex:
        log.warning(f"OpenSea movers error: {ex}")

# ─── MONITOR 5: ETHERSCAN NEW ERC-721 CONTRACTS ───────────
def check_new_eth_contracts():
    log.info("Checking Etherscan for new ERC-721 contracts...")
    try:
        # Get latest verified ERC-721 contract deployments
        params = {
            "module": "account",
            "action": "tokentx",
            "contractaddress": "0x0000000000000000000000000000000000000000",
            "page": 1,
            "offset": 20,
            "sort": "desc",
            "apikey": "YourApiKeyToken"  # works without key at low rate
        }
        # Use the token tracker endpoint instead
        r = requests.get(
            "https://etherscan.io/tokens?q=nft&t=1",
            headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(r.text, "html.parser")

        rows = soup.select("table tbody tr")
        for row in rows[:10]:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            name_el = row.find("a", href=True)
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            href = name_el.get("href", "")
            contract = href.split("/token/")[-1].split("?")[0] if "/token/" in href else ""
            if not contract or not is_new(f"ethcontract_{contract}"):
                continue
            link = f"https://etherscan.io/token/{contract}"
            alert(
                "newcontract",
                f"New ETH NFT: {name}",
                link,
                "Etherscan",
                f"Contract: {contract[:20]}..."
            )
    except Exception as ex:
        log.warning(f"Etherscan error: {ex}")

# ─── MONITOR 6: MINTYSCORE UPCOMING MINTS ────────────────
def check_mintyscore():
    log.info("Checking MINTYscore upcoming mints...")
    try:
        r = requests.get("https://mintyscore.com/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Look for project cards/links
        cards = soup.select("a[href]")
        for card in cards[:20]:
            href = card.get("href", "")
            if not href or href == "#" or "http" not in href and "/" not in href:
                continue
            text = card.get_text(separator=" ", strip=True)
            if len(text) < 5:
                continue
            full_url = href if href.startswith("http") else f"https://mintyscore.com{href}"
            key = f"minty_{text[:60]}"
            if is_new(key):
                alert("upcoming", f"Upcoming Mint: {text[:80]}", full_url, "MINTYscore")
    except Exception as ex:
        log.warning(f"MINTYscore error: {ex}")

# ─── MONITOR 7: BLUR.IO TRENDING ─────────────────────────
def check_blur_trending():
    log.info("Checking Blur.io trending...")
    try:
        # Blur has a public API for collections
        r = requests.get(
            "https://core-api.prod.blur.io/v1/collections/?filters=%7B%22sort%22%3A%22VOLUME_ONE_DAY%22%2C%22order%22%3A%22DESC%22%7D",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=15
        )
        data = r.json()
        collections = data.get("collections", [])[:10]
        for col in collections:
            name     = col.get("name", "")
            slug     = col.get("collectionSlug", "")
            floor    = col.get("floorPrice", {}).get("amount", "?")
            volume   = col.get("volumeOneDay", {}).get("amount", "?")
            link     = f"https://blur.io/collection/{slug}"
            key      = f"blur_{slug}_{datetime.now().strftime('%Y-%m-%d')}"
            if name and is_new(key):
                alert(
                    "blur",
                    f"{name} — Floor: {floor} ETH | 24h Vol: {volume} ETH",
                    link,
                    "Blur.io"
                )
    except Exception as ex:
        log.warning(f"Blur error: {ex}")

# ─── MAIN CYCLE ───────────────────────────────────────────
def run_cycle():
    log.info("=" * 40)
    log.info("Running watch cycle v6...")
    check_rss()
    check_nitter()
    check_opensea_drops()
    check_opensea_movers()
    check_new_eth_contracts()
    check_mintyscore()
    check_blur_trending()
    log.info("Cycle complete.")

# ─── COMMAND HANDLER ──────────────────────────────────────
def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 10}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=15)
        return r.json().get("result", [])
    except:
        return []

def handle_commands():
    updates = get_updates()
    if not updates:
        return None
    last_id = None
    for update in updates:
        last_id = update["update_id"]
        msg = update.get("message", {})
        text = msg.get("text", "").strip().lower()
        user_id = str(msg.get("chat", {}).get("id", ""))

        # Only respond to your own chat
        if user_id != CHAT_ID:
            continue

        if text == "/run":
            send("⚡ *Manual scan triggered!* Running now...")
            run_cycle()
            send("✅ Scan complete! Check above for any new alerts.")

        elif text == "/status":
            send(
                "🟢 *Bot Status: ONLINE*\n\n"
                f"⏰ Last checked: `{datetime.now().strftime('%H:%M • %d %b %Y')}`\n"
                f"📦 Seen cache: `{len(seen)} entries`\n"
                f"⏱ Auto-scan every: `{CHECK_INTERVAL_MINUTES} mins`\n"
                "🔁 GitHub Actions: Running every 6hrs"
            )

        elif text == "/opensea":
            send("🌊 *Checking OpenSea now...*")
            try:
                r = requests.get("https://opensea.io/drops", headers=HEADERS, timeout=10)
                send(f"🌊 OpenSea status: `{'✅ Online' if r.status_code == 200 else '❌ Down'}`\n"
                     f"Response: `{r.status_code}`")
            except Exception as e:
                send(f"❌ OpenSea unreachable: `{e}`")

        elif text == "/xstatus":
            send("🐦 *Checking X feeds now...*")
            results = []
            x_feeds = [
                ("WL/Collab", "https://rss.app/feeds/ZF8us3eIdkhMU7bF.xml"),
                ("Free Mint",  "https://rss.app/feeds/nUafp1OUmSQhuLqX.xml"),
                ("Early Alpha","https://rss.app/feeds/knbtLb0iKoYYLcjw.xml"),
            ]
            for name, url in x_feeds:
                try:
                    feed = feedparser.parse(url)
                    count = len(feed.entries)
                    results.append(f"✅ {name}: `{count} posts`")
                except:
                    results.append(f"❌ {name}: unreachable")
            send("🐦 *X Feed Status:*\n" + "\n".join(results))

        elif text == "/help":
            send(
                "🤖 *Available Commands:*\n\n"
                "/run — Trigger manual scan now\n"
                "/status — Check bot health\n"
                "/opensea — Check OpenSea connectivity\n"
                "/xstatus — Check X RSS feeds\n"
                "/help — Show this menu"
            )

    # Mark all updates as read
    if last_id:
        get_updates(offset=last_id + 1)

# ─── SET BOT COMMANDS MENU ────────────────────────────────
def set_bot_commands():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
    commands = [
        {"command": "run",      "description": "Trigger manual scan now"},
        {"command": "status",   "description": "Check bot health & stats"},
        {"command": "opensea",  "description": "Check OpenSea connectivity"},
        {"command": "xstatus",  "description": "Check X RSS feed status"},
        {"command": "help",     "description": "Show all commands"},
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=10)
        log.info("Bot commands menu set.")
    except Exception as e:
        log.warning(f"Could not set commands: {e}")

def main():
    log.info("Bot v6 starting...")
    set_bot_commands()
    send(
        "🤖 *Web3 Watcher Bot v6 is online!*\n\n"
        "Monitoring:\n"
        "🎯 WL/Collab alerts from X\n"
        "🆓 Free mint alerts from X\n"
        "🔍 Early NFT alpha from X\n"
        "🌊 OpenSea drops & movers\n"
        "⚡ New ETH NFT contracts\n"
        "📅 Upcoming mints\n"
        "🔥 Blur.io trending\n\n"
        "Commands: /run /status /opensea /xstatus /help"
    )
    run_cycle()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_cycle)
    schedule.every(1).minutes.do(handle_commands)
    while True:
        schedule.run_pending()
        time.sleep(10)

if __name__ == "__main__":
    main()
