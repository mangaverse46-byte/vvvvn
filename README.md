# 🖤 Manga Virus

بوت تيليجرام للبحث عن المانجا والمانهوا وجلب صور الفصول من Manga API ثم تحويلها محلياً إلى PDF باستخدام `img2pdf`.

## المميزات الحالية
- اكتشاف المصادر المفعّلة تلقائياً من `action=sources`، مع cache مؤقت يُحدّث بعد 5 دقائق.
- لا توجد أسماء أو معرّفات مصادر ثابتة في كود البوت.
- البحث عن المانجا عبر `/search اسم المانجا`.
- عرض أحدث المانجا عبر `/latest`.
- عرض تفاصيل المانجا والفصول.
- تنزيل صور الفصل بترتيبها وإنشاء PDF محلياً ثم إرساله إلى تيليجرام.
- إعادة المحاولة عند أخطاء 429 و5xx واحترام Retry-After.
- مفضلة ومتابعة محليتان عبر SQLite.
- إشعارات تلقائية للفصول الجديدة للمانجا المتابَعة، مع فحص كل 15 دقيقة افتراضياً ومنع إشعار الفصول القديمة عند بدء المتابعة.
- اشتراك إجباري اختياري ولوحة إحصائيات للمشرف.

## متطلبات التشغيل
Python 3.10 أو أحدث، وبوت Telegram token.

## التثبيت
```bash
git clone https://github.com/mangaverse46-byte/vvvvn.git
cd vvvvn
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python main.py
```

ضع رمز البوت في `BOT_TOKEN` داخل `.env`. لا ترفع ملف `.env` إلى GitHub.

## الإعدادات
- `BOT_TOKEN`: رمز البوت من BotFather.
- `MANGA_API_BASE`: رابط API الموحد.
- `ADMIN_IDS`: أرقام Telegram ID للمشرفين، مفصولة بفواصل.
- `FORCE_SUB_CHANNEL`: يوزر القناة مثل `@channelname`، اتركه فارغاً لتعطيل الاشتراك الإجباري. يجب أن يكون البوت مشرفاً بالقناة.
- `MAX_DOWNLOAD_CONCURRENCY`: عدد تنزيلات الصور المتزامنة.
- `MAX_PDF_PAGES`: الحد الأعلى لصفحات PDF في النسخة الحالية.
- `CHECK_INTERVAL`: مدة فحص الفصول الجديدة بالثواني (افتراضياً 900 ثانية = 15 دقيقة).

## أوامر البوت
- `/start` بدء البوت.
- `/sources` عرض المصادر المفعّلة.
- `/search اسم المانجا` البحث.
- `/latest` أحدث المانجا.
- `/admin` إحصائيات الإدارة للمستخدمين الموجودين في ADMIN_IDS.

## عقد API المطلوب
يستخدم البوت واجهة موحدة:
- GET `?action=sources`
- GET `?action=latest&source=SOURCE_ID&page=1`
- GET `?action=search&source=SOURCE_ID&q=QUERY&page=1`
- GET `?action=details&source=SOURCE_ID&url=MANGA_URL`
- GET `?action=pages&source=SOURCE_ID&id=CHAPTER_ID_OR_URL`

لكي يظهر أي مصدر جديد تلقائياً، أضفه إلى سجل المصادر في API واجعله يدعم العمليات العامة نفسها. لا يحتاج البوت إلى تعديل عند إضافة مصدر متوافق.

## ملاحظات
- التحويل إلى PDF يتم داخل البوت محلياً، ولا يستخدم خدمة PDF خارجية.
- لا يرفع هذا المشروع أي token أو قاعدة بيانات أو ملفات PDF إلى GitHub.
- ميزة دمج عدة فصول تحتاج أن يدعم API عملية `action=merge`؛ سيتم تفعيلها في واجهة البوت بعد توصيل تدفق اختيار الفصول.
