# التشغيل والمراجعة — محاكاة فقط

لا توجد واجهة تداول Live ولا مسار اتصال فعلي بـ IBKR. رمز API هنا مفتاح محلي لتطبيقك، وليس بيانات دخول لوسيط. لا تُرسل المفاتيح إلى المحادثة ولا تُضمّنها في المصدر أو APK.

## حاسوب Linux / macOS / Windows مع Python

من جذر المشروع:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e './backend[test]'
cd backend
python -m pytest -q
```

أنشئ رمزًا محليًا في الطرفية دون إدخاله في المحادثة:

```sh
export OPTIONS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export DATABASE_URL=sqlite:///options_demo.db
export TRADING_MODE=paper
export ENABLE_LIVE=false
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

يمكن تشغيل عامل الظل في طرفية أخرى بنفس `DATABASE_URL`، مستقلًا عن التطبيق:

```sh
cd backend
python -m app.worker
```

العامل يحلل بيانات اصطناعية ويسجل قرارات وفرصًا؛ لا يرسل أوامر تلقائية. افتح `/docs` محليًا لمراجعة API وأضف ترويسة `Authorization: Bearer <local-token>` في العميل. `/health` فقط متاح دون المصادقة. عدم وجود رمز قوي يمنع تشغيل API.

حالة الحساب بعد إعادة فتح قاعدة البيانات تصبح غير معروفة عمدًا. استخدم زر المصالحة في التطبيق أو مسار `/api/accounts/{id}/reconcile` قبل إرسال أمر محاكاة جديد. المصالحة Mock فقط؛ ليست مصالحة IBKR. الافتراضي NVDA/AAPL/TSLA في قائمة غير مفعّلة؛ فعّل كل سهم بعد تحقق Mock. لا تمثل هذه العملية تصريح بيانات سوق حقيقية.

## Docker + PostgreSQL

```sh
python scripts/local_env.py
cd infra
docker compose --env-file .env -f compose.yaml up --build -d
```

يستمع API افتراضيًا على localhost فقط. تحفظ PostgreSQL الحالة في volume دائم. لا تنشر API إلى الإنترنت دون TLS وإدارة وصول مناسبة. ملف `.env` مولّد بصلاحية محلية محدودة ومُستبعد من Git، ولا يتضمن بيانات وسيط. لا تُحذف volume إلا إن كنت تريد حذف سجلات المحاكاة.

ملفات Docker وPostgreSQL مُعدّة؛ نتائج تشغيلها الفعلية موضحة في تقرير الاختبارات. لا تعتبر إعداد CI دليلاً على أن المهمة نفذت هناك.

## هاتف Android

أنشئ APK تجريبيًا على حاسوب يدعم Flutter/Android SDK أو شغّل مهمة GitHub Actions بعد رفع المشروع إلى مستودعك الخاص. تفاصيل تهيئة المنصات في `docs/MOBILE.md`. عند تثبيت التطبيق اكتب عنوان الخادم ورمز API محليًا في شاشة الاتصال. لا تحفظ الشاشة أو تشارك رمز الاتصال. الرمز يبقى في ذاكرة التطبيق ولا يُحفظ تلقائيًا على الجهاز.

للهاتف مع خادم على حاسوب عبر USB:

```sh
adb reverse tcp:8000 tcp:8000
```

استخدم `http://127.0.0.1:8000` للتجربة عبر هذا النفق. محاكي Android يستخدم عادة `http://10.0.2.2:8000`. وصول شبكة خارج localhost يتطلب HTTPS، ولا تعرض المنفذ العمومي مباشرة. نسخة التطوير تسمح بـHTTP المحلي فقط حسب التحقق في العميل.

## Termux

Termux مناسب لتجربة خادم Python محليًا، وليس لبناء iOS. بناء Flutter/Android الكامل غير مختبر داخل Termux. على جهازك، بعد توفير Python وGit في Termux، انسخ المشروع ثم:

```sh
cd options-ai-trader
python -m venv .venv
. .venv/bin/activate
pip install fastapi uvicorn pytest httpx
cd backend
python -m pytest -q
export OPTIONS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export DATABASE_URL=sqlite:///options_demo.db
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

مسار SQLite لا يحتاج psycopg؛ تثبيت حزمة PostgreSQL الثنائية قد لا يكون متاحًا لمعمارية Android. هذا المسار البديل يستخدم مصدر `app` مباشرة دون تثبيت الحزمة القابلة للتحرير. قد تتطلب Pydantic تبعيات بناء حسب بيئة هاتفك؛ Termux لم يُختبر على جهاز فعلي هنا.

استخدم التطبيق على الهاتف نفسه مع localhost ورمزك المحلي. Android قد يوقف العمليات الخلفية؛ Termux للاختبار فقط وليس بديلًا لخادم دائم. للخادم المستقل شغّل Docker/خدمة على Linux منفصلة عن الهاتف، مع نسخ احتياطي دوري لقاعدة المحاكاة.

## الإيقاف الطارئ

الإيقاف على الحساب أو عالميًا دائم في قاعدة البيانات، يلغي الأوامر غير المنفذة ويمنع الطلبات الجديدة. لا توجد إعادة تفعيل من الواجهة في هذه النسخة. لا يغلق الإيقاف المراكز تلقائيًا. يمكن مراجعة السجل؛ الإيقاف يمنع أيضًا إرسال أوامر إغلاق جديدة في هذه النسخة، وأي سياسة إعادة تشغيل أو تصفية تحتاج تصميمًا واختبارًا لاحقين.

## إنشاء مستودع خاص لاحقًا

المشروع له Git محلي مستقل. لا تتضمن الحزمة ملفات موج. لإنشاء مستودع خاص بعد توفير GitHub CLI وصلاحية حسابك محليًا:

```sh
gh repo create options-ai-trader --private --source=. --remote=origin --push
```

هذا الأمر إجراء لاحق لم يُنفّذ هنا. لا تستخدم أي remote يخص موج، ولا ترفع `.env` أو قاعدة البيانات.
