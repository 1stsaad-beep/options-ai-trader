# تقرير الاختبارات الفعلية — Engineering RC2 build 14

تاريخ التحقق **2026-10-11 UTC**. هذا قبول للسيناريوهات المحددة في المحاكاة والبحث، وليس اكتمال V1.0 أو نجاح تكامل وسيط.

## المصدر والأدلة

- بدء الاستئناف من رأس نظيف `3a72226143944dd8985f14d82cc14afc45acbb8f`.
- الخادم المقبول: `381eec3cf2ed1454764d75ab51683dcf3634e453`.
- الهاتف build 14: `c6345ceeb5a94642385aa6eacaaaca322554f29d`؛ لم يغير runtime الخادم.
- أدلة الانتهاء والخادم: [expiry-20261011](evidence/expiry-20261011/). الهاتف: [backup-20261011](evidence/backup-20261011/).
- سجل build 13 السابق (782 Python،171 Flutter،14 PostgreSQL) محفوظ في [engineering-20261011](evidence/engineering-20261011/) وتاريخ Git وPROGRESS. الأرقام التالية هي القبول الحالي؛ لا تُجمع المجموعات الجزئية أو منصتا Flutter لتضخيمه.

| البوابة | النتيجة الفعلية | ملف الدليل |
|---|---|---|
| Python كاملة محليًا | 850 ناجحًا، صفر فشل/خطأ/تجاوز | `expiry-20261011/python-full.xml` و`.txt` |
| Python كاملة في CI | 850 ناجحًا، صفر فشل/خطأ/تجاوز | `expiry-20261011/cloud-backend-test-results.xml` |
| الانتهاء/التنفيذ المستهدف | 214 ناجحًا، قبل إضافة آخر حالتي تكامل | `expiry-20261011/expiry-targeted.xml` |
| الانتهاء: المصدر الأصلي مقابل الحالي | 22 فشلًا قبل الإصلاح،22 نجاحًا بعده | `expiry-20261011/us-expiry-before.xml` و`us-expiry-after.xml` |
| HTTP/worker/process restart | ناجح محليًا وعلى CI | `expiry-20261011/http-smoke.txt` و`cloud-backend-http-smoke.json` |
| PostgreSQL أساسي | ناجح | `expiry-20261011/cloud-backend-postgres-basic.txt` |
| PostgreSQL V1 | 22 فحصًا ناجحًا، صفر فاشل | `expiry-20261011/cloud-backend-postgres-v1-results.json` |
| PostgreSQL backup/restore | 10 فحوص ناجحة | `expiry-20261011/cloud-backend-postgres-backup-restore.json` |
| Docker Compose | 12 فحصًا ناجحًا، migrations 1–5 | `expiry-20261011/cloud-compose-compose-smoke.json` |
| Flutter Linux | 186 ناجحًا، صفر فشل/خطأ/تجاوز، done.success=true | `backup-20261011/flutter-android-build14.jsonl` |
| Flutter macOS | 186 ناجحًا، صفر فشل/خطأ/تجاوز، done.success=true | `backup-20261011/flutter-ios-build14.jsonl` |
| Flutter analyze والبناء | ناجحة على المنصتين | تشغيلات Android/iOS أدناه |
| الأسرار/الاعتماديات | بوابة ناجحة ضمن حدود الفحص | `backup-20261011/cloud-security-*` |

Python لديه تحذير Starlette/httpx واحد سابق. Flutter وPostgreSQL وDocker لم تُشغّل محليًا؛ النتائج أعلاه من GitHub Actions الفعلي. نسخة PostgreSQL harness التي جُربت على SQLite موسومة `postgresql_executed:false` ولا تستخدم كدليل PostgreSQL؛ التقرير السحابي المستقل يثبت تشغيله الفعلي.

## ما تثبته الدفعتان الجديدتان

- **46 حالة تقويم انتهاء نقية و22 حالة خدمة/تنفيذ:** Call/Put، DST، عطلة الجمعة والإغلاق المبكر، السماح بالتخفيض قبل cutoff، حفظ تكلفة وكمية المتبقي بعد تنفيذ جزئي، رسوم وإيصالات لا تتكرر بعد restart، عدم اختلاق تقييم من mark جديد، قفل العكس عند تعرض غير مسوى، missed tick، calendar unavailable، منع تبديل السياسة لتجاوز القفل، وإبقاء إغلاق المملوك الصحيح ممكنًا.
- **15 حالة هاتف جديدة:** 12 محرك/مخزن و3 widget. نقل دفتر Demo كامل وإعادة فتحه مع الأصل المحفوظ، حسابات وصلاحيات مستقلة، JSON غير صالح/إصدار مستقبلي/حجم/خلط ملكية/حقول اعتماد، clipboard الصريح، معاينة وإلغاء وتأكيد، فشل حفظ قبل/بعد الكتابة، فشل rollback وقفل عدم اليقين، قراءة تالفة/مفقودة، تزامن ومعاينة قديمة.
- إصلاح الحفظ العادي يغطي أيضًا كتابة ناجحة جزئيًا يعقبها استثناء؛ الذاكرة وحدها لا تُعد إثباتًا لعودة المخزن. الاختبارات تستخدم واجهة DemoStore؛ SharedPreferences الفعلي والتحمل أمام انقطاع الطاقة غير مثبتين.
- اختبارات السلامة السابقة ما زالت ضمن المجموعة: BUY آلي وهمي، SL/TP/trailing/partial/time/swing، الخروج رغم فشل تحليل اختياري، العكس بعد flat والمصالحة في الاتجاهين، منع المتعاكس والمكرر وبيع غير المملوك، الحسابات والرسوم والتزامن والانقطاع وLive المقفل وسببية replay. [مصفوفة الحالات](RC2_SAFETY_MATRIX.md).

## المحاولات الفاشلة والتصحيحات

المصدر المحفوظ 3a722 فشل في 22 اختبار انتهاء جديدة قبل الإصلاح. أثناء التوافق الأول ظهر اختلاف في نص خطأ السنة غير المدعومة (1 فشل،147 نجاحًا)؛ أعيد ترتيب تشخيص Market session قبل تشخيص الانتهاء دون إلغاء أي قيد. القبول النهائي 850 ناجحًا.

المراجعة المستقلة للهاتف وجدت حالات المعاينة القديمة وعدم يقين rollback وفساد القراءة بعده، وكذلك خلل الحفظ العادي الذي كان يرجع الذاكرة فقط. صُححت قبل checkpoint c6345ce، واجتازت بوابتاه analyze والاختبارات والبناء من أول تشغيل لهذا المصدر. لا ادعاء بتشغيل Flutter محليًا. إخفاقات دفعات build 13 الأقدم وتفاصيل إصلاحها محفوظة في PROGRESS وأدلتها الأصلية.

## التشغيلات

- [الخادم/PostgreSQL/Compose 38126076027](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38126076027).
- [أمان الخادم 38126076071](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38126076071).
- [Android/Flutter 38126818937](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38126818937).
- [iOS/Flutter 38126818914](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38126818914).
- [أمان build 14 رقم 38126818920](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38126818920).

## ملفات البناء والتحقق

APK 1.0.0 code 14، 154973056 بايت، SHA-256 `b567ae38c0e8df58a48b8799cd6dbb3fe746a8a9aa5ea3ff3d52333369dc2ef6`؛ طابق checksum CI، وCRC صحيح، وapksigner v2 ناجح بشهادة runner Debug مؤقتة. ليس مفتاحًا ثابتًا ولا دليل تثبيت جهاز.

أرشيف iOS SHA-256 `96a5c3589ee8b5ef6c82ef582dfcc86366fb940d9ee3df58a6772a45621c5e30`؛ CRC وInfo.plist تحققا، Runner.app 1.0.0 build 14، iOS 15.0. لا توقيع للتطبيق الرئيسي أو TestFlight؛ وجود CodeResources في frameworks المضمنة لا يمنح توقيع توزيع للتطبيق.

## الحدود

لا اختبار هاتف/محاكي تثبيت أو ترقية أو أداء جهاز، ولا ضمان SharedPreferences/fsync. استيراد نسخة من حالة تخزين تالفة عند الفتح الأول غير مدعوم. لا IBKR/Paper أو سوق حقيقي أو ربحية OOS، ولا ممارسة/تخصيص/تسوية مؤهلة، ولا إنتاج طويل أو pentest. الأدلة لا تتجاوز هذه الحدود.
