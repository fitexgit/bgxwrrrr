import os
import asyncio
import logging
from pathlib import Path
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ==================== توکن برای تست ====================
TOKEN = "7534267402:AAFaOmAaFbVmdpdC6RjKjV-71evLGVwd5Oc"
# ======================================================

if not TOKEN or ":" not in TOKEN:
    raise ValueError("❌ توکن نامعتبر است!")

# تنظیمات
GENERATOR_URL = "https://perchance.org/ai-girl-image-generator"
OUTPUT_DIR = Path("generated_images")
OUTPUT_DIR.mkdir(exist_ok=True)

# لاگ کردن خطاها
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋\n"
        "پرامپت تصویر رو بفرست تا برات بسازم.\n\n"
        "مثال:\n"
        "`cute korean girl, long black hair, soft smile, white sweater`\n\n"
        "برای توقف: /cancel",
        parse_mode="Markdown"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.")


async def generate_with_playwright(prompt: str, negative: str = "low quality, blurry, deformed, bad anatomy, extra limbs") -> list[Path]:
    """تولید تصویر با Playwright و برگرداندن لیست مسیر فایل‌ها"""
    image_paths = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            print("در حال باز کردن صفحه...")
            await page.goto(GENERATOR_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)

            # پر کردن Description
            print("در حال نوشتن پرامپت...")
            desc = page.locator("textarea").first
            await desc.wait_for(state="visible", timeout=20000)
            await desc.fill(prompt)

            # سعی در پر کردن negative
            try:
                negative_area = page.locator("text=Anti-Description").locator("..").locator("textarea").first
                if await negative_area.count() > 0:
                    await negative_area.fill(negative)
            except Exception as e:
                print(f"نتوانست negative را پر کند: {e}")

            # کلیک Generate
            print("در حال کلیک روی Generate...")
            generate_btn = page.locator("button:has-text('generate'), button:has-text('Generate')").first
            await generate_btn.wait_for(state="visible", timeout=10000)
            await generate_btn.click()

            # صبر ۲.۵ دقیقه
            print("منتظر ساخت تصاویر (حدود ۱۵۰ ثانیه)...")
            await page.wait_for_timeout(150000)

            # گرفتن تصاویر از iframeها
            print("در حال جمع‌آوری تصاویر...")
            for frame in page.frames:
                try:
                    imgs = await frame.locator("img").all()
                    for img in imgs:
                        src = await img.get_attribute("src")
                        if not src:
                            continue

                        if src.startswith("data:image"):
                            import base64
                            header, encoded = src.split(",", 1)
                            data = base64.b64decode(encoded)
                            path = OUTPUT_DIR / f"img_{len(image_paths)}_{os.urandom(4).hex()}.png"
                            with open(path, "wb") as f:
                                f.write(data)
                            image_paths.append(path)
                            print(f"تصویر ذخیره شد: {path}")
                except Exception as e:
                    logger.warning(f"خطا در خواندن فریم: {e}")
                    continue

        except PlaywrightTimeoutError:
            raise Exception("زمان اتصال به سایت تمام شد (Timeout)")
        except Exception as e:
            raise Exception(f"خطا در تولید تصویر: {str(e)}")
        finally:
            await browser.close()

    return image_paths


async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    prompt = update.message.text.strip()

    if len(prompt) < 5:
        await update.message.reply_text("پرامپت خیلی کوتاهه. لطفاً جزئیات بیشتری بنویس.")
        return

    status_msg = await update.message.reply_text("⏳ در حال ساخت تصویر...\nحدود ۲ تا ۳ دقیقه صبر کن.")

    try:
        image_paths = await generate_with_playwright(prompt)

        if not image_paths:
            await status_msg.edit_text("❌ هیچ تصویری ساخته نشد.\nممکنه سایت شلوغ باشه یا پرامپت مشکل داشته باشه. دوباره امتحان کن.")
            return

        # ارسال تصاویر (حداکثر ۹ تا)
        media = []
        files_to_close = []
        try:
            for path in image_paths[:9]:
                f = open(path, "rb")
                files_to_close.append(f)
                media.append(InputMediaPhoto(media=f))

            await update.message.reply_media_group(media=media)
            await status_msg.delete()
        finally:
            for f in files_to_close:
                f.close()

        # پاک کردن فایل‌های موقت
        for path in image_paths:
            try:
                path.unlink(missing_ok=True)
            except:
                pass

    except Exception as e:
        error_text = f"❌ خطا رخ داد:\n`{str(e)}`"
        logger.error(f"User {user.id} | Error: {e}")
        try:
            await status_msg.edit_text(error_text, parse_mode="Markdown")
        except:
            await update.message.reply_text(error_text, parse_mode="Markdown")


def main():
    print("ربات در حال راه‌اندازی...")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))

    print("✅ ربات شروع به کار کرد. منتظر پیام کاربران...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
