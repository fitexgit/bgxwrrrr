import os
import asyncio
import logging
import base64
from pathlib import Path
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ==================== توکن برای تست ====================
TOKEN = "7534267402:AAFaOmAaFbVmdpdC6RjKjV-71evLGVwd5Oc"
# ======================================================

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
        "سلام 👋\n"
        "پرامپت تصویر رو بفرست تا برات بسازم.\n\n"
        "مثال:\n"
        "`cute korean girl, long black hair, soft smile, white sweater`",
        parse_mode="Markdown"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.")


async def generate_with_playwright(prompt: str, negative: str = "low quality, blurry, deformed, bad anatomy, extra limbs, watermark") -> list[Path]:
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
                "--window-size=1280,900",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            ignore_https_errors=True,
            java_script_enabled=True,
        )
        page = await context.new_page()

        try:
            logger.info("در حال باز کردن صفحه...")
            await page.goto(GENERATOR_URL, wait_until="networkidle", timeout=180000)
            
            # صبر اضافی برای لود کامل جاوااسکریپت
            await page.wait_for_timeout(12000)

            logger.info("در حال پیدا کردن فیلد پرامپت...")

            # چند روش مختلف برای پیدا کردن textarea
            textarea = None
            selectors = [
                "textarea",
                "textarea[placeholder*='description' i]",
                "textarea[placeholder*='prompt' i]",
                "textarea[data-name='description']",
                ".input-ctn textarea",
                "#appEl textarea",
            ]

            for selector in selectors:
                try:
                    loc = page.locator(selector).first
                    await loc.wait_for(state="visible", timeout=15000)
                    textarea = loc
                    logger.info(f"فیلد پیدا شد با سلکتور: {selector}")
                    break
                except:
                    continue

            if textarea is None:
                # آخرین تلاش: همه textareaها را چک کن
                all_textareas = await page.locator("textarea").all()
                logger.info(f"تعداد textarea پیدا شده: {len(all_textareas)}")
                if all_textareas:
                    textarea = all_textareas[0]
                else:
                    # اسکرین‌شات برای دیباگ
                    screenshot_path = OUTPUT_DIR / "debug_timeout.png"
                    await page.screenshot(path=screenshot_path, full_page=True)
                    raise Exception("هیچ فیلد متنی (textarea) پیدا نشد. احتمالاً صفحه کامل لود نشده.")

            await textarea.click()
            await textarea.fill("")
            await textarea.fill(prompt)
            logger.info("پرامپت نوشته شد.")

            # سعی در نوشتن negative
            try:
                neg = page.locator("text=Anti-Description").locator("xpath=..").locator("textarea").first
                if await neg.count() > 0:
                    await neg.fill(negative)
            except:
                pass

            # پیدا کردن و کلیک دکمه Generate
            logger.info("در حال پیدا کردن دکمه Generate...")
            generate_btn = None
            btn_selectors = [
                "button:has-text('generate')",
                "button:has-text('Generate')",
                "button:has-text('Generate')",
                "text=generate",
                "button >> text=/generate/i",
            ]

            for sel in btn_selectors:
                try:
                    btn = page.locator(sel).first
                    await btn.wait_for(state="visible", timeout=10000)
                    generate_btn = btn
                    break
                except:
                    continue

            if generate_btn is None:
                raise Exception("دکمه Generate پیدا نشد.")

            await generate_btn.click()
            logger.info("دکمه Generate کلیک شد. منتظر ساخت تصاویر...")

            # صبر طولانی برای تولید تصویر
            await page.wait_for_timeout(200000)  # حدود ۳ دقیقه و ۲۰ ثانیه

            logger.info("در حال جمع‌آوری تصاویر...")
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
                            logger.info(f"تصویر ذخیره شد: {path.name}")
                except Exception as e:
                    logger.warning(f"خطا در فریم: {e}")

            if not image_paths:
                # اسکرین‌شات نهایی برای دیباگ
                await page.screenshot(path=OUTPUT_DIR / "debug_no_image.png", full_page=True)

        except PlaywrightTimeoutError as e:
            try:
                await page.screenshot(path=OUTPUT_DIR / "debug_timeout.png", full_page=True)
            except:
                pass
            raise Exception("زمان اتصال به سایت تمام شد (Timeout) - صفحه کامل لود نشد یا فیلدها پیدا نشدند")
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

    status_msg = await update.message.reply_text(
        "⏳ در حال ساخت تصویر...\n"
        "حدود ۳ تا ۴ دقیقه صبر کن.\n"
        "لطفاً پیام جدید نفرست."
    )

    try:
        image_paths = await generate_with_playwright(prompt)

        if not image_paths:
            await status_msg.edit_text(
                "❌ هیچ تصویری ساخته نشد.\n"
                "سایت ممکن است شلوغ باشد یا مشکل موقت داشته باشد.\n"
                "چند دقیقه دیگر دوباره امتحان کن."
            )
            return

        media = []
        files = []
        try:
            for path in image_paths[:9]:
                f = open(path, "rb")
                files.append(f)
                media.append(InputMediaPhoto(media=f))

            await update.message.reply_media_group(media=media)
            await status_msg.delete()
        finally:
            for f in files:
                try:
                    f.close()
                except:
                    pass

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

    print("✅ ربات شروع به کار کرد.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
