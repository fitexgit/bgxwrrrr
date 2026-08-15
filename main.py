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
        "سلام 👋\nپرامپت تصویر رو بفرست.\n\nمثال:\n`cute korean girl, long black hair, soft smile`",
        parse_mode="Markdown"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.")


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
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1400, "height": 1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            ignore_https_errors=True,
        )
        page = await context.new_page()

        try:
            logger.info("باز کردن صفحه...")
            await page.goto(GENERATOR_URL, wait_until="domcontentloaded", timeout=120000)
            await page.wait_for_timeout(15000)

            logger.info("ست کردن پرامپت...")

            # روش قوی‌تر برای ست کردن پرامپت در فریم‌ورک Perchance
            await page.evaluate(
                """(promptText) => {
                    // ۱. پیدا کردن textarea اصلی
                    const textareas = Array.from(document.querySelectorAll('textarea'));
                    let ta = textareas.find(t => t.offsetWidth > 150 && t.offsetHeight > 50);
                    if (!ta) ta = textareas[0];
                    if (!ta) return 'no-textarea';

                    // ۲. پاک کردن و نوشتن
                    ta.focus();
                    ta.value = '';
                    ta.value = promptText;

                    // ۳. تریگر eventها
                    ta.dispatchEvent(new Event('input', { bubbles: true }));
                    ta.dispatchEvent(new Event('change', { bubbles: true }));

                    // ۴. اگر فریم‌ورک از window.input استفاده می‌کند
                    if (window.input) {
                        window.input.description = promptText;
                    }

                    return 'ok';
                }""",
                prompt
            )

            await page.wait_for_timeout(2000)

            logger.info("کلیک روی Generate...")

            # چند روش برای کلیک
            clicked = await page.evaluate("""() => {
                // روش ۱: پیدا کردن دکمه با متن
                let btn = Array.from(document.querySelectorAll('button')).find(b => 
                    b.innerText.toLowerCase().includes('generate')
                );
                
                if (btn) {
                    btn.click();
                    return 'clicked-by-text';
                }

                // روش ۲: پیدا کردن دکمه‌ای که کلاس یا استایل خاصی دارد
                btn = document.querySelector('button');
                if (btn) {
                    btn.click();
                    return 'clicked-first-button';
                }

                return 'not-found';
            }""")

            logger.info(f"نتیجه کلیک: {clicked}")

            # صبر طولانی
            logger.info("منتظر تولید تصویر (۳.۵ دقیقه)...")
            await page.wait_for_timeout(210000)

            # اسکرین‌شات بعد از صبر
            await page.screenshot(path=OUTPUT_DIR / "after_generate.png", full_page=True)
            logger.info("اسکرین‌شات after_generate.png ذخیره شد")

            # جمع‌آوری تصاویر
            logger.info("جمع‌آوری تصاویر...")
            sources = [page] + list(page.frames)

            for source in sources:
                try:
                    for img in await source.locator("img").all():
                        src = await img.get_attribute("src")
                        if src and src.startswith("data:image") and len(src) > 1000:
                            try:
                                header, encoded = src.split(",", 1)
                                data = base64.b64decode(encoded)
                                if len(data) > 8000:  # فیلتر کردن آیکون‌های کوچک
                                    path = OUTPUT_DIR / f"img_{len(image_paths)}_{os.urandom(3).hex()}.png"
                                    with open(path, "wb") as f:
                                        f.write(data)
                                    image_paths.append(path)
                                    logger.info(f"تصویر ذخیره شد: {path.name}")
                            except:
                                pass
                except:
                    continue

            logger.info(f"تعداد کل تصاویر: {len(image_paths)}")

        except Exception as e:
            try:
                await page.screenshot(path=OUTPUT_DIR / "error.png", full_page=True)
            except:
                pass
            raise Exception(str(e))
        finally:
            await browser.close()

    return image_paths


async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text.strip()
    if len(prompt) < 3:
        await update.message.reply_text("پرامپت کوتاهه.")
        return

    status = await update.message.reply_text("⏳ در حال ساخت...\nحدود ۳.۵ دقیقه صبر کن.")

    try:
        paths = await generate_with_playwright(prompt)

        if not paths:
            await status.edit_text("❌ تصویری ساخته نشد.\nفایل after_generate.png را چک کن.")
            return

        media = []
        files = []
        try:
            for p in paths[:8]:
                f = open(p, "rb")
                files.append(f)
                media.append(InputMediaPhoto(media=f))
            await update.message.reply_media_group(media=media)
            await status.delete()
        finally:
            for f in files:
                f.close()

        for p in paths:
            try:
                p.unlink(missing_ok=True)
            except:
                pass

    except Exception as e:
        logger.error(str(e))
        await status.edit_text(f"❌ خطا:\n`{e}`", parse_mode="Markdown")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))
    print("✅ ربات آماده است")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
