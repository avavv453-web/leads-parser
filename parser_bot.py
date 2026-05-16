import os
import time
import hashlib
import logging
import schedule
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from telegram import Bot
from telegram.error import TelegramError
import redis

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

# ===== REDIS для зберігання seen IDs (не стирається при редеплої) =====
try:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()
    USE_REDIS = True
except Exception as e:
    logging.warning(f"Redis unavailable, using file fallback: {e}")
    USE_REDIS = False

SEEN_IDS_FILE = "seen_ids.txt"
# Зберігаємо ID 30 днів (в секундах)
SEEN_TTL = 60 * 60 * 24 * 30

KEYWORDS = [
    "сайт", "лендінг", "лендинг", "посадкова сторінка", "посадочная страница",
    "розробка сайту", "зробити сайт", "потрібен сайт", "потрібний сайт",
    "інтернет магазин", "інтернет-магазин", "онлайн магазин",
    "wordpress", "вордпрес", "tilda", "тільда", "webflow", "вебфлоу",
    "сделать сайт", "нужен сайт", "разработка сайта",
    "таргет", "таргетолог", "таргетована реклама", "налаштування реклами",
    "реклама facebook", "реклама instagram", "реклама фейсбук",
    "просування", "таргетированная реклама", "настройка рекламы",
    "розсилка", "розсилання", "масова розсилка",
    "рассылка", "массовая рассылка",
    "email розсилка", "email рассылка", "email маркетинг",
    "telegram розсилка", "розсилка telegram", "розсилка телеграм",
    "tg розсилка", "telegram рассылка", "рассылка телеграм",
    "viber розсилка", "viber рассылка",
    "sms розсилка", "sms рассылка",
    "newsletter",
    "дизайн сайту", "дизайн сайта", "веб дизайн", "ui дизайн", "ux дизайн",
    "логотип", "брендинг", "фірмовий стиль", "фирменный стиль",
    "банер", "баннер", "креатив", "крео",
    "smm", "ведення соцмереж", "ведение соцсетей", "контент план",
    "landing page", "web design", "website", "web developer",
    "facebook ads", "instagram ads", "google ads", "email marketing",
    "smm manager", "graphic design", "logo design", "branding",
    "telegram bot", "chatbot", "чат-бот",
    "потрібно", "потрібен", "потрібна", "шукаю виконавця", "замовити",
    "looking for", "need a", "need someone",
    "нужен", "ищу исполнителя", "ищу подрядчика", "требуется",
]

STOP_WORDS = [
    "$/hour", "$/hr", "per hour", "hourly", "грн/год", "$/час",
    "full-time", "fulltime", "full time", "part-time", "parttime",
    "permanent", "employee", "employment",
    "join our team", "join our company", "we are hiring", "we're hiring",
    "vacancy", "вакансія", "вакансия",
    "salary", "зарплата", "оклад", "ставка",
    "i offer", "i provide", "i am offering", "my services",
    "hire me", "check my portfolio",
    "пропоную послуги", "надаю послуги", "мої послуги",
    "предлагаю услуги", "мои услуги", "предлагаю свои",
    "займ", "кредит", "казино", "ставки",
]

CHECK_INTERVAL_MINUTES = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


# ===== SEEN IDS - Redis або файл =====
def is_seen(uid):
    if USE_REDIS:
        return r.exists(f"seen:{uid}")
    if not os.path.exists(SEEN_IDS_FILE):
        return False
    with open(SEEN_IDS_FILE, "r") as f:
        return uid in f.read()

def mark_seen(uid):
    if USE_REDIS:
        r.setex(f"seen:{uid}", SEEN_TTL, "1")
    else:
        with open(SEEN_IDS_FILE, "a") as f:
            f.write(uid + "\n")

def make_id(text):
    return hashlib.md5(text.encode()).hexdigest()

def contains_keyword(text):
    t = text.lower()
    return any(kw.lower() in t for kw in KEYWORDS)

def is_spam(text):
    t = text.lower()
    return any(sw.lower() in t for sw in STOP_WORDS)

def send_to_telegram(message):
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info("Sent to Telegram")
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def format_message(source, title, description, link):
    msg = f"\U0001f514 <b>Новий запит [{source}]</b>\n\n"
    msg += f"\U0001f4cc <b>{title[:200]}</b>\n\n"
    if description and description.strip():
        desc = description.strip()[:500]
        if len(description.strip()) > 500:
            desc += "..."
        msg += f"{desc}\n\n"
    msg += f"\U0001f517 <a href='{link}'>Відкрити</a>"
    return msg

def parse_rss(source, url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"{source}: status {resp.status_code}")
            return
        root = ET.fromstring(resp.content)
        items = root.findall('.//item')
        if not items:
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            items = root.findall('.//atom:entry', ns)
        new_count = 0
        for item in items[:30]:
            title_el = item.find('title')
            link_el = item.find('link')
            desc_el = item.find('description') or item.find('summary')
            if title_el is None:
                continue
            title = (title_el.text or "").strip()
            link = ""
            if link_el is not None:
                link = link_el.text or link_el.get('href', '')
            link = (link or "").strip()
            desc = ""
            if desc_el is not None and desc_el.text:
                desc = BeautifulSoup(desc_el.text, "html.parser").get_text()
            uid = make_id(link or title)
            if is_seen(uid):
                continue
            full_text = title + " " + desc
            if contains_keyword(full_text) and not is_spam(full_text):
                send_to_telegram(format_message(source, title, desc, link))
                mark_seen(uid)
                new_count += 1
                time.sleep(2)
        logger.info(f"{source}: OK, {new_count} new")
    except Exception as e:
        logger.error(f"{source} error: {e}")

def parse_freelance_ua():
    source = "freelance.ua"
    spec_ids = [
        132, 131, 130, 129, 128, 114,  # Веб
        52, 58, 65, 49, 55, 51, 86,     # Дизайн
        136, 175, 176, 96, 98, 177, 145, 144,  # Маркетинг
        151, 152,  # Контент
    ]
    params = "&".join([f"specs[]={sid}" for sid in spec_ids])
    url = f"https://freelance.ua/ru/orders/?{params}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return
        soup = BeautifulSoup(resp.text, "html.parser")
        orders = soup.find_all(class_="j-order")
        new_count = 0
        for order in orders[:40]:
            title_el = order.find(class_="l-project-title")
            if not title_el:
                continue
            link_el = title_el.find("a")
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            link = link_el.get("href", "")
            if not link.startswith("http"):
                link = "https://freelance.ua" + link
            desc_el = order.find(class_="l-project-description") or order.find("p")
            desc = desc_el.get_text(strip=True) if desc_el else ""
            tags_els = order.find_all(class_=lambda c: c and "tag" in c.lower())
            tags = " ".join([t.get_text(strip=True) for t in tags_els])
            uid = make_id(link or title)
            if is_seen(uid):
                continue
            if not is_spam(title + " " + desc + " " + tags):
                send_to_telegram(format_message(source, title, desc or tags, link))
                mark_seen(uid)
                new_count += 1
                time.sleep(2)
        logger.info(f"{source}: OK, {len(orders)} orders, {new_count} new")
    except Exception as e:
        logger.error(f"{source} error: {e}")

def parse_freelance_ua_keyword(keyword, label):
    source = f"freelance.ua [{label}]"
    url = f"https://freelance.ua/ru/orders/?q={requests.utils.quote(keyword)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return
        soup = BeautifulSoup(resp.text, "html.parser")
        orders = soup.find_all(class_="j-order")
        new_count = 0
        for order in orders[:20]:
            title_el = order.find(class_="l-project-title")
            if not title_el:
                continue
            link_el = title_el.find("a")
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            link = link_el.get("href", "")
            if not link.startswith("http"):
                link = "https://freelance.ua" + link
            desc_el = order.find(class_="l-project-description") or order.find("p")
            desc = desc_el.get_text(strip=True) if desc_el else ""
            uid = make_id(link or title)
            if is_seen(uid):
                continue
            if not is_spam(title + " " + desc):
                send_to_telegram(format_message(source, title, desc, link))
                mark_seen(uid)
                new_count += 1
                time.sleep(2)
        logger.info(f"{source}: OK, {new_count} new")
    except Exception as e:
        logger.error(f"{source} error: {e}")

def parse_telegram_channels():
    channels = [
        "ukr_freelance_jobs",
        "freelance_ukraine",
        "zamovlennya_ua",
        "freelance_jobs_ua",
    ]
    for channel in channels:
        try:
            url = f"https://t.me/s/{channel}"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            messages = soup.find_all("div", class_="tgme_widget_message_text")
            date_links = soup.find_all("a", class_="tgme_widget_message_date")
            new_count = 0
            for i, msg_el in enumerate(messages[-25:]):
                text = msg_el.get_text(separator=" ").strip()
                if len(text) < 20:
                    continue
                uid = make_id(channel + text[:120])
                if is_seen(uid):
                    continue
                if contains_keyword(text) and not is_spam(text):
                    post_link = f"https://t.me/{channel}"
                    try:
                        real_i = len(messages) - 25 + i
                        if 0 <= real_i < len(date_links):
                            post_link = date_links[real_i].get("href", post_link)
                    except:
                        pass
                    send_to_telegram(format_message(f"TG @{channel}", text[:100], text, post_link))
                    mark_seen(uid)
                    new_count += 1
                    time.sleep(2)
            logger.info(f"TG @{channel}: OK, {new_count} new")
            time.sleep(3)
        except Exception as e:
            logger.error(f"TG @{channel} error: {e}")

def run_all_parsers():
    logger.info("=" * 50)
    logger.info("Start parsing...")

    parse_freelance_ua()
    time.sleep(3)
    parse_freelance_ua_keyword("webflow", "Webflow")
    time.sleep(2)
    parse_freelance_ua_keyword("розсилка телеграм", "TG розсилка")
    time.sleep(2)
    parse_freelance_ua_keyword("розсилка viber", "Viber розсилка")
    time.sleep(2)
    parse_freelance_ua_keyword("розсилка email", "Email розсилка")
    time.sleep(2)
    parse_freelance_ua_keyword("telegram бот", "Telegram бот")
    time.sleep(2)
    parse_freelance_ua_keyword("чат-бот", "Чат-бот")
    time.sleep(2)

    parse_rss("FreelanceHunt", "https://freelancehunt.com/projects/feed")
    parse_rss("Kabanchik", "https://kabanchik.ua/ua/tasks/feed")
    parse_rss("Weblancer", "https://www.weblancer.net/jobs/feed/rss/")

    parse_rss("PeoplePerHour", "https://www.peopleperhour.com/job-feed/rss")
    parse_rss("Freelancer Web", "https://www.freelancer.com/rss/category/3.xml")
    parse_rss("Freelancer Design", "https://www.freelancer.com/rss/category/4.xml")
    parse_rss("Freelancer Marketing", "https://www.freelancer.com/rss/category/7.xml")
    parse_rss("Guru.com", "https://www.guru.com/jobs/feed.aspx")
    parse_rss("Upwork webdev", "https://www.upwork.com/ab/feed/jobs/rss?q=web+development&sort=recency")
    parse_rss("Upwork landing", "https://www.upwork.com/ab/feed/jobs/rss?q=landing+page&sort=recency")
    parse_rss("Upwork smm", "https://www.upwork.com/ab/feed/jobs/rss?q=smm+social+media&sort=recency")
    parse_rss("Upwork design", "https://www.upwork.com/ab/feed/jobs/rss?q=web+design+logo&sort=recency")
    parse_rss("Upwork ads", "https://www.upwork.com/ab/feed/jobs/rss?q=facebook+instagram+ads&sort=recency")
    parse_rss("Upwork email", "https://www.upwork.com/ab/feed/jobs/rss?q=email+marketing&sort=recency")
    parse_rss("Upwork webflow", "https://www.upwork.com/ab/feed/jobs/rss?q=webflow&sort=recency")
    parse_rss("Upwork tg bot", "https://www.upwork.com/ab/feed/jobs/rss?q=telegram+bot&sort=recency")

    parse_telegram_channels()

    logger.info("Parsing done.")

if __name__ == "__main__":
    logger.info("Parser started.")
    logger.info(f"Redis: {'connected' if USE_REDIS else 'file fallback'}")
    run_all_parsers()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_all_parsers)
    while True:
        schedule.run_pending()
        time.sleep(30)
