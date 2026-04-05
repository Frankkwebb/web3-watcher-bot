"""
Web3 Watcher Bot — justFranknftbot
Monitors crypto news + Twitter (via Nitter) for:
- NFT launches
- Whitelist/allowlist drops
- Web3 jobs
- New crypto project accounts

Run: python bot.py
"""

import time
import hashlib
import logging
import schedule
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# ─── CONFIG (pre-filled) ──────────────────────────────────
BOT_TOKEN = "8680806881:AAGf2HGf0_EdjehNOtDie0ZVBNp6W_ksxNE"
CHAT_ID   = "1836559698"
CHECK_INTERVAL_MINUTES = 15

# ─── KEYWORDS ─────────────────────────────────────────────
NFT_KEYWORDS       = ["nft", "mint", "collection", "pfp", "generative", "nft drop", "nft launch"]
WHITELIST_KEYWORDS = ["whitelist", "allowlist", "wl drop", "free mint", "og list", "presale", "wl open"]
JOB_KEYWORDS       = ["web3 job", "crypto job", "solidity developer", "nft developer",
                       "blockchain engineer", "dao contributor", "remote web3", "hiring web3"]
PROJECT_KEYWORDS   = ["new project", "just launched", "stealth launch", "new protocol",
                      "introducing", "just deployed", "new collection"]

# ─── RSS FEEDS ────────────────────────────────────────────
RSS_FEEDS = [
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt",       "https://decrypt.co/feed"),
    ("NFT Evening",   "https://nftevening.com/feed/"),
    ("The Block",     "https://www.theblock.co/rss.xml"),
    ("BeInCrypto",    "https://beincrypto.com/feed/"),
]

# ─── NITTER INSTANCES (free Twitter mirror) ───────────────
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.pussthecat.org",
]

TWITTER_ACCOUNTS = [
    "NFTdrop",
    "nftcalendar",
    "web3jobs",
    "cryptojobslist",
    "NFTDropAlert",
    "WhitelistAlerts",
]

# ─── SEEN CACHE ───────────────────────────────────────────
seen = set()

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
    return True

def matches(text, keywords):
    t = text.lower()
    return any(k in t for k in keywords)

def categorize(title, summary=""):
    full = f"{title} {summary}"
    if matches(full, WHITELIST_KEYWORDS): return "whitelist"
    if matches(full, JOB_KEYWORDS):       return "job"
    if matches(full, NFT_KEYWORDS):       return "nft"
    if matches(full, PROJECT_KEYWORDS):   return "project"
    return None

CATEGORY_META = {
    "whitelist": ("🎯", "WHITELIST / ALLOWLIST"),
    "job":       ("💼", "WEB3 JOB"),
    "nft":       ("🖼", "NFT LAUNCH"),
    "project":   ("🚀", "NEW PROJECT"),
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

# ─── MONITORS ─────────────────────────────────────────────
def check_rss():
    log.info("Checking RSS feeds...")
    for name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:8]:
                title   = e.get("title", "")
                link    = e.get("link", "")
                summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text()
                key     = title + link
                if not is_new(key): continue
                cat = categorize(title, summary)
                if cat:
                    alert(cat, title, link, name, summary[:200])
        except Exception as ex:
            log.warning(f"RSS error ({name}): {ex}")

def check_nitter():
    log.info("Checking Nitter (Twitter)...")
    for account in TWITTER_ACCOUNTS:
        for instance in NITTER_INSTANCES:
            try:
                feed = feedparser.parse(f"{instance}/{account}/rss")
                if not feed.entries:
                    continue
                for e in feed.entries[:5]:
                    title = e.get("title", "")
                    link  = e.get("link", "").replace(instance, "https://twitter.com")
                    key   = account + title
                    if not is_new(key): continue
                    cat = categorize(title)
                    if cat:
                        alert(cat, f"@{account}: {title[:80]}", link, f"X/@{account}")
                break
            except Exception as ex:
                log.warning(f"Nitter error ({instance}/{account}): {ex}")

def check_nft_calendar():
    log.info("Checking NFT Calendar...")
    try:
        r = requests.get("https://nftcalendar.io/", timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select("article, .event-item")[:8]:
            title = item.get_text(strip=True)[:120]
            if len(title) > 10 and is_new(title):
                alert("nft", title, "https://nftcalendar.io/", "NFT Calendar")
    except Exception as ex:
        log.warning(f"NFT Calendar error: {ex}")

def run_cycle():
    log.info("=" * 40)
    log.info("Running watch cycle...")
    check_rss()
    check_nitter()
    check_nft_calendar()
    log.info("Cycle complete.")

# ─── MAIN ─────────────────────────────────────────────────
def main():
    log.info("Bot starting...")
    send(
        "🤖 *Web3 Watcher Bot is online\!*\n\n"
        "Monitoring every 15 mins for:\n"
        "🖼 NFT launches\n"
        "🎯 Whitelist drops\n"
        "💼 Web3 jobs\n"
        "🚀 New projects\n\n"
        "_justFranknftbot is watching the market for you_ 👀"
    )

    run_cycle()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_cycle)

    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
