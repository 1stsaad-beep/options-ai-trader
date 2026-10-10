# Options AI Trader V0.3 — التشغيل والمحاكاة

هذه النسخة تستخدم MockBroker وبيانات اصطناعية فقط. وضع الحساب `paper` هنا يعني دفتر تنفيذ محليًا، وليس حساب IBKR Paper. `shadow` و`analysis` يمنعان التنفيذ. Live وIBKR وموج معطلة في الخادم والتطبيق. لا توجد كلمات مرور وسيط أو أموال حقيقية في خطوات التشغيل.

## التشغيل المحلي

تحتاج Python3.12 في بيئة الاختبار الموثقة، وGit عند استخدام سجل المشروع. من جذر المشروع:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.lock
pip install --no-deps -e './backend[test]'
python -m pytest -q backend --junitxml=test-results.xml
python scripts/smoke_http.py
```

شغّل API في الطرفية نفسها؛ يُولّد رمز محلي لا يُطبع أو يُرسل إلى المحادثة:

```sh
export OPTIONS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export DATABASE_URL=sqlite:///options_demo.db
export TRADING_MODE=paper
export ENABLE_LIVE=false
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

للعامل المستقل، افتح طرفية ثانية مع قاعدة البيانات نفسها ثم:

```sh
export DATABASE_URL=sqlite:///options_demo.db
export TRADING_MODE=paper
export ENABLE_LIVE=false
cd backend
python -m app.worker --interval 30
```

العامل يستمر دون التطبيق، ويسجل تحليلات وفرصًا وأسباب عدم التنفيذ. **لا يرسل أوامر تلقائية** ولا يصالح الحساب تلقائيًا. تشغيل API أو العامل بعد إعادة فتح القاعدة يبطل ثقة الحالة؛ أعد المصالحة من التطبيق بعد تشغيلهما. لا تُشغّل عمليات كثيرة لإبقاء الحالة موثوقة تلقائيًا.

API و`/docs` و`/openapi.json` تحتاج الترويسة `Authorization: Bearer <local-token>`. `/health` فقط متاح دون مصادقة ويعرض الإصدار ووسم المحاكاة. يمكن قراءة المخطط محليًا بواسطة:

```sh
curl -H "Authorization: Bearer $OPTIONS_API_TOKEN" http://127.0.0.1:8000/openapi.json
```

Swagger محمي أيضًا؛ فتحه العادي دون ترويسة مصادقة سيُرفض. الرمز هنا وصول شخصي لكل حسابات المحاكاة، وليس نظام مستخدمين متعددين.

## أول تجربة من Android

تحتاج Android7.0 أوأحدث (minSdk24،targetSdk36). APK التجريبي `options-ai-trader-v0.3.apk` موجود فيالتسليم وبُني فعليًا. افتحه علىالهاتف للتثبيت أو، معADB محلي:

```sh
adb install -r options-ai-trader-v0.3.apk
```

هذه نسخةdebug موقعة للتجربة، لم يُختبر تثبيتها علىهاتف فيهذه المهمة. افتح اتصال الخادم في التطبيق وأدخل الرمز محليًا؛ يبقى في الذاكرة ولا يُضمّن في APK.

إذا كان API على الحاسوب، مع اتصال USB:

```sh
adb reverse tcp:8000 tcp:8000
```

استخدم `http://127.0.0.1:8000` على الهاتف، أو `http://10.0.2.2:8000` في محاكي Android. الخادم البعيد يحتاج HTTPS؛ العميل يرفض HTTP البعيد وإعادة التوجيه. نسخة Android debug تسمح بالاتصال المحلي. لم تُختبر التجربة على هاتف فعلي إلا إذا ورد ذلك صراحةً في تقرير الاختبارات.

1. أضف حساب Mock ثم صالِح حالته. الحسابات قابلة للإضافة دون حد ثابت بثلاثة.
2. قائمة NVDA/AAPL/TSLA تبدأ غير مفعلة. أضف أو احذف أو أوقف أو فعّل الرموز لكل حساب. التحقق خاص بكتالوج Mock الموثق؛ ليس تحقق IBKR.
3. فعّل السهم أو اضغط تحديث بيانات المحاكاة لإنشاء ملاحظة سوق جديدة. مصالحة الحساب وحدها **لا تحدّث السوق**.
4. حالة الحساب صالحة120 ثانية، وملاحظة السوق60 ثانية. عند انتهاء الحد، يرفض الخادم شراءًا جديدًا حتى التحديث الصريح. الانقطاع ليس إذنًا لإعادة إرسال بمفتاح جديد.
5. أنشئ أمر Mock بحد سعري وعقد Call/Put. احتفظ بمفتاح منع التكرار؛ عند فقد الرد أعد الطلب نفسه بالمفتاح والحقول نفسها أو راجع قائمة الأوامر. اختلاف الحقول بالمفتاح نفسه مرفوض.
6. استخدم زر محاكاة التنفيذ الجزئي أو الإلغاء. التنفيذ يدوي واصطناعي؛ ليست هذه محاكاة سيولة بورصة أو أمرًا لدى وسيط.

كتالوج Mock يدعم رموزًا أكثر من الثلاثة الافتراضية. صيغة الخيار: Call أو Put طويل، مضاعف100، سعر تنفيذ صحيح بالدولار ضمن $50–$1000، انتهاء الجمعة خلال90 يومًا دون0DTE. القسط في النموذج بالسنت **لكل سهم**؛ تكلفة العقد تساوي القسط×100. اختيار العقد الكمي يستخدم فلاتر مستقلة موثقة في ENGINES.md.

## المخاطر والطوارئ

لكل حساب إعدادات مخاطر واستراتيجيات وقائمة ومراكز وأوامر مستقلة. الحدود الحالية تقبل أعدادًا صحيحة: مخاطرة الصفقة1–2%، الخسارة اليومية1–3%، التخصيص1–30%. يمكن تقليل حدود المجموعة المرتبطة، ويطبق المشرف أشد إعداد بين أعضائها مع حدود عالمية إضافية. `risk_group` و`connection_id` معرفا محاكاة، وليس بيانات دخول وسيط.

الإيقاف دائم ويمنع فتح مراكز جديدة ويلغي المتبقي من الأوامر النشطة. يمكن بعدها إرسال `SELL_TO_CLOSE` محدود السعر لعقود مملوكة فقط، بعد مصالحة حديثة ودفتر موثوق. انقطاع بيانات السوق لا يسمح بشراء جديد، لكنه لا يمنع إغلاقًا محدودًا للملكية الموثوقة. حالة حساب مجهولة أو دفتر متعارض يمنعان حتى هذا الإغلاق إلى أن تُحل المصالحة. لا تصفية تلقائية ولا إعادة تفعيل تلقائية ولا مسار Live.

انقطاع اتصال Mock مشترك يبطل ثقة كل الحسابات ذات `connection_id` نفسه. تُصالح الدفاتر لكل حساب على حدة دون خلط أو إعادة إرسال. الاتصال الحقيقي وإقرارات إلغاء الوسيط وأوامر حالتها غير محسومة ليست منفذة في هذه النسخة.

## الترقية من قاعدة V0.2

أوقف API والعامل، ثم أنشئ نسخة احتياطية قبل التشغيل الجديد. للـSQLite يمكن استخدام واجهة النسخ الرسمية في Python:

```sh
python - <<'PY'
import sqlite3
with sqlite3.connect('backend/options_demo.db') as source:
    with sqlite3.connect('options_demo_v02_backup.db') as backup:
        source.backup(backup)
PY
```

شغّل V0.3 على **قاعدة المشروع نفسها**. ستطبق الترحيلات1–3 في معاملة وتحفظ الحسابات والأوامر والتنفيذ والمراكز والسجلات. لا تُطبّقها على قاعدة مشروع آخر. العلاقات اليتيمة أو تاريخ ترحيلات غير متوافق يمنعان التشغيل. حدث الرصيد المستورد موسوم بأنه محلي وغير متحقق لدى وسيط. تفاصيل الترقيات في DATABASE_V03.md؛ الرجوع يتطلب استعادة نسخة احتياطية، ولا توجد downgrade تلقائية.

## Docker/PostgreSQL

```sh
python scripts/local_env.py
cd infra
docker compose --env-file .env -f compose.yaml up --build -d
```

الملف `.env` محلي بصلاحية0600 ومُستبعد منGit. API على localhost فقط، وPostgreSQL بلا منفذ منشور أو واجهة إدارة. لم يُشغّل Docker أو PostgreSQL بنجاح في هذه البيئة؛ نتيجة التهيئة والقيود في التقرير. لتجربة PostgreSQL على حاسوب مناسب استخدم قاعدة فارغة قابلة للحذف مع `scripts/postgres_check.py` وفق DATABASE_V03.md. لا تشغّله على بيانات مهمة.

## Termux

يمكن تجربة SQLite وAPI على الهاتف نفسه بعد توفير Python/Git في Termux. بناء Flutter/iOS داخل Termux ليس مسارًا مختبرًا هنا.

```sh
python -m venv .venv
. .venv/bin/activate
python - <<'PY'
from pathlib import Path
pins = Path('backend/requirements.lock').read_text().splitlines()
Path('requirements-termux.txt').write_text('\n'.join(p for p in pins if not p.startswith(('psycopg==', 'psycopg-binary=='))) + '\n')
PY
pip install -r requirements-termux.txt
cd backend
python -m pytest -q
export OPTIONS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export DATABASE_URL=sqlite:///options_demo.db
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

هذا المسار يستخدم مصدر `app` مباشرة، ولا يحتاج psycopg للـSQLite. قد تحتاج تبعيات Pydantic بناءً إضافيًا حسب هاتفك؛ لم يُختبر Termux على جهاز فعلي. إدارة الطاقة في Android قد توقف الخادم؛ للخدمة المستقلة المستمرة استخدم حاسوب Linux مستقلًا، دون نشر خدمة مدفوعة في هذه المهمة.

## بناء Android وiPhone لاحقًا

المصدر المشترك في `mobile/`، والمجلدان `android/` و`ios/` ضمن حزمة V0.3. انظر BUILD_V03.md وMOBILE.md للنسخ والقيود الفعلية. خطوات حاسوب يدعمFlutter:

```sh
cd mobile
./scripts/bootstrap.sh
flutter analyze
flutter test
flutter build apk --debug
```

GitHub Actions في `.github/workflows/android.yaml` يبني APK ويرفع artifact بعد نجاح التحليل والاختبارات. إعداد workflow لا يعني تشغيله. iOS workflow يدوي علىmacOS يبني دون توقيع؛ لا ادعاء بنجاحه هنا. تخصيص Bundle Identifier ومتطلبات Apple Developer/TestFlight في BUILD_V03.md. توزيع iPhone يتطلب حساب Apple وتوقيعًا وإجراءات TestFlight خارج هذا التسليم؛ لا بيانات اعتماد مطلوبة في المحادثة.

## ربط GitHub خاص

سجل Git محلي مستقل ويحفظ تاريخ V0.2 ودفعات V0.3. داخلZIP يوجد `repository/options-ai-trader.bundle`؛ لاستعادة مستودع كامل بتاريخه، من مجلدrepository بعد فك الضغط:

```sh
git clone options-ai-trader.bundle options-ai-trader-restored
cd options-ai-trader-restored
```

النسخة المباشرة في مجلدoptions-ai-trader صالحة لقراءة المصدر وتشغيله؛ استخدم النسخة المستعادة عند ربطGitHub. لا توجد صلاحية GitHub مثبتة في هذه المهمة. بعد توفير حسابك وGitHub CLI محليًا، من جذرالمشروع:

```sh
gh repo create options-ai-trader --private --source=. --remote=origin --push
```

إذا كان المستودع الخاص موجودًا مسبقًا، أضف remote الخاص به بدل إنشاء آخر. لا تستخدم remote موج. `.gitignore` يستبعد الأسرار وقواعد البيانات والتوقيع والمخرجات المؤقتة. لا يُنفّذ أي رفع خارجي أو تشغيلCI تلقائي هنا.
