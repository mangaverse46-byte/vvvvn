# Manga Virus v2

إعادة بناء منظمة لبوت المانجا باستخدام Python 3.11 وPyrogram 2.

## الحالة
هذه نسخة V2 مستقلة على فرع `rewrite/v2-clean-architecture`. لا تحذف أو تستبدل ملفات V1 أو قاعدة بياناتها.

## التشغيل على Debian / Ubuntu

```bash
cd /root/vvvvn
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python -m mangavirus.main
```

ضع بيانات تيليجرام في `.env` فقط:
- `API_ID`
- `API_HASH`
- `BOT_TOKEN`
- `OWNER_ID`

لا تضع بيانات حقيقية داخل GitHub ولا ترسلها في المحادثات.

## الأوامر
- `/start` القائمة الرئيسية
- `/search اسم المانجا` بحث في المصادر المفعلة
- `/latest` أحدث المانجا
- `/favorites` المفضلة
- `/stats` إحصائيات المالك

## التصميم
- `config.py`: إعدادات البيئة والتحقق منها.
- `database.py`: SQLite مع WAL وعمليات قصيرة.
- `manga_api.py`: عميل API غير حاجب للـ event loop.
- `pdf_engine.py`: تكوين PDF عبر واجهة المحرك.
- `handlers.py`: أوامر تيليجرام والأزرار.
- `state.py`: تخزين مؤقت محدود لمفاتيح callback.

## ملاحظات
- قاعدة البيانات الجديدة منفصلة افتراضياً في `data/mangavirus.sqlite3`.
- لا تنقل قاعدة V1 قبل تنفيذ أداة ترحيل واختبارها على نسخة احتياطية.
- ابدأ التشغيل في نافذة واحدة فقط لكل bot token.
