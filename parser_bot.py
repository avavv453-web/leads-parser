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

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Ключевые слова - ЧТО ищем (наши услуги)
KEYWORDS = [
    # Веб-разработка
    "сайт", "лендинг", "landing", "website", "веб", "web",
    "розробка сайту", "зробити сайт", "потрібен сайт",
    "інтернет магазин", "інтернет-магазин",
    "wordpress", "вордпрес", "tilda", "тільда",
    "розробка сайта", "сделать сайт", "нужен сайт",
    # Таргет / реклама
    "таргет", "таргетолог", "таргетована реклама", "таргетированная реклама",
    "реклама facebook", "реклама instagram",
    "налаштування реклами", "настройка рекламы",
    "smm", "просування", "продвижение",
    "facebook ads", "instagram ads", "google ads",
    # Рассылки
    "розсилка", "рассылка", "email розсилка", "email рассылка",
    "telegram розсилка", "newsletter",
    # Дизайн / крео
    "дизайн", "банер", "баннер", "креатив", "graphic design",
    "логотип", "брендинг",
    # Международные
    "web developer", "web design", "frontend", "backend",
    "email marketing", "smm manager", "content creator",
    # Маркеры заказа
    "потрібен", "потрібно", "шукаю", "замовити", "замовлення",
    "ищу исполнителя", "ищу подрядчика", "нужен фрилансер",
    "looking for", "need a", "hiring freelancer", "freelance project",
    "need developer", "need designer",
]

# Стоп-слова - фильтруем ВАКАНСИИ и предложения работы
STOP_WORDS = [
    # Признаки вакансии (работа за зарплату/час)
    "$/hour", "$/hr", "per hour", "hourly rate", "hourly pay",
    "€/hour", "€/hr", "грн/год", "грн/час", "$/час",
    "full-time", "full time", "part-time", "part time",
    "remote job", "remote position", "job opening", "job opportunity",
    "we are hiring", "we're hiring", "join our team", "join our company",
    "vacancy", "vacancies", "вакансія", "вакансия",
    "permanent position", "long-term employee", "staff position",
    "salary", "зарплата", "зарплата від", "оклад",
    "employment", "employed", "employee benefits",
    "work from home job", "wfh position",
    # Предложения услуг (не заказы, а сами предлагают)
    "i offer", "i provide", "i can help", "i am available",
    "my services", "hire me", "check my portfolio",
    "пропоную послуги", "надаю послуги", "мої послуги",
    "предлагаю услуги", "мои услуги",
]

SEEN_IDS_FILE = "seen_ids.txt"
CHECK_INTERVAL_MINUTES = 15

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

def load_seen_ids():
    if not os.path.exists(SEEN_IDS_FILE):
        return set()
    with open(SEEN_IDS_FILE, "r") as f:
        return set(line.strip() for line in f.readlines())

def save_seen_id(uid):
    with open(SEEN_IDS_FILE, "a") as f:
        f.write(uid + "\n")

def make_id(text):
    return hashlib.md5(text.encode()).hexdigest()

def contains_keyword(text):
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KEYWORDS)

def is_spam(text):
    """Возвращает True если это вакансия или предложение услуг, а не заказ"""
    text_lower = text.lower()
    return any(sw.lower() in text_lower for sw in STOP_WORDS)

def send_to_telegram(message):
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="HTML", disable_web_page_preview=True)
        logger.info("Отправлено в Telegram")
    except TelegramError as e:
        logger.error(f"Ошибка Telegram: {e}")
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

def format_message(source, title, description, link):
    msg = f"🔔 <b>Новый запрос [{source}]</b>\n\n"
    msg += f"📌 <b>{title[:200]}</b>\n\n"
    if description:
        desc = description[:500]
        if len(description) > 500:
            desc += "..."
        msg += f"{desc}\n\n"
    msg += f"🔗 <a href=\'{link}\'>Открыть</a>"
    return msg

def parse_rss(source, url):
    seen = load_seen_ids()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"{source}: статус {resp.status_code}")
            return
        root = ET.fromstring(resp.content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        items = root.findall('.//item')
        if not items:
            items = root.findall('.//atom:entry', ns)
        for item in items[:20]:
            title_el = item.find('title')
            link_el = item.find('link')
            desc_el = item.find('description') or item.find('summary')
            if title_el is None:
                continue
            title = title_el.text or ""
            link = link_el.text if link_el is not None and link_el.text else ""
            if not link and link_el is not None:
                link = link_el.get('href', '')
            desc = ""
            if desc_el is not None and desc_el.text:
                desc = BeautifulSoup(desc_el.text, "html.parser").get_text()
            uid = make_id(link or title)
            if uid in seen:
                continue
            full_text = title + " " + desc
            if contains_keyword(full_text) and not is_spam(full_text):
                send_to_telegram(format_message(source, title, desc, link))
                save_seen_id(uid)
                time.sleep(2)
        logger.info(f"{source}: проверено")
    except Exception as e:
        logger.error(f"{source} ошибка: {e}")

def parse_reddit():
    # Только нерусские сабреддиты
    subreddits = ["forhire", "slavelabour", "ukraineforhire", "hiring", "freelance", "entrepreneur"]
    seen = load_seen_ids()
    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
            resp = requests.get(url, headers={**HEADERS, "User-Agent": "LeadParserBot/1.0"}, timeout=15)
            if resp.status_code != 200:
                time.sleep(3)
                continue
            posts = resp.json().get("data", {}).get("children", [])
            for post in posts:
                d = post.get("data", {})
                uid = d.get("id", "")
                if uid in seen:
                    continue
                title = d.get("title", "")
                desc = d.get("selftext", "")
                link = "https://reddit.com" + d.get("permalink", "")
                full_text = title + " " + desc
                if contains_keyword(full_text) and not is_spam(full_text):
                    send_to_telegram(format_message(f"Reddit r/{sub}", title, desc, link))
                    save_seen_id(uid)
                    time.sleep(2)
            logger.info(f"Reddit r/{sub}: проверено")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Reddit r/{sub} ошибка: {e}")

def parse_telegram_channels():
    # Публичные украинские и европейские каналы с заказами
    channels = [
        "freelance_ua",
        "freelance_jobs_ua",
        "tenders_ua",
        "web_freelance",
        "it_jobs_ukraine",
        "smm_freelance",
        "freelance_europe",
        "freelancers_chat",
        "prjctr_jobs",
        "digital_freelance_ua",
    ]
    seen = load_seen_ids()
    for channel in channels:
        try:
            url = f"https://t.me/s/{channel}"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            messages = soup.find_all("div", class_="tgme_widget_message_text")
            links_els = soup.find_all("a", class_="tgme_widget_message_date")
            for i, msg in enumerate(messages[-20:]):
                text = msg.get_text()
                uid = make_id(channel + text[:100])
                if uid in seen:
                    continue
                if contains_keyword(text) and not is_spam(text):
                    post_link = ""
                    try:
                        post_link = links_els[i].get("href", f"https://t.me/{channel}")
                    except:
                        post_link = f"https://t.me/{channel}"
                    send_to_telegram(format_message(f"Telegram @{channel}", text[:100], text, post_link))
                    save_seen_id(uid)
                    time.sleep(2)
            logger.info(f"Telegram @{channel}: проверено")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Telegram @{channel} ошибка: {e}")

def run_all_parsers():
    logger.info("=" * 50)
    logger.info("Запуск парсинга всех источников...")

    # Украина
    parse_rss("FreelanceHunt UA", "https://freelancehunt.com/projects/feed")
    parse_rss("Kabanchik UA", "https://kabanchik.ua/ua/news/feed")
    parse_rss("Weblancer", "https://www.weblancer.net/jobs/feed/rss/")

    # Европа / Международные (без аккаунта)
    parse_rss("PeoplePerHour", "https://www.peopleperhour.com/job-feed/rss")
    parse_rss("Freelancer.com Web", "https://www.freelancer.com/rss/category/3.xml")
    parse_rss("Freelancer.com Design", "https://www.freelancer.com/rss/category/4.xml")
    parse_rss("Freelancer.com Marketing", "https://www.freelancer.com/rss/category/7.xml")
    parse_rss("Guru.com", "https://www.guru.com/jobs/feed.aspx")
    parse_rss("Upwork web", "https://www.upwork.com/ab/feed/jobs/rss?q=web+development&sort=recency")
    parse_rss("Upwork smm", "https://www.upwork.com/ab/feed/jobs/rss?q=smm&sort=recency")
    parse_rss("Upwork ads", "https://www.upwork.com/ab/feed/jobs/rss?q=facebook+ads&sort=recency")
    parse_rss("Upwork landing", "https://www.upwork.com/ab/feed/jobs/rss?q=landing+page&sort=recency")
    parse_rss("Upwork email", "https://www.upwork.com/ab/feed/jobs/rss?q=email+marketing&sort=recency")

    # Reddit
    parse_reddit()

    # Telegram каналы
    parse_telegram_channels()

    logger.info("Парсинг завершён.")

if __name__ == "__main__":
    logger.info("Парсер лидов запущен.")
    run_all_parsers()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_all_parsers)
    while True:
        schedule.run_pending()
        time.sleep(30)
