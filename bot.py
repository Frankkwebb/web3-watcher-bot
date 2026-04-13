"""
Web3 Watcher Bot v10 — justFranknftbot
- Digest format: one clean summary message per cycle
- English-only filter for X posts
- Dual Chat ID support
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
CHAT_IDS               = ["1836559698", "6343548108", "6788177449"]  # Main + second account
CHECK_INTERVAL_MINUTES = 15
X_CHECK_INTERVAL       = 30
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

# ─── NON-ENGLISH INDICATORS ───────────────────────────────
NON_ENGLISH_PATTERNS = [
    r'[\u4e00-\u9fff]',   # Chinese
    r'[\u3040-\u30ff]',   # Japanese
    r'[\uac00-\ud7af]',   # Korean
    r'[\u0600-\u06ff]',   # Arabic
    r'[\u0400-\u04ff]',   # Cyrillic (Russian etc)
    r'[\u0e00-\u0e7f]',   # Thai
    r'[\u0900-\u097f]',   # Hindi/Devanagari
]

def is_english(text):
    for pattern in NON_ENGLISH_PATTERNS:
        if re.search(pattern, text):
            return False
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    total_chars   = len(text.replace(" ", ""))
    if total_chars == 0:
        return True
    return (english_chars / total_chars) >= 0.5

# ─── RSS + X FEEDS ────────────────────────────────────────
RSS_FEEDS = [
    ("NFT Evening", "https://nftevening.com/feed/"),
    ("NFT Now",     "https://nftnow.com/feed/"),
    ("Decrypt",     "https://decrypt.co/feed"),
    ("BeInCrypto",  "https://beincrypto.com/feed/"),
]
X_FEEDS = [
    ("X: WL/Collab",    "https://rss.app/feeds/ZF8us3eIdkhMU7bF.xml"),
    ("X: Free Mint ETH","https://rss.app/feeds/nUafp1OUmSQhuLqX.xml"),
    ("X: NFT Alpha",    "https://rss.app/feeds/knbtLb0iKoYYLcjw.xml"),
]
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.pussthecat.org",
]
TWITTER_ACCOUNTS = [
    "NFTdrop", "NFTDropAlert", "WhitelistAlerts", "nftcalendar",
    "beaniemaxi", "punk6529", "NFT_GOD", "garyvee", "Zeneca_33",
    "iamDCinvestor",
]

CATEGORY_META = {
    "whitelist":   ("🎯", "WHITELIST / ALLOWLIST"),
    "job":         ("💼", "WEB3 JOB"),
    "nft":         ("🖼", "NFT DROP"),
    "project":     ("🚀", "NEW PROJECT"),
    "opensea":     ("🌊", "OPENSEA DROP"),
    "mover":       ("📈", "FLOOR MOVER"),
    "newcontract": ("⚡", "NEW ETH CONTRACT"),
    "upcoming":    ("📅", "UPCOMING MINT"),
    "blur":        ("🔥", "BLUR TRENDING"),
    "x_alert":     ("🐦", "X ALERT"),
}

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

# ─── DIGEST BUFFER ────────────────────────────────────────
digest = {}  # {label: [(title, url, source, snippet)]}

# ─── HELPERS ──────────────────────────────────────────────
def is_new(text):
    h = hashlib.md5(text.encode()).hexdigest()
    if h in seen:
        return False
    seen.add(h)
    save_seen(seen)
    return True

def is_fresh(entry, hours=24):
    for field in ["published", "updated"]:
        val = entry.get(field)
        if val:
            try:
                pub = parsedate_to_datetime(val)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
                return age <= hours
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

def shorten(url):
    try:
        r = requests.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=5)
        if r.status_code == 200 and r.text.startswith("http"):
            return r.text.strip()
    except:
        pass
    return url

# ─── SEND TO ALL CHAT IDs ────────────────────────────────
def send(text, chat_id=None):
    targets = [chat_id] if chat_id else CHAT_IDS
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for cid in targets:
        try:
            r = requests.post(api_url, json={
                "chat_id": cid,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }, timeout=10)
            r.raise_for_status()
        except Exception as e:
            log.error(f"Send error to {cid}: {e}")

# ─── ADD TO DIGEST ────────────────────────────────────────
def add_to_digest(category, title, url, source, snippet=""):
    emoji, label = CATEGORY_META.get(category, ("📢", "ALERT"))
    short_url    = shorten(url)
    key          = f"{emoji} {label}"
    if key not in digest:
        digest[key] = []
    digest[key].append({
        "title": title[:80],
        "url": short_url,
        "source": source,
        "snippet": snippet[:100]
    })
    log.info(f"Buffered [{category}] {title[:60]}")

# ─── SEND DIGEST ──────────────────────────────────────────
def send_digest(cycle_name="Scan"):
    now   = datetime.now().strftime("%H:%M • %d %b %Y")
    total = sum(len(v) for v in digest.values())

    if not digest or total == 0:
        send(
            f"📋 *{cycle_name} — {now}*\n"
            f"{'━' * 18}\n"
            "No new alerts this cycle. Bot is watching all sources — you'll be notified the moment something drops. 👀\n"
            f"{'─' * 18}"
        )
        digest.clear()
        return

    # Build digest message
    msg = (
        f"📋 *{cycle_name} Digest — {now}*\n"
        f"{'━' * 18}\n"
        f"Found *{total} new alert(s)* across *{len(digest)} categories*\n\n"
    )

    for label, items in digest.items():
        msg += f"{label} *({len(items)})*\n"
        for item in items:  # show ALL items
            msg += f"• {item['title']}\n  {item['url']}\n"
        msg += "\n"
        # Split and send if message getting long
        if len(msg) > 3000:
            send(msg)
            msg = ""

    # Summary paragraph
    msg += f"{'─' * 18}\n"
    if "🎯 WHITELIST / ALLOWLIST" in digest:
        msg += f"⚡ *{len(digest['🎯 WHITELIST / ALLOWLIST'])} WL spot(s)* open — act fast!\n"
    if "🖼 NFT DROP" in digest:
        msg += f"🖼 *{len(digest['🖼 NFT DROP'])} NFT drop(s)* — verify before minting.\n"
    if "🌊 OPENSEA DROP" in digest:
        msg += f"🌊 *{len(digest['🌊 OPENSEA DROP'])} OpenSea drop(s)* — some minting now.\n"
    msg += "\n_In NFTs, minutes matter. Move fast!_ 🚀"

    send(msg)
    digest.clear()

# ─── MONITORS ─────────────────────────────────────────────
def check_rss():
    log.info("Checking RSS...")
    for name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:10]:
                title   = e.get("title", "")
                link    = e.get("link", "")
                summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text()
                if not is_new(link or title): continue
                if not is_fresh(e): continue
                if not is_english(title + summary): continue
                cat = categorize(title, summary)
                if cat:
                    add_to_digest(cat, title, link, name, summary[:150])
        except Exception as ex:
            log.warning(f"RSS error ({name}): {ex}")

def check_x_feeds():
    log.info("Checking X feeds...")
    for name, url in X_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:15]:
                title   = e.get("title", "")
                link    = e.get("link", "")
                summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text()
                if not is_new(link or title): continue
                if not is_fresh(e, hours=2): continue
                if not is_english(title + summary): continue  # English filter
                cat = categorize(title, summary) or "x_alert"
                add_to_digest(cat, title, link, name, summary[:150])
        except Exception as ex:
            log.warning(f"X feed error ({name}): {ex}")

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
                    if not is_english(title): continue
                    cat = categorize(title)
                    if cat:
                        add_to_digest(cat, f"@{account}: {title[:70]}", link, f"X/@{account}")
                break
            except Exception as ex:
                log.warning(f"Nitter error ({instance}/{account}): {ex}")

def check_opensea_minting_now():
    log.info("Checking OpenSea Minting Now...")
    try:
        r = requests.get("https://opensea.io/drops", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        seen_slugs = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/collection/" not in href or "/overview" not in href:
                continue
            slug = href.split("/collection/")[-1].replace("/overview", "")
            if slug in seen_slugs: continue
            seen_slugs.add(slug)
            parent_text = a.parent.get_text(separator=" ", strip=True).lower() if a.parent else ""
            if "minting now" not in parent_text: continue
            text  = a.get_text(separator=" ", strip=True)
            title = text[:80] if text else slug
            link  = f"https://opensea.io/collection/{slug}/overview"
            if is_new(f"os_minting_{slug}"):
                add_to_digest("opensea", f"🟢 Minting Now: {title}", link, "OpenSea")
    except Exception as ex:
        log.warning(f"OpenSea minting error: {ex}")

def check_opensea_trending():
    log.info("Checking OpenSea Trending...")
    try:
        r = requests.get("https://opensea.io/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        seen_slugs = set()
        count = 0
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/collection/" not in href: continue
            slug = href.split("/collection/")[-1].split("/")[0]
            if not slug or slug in seen_slugs: continue
            seen_slugs.add(slug)
            text = a.get_text(separator=" ", strip=True)
            if "ETH" not in text and "USDC" not in text: continue
            title = f"Trending: {slug.replace('-', ' ').title()} — {text[:50]}"
            link  = f"https://opensea.io/collection/{slug}"
            key   = f"os_trending_{slug}_{datetime.now().strftime('%Y-%m-%d')}"
            if is_new(key):
                add_to_digest("opensea", title, link, "OpenSea Trending")
                count += 1
                if count >= 5: break
    except Exception as ex:
        log.warning(f"OpenSea trending error: {ex}")

def check_opensea_movers():
    log.info("Checking OpenSea Movers...")
    try:
        r = requests.get("https://opensea.io/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/collection/" not in href: continue
            text = a.get_text(separator=" ", strip=True)
            for m in re.findall(r'([+-]\d+\.?\d*)%', text):
                if abs(float(m)) >= 50:
                    slug  = href.split("/collection/")[-1].split("/")[0]
                    title = f"{slug.replace('-', ' ').title()} moved {m}% today"
                    link  = f"https://opensea.io/collection/{slug}"
                    if is_new(f"mover_{slug}_{m}"):
                        add_to_digest("mover", title, link, "OpenSea")
    except Exception as ex:
        log.warning(f"OpenSea movers error: {ex}")

def check_new_eth_contracts():
    log.info("Checking Etherscan...")
    try:
        r    = requests.get("https://etherscan.io/tokens?q=nft&t=1", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select("table tbody tr")[:10]:
            name_el  = row.find("a", href=True)
            if not name_el: continue
            name     = name_el.get_text(strip=True)
            href     = name_el.get("href", "")
            contract = href.split("/token/")[-1].split("?")[0] if "/token/" in href else ""
            if not contract or not is_new(f"ethcontract_{contract}"): continue
            link = f"https://etherscan.io/token/{contract}"
            add_to_digest("newcontract", f"New ETH NFT: {name}", link, "Etherscan", f"Contract: {contract[:20]}")
    except Exception as ex:
        log.warning(f"Etherscan error: {ex}")

def check_blur_trending():
    log.info("Checking Blur...")
    try:
        r    = requests.get(
            "https://core-api.prod.blur.io/v1/collections/?filters=%7B%22sort%22%3A%22VOLUME_ONE_DAY%22%2C%22order%22%3A%22DESC%22%7D",
            headers={**HEADERS, "Accept": "application/json"}, timeout=15
        )
        for col in r.json().get("collections", [])[:8]:
            name   = col.get("name", "")
            slug   = col.get("collectionSlug", "")
            floor  = col.get("floorPrice", {}).get("amount", "?")
            volume = col.get("volumeOneDay", {}).get("amount", "?")
            link   = f"https://blur.io/collection/{slug}"
            key    = f"blur_{slug}_{datetime.now().strftime('%Y-%m-%d')}"
            if name and is_new(key):
                add_to_digest("blur", f"{name} — Floor: {floor} ETH | Vol: {volume} ETH", link, "Blur.io")
    except Exception as ex:
        log.warning(f"Blur error: {ex}")

def check_mintyscore():
    log.info("Checking MINTYscore...")
    try:
        r    = requests.get("https://mintyscore.com/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("a[href]")[:20]:
            href = card.get("href", "")
            if not href or href == "#": continue
            text = card.get_text(separator=" ", strip=True)
            if len(text) < 5: continue
            full_url = href if href.startswith("http") else f"https://mintyscore.com{href}"
            if is_new(f"minty_{text[:60]}"):
                add_to_digest("upcoming", f"Upcoming Mint: {text[:80]}", full_url, "MINTYscore")
    except Exception as ex:
        log.warning(f"MINTYscore error: {ex}")

# ─── COMMAND HANDLER ──────────────────────────────────────
last_update_id = None

def get_updates(offset=None):
    url    = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
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
        if user_id not in CHAT_IDS:
            continue

        if text == "/run":
            send("⚡ *Manual scan triggered!* Running now...", chat_id=user_id)
            run_cycle()

        elif text == "/status":
            send(
                f"🟢 *Bot Status: ONLINE*\n"
                f"{'━' * 18}\n"
                f"⏰ `{datetime.now().strftime('%H:%M • %d %b %Y')}`\n"
                f"📦 Cache: `{len(seen)} entries`\n"
                f"⏱ Main scan: every `{CHECK_INTERVAL_MINUTES} mins`\n"
                f"🐦 X scan: every `{X_CHECK_INTERVAL} mins`\n"
                f"👥 Authorized users: `{len(CHAT_IDS)}`\n"
                f"{'─' * 18}",
                chat_id=user_id
            )

        elif text == "/opensea":
            send("🌊 *Fetching OpenSea...*", chat_id=user_id)
            check_opensea_minting_now()
            check_opensea_trending()
            send_digest("OpenSea")

        elif text == "/etherscan":
            send("⚡ *Fetching Etherscan...*", chat_id=user_id)
            check_new_eth_contracts()
            send_digest("Etherscan")

        elif text == "/xstatus":
            results = []
            for name, url in X_FEEDS:
                try:
                    feed  = feedparser.parse(url)
                    count = len(feed.entries)
                    latest = feed.entries[0].get("title", "N/A")[:50] if feed.entries else "N/A"
                    results.append(f"✅ *{name}*: `{count} posts`\n   _{latest}_")
                except:
                    results.append(f"❌ *{name}*: unreachable")
            send("🐦 *X Feed Status:*\n\n" + "\n\n".join(results), chat_id=user_id)

        elif text == "/help":
            send(
                "🤖 *Commands:*\n"
                f"{'━' * 18}\n"
                "/run — Full manual scan\n"
                "/status — Bot health\n"
                "/opensea — OpenSea drops\n"
                "/etherscan — New NFT contracts\n"
                "/xstatus — X feed status\n"
                "/help — This menu",
                chat_id=user_id
            )

# ─── SET BOT COMMANDS ─────────────────────────────────────
def set_bot_commands():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
    commands = [
        {"command": "run",       "description": "Full manual scan now"},
        {"command": "status",    "description": "Bot health & stats"},
        {"command": "opensea",   "description": "OpenSea drops digest"},
        {"command": "etherscan", "description": "New NFT contracts"},
        {"command": "xstatus",   "description": "X feed status"},
        {"command": "help",      "description": "Show all commands"},
    ]
    try:
        requests.post(url, json={"commands": commands}, timeout=10)
    except Exception as e:
        log.warning(f"Could not set commands: {e}")

# ─── MAIN CYCLES ──────────────────────────────────────────
def run_cycle():
    log.info("=" * 40)
    log.info("Running main cycle v10...")
    check_rss()
    check_nitter()
    check_opensea_minting_now()
    check_opensea_trending()
    check_opensea_movers()
    check_new_eth_contracts()
    check_blur_trending()
    check_mintyscore()
    send_digest("Main Scan")
    log.info("Main cycle complete.")

def run_x_cycle():
    log.info("Running X cycle...")
    check_x_feeds()
    send_digest("X Feed Scan")
    log.info("X cycle complete.")

def main():
    log.info("Bot v10 starting...")
    set_bot_commands()
    send(
        "🤖 *Web3 Watcher Bot v10 is online!*\n"
        f"{'━' * 18}\n"
        "Now monitoring:\n"
        "🐦 X alerts — English only, every 30 mins\n"
        "🌊 OpenSea: Minting Now + Trending + Movers\n"
        "⚡ New ETH NFT contracts\n"
        "📅 Upcoming mints\n"
        "🔥 Blur.io trending\n\n"
        "📋 Digest format — one clean summary per cycle\n"
        f"{'─' * 18}\n"
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
