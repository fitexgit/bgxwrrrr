FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

# کپی فایل‌های پروژه
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# مرورگر از قبل داخل ایمیج هست، ولی برای اطمینان:
RUN playwright install chromium

CMD ["python", "main.py"]
