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

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
REDIS_URL = os.environ.get("REDIS_URL", "")

# Redis для зберігання seen IDs
USE_REDIS = False
r = None
if REDIS_AVAILABLE and REDIS_URL:
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        USE_REDIS = True
    except Exception as e:
        pass

SEEN_IDS_FILE = "/tmp/seen_ids.txt"
SEEN_TTL = 60 * 60 * 24 * 60  # 60 днів

# Максимальне розширені ключові слова - захоплюємо весь ринок
KEYWORDS = [
    # === ВЕБ-РОЗРОБКА (UA) ===
    "сайт", "лендінг", "посадкова", "вебсайт",
    "розробка сайту", "зробити сайт", "потрібен сайт", "замовити сайт",
    "створити сайт", "розробник сайту", "інтернет магазин", "інтернет-магазин",
    "розробка магазину", "корпоративний сайт", "візитка сайт",
    "переробити сайт", "оновити сайт", "доопрацювати сайт",
    "верстка сайту", "html верстка", "адаптивна верстка",
    # === ВЕБ-РОЗРОБКА (RU) ===
    "лендинг", "сделать сайт", "нужен сайт", "заказать сайт",
    "разработка сайта", "создать сайт", "интернет магазин", "интернет-магазин",
    "корпоративный сайт", "переделать сайт", "доработать сайт",
    "верстка сайта", "адаптивная верстка",
    # === CMS / КОНСТРУКТОРИ ===
    "wordpress", "вордпрес", "tilda", "тільда", "тильда",
    "webflow", "вебфлоу", "wix", "shopify", "opencart",
    "bitrix", "бітрікс", "drupal", "joomla", "prestashop",
    "woocommerce", "magento",
    # === ТАРГЕТ / РЕКЛАМА (UA) ===
    "таргет", "таргетолог", "таргетована реклама",
    "налаштування реклами", "реклама facebook", "реклама instagram",
    "реклама фейсбук", "реклама в instagram", "реклама в facebook",
    "просування в соцмережах", "реклама google", "google ads",
    "контекстна реклама", "ppc реклама", "платна реклама",
    "налаштувати рекламу", "запустити рекламу",
    # === ТАРГЕТ / РЕКЛАМА (RU) ===
    "таргетированная реклама", "настройка рекламы", "реклама вконтакте",
    "продвижение в соцсетях", "контекстная реклама",
    "настроить рекламу", "запустить рекламу",
    # === РОЗСИЛКИ (UA) ===
    "розсилка", "розсилання", "масова розсилка",
    "email розсилка", "email маркетинг", "розсилка на email",
    "telegram розсилка", "розсилка telegram", "розсилка телеграм",
    "tg розсилка", "розсилка в telegram", "розсилка в тг",
    "viber розсилка", "розсилка viber", "розсилка вайбер",
    "sms розсилка", "sms маркетинг",
    "розсилка повідомлень", "автоматична розсилка",
    # === РОЗСИЛКИ (RU) ===
    "рассылка", "массовая рассылка", "email рассылка",
    "telegram рассылка", "рассылка телеграм", "рассылка в telegram",
    "viber рассылка", "рассылка viber", "sms рассылка",
    "рассылка сообщений", "автоматическая рассылка",
    "newsletter",
    # === ДИЗАЙН (UA) ===
    "дизайн сайту", "веб дизайн", "ui дизайн", "ux дизайн", "ui/ux",
    "логотип", "логотип для", "розробка логотипу",
    "брендинг", "фірмовий стиль", "фірмова айдентика",
    "банер", "банери для", "рекламний банер",
    "креатив", "крео для реклами",
    "дизайн презентації", "дизайн листівки",
    # === ДИЗАЙН (RU) ===
    "дизайн сайта", "веб-дизайн",
    "разработка логотипа", "фирменный стиль",
    "баннер", "рекламный баннер", "креатив для рекламы",
    "дизайн презентации",
    # === SMM (UA) ===
    "smm", "ведення соцмереж", "ведення instagram",
    "ведення facebook", "контент план", "контент для instagram",
    "просування instagram", "розкрутка instagram",
    "smm спеціаліст", "smm менеджер",
    # === SMM (RU) ===
    "ведение соцсетей", "ведение instagram",
    "контент для инстаграм", "продвижение instagram",
    "smm специалист", "smm менеджер",
    # === TELEGRAM БОТ ===
    "telegram бот", "телеграм бот", "tg бот",
    "розробка бота", "зробити бота", "чат-бот",
    "chatbot", "telegram bot", "створити бота",
    # === МІЖНАРОДНІ (EN) ===
    "landing page", "web design", "website development",
    "web developer", "frontend developer", "wordpress developer",
    "facebook ads", "instagram ads", "google ads setup",
    "email marketing", "email campaign", "newsletter design",
    "smm manager", "social media manager", "content creator",
    "graphic design", "logo design", "branding identity",
    "ui ux design", "webflow developer", "shopify store",
    "telegram bot development", "chatbot development",
    # === МАРКЕРИ ЗАМОВЛЕННЯ ===
    "потрібно", "потрібен", "потрібна", "потрібний",
    "шукаю виконавця", "шукаю підрядника", "шукаю спеціаліста",
    "замовити", "замовлення на", "хочу замовити",
    "нужен", "нужна", "ищу исполнителя", "ищу подрядчика",
    "требуется", "заказать",
    "looking for", "need a", "need someone", "hire a",
    "seeking", "wanted", "require",
]

STOP_WORDS = [
    # Погодинна оплата
    "$/hour", "$/hr", "per hour", "hourly rate", "hourly pay",
    "грн/год", "$/час", "uah/hour", "usd/hour",
    # Вакансії на постійну роботу
    "full-time", "fulltime", "full time",
    "part-time", "parttime", "part time",
    "permanent position", "long-term employment",
    "join our team", "join our company",
    "we are hiring", "we're hiring", "now hiring",
    "vacancy", "vacancies", "вакансія", "вакансия",
    "salary range", "зарплата від", "оклад", "ставка в місяць",
    "employment contract", "трудовий договір",
    # Пропозиції своїх послуг
    "i offer", "i provide", "i am offering",
    "my services include", "check my portfolio",
    "hire me", "i am available for",
    "пропоную послуги", "надаю послуги", "мої послуги",
    "предлагаю услуги", "мои услуги", "предлагаю свои",
    "портфоліо", "моє портфоліо",
    # Спам
    "займ", "кредит", "казино", "ставки на спорт",
    "криптовалюта заробіток", "пасивний дохід",
]

CHECK_INTERVAL_MINUTES = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}


def is_seen(uid):
    if USE_REDIS and r:
        return bool(r.exists(f"seen:{uid}"))
    if not os.path.exists(SEEN_IDS_FILE):
        return False
    with open(SEEN_IDS_FILE, "r") as f:
        return uid in f.read()

def mark_seen(uid):
    if USE_REDIS and r:
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
    msg = f"\U0001f514 <b>[{source}]</b>\n\n"
    msg += f"\U0001f4cc <b>{title[:200]}</b>\n\n"
    if description and description.strip():
        desc = description.strip()[:400]
        if len(description.strip()) > 400:
            desc += "..."
        msg += f"{desc}\n\n"
    msg += f"\U0001f517 <a href='{link}'>Відкрити</a>"
    return msg

def parse_rss(source, url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"{source}: status {resp.status_code}")
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
                send_to_telegram(format_message(source, title, desc, link))
                mark_seen(uid)
                new_count += 1
                time.sleep(2)
        logger.info(f"{source}: OK, {new_count} new")
        return new_count
    except ET.ParseError as e:
        logger.warning(f"{source}: XML parse error - {e}")
        return 0
    except Exception as e:
        logger.error(f"{source} error: {e}")
        return 0

def parse_freelance_ua():
    source = "freelance.ua"
    spec_ids = [
        132, 131, 130, 129, 128, 114,
        52, 58, 65, 49, 55, 51, 86,
        136, 175, 176, 96, 98, 177, 145, 144,
        151, 152,
    ]
    params = "&".join([f"specs[]={sid}" for sid in spec_ids])
    url = f"https://freelance.ua/ru/orders/?{params}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return 0
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
            if not is_spam(title + " " + desc):
                send_to_telegram(format_message(source, title, desc or tags, link))
                mark_seen(uid)
                new_count += 1
                time.sleep(2)
        logger.info(f"{source}: OK, {len(orders)} orders, {new_count} new")
        return new_count
    except Exception as e:
        logger.error(f"{source} error: {e}")
        return 0

def parse_freelance_ua_search(keyword, label):
    source = f"freelance.ua [{label}]"
    import urllib.parse
    url = f"https://freelance.ua/ru/orders/?q={urllib.parse.quote(keyword)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return 0
        soup = BeautifulSoup(resp.text, "html.parser")
        orders = soup.find_all(class_="j-order")
        new_count = 0
        for order in orders[:15]:
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
        return new_count
    except Exception as e:
        logger.error(f"{source} error: {e}")
        return 0

def parse_freelancehunt():
    """FreelanceHunt - правильний RSS URL"""
    return parse_rss("FreelanceHunt", "https://freelancehunt.com/projects.rss?filter%5Bonly%5D=new")

def parse_telegram_channels():
    channels = [
        "ukr_freelance_jobs",
        "freelance_ukraine",
        "zamovlennya_ua",
        "freelance_jobs_ua",
    ]
    total_new = 0
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
            total_new += new_count
            logger.info(f"TG @{channel}: OK, {new_count} new")
            time.sleep(3)
        except Exception as e:
            logger.error(f"TG @{channel} error: {e}")
    return total_new

def run_all_parsers():
    logger.info("=" * 50)
    logger.info("Start parsing...")
    total = 0

    # УКРАЇНА
    total += parse_freelance_ua()
    time.sleep(3)
    for kw, label in [
        ("webflow", "Webflow"),
        ("розсилка телеграм", "TG розсилка"),
        ("розсилка viber", "Viber розсилка"),
        ("розсилка email", "Email розсилка"),
        ("telegram бот", "Telegram бот"),
        ("чат-бот", "Чат-бот"),
        ("розсилка повідомлень", "Розсилка"),
    ]:
        total += parse_freelance_ua_search(kw, label)
        time.sleep(2)

    total += parse_freelancehunt()
    time.sleep(3)

    # МІЖНАРОДНІ (тільки ті що реально працюють)
    # Upwork RSS
    upwork_queries = [
        ("web+development", "Upwork webdev"),
        ("landing+page", "Upwork landing"),
        ("smm+social+media+manager", "Upwork SMM"),
        ("web+design", "Upwork design"),
        ("facebook+ads+instagram+ads", "Upwork ads"),
        ("email+marketing+newsletter", "Upwork email"),
        ("webflow+developer", "Upwork webflow"),
        ("telegram+bot+chatbot", "Upwork TG bot"),
        ("logo+design+branding", "Upwork logo"),
    ]
    for q, label in upwork_queries:
        total += parse_rss(label, f"https://www.upwork.com/ab/feed/jobs/rss?q={q}&sort=recency")
        time.sleep(2)

    # PeoplePerHour
    total += parse_rss("PeoplePerHour", "https://www.peopleperhour.com/job-feed/rss")
    time.sleep(2)

    # Guru.com
    total += parse_rss("Guru.com", "https://www.guru.com/jobs/feed.aspx")
    time.sleep(2)

    # TELEGRAM
    total += parse_telegram_channels()

    logger.info(f"Parsing done. Total new: {total}")

if __name__ == "__main__":
    logger.info("Parser started.")
    logger.info(f"Redis: {'connected' if USE_REDIS else 'file fallback (/tmp)'}")
    run_all_parsers()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_all_parsers)
    while True:
        schedule.run_pending()
        time.sleep(30)
