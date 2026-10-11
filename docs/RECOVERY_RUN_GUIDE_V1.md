# دليل التشغيل والاستئناف — RC2 Recovery

## Android المحلي

نزّل `options-ai-trader-v1.0-rc2-preview.apk` وتحقق من SHA256SUMS. استخدم preview الموقع، لا unsigned. هوية التطبيق منفصلة عن RC1 وV0.5؛ احتفظ بالتطبيقات القديمة وبياناتها. لا يوجد اختبار تثبيت جهاز موثق حتى الآن.

Demo يعمل بلا خادم أو شبكة. ابدأ بحساب اصطناعي، فعّل إعدادات الأتمتة، وتقدم بملاحظات السوق. راقب الأوامر والجزئيات والرسوم والإغلاق وسجل القرار. التعزيز والانعكاس يحتاجان تفعيلًا مستقلًا. فتح التطبيق في وضع الطيران تجربة مناسبة للفصل عن Backend. الزمن يتوقف بالخلفية.

تفاصيل الواجهات والتثبيت في `options-ai-trader-v1.0-android-guide.md` و`MOBILE_V1.md` و`RC2_RESEARCH_UI.md`.

## خادم Mock اختياري

من checkout للفرع `recovery/v1.0-20261011` وباستخدام Python 3.12:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.lock
pip install --no-deps -e './backend[test]'
python -m pytest -q backend
python scripts/smoke_http.py
python scripts/demo_lifecycle.py
```

سكربت HTTP ينشئ خادم loopback وقاعدة مؤقتة خاصة به ويغلقهما؛ لا يستخدم حساب تداول. تثبيت backend مطلوب لسكربتات العرض.

لتشغيل خادم دائم داخل جهازك فقط:

```bash
export OPTIONS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export TRADING_MODE=paper
export BROKER_PROVIDER=mock
export ENABLE_LIVE=false
export DATABASE_URL="sqlite:///$PWD/options_demo.db"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`paper` هنا تسمية لوضع Mock القديم، وليس اتصال IBKR. `/health` عام، و`/api/*` و`/docs` و`/openapi.json` تتطلب الرمز. لا تضع الرمز في Git أو المحادثة. Demo الهاتف وMock الخادم منفصلان ولا ينقلان الحسابات تلقائيًا.

في طرفية أخرى تحمل متغيرات البيئة نفسها:

```bash
python -m app.worker --once
# بعد المصالحة الصريحة وتفعيل الحساب وتحديث بيانات Mock فقط:
python -m app.worker --execute-mock --interval 30
```

فتح Repository في عملية جديدة يبطل الثقة حتى المصالحة؛ لا تستنتج صلاحية الحساب من بدء العامل. اقتباسات Mock تنتهي بعد 60 ثانية وتحتاج تحديثًا صريحًا؛ لا توجد تغذية سوق حقيقية. دليل `OPERATIONS_V1.md` يوضح Docker والإعدادات و`POSTGRES_BACKUP_RESTORE.md` يوضح استعادة PostgreSQL إلى هدف جديد.

## iOS

ملف ZIP يحتفظ بـRunner.app غير موقع ونتائج Flutter. ليس IPA أو رابط TestFlight. البناء نجح على macOS؛ التوزيع يحتاج شهادات وProvisioning وحسابًا مخولًا واختبار جهاز. لم تُشتر خدمة أو عضوية. تفاصيل إعادة البناء في `options-ai-trader-v1.0-iphone-guide.md`.

## استئناف التطوير دون فقد العمل

1. اقرأ `FINAL_DELIVERY.md` و`PROGRESS.md` و`RECOVERY_STATUS.md` وافحص رأس الفرع البعيد قبل التعديل.
2. احتفظ بأي تغييرات متاحة في فرع مستقل. لا تفترض وجود workspace جلسة منتهية.
3. أنجز دفعة محدودة، ثم الاختبارات المرتبطة وCommit ورفعًا دون force، واقرأ الرأس البعيد للتحقق قبل الدفعة التالية.
4. حدّث PROGRESS في كل دفعة. شغّل البوابة الكاملة عند القبول؛ لا تعِد بناء الهاتف عند تغيير تقارير أو خادم فقط.
5. النواقص الوظيفية مرتبة في `RECOVERY_REQUIREMENTS_V1.md`. لا تبدأ من main/V0.5 ولا تعِد تنفيذ ميزات RC2 المحفوظة.

لم يتوفر اعتماد Git HTTPS مباشر في جلسة الاستعادة؛ نُشرت Commits عبر Git Data API بأب سابق وشجرة مطابقة وتحديث مرجع غير قسري، ثم تحققت المطابقة محليًا. المصدر وتاريخ Git محفوظان في المستودع؛ عدم توفر المصادقة المحلية لا يعني إنشاء مشروع جديد.

## تحديث التشغيل — Engineering build 13

ملف التسليم الحالي build 13 في `FINAL_DELIVERY.md`؛ تعليمات فحص الجهاز والترقية في `PHONE_ACCEPTANCE_GUIDE_V1.md`. لا تفترض توافق توقيع معاينتين من runner مختلف. لا واجهة تصدير/استيراد Demo كاملة حاليًا، لذلك احتفظ بالتطبيق القديم واستعمل بيئة اختبار منفصلة عند تعارض التوقيع.

قاعدة البيانات أصبحت migration **5** بإضافة جدول ملاحظات البحث وقيود immutability. خذ نسخة احتياطية قبل ترقية قاعدة مستخدمة؛ اختُبرت إضافة migration من v4 وPostgreSQL backup/restore إلى قاعدة جديدة. لا تُشغّل سكربتات الاختبار disposable على بيانات مستخدمة.

مسار مختبر البحث المتصل (كل مسارات `/api` تتطلب Bearer، ولا تستعمل وسيطًا):

- `GET /api/accounts/{account}/research/{symbol}`: بحث اصطناعي Shadow.
- `POST /api/accounts/{account}/research/{symbol}/snapshot` بجسم `{}`: حفظ أصل القرار.
- `GET /api/accounts/{account}/research/{symbol}/snapshots`: قائمة محدودة مع `truncated`.
- `POST /api/accounts/{account}/research/{symbol}/snapshots/{id}/observations` بجسم `{}`: حفظ الملاحظة الاصطناعية الحالية فقط.
- `GET /api/accounts/{account}/research/{symbol}/snapshots/{id}/replay`: يعرض الأصل ويحسب outcome فقط من ملاحظتين لاحقتين محفوظتين.

احفظ ملاحظتين في دقيقتين مختلفتين بعد القرار. مرور الوقت أو إعادة GET وحده لا يملأ النقص. النتيجة ليست أسعار سوق. اللقطات القديمة بلا quote model version تبقى للعرض ولا نختلق إصدارًا لها. واجهة الهاتف تعرض الأزرار بالعربية وتمنع إعادة POST تلقائيًا بعد فقد الرد.

إعداد الحساب الافتراضي `session_policy=synthetic_24x7`. يمكن عبر إعدادات مخاطر API اختيار `us_equity_options_2026_2027` مع `session_exit_buffer_minutes` من 1 إلى 120 (15 افتراضيًا). اقرأ `MARKET_SESSION_POLICY_V1.md` قبل تفعيله: عطلات/إغلاق مبكر وDST للخادم فقط، وخارج السنوات المدعومة يفشل الإذن. لا يجعل هذا الخيار العقد أو سياسة الانتهاء واقعية.

للاستئناف الهندسي التفصيلي اقرأ `ENGINEERING_RESUME_V1.md`؛ لا تعِد تنفيذ الأعمال المحفوظة أو تستبدل الأدلة التاريخية بنتائج متخيلة.
