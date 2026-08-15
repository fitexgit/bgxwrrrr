import os
import asyncio
import logging
import base64
from pathlib import Path
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

TOKEN = "7534267402:AAFaOmAaFbVmdpdC6RjKjV-71evLGVwd5Oc"

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
            viewport={"width": 1400, "height": 1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            ignore_https_errors=True,
        )
        page = await context.new_page()

        try:
            logger.info("۱. باز کردن صفحه...")
            await page.goto(GENERATOR_URL, wait_until="domcontentloaded", timeout=120000)
            await page.wait_for_timeout(12000)

            logger.info("۲. نوشتن پرامپت...")

            # نوشتن پرامپت + تریگر کردن همه eventهای لازم
            await page.evaluate(
                """(promptText) => {
                    const textareas = Array.from(document.querySelectorAll('textarea'));
                    let target = textareas.find(t => t.offsetWidth > 100 && t.offsetHeight > 40);
                    if (!target) target = textareas[0];
                    if (!target) return false;

                    target.focus();
                    target.value = '';
                    target.value = promptText;

                    // تریگر کردن eventهای مهم برای فریم‌ورک Perchance
                    ['input', 'change', 'keyup', 'blur'].forEach(evt => {
                        target.dispatchEvent(new Event(evt, { bubbles: true }));
                    });
                    return true;
                }""",
                prompt
            )
            logger.info("پرامپت نوشته شد.")
            await page.wait_for_timeout(2000)

            logger.info("۳. کلیک Generate...")

            await page.evaluate("""() => {
                const btn = Array.from(document.querySelectorAll('button')).find(b => 
                    b.innerText.toLowerCase().includes('generate')
                );
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            }""")
            logger.info("دکمه Generate کلیک شد.")

            # صبر بیشتر
            logger.info("۴. منتظر ساخت تصاویر (۳.۵ دقیقه)...")
            await page.wait_for_timeout(210000)

            logger.info("۵. جمع‌آوری تصاویر...")

            # اسکرین‌شات برای دیباگ
            await page.screenshot(path=OUTPUT_DIR / "after_wait.png", full_page=True)

            # جمع‌آوری از همه جا
            sources = [page] + page.frames
            for source in sources:
                try:
                    imgs = await source.locator("img").all()
                    for img in imgs:
                        src = await img.get_attribute("src")
                        if not src:
                            continue
                        if src.startswith("data:image"):
                            try:
                                header, encoded = src.split(",", 1)
                                data = base64.b64decode(encoded)
                                if len(data) > 5000:  # فقط تصاویر واقعی (نه آیکون)
                                    path = OUTPUT_DIR / f"img_{len(image_paths)}_{os.urandom(3).hex()}.png"
                                    with open(path, "wb") as f:
                                        f.write(data)
                                    image_paths.append(path)
                                    logger.info(f"تصویر ذخیره شد: {path.name}")
                            except:
                                pass
                except:
                    continue

            logger.info(f"تعداد تصاویر پیدا شده: {len(image_paths)}")

        except Exception as e:
            try:
                await page.screenshot(path=OUTPUT_DIR / "debug_error.png", full_page=True)
            except:
                pass
            raise Exception(str(e))
        finally:
            await browser.close()

    return image_paths


async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text.strip()
    if len(prompt) < 3:
        await update.message.reply_text("پرامپت خیلی کوتاهه.")
        return

    status_msg = await update.message.reply_text("⏳ در حال ساخت تصویر...\nحدود ۳.۵ دقیقه صبر کن.")

    try:
        image_paths = await generate_with_playwright(prompt)

        if not image_paths:
            await status_msg.edit_text("❌ تصویری ساخته نشد.\nفایل after_wait.png را چک کن.")
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
        logger.error(str(e))
        try:
            await status_msg.edit_text(f"❌ خطا:\n`{str(e)}`", parse_mode="Markdown")
        except:
            await update.message.reply_text(f"❌ خطا: {str(e)}")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))
    print("✅ ربات آماده است.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
