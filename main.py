import os
import asyncio
import logging
import base64
from pathlib import Path
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ==================== توکن ====================
TOKEN = "7534267402:AAFaOmAaFbVmdpdC6RjKjV-71evLGVwd5Oc"
# ==============================================

GENERATOR_URL = "https://perchance.org/ai-girl-image-generator"
OUTPUT_DIR = Path("generated_images")
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋\nپرامپت تصویر رو بفرست تا برات بسازم.\n\nمثال:\n`cute korean girl, long black hair, soft smile`",
        parse_mode="Markdown"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.")


async def generate_with_playwright(prompt: str) -> list[Path]:
    image_paths = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-gpu",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            ignore_https_errors=True,
        )
        page = await context.new_page()

        try:
            logger.info("۱. باز کردن صفحه...")
            await page.goto(GENERATOR_URL, wait_until="domcontentloaded", timeout=120000)
            await page.wait_for_timeout(10000)

            logger.info("۲. پیدا کردن و پر کردن Description...")

            # روش مطمئن‌تر: پیدا کردن textarea نزدیک به متن Description
            description_textarea = page.locator("text=Description").locator("xpath=following::textarea[1]")
            await description_textarea.wait_for(state="visible", timeout=20000)
            await description_textarea.click()
            await description_textarea.fill("")          # پاک کردن متن قبلی
            await description_textarea.fill(prompt)
            logger.info("پرامپت نوشته شد.")

            # Anti-Description (اختیاری)
            try:
                anti = page.locator("text=Anti-Description").locator("xpath=following::input[1], xpath=following::textarea[1]")
                if await anti.count() > 0:
                    await anti.first.fill("low quality, blurry, deformed, bad anatomy, extra limbs")
            except:
                pass

            logger.info("۳. کلیک روی دکمه Generate...")

            # چند روش برای پیدا کردن دکمه
            generate_btn = page.locator("button:has-text('generate')").first
            await generate_btn.wait_for(state="visible", timeout=15000)
            await generate_btn.click()
            logger.info("دکمه Generate کلیک شد.")

            # صبر برای تولید تصویر
            logger.info("۴. منتظر ساخت تصاویر (۳ دقیقه)...")
            await page.wait_for_timeout(180000)

            logger.info("۵. جمع‌آوری تصاویر...")
            # گرفتن همه imgهایی که data:image دارند
            all_images = await page.locator("img").all()
            for img in all_images:
                try:
                    src = await img.get_attribute("src")
                    if src and src.startswith("data:image"):
                        header, encoded = src.split(",", 1)
                        data = base64.b64decode(encoded)
                        path = OUTPUT_DIR / f"img_{len(image_paths)}_{os.urandom(4).hex()}.png"
                        with open(path, "wb") as f:
                            f.write(data)
                        image_paths.append(path)
                        logger.info(f"تصویر ذخیره شد → {path.name}")
                except:
                    continue

            # اگر هنوز تصویری پیدا نشد، از فریم‌ها هم چک کن
            if not image_paths:
                for frame in page.frames:
                    try:
                        imgs = await frame.locator("img").all()
                        for img in imgs:
                            src = await img.get_attribute("src")
                            if src and src.startswith("data:image"):
                                header, encoded = src.split(",", 1)
                                data = base64.b64decode(encoded)
                                path = OUTPUT_DIR / f"img_{len(image_paths)}_{os.urandom(4).hex()}.png"
                                with open(path, "wb") as f:
                                    f.write(data)
                                image_paths.append(path)
                    except:
                        continue

            if not image_paths:
                await page.screenshot(path=OUTPUT_DIR / "debug_no_images.png", full_page=True)
                logger.warning("هیچ تصویری پیدا نشد. اسکرین‌شات ذخیره شد.")

        except Exception as e:
            try:
                await page.screenshot(path=OUTPUT_DIR / "debug_error.png", full_page=True)
            except:
                pass
            raise Exception(f"خطا: {str(e)}")
        finally:
            await browser.close()

    return image_paths


async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    prompt = update.message.text.strip()

    if len(prompt) < 3:
        await update.message.reply_text("پرامپت خیلی کوتاهه.")
        return

    status_msg = await update.message.reply_text("⏳ در حال ساخت تصویر...\nحدود ۳ دقیقه صبر کن.")

    try:
        image_paths = await generate_with_playwright(prompt)

        if not image_paths:
            await status_msg.edit_text("❌ تصویری ساخته نشد. چند دقیقه دیگر دوباره امتحان کن.")
            return

        media = []
        files = []
        try:
            for path in image_paths[:8]:
                f = open(path, "rb")
                files.append(f)
                media.append(InputMediaPhoto(media=f))
            await update.message.reply_media_group(media=media)
            await status_msg.delete()
        finally:
            for f in files:
                f.close()

        for path in image_paths:
            try:
                path.unlink(missing_ok=True)
            except:
                pass

    except Exception as e:
        logger.error(f"User {user.id} | {e}")
        try:
            await status_msg.edit_text(f"❌ خطا رخ داد:\n`{str(e)}`", parse_mode="Markdown")
        except:
            await update.message.reply_text(f"❌ خطا: {str(e)}")


def main():
    print("ربات در حال راه‌اندازی...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))
    print("✅ ربات آماده است.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
