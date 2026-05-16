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
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
REDIS_URL = os.environ.get("REDIS_URL", "")

# Redis for seen IDs deduplication
USE_REDIS = False
r = None
if REDIS_AVAILABLE and REDIS_URL:
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        USE_REDIS = True
        logger.info("Redis connected OK - dedup enabled")
    except Exception as e:
        logger.error(f"Redis connection failed: {e} - falling back to file")
else:
    if not REDIS_AVAILABLE:
        logger.warning("redis module not installed")
    if not REDIS_URL:
        logger.warning("REDIS_URL env var not set - will use /tmp/seen_ids.txt (resets on redeploy!)")

SEEN_IDS_FILE = "/tmp/seen_ids.txt"
SEEN_TTL = 60 * 60 * 24 * 60  # 60 days

KEYWORDS = [
    # === САЙТИ / WEB (UA) ===
    "сайт", "лендінг", "лендинг", "інтернет-магазин", "магазин",
    "вебсайт", "веб-сайт", "веб сайт", "корпоративний сайт",
    "портфоліо сайт", "одностронічний сайт", "посадкова сторінка",
    "редизайн", "верстка", "layout", "landing page", "веб-розробка",
    # === САЙТИ / WEB (RU) ===
    "сайт", "лендинг", "лендос", "интернет-магазин", "магазин",
    "вебсайт", "веб-сайт", "корпоративный сайт", "портфолио сайт",
    "редизайн", "верстка", "одностраничный", "посадочная",
    # === WEB (EN) ===
    "website", "web site", "landing page", "web design", "webdesign",
    "ecommerce", "e-commerce", "online store", "web development",
    "responsive design", "frontend", "front-end", "html", "css",
    "redesign", "portfolio website", "one-page site",
    # === WEBFLOW ===
    "webflow", "web flow", "вебфлоу",
    # === WORDPRESS / CMS ===
    "wordpress", "wordpress сайт", "woocommerce", "elementor",
    "joomla", "drupal", "cms", "opencart", "prestashop",
    # === SHOPIFY / ECOM ===
    "shopify", "shopify store", "wix", "squarespace", "tilda", "тільда",
    # === РОЗСИЛКИ / MESSAGING ===
    "розсилка", "розсилки", "масова розсилка", "масові повідомлення",
    "розсилка telegram", "розсилка viber", "розсилка email",
    "розсилка sms", "email розсилка", "смс розсилка",
    "рассылка", "рассылки", "массовая рассылка", "массовые сообщения",
    "рассылка telegram", "рассылка viber", "email рассылка",
    "рассылка sms", "смс рассылка", "телеграм рассылка",
    "email marketing", "email campaign", "newsletter",
    "sms marketing", "sms campaign", "viber рассылка",
    "mailing", "bulk email", "bulk sms", "bulk messaging",
    "drip campaign", "email automation",
    # === TELEGRAM БОТ / CHATBOT ===
    "telegram bot", "телеграм бот", "тг бот", "telegram бот",
    "chatbot", "chat-bot", "чат-бот", "чатбот", "бот telegram",
    "telebot", "aiogram", "pyrogram", "bot api",
    "viber bot", "вайбер бот", "whatsapp bot",
    # === ТАРГЕТ / ADS ===
    "таргет", "таргетинг", "таргетована реклама",
    "facebook ads", "instagram ads", "meta ads",
    "google ads", "контекстна реклама", "контекстная реклама",
    "ppc", "smm", "соціальні мережі", "социальные сети",
    "просування", "продвижение", "реклама facebook",
    "tiktok ads", "youtube ads",
    # === SMM / КОНТЕНТ ===
    "smm", "контент", "контент-план", "контент план",
    "дизайн постів", "дизайн постов", "сторіс", "сторис",
    "reels", "instagram", "tiktok", "linkedin",
    "копірайтинг", "копирайтинг", "copywriting",
    "графічний дизайн", "графический дизайн",
    # === ДИЗАЙН / KREATIV ===
    "дизайн", "design", "ui/ux", "ui ux", "ux design", "ui design",
    "figma", "adobe xd", "photoshop", "illustrator",
    "логотип", "логотип", "logo", "брендинг", "branding",
    "банер", "баннер", "banner", "флаєр", "флаер", "flyer",
    "презентація", "презентация", "presentation",
    "creo", "крео", "креатив", "creative",
    # === SEO / ПРОСУВАННЯ ===
    "seo", "просування сайту", "продвижение сайта", "пошукова оптимізація",
    "поисковая оптимизация", "google ranking", "yoast",
    # === ПРОГРАМУВАННЯ / DEV ===
    "розробка", "разработка", "development", "programmer", "developer",
    "python", "javascript", "react", "vue", "nodejs", "php",
    "мобільний додаток", "мобильное приложение", "mobile app",
    "api", "інтеграція", "интеграция", "integration",
    # === CRM / AUTOMATION ===
    "crm", "автоматизація", "автоматизация", "automation",
    "amocrm", "bitrix", "bitrix24", "pipedrive", "hubspot",
    "make", "zapier", "n8n",
    # === ЗАГАЛЬНЕ ===
    "фриланс", "freelance", "замовлення", "заказ", "проєкт", "проект",
    "завдання", "задача", "потрібен", "нужен", "шукаю", "ищу",
    "розробник", "разработчик", "спеціаліст", "специалист",
    "терміново", "срочно", "urgent", "asap",
]

STOP_WORDS = [
    # Vacancies / job offers
    "$/hour", "per hour", "hourly rate", "hourly pay", "full-time",
    "part-time", "salary", "зарплата", "ставка", "оклад",
    "вакансія", "вакансия", "vacancy", "job opening", "we are hiring",
    "hiring now", "join our team", "looking for employee",
    "шукаємо співробітника", "ищем сотрудника",
    # Service offers
    "пропоную послуги", "предлагаю услуги", "надаю послуги",
    "hire me", "i am available", "i can help", "я готов помочь",
    "мої послуги", "мои услуги", "my services", "portfolio",
    "check out my work", "available for hire",
    # Hourly rates
    "$/hr", "usd/hour", "грн/год", "грн/час",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en;q=0.7",
}

def is_seen(uid):
    if USE_REDIS and r:
        try:
            return bool(r.exists(f"seen:{uid}"))
        except Exception as e:
            logger.error(f"Redis is_seen error: {e}")
    if not os.path.exists(SEEN_IDS_FILE):
        return False
    with open(SEEN_IDS_FILE, "r") as f:
        return uid in f.read()

def mark_seen(uid):
    if USE_REDIS and r:
        try:
            r.setex(f"seen:{uid}", SEEN_TTL, "1")
            return
        except Exception as e:
            logger.error(f"Redis mark_seen error: {e}")
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
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except TelegramError as e:
        logger.error(f"Telegram error: {e}")

def format_message(source, title, desc, link):
    desc_short = desc[:300] + "..." if len(desc) > 300 else desc
    return (
        f"<b>{source}</b>\n"
        f"<b>{title}</b>\n"
        f"{desc_short}\n"
        f"<a href=\"{link}\">Переглянути →</a>"
    )

def parse_rss(source, url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"{source}: HTTP {resp.status_code}")
            return 0
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
                link = (link_el.text or link_el.get('href', '')).strip()
            desc = ""
            if desc_el is not None and desc_el.text:
                desc = BeautifulSoup(desc_el.text, "html.parser").get_text()
            uid = make_id(link or title)
            if is_seen(uid):
                continue
            full_text = title + " " + desc
            if contains_keyword(full_text) and not is_spam(full_text):
                mark_seen(uid)
                send_to_telegram(format_message(source, title, desc, link))
                new_count += 1
                time.sleep(2)
            else:
                mark_seen(uid)
        logger.info(f"{source}: {new_count} new leads")
        return new_count
    except ET.ParseError as e:
        logger.warning(f"{source} XML parse error: {e}")
        return 0
    except Exception as e:
        logger.error(f"{source} error: {e}")
        return 0

def parse_freelance_ua():
    CATEGORY_IDS = [
        3, 5, 6, 7, 8, 15, 16, 17, 18, 19, 20, 21, 22, 23,
        24, 25, 26, 27, 28, 29, 30, 31, 32, 33
    ]
    new_count = 0
    seen_links = set()
    for cat_id in CATEGORY_IDS:
        url = f"https://freelance.ua/ru/orders/?subcategory={cat_id}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            orders = soup.select("div.order-list__item, div.b-post, article.order")
            if not orders:
                orders = soup.select("div[class*='order']")
            for order in orders[:20]:
                a = order.find('a', href=True)
                if not a:
                    continue
                link = a['href']
                if not link.startswith('http'):
                    link = 'https://freelance.ua' + link
                if link in seen_links:
                    continue
                seen_links.add(link)
                title = a.get_text(strip=True)
                desc_el = order.find('div', class_=lambda c: c and 'desc' in c.lower())
                desc = desc_el.get_text(strip=True) if desc_el else ""
                uid = make_id(link)
                if is_seen(uid):
                    continue
                full_text = title + " " + desc
                if contains_keyword(full_text) and not is_spam(full_text):
                    mark_seen(uid)
                    send_to_telegram(format_message("🇺🇦 Freelance.UA", title, desc, link))
                    new_count += 1
                    time.sleep(2)
                else:
                    mark_seen(uid)
        except Exception as e:
            logger.error(f"freelance.ua cat {cat_id}: {e}")
        time.sleep(1)
    logger.info(f"freelance.ua: {new_count} new leads")
    return new_count

def parse_freelance_ua_search():
    SEARCH_TERMS = [
        "сайт", "лендінг", "розсилка", "telegram бот", "чат-бот",
        "webflow", "smm", "дизайн", "таргет", "реклама"
    ]
    new_count = 0
    seen_links = set()
    for term in SEARCH_TERMS:
        url = f"https://freelance.ua/ru/orders/?search={requests.utils.quote(term)}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            orders = soup.select("div.order-list__item, div.b-post, article.order")
            if not orders:
                orders = soup.select("div[class*='order']")
            for order in orders[:15]:
                a = order.find('a', href=True)
                if not a:
                    continue
                link = a['href']
                if not link.startswith('http'):
                    link = 'https://freelance.ua' + link
                if link in seen_links:
                    continue
                seen_links.add(link)
                title = a.get_text(strip=True)
                desc_el = order.find('div', class_=lambda c: c and 'desc' in c.lower())
                desc = desc_el.get_text(strip=True) if desc_el else ""
                uid = make_id(link)
                if is_seen(uid):
                    continue
                full_text = title + " " + desc
                if contains_keyword(full_text) and not is_spam(full_text):
                    mark_seen(uid)
                    send_to_telegram(format_message("🇺🇦 Freelance.UA (пошук)", title, desc, link))
                    new_count += 1
                    time.sleep(2)
                else:
                    mark_seen(uid)
        except Exception as e:
            logger.error(f"freelance.ua search '{term}': {e}")
        time.sleep(1)
    logger.info(f"freelance.ua search: {new_count} new leads")
    return new_count

def parse_freelancehunt():
    url = "https://freelancehunt.com/projects.rss?filter%5Bonly%5D=new"
    return parse_rss("🇺🇦 FreelanceHunt", url)

def run_all():
    logger.info("=== Starting parse cycle ===")
    logger.info(f"Redis: {'ON' if USE_REDIS else 'OFF (file fallback)'}")
    total = 0
    total += parse_freelance_ua()
    time.sleep(3)
    total += parse_freelance_ua_search()
    time.sleep(3)
    total += parse_freelancehunt()
    time.sleep(3)

    RSS_SOURCES = [
        ("🌍 Upwork (webdev)", "https://www.upwork.com/ab/feed/jobs/rss?q=web+development&sort=recency&paging=0%3B10"),
        ("🌍 Upwork (landing)", "https://www.upwork.com/ab/feed/jobs/rss?q=landing+page&sort=recency&paging=0%3B10"),
        ("🌍 Upwork (smm)", "https://www.upwork.com/ab/feed/jobs/rss?q=social+media+marketing&sort=recency&paging=0%3B10"),
        ("🌍 Upwork (design)", "https://www.upwork.com/ab/feed/jobs/rss?q=website+design&sort=recency&paging=0%3B10"),
        ("🌍 Upwork (ads)", "https://www.upwork.com/ab/feed/jobs/rss?q=facebook+ads+instagram+ads&sort=recency&paging=0%3B10"),
        ("🌍 Upwork (email)", "https://www.upwork.com/ab/feed/jobs/rss?q=email+marketing&sort=recency&paging=0%3B10"),
        ("🌍 Upwork (webflow)", "https://www.upwork.com/ab/feed/jobs/rss?q=webflow&sort=recency&paging=0%3B10"),
        ("🌍 Upwork (chatbot)", "https://www.upwork.com/ab/feed/jobs/rss?q=telegram+bot+chatbot&sort=recency&paging=0%3B10"),
        ("🌍 Upwork (logo)", "https://www.upwork.com/ab/feed/jobs/rss?q=logo+design+branding&sort=recency&paging=0%3B10"),
        ("🌍 PeoplePerHour", "https://www.peopleperhour.com/rss/hourlies"),
        ("🌍 Guru.com", "https://www.guru.com/d/jobs/rss/"),
    ]
    for name, url in RSS_SOURCES:
        total += parse_rss(name, url)
        time.sleep(2)

    logger.info(f"=== Cycle done. Total new leads: {total} ===")

if __name__ == "__main__":
    logger.info("Lead parser bot started")
    run_all()
    schedule.every(10).minutes.do(run_all)
    while True:
        schedule.run_pending()
        time.sleep(30)
