# ============================================================
# PROFESSIONAL SAM.gov AI CAPTURE BOT
# Enterprise Federal Opportunity Intelligence Platform
# Optimized for Google Colab
# ============================================================

# =========================
# INSTALL REQUIRED PACKAGES
# =========================

!pip install -q python-telegram-bot==20.7 nest_asyncio requests

# =========================
# IMPORTS
# =========================

import os
import asyncio
import logging
import sqlite3
import requests
import nest_asyncio

from html import escape
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# COLAB ASYNC FIX
# =========================

nest_asyncio.apply()

# ============================================================
# YOUR API KEYS
# ============================================================

# TELEGRAM BOT TOKEN
os.environ["TELEGRAM_BOT_TOKEN"] = "8909028411:AAFc8El2rYvqAqLzNiZRDRqq6mquL0jS5Ew"

# SAM.GOV API KEY
os.environ["SAM_API_KEY"] = "SAM-7cca2348-9aa1-43b5-88ff-4130b8a64240 "

# GEMINI API KEY
os.environ["GEMINI_API_KEY"] = "AIzaSyAxzhb1DJCCHmGWFBii8nb1ZjFEp8nt8EM"

# YOUR TELEGRAM CHAT ID
os.environ["ADMIN_CHAT_ID"] = " 8565197842"

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SAM_API_KEY = os.getenv("SAM_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# ============================================================
# DATABASE
# ============================================================

conn = sqlite3.connect(
    "sam_capture.db",
    check_same_thread=False
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS opportunities (
    notice_id TEXT PRIMARY KEY
)
""")

conn.commit()

# ============================================================
# DUPLICATE PROTECTION
# ============================================================

def is_duplicate(notice_id):

    cursor.execute(
        "SELECT notice_id FROM opportunities WHERE notice_id=?",
        (notice_id,)
    )

    return cursor.fetchone() is not None


def save_opportunity(notice_id):

    try:
        cursor.execute(
            "INSERT INTO opportunities (notice_id) VALUES (?)",
            (notice_id,)
        )

        conn.commit()

    except:
        pass

# ============================================================
# CONFIGURATION
# ============================================================

TARGET_AGENCIES = {
    "2100": "Department of the Army",
    "5700": "Department of the Air Force",
    "S": "Department of State",
    "SA": "Embassy Opportunities",
}

NOTICE_TYPES = [
    "Solicitation",
    "Combined Synopsis/Solicitation",
]

NAICS_CODES = [
    "541511",
    "541512",
    "541519",
    "541330",
]

CHECK_INTERVAL = 900

# ============================================================
# DEADLINE PRIORITY ENGINE
# ============================================================

def get_deadline_priority(deadline_str):

    try:
        deadline = datetime.fromisoformat(
            deadline_str.replace("Z", "+00:00")
        )

        now = datetime.now(timezone.utc)

        days_left = (deadline - now).days

        if days_left <= 1:
            return "🔴 URGENT - 24 HOURS"

        elif days_left <= 2:
            return "🟠 HIGH PRIORITY - 2 DAYS"

        elif days_left <= 3:
            return "🟡 MEDIUM PRIORITY - 3 DAYS"

        elif days_left <= 7:
            return "🟢 THIS WEEK"

        return "⚪ NORMAL"

    except:
        return "⚪ UNKNOWN"

# ============================================================
# SAM.gov CLIENT
# ============================================================

class SAMGovClient:

    BASE_URL = "https://api.sam.gov/prod/opportunities/v2/search"

    def search_opportunities(
        self,
        agency,
        notice_type,
        naics,
    ):

        today = datetime.now(timezone.utc)

        params = {

            "api_key": SAM_API_KEY,

            # ACTIVE OPPORTUNITIES ONLY
            "active": "true",

            # NEW OPPORTUNITIES
            "postedFrom": (
                today - timedelta(hours=6)
            ).strftime("%m/%d/%Y"),

            "postedTo": today.strftime("%m/%d/%Y"),

            # DEADLINE FILTER
            "responseDeadLineFrom":
                today.strftime("%m/%d/%Y"),

            "responseDeadLineTo":
                (
                    today + timedelta(days=7)
                ).strftime("%m/%d/%Y"),

            # FILTERS
            "noticeType": notice_type,
            "organizationCode": agency,
            "naicsCode": naics,

            # FULL & OPEN
            "typeOfSetAside": "NONE",

            # LIMIT
            "limit": 25,
            "offset": 0,

            # SORTING
            "sort": "postedDate",
            "order": "desc",
        }

        try:

            response = requests.get(
                self.BASE_URL,
                params=params,
                timeout=30,
            )

            # RATE LIMIT PROTECTION
            if response.status_code == 429:
                logger.warning(
                    "SAM.gov rate limit reached."
                )
                return []

            if response.status_code != 200:
                logger.error(
                    f"SAM API Error: "
                    f"{response.status_code}"
                )
                return []

            data = response.json()

            return data.get(
                "opportunitiesData",
                []
            )

        except Exception as e:
            logger.error(f"SAM Error: {e}")
            return []

# ============================================================
# GEMINI AI ENGINE
# ============================================================

class GeminiAI:

    BASE_URL = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/"
        "gemini-2.0-flash:generateContent"
    )

    def analyze(
        self,
        title,
        description,
    ):

        prompt = f"""
        Analyze this federal opportunity.

        TITLE:
        {title}

        DESCRIPTION:
        {description[:3000]}

        Return:

        1. Opportunity summary
        2. Key requirements
        3. Estimated contract value
        4. Win probability
        5. Recommended strategy
        """

        try:

            response = requests.post(
                f"{self.BASE_URL}"
                f"?key={GEMINI_API_KEY}",

                json={
                    "contents": [{
                        "parts": [{
                            "text": prompt
                        }]
                    }],
                },

                timeout=60,
            )

            if response.status_code != 200:
                return "AI analysis unavailable."

            result = response.json()

            return result["candidates"][0][
                "content"
            ]["parts"][0]["text"]

        except Exception as e:
            logger.error(f"AI Error: {e}")
            return "AI analysis failed."

# ============================================================
# INITIALIZE SERVICES
# ============================================================

sam_client = SAMGovClient()
ai_engine = GeminiAI()

# ============================================================
# START COMMAND
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [
        [
            InlineKeyboardButton(
                "📊 Latest Opportunities",
                callback_data="latest"
            )
        ],
        [
            InlineKeyboardButton(
                "⚡ System Status",
                callback_data="status"
            )
        ],
    ]

    reply_markup = InlineKeyboardMarkup(
        keyboard
    )

    text = """
🚀 SAM Capture AI Bot Online

Professional Federal Opportunity Intelligence Platform

Monitoring:
✅ Department of the Army
✅ Department of the Air Force
✅ Embassy Opportunities
✅ Full & Open Competition

Commands:
/latest
/status
/help
"""

    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
    )

# ============================================================
# HELP COMMAND
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = """
📘 AVAILABLE COMMANDS

/latest → latest opportunities
/status → system status
/help → help menu
"""

    await update.message.reply_text(text)

# ============================================================
# STATUS COMMAND
# ============================================================

async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = f"""
✅ SYSTEM ONLINE

⏰ UTC:
{datetime.now(timezone.utc)}

🏢 Agencies:
{len(TARGET_AGENCIES)}

📂 NAICS:
{len(NAICS_CODES)}

📡 Monitoring Active
🤖 AI Engine Online
"""

    await update.message.reply_text(text)

# ============================================================
# LATEST COMMAND
# ============================================================

async def latest(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔎 Searching SAM.gov..."
    )

    total_found = 0

    for agency_code in TARGET_AGENCIES.keys():

        for notice_type in NOTICE_TYPES:

            for naics in NAICS_CODES:

                opportunities = (
                    sam_client.search_opportunities(
                        agency_code,
                        notice_type,
                        naics,
                    )
                )

                await asyncio.sleep(2)

                for opp in opportunities[:2]:

                    total_found += 1

                    title = escape(
                        opp.get(
                            "title",
                            "No Title"
                        )
                    )

                    notice_id = escape(
                        opp.get(
                            "noticeId",
                            "N/A"
                        )
                    )

                    agency = escape(
                        opp.get(
                            "fullParentPathName",
                            "Unknown Agency"
                        )
                    )

                    deadline = escape(
                        opp.get(
                            "responseDeadLine",
                            "Not Specified"
                        )
                    )

                    priority = (
                        get_deadline_priority(
                            opp.get(
                                "responseDeadLine",
                                ""
                            )
                        )
                    )

                    message = f"""
🎯 <b>FEDERAL OPPORTUNITY</b>

🏢 <b>Agency:</b>
{agency}

📋 <b>Notice ID:</b>
<code>{notice_id}</code>

📌 <b>Title:</b>
{title}

📅 <b>Deadline:</b>
{deadline}

⚠ <b>Priority:</b>
{priority}

🔓 <b>Competition:</b>
Full & Open
"""

                    keyboard = [[
                        InlineKeyboardButton(
                            "🌐 View SAM.gov",
                            url=f"https://sam.gov/opp/{notice_id}/view"
                        )
                    ]]

                    reply_markup = InlineKeyboardMarkup(
                        keyboard
                    )

                    await update.message.reply_text(
                        message,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )

    if total_found == 0:

        await update.message.reply_text(
            "No new opportunities found."
        )

# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if query.data == "latest":

        await query.message.reply_text(
            "Use /latest command."
        )

    elif query.data == "status":

        await query.message.reply_text(
            "✅ System operational."
        )

# ============================================================
# BACKGROUND MONITORING
# ============================================================

async def monitor_opportunities(application):

    logger.info(
        "Background monitoring started..."
    )

    while True:

        try:

            for agency_code in TARGET_AGENCIES.keys():

                for notice_type in NOTICE_TYPES:

                    for naics in NAICS_CODES:

                        opportunities = (
                            sam_client.search_opportunities(
                                agency_code,
                                notice_type,
                                naics,
                            )
                        )

                        await asyncio.sleep(2)

                        for opp in opportunities:

                            notice_id = (
                                opp.get("noticeId")
                            )

                            if not notice_id:
                                continue

                            # DUPLICATE FILTER
                            if is_duplicate(
                                notice_id
                            ):
                                continue

                            save_opportunity(
                                notice_id
                            )

                            title = escape(
                                opp.get(
                                    "title",
                                    "No Title"
                                )
                            )

                            agency = escape(
                                opp.get(
                                    "fullParentPathName",
                                    "Unknown Agency"
                                )
                            )

                            deadline = (
                                opp.get(
                                    "responseDeadLine",
                                    ""
                                )
                            )

                            priority = (
                                get_deadline_priority(
                                    deadline
                                )
                            )

                            # AI ANALYSIS
                            ai_analysis = (
                                ai_engine.analyze(
                                    title,
                                    opp.get(
                                        "description",
                                        ""
                                    )
                                )
                            )

                            message = f"""
🚨 <b>NEW SAM.gov OPPORTUNITY</b>

🏢 <b>Agency:</b>
{agency}

📌 <b>Title:</b>
{title}

🆔 <b>Notice ID:</b>
<code>{notice_id}</code>

⚠ <b>Priority:</b>
{priority}

🔓 Full & Open Competition

🤖 <b>AI ANALYSIS:</b>

{escape(ai_analysis[:1500])}
"""

                            keyboard = [[
                                InlineKeyboardButton(
                                    "🌐 View SAM.gov",
                                    url=f"https://sam.gov/opp/{notice_id}/view"
                                )
                            ]]

                            reply_markup = (
                                InlineKeyboardMarkup(
                                    keyboard
                                )
                            )

                            await application.bot.send_message(
                                chat_id=ADMIN_CHAT_ID,
                                text=message,
                                parse_mode="HTML",
                                reply_markup=reply_markup,
                            )

                            logger.info(
                                f"New opportunity: "
                                f"{notice_id}"
                            )

            logger.info(
                f"Sleeping for "
                f"{CHECK_INTERVAL} seconds..."
            )

            await asyncio.sleep(
                CHECK_INTERVAL
            )

        except Exception as e:

            logger.error(
                f"Monitoring Error: {e}"
            )

            await asyncio.sleep(60)

# ============================================================
# POST INIT
# ============================================================

async def post_init(application):

    asyncio.create_task(
        monitor_opportunities(application)
    )

# ============================================================
# MAIN
# ============================================================

async def main():

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # COMMANDS
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("help", help_command)
    )

    app.add_handler(
        CommandHandler("status", status)
    )

    app.add_handler(
        CommandHandler("latest", latest)
    )

    # BUTTONS
    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    logger.info(
        "SAM Capture AI Bot started..."
    )

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    while True:
        await asyncio.sleep(60)

# ============================================================
# RUN APPLICATION
# ============================================================

await main()
