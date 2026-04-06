"""
Web3 Watcher Bot v3 — justFranknftbot
Added: OpenSea Drops scraper, floor price movers, NFT KOL Twitter accounts
"""

import time
import hashlib
import logging
import json
import os
import schedule
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# ─── CONFIG ───────────────────────────────────────────────
BOT_TOKEN = "8680806881:AAGf2HGf0_EdjehNOtDie0ZVBNp6W_ksxNE"
CHAT_ID   = "1836559698"
CHECK_INTERVAL_MINUTES = 15
SEEN_FILE = "seen_cache.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ─── STRICT KEYWORDS ──────────────────────────────────────
NFT_KEYWORDS = [
    "nft drop", "nft launch", "nft mint", "new nft", "nft collection",
    "pfp drop", "free mint", "mint is live", "minting now", "nft release"
]
WHITELIST_KEYWORDS = [
    "whitelist", "allowlist", "wl drop", "og list", "presale open",
    "wl open", "wl spots", "allowlist open", "mint pass"
]
JOB_KEYWORDS = [
    "web3 job", "crypto job", "solidity developer", "nft developer",
    "blockchain engineer", "dao contributor", "remote web3", "hiring web3",
    "web3 hiring", "smart contract developer"
]
PROJECT_KEYWORDS = [
    "stealth launch", "just deployed", "new collection dropping",
    "new nft project", "launching today", "drop today"
]

# ─── NFT RSS FEEDS ────────────────────────────────────────
RSS_FEEDS = [
    ("NFT Evening",  "https://nftevening.com/feed/"),
    ("NFT Now",      "https://nftnow.com/feed/"),
    ("Decrypt",      "https://decrypt.co/feed"),
    ("BeInCrypto",   "https://beincrypto.com/feed/"),
]

# ─── NITTER INSTANCES ─────────────────────────────────────
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.pussthecat.org",
]

# ─── TWITTER ACCOUNTS (KOLs + Alert accounts) ─────────────
TWITTER_ACCOUNTS = [
    # Alert bots
    "NFTdrop",
    "NFTDropAlert",
    "WhitelistAlerts",
    "nftcalendar",
    # NFT KOLs
    "beaniemaxi",
    "punk6529",
    "NFT_GOD",
    "garyvee",
    "Zeneca_33",
    "iamDCinvestor",
    # Web3 jobs
    "web3jobs",
    "cryptojobslist",
]

# ─── PERSISTENT SEEN CACHE ────────────────────────────────
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
    handlers=[
        logging.FileHandler("web3_bot.log"),
        logging.StreamHandler()
    ]
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

# ─── MONITOR 1: RSS FEEDS ─────────────────────────────────
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

# ─── MONITOR 2: NITTER / KOL TWEETS ──────────────────────
def check_nitter():
    log.info("Checking Nitter (KOLs + alerts)...")
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

        # Find drop items — look for links with collection paths
        drop_links = soup.find_all("a", href=True)
        seen_slugs = set()

        for a in drop_links:
            href = a.get("href", "")
            if "/collection/" not in href or "/overview" not in href:
                continue
            slug = href.split("/collection/")[-1].replace("/overview", "")
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            text = a.get_text(separator=" ", strip=True)
            title = text[:120] if text else slug

            # Check for minting status in surrounding text
            parent_text = ""
            if a.parent:
                parent_text = a.parent.get_text(separator=" ", strip=True).lower()

            status = "🟢 Minting Now" if "minting now" in parent_text else "🔜 Upcoming Drop"
            full_title = f"{status} — {title}"
            link = f"https://opensea.io/collection/{slug}/overview"

            if is_new(f"opensea_{slug}"):
                alert("opensea", full_title, link, "OpenSea Drops")

    except Exception as ex:
        log.warning(f"OpenSea drops error: {ex}")

# ─── MONITOR 4: OPENSEA TOP MOVERS ───────────────────────
def check_opensea_movers():
    log.info("Checking OpenSea floor movers...")
    try:
        r = requests.get("https://opensea.io/", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Look for percentage changes in top movers section
        links = soup.find_all("a", href=True)
        for a in links:
            href = a.get("href", "")
            if "/collection/" not in href:
                continue
            text = a.get_text(separator=" ", strip=True)

            # Find entries with large % changes (>50%)
            import re
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

# ─── MAIN CYCLE ───────────────────────────────────────────
def run_cycle():
    log.info("=" * 40)
    log.info("Running watch cycle v3...")
    check_rss()
    check_nitter()
    check_opensea_drops()
    check_opensea_movers()
    log.info("Cycle complete.")

def main():
    log.info("Bot v3 starting...")
    send(
        "🤖 *Web3 Watcher Bot v3 is online!*\n\n"
        "Now monitoring:\n"
        "🖼 NFT drops & launches\n"
        "🎯 Whitelist / allowlist opens\n"
        "🌊 OpenSea drops (live + upcoming)\n"
        "📈 Floor price movers (50%+)\n"
        "💼 Web3 jobs\n"
        "🧠 NFT KOL tweets (punk6529, beanie, NFT_GOD...)\n\n"
        "_justFranknftbot v3 — watching everything_ 👀"
    )

    run_cycle()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_cycle)

    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
