# تقرير الاختبارات الفعلية — Engineering RC2، 2026-10-11 UTC

> أحدث دفعة للخادم: 850 Python ناجحًا محليًا وHTTP/worker/restart ناجح؛ قبل الإصلاح 22 فشلًا وبعده 22 نجاحًا لحالات الانتهاء. الأدلة في `evidence/expiry-20261011/`. نجحت بوابات PostgreSQL (22) وbackup/restore (10) وCompose (12) والأمان للمصدر `381eec3`؛ الأرقام والروابط أدناه سجل قبول build 13 السابق.

**القبول يخص المحاكاة والبحث المحددين، وليس اكتمال V1.0 أو اتصالًا بوسيط.** الأدلة في `docs/evidence/engineering-20261011/`؛ الأدلة التاريخية باقية في `docs/evidence/recovery-20261011/` و`docs/evidence/rc2/`.

## تتبع المصدر

- بدأت المهمة من `72abca1c637fbabf55ecf5d30dcb276c9798170c` على Recovery، لا main.
- آخر تغيير runtime: `055f42c4aed2d1baaef199a4e38b6873ab1e63b2`.
- مصدر بناء الهاتف: `67ddb6e7cf58cd59604ab7187a6864d527a69aac`؛ الفرق بعد 055f اختبار widget وسجله وPROGRESS فقط، دون runtime أو lockfile.
- رأس تسليم التقارير اللاحق لا يعيد بناء التطبيق لأن ملفات التنفيذ لم تتغير.

| البوابة | النتيجة الفعلية | الدليل |
|---|---|---|
| Python كاملة محليًا | 782 ناجحًا، 0 فشل/خطأ/تجاوز | `python-evidence-full.xml` و`.txt` |
| Python كاملة في CI | 782 ناجحًا، 0 فشل/خطأ/تجاوز | `cloud-backend-test-results.xml`، 10.733 ثانية |
| عقد بحث Python/Dart | 34 ناجحًا في دفعة العقد | `research-contract.xml`؛ fixture خدمة حقيقي يقرأه Dart |
| مخاطر التنفيذ والخروج المستهدفة | 164 ناجحًا بعد الإصلاح | `safety-after.junit.xml` |
| التقويم والتنفيذ المستهدف | 120 ناجحًا | `session-execution.xml`، منها 70 حالة تقويم نقية |
| البحث/الملاحظات/الترحيل المستهدف | 52 ناجحًا | `research-observations.xml` |
| HTTP وعامل مستقل وإعادة خدمة | ناجح | `cloud-backend-http-smoke.json` و`http-evidence-gate.json` |
| PostgreSQL أساسي | ناجح | `cloud-backend-postgres-basic.txt` |
| PostgreSQL V1 | 14 فحصًا ناجحًا، صفر فاشل | `cloud-backend-postgres-v1-results.json` |
| PostgreSQL backup/restore | 10 فحوص ناجحة | `cloud-backend-postgres-backup-restore.json` |
| Docker Compose | 12 فحصًا ناجحًا، schema 1–5 | `cloud-compose-compose-smoke.json` |
| Flutter macOS | 171 ناجحًا، صفر خطأ/تجاوز، final success=true | `flutter-ios-build13.jsonl` |
| Flutter Linux / Android | 171 ناجحًا، صفر خطأ/تجاوز، final success=true | `flutter-android-build13.jsonl` |
| Flutter Analyze | ناجح Linux وmacOS | خطوات تشغيلات الهاتف أدناه |
| الأسرار والاعتماديات | نجحت البوابة؛ التفاصيل والحدود في تقرير الأمان | `build13-security-*.json` |

المجموعات المستهدفة subsets من الكاملة ولا تُجمع لتضخيم الرقم؛ لا نجمع اختبار Flutter نفسه على نظامين. تحذير Starlette/httpx واحد معروف في Python، دون فشل. Docker/PostgreSQL/Flutter لم تُشغّل محليًا؛ الأدلة من GitHub Actions الفعلي.

## الحالات الحرجة والفشل الذي أُصلح

`RC2_SAFETY_MATRIX.md` يربط دخول Call/Put الآلي، SL/TP/المتحرك/الجزئي والزمني، الإغلاق اليدوي والعكس في الاتجاهين بعد flat والمصالحة، منع التعارض والتكرار وبيع غير المملوك، التزامن والانقطاع والرسوم، العزل وتقادم البيانات/الانتهاء، فشل التحليل والمخاطر وLive المقفل وسببية البادئات بمعرفات اختبارات فعلية. فشل LLM لا يمنح إذنًا؛ لا LLM خارجي مستخدم للتنفيذ في هذه البيئة.

- أُعيد إنتاج خلل الجني الجزئي وصلاحية الأوامر المعلقة: 19 فشلًا و3 نجاحات في مجموعة قبل الإصلاح، ثم 164 نجاحًا بعده. الاستئناف الآن يحافظ على كمية الخروج المقبولة، وتُعاد صلاحية الشراء الحالي عند التعبئة دون تكرار الإيصالات.
- التحليل الاختياري لا يعطل مخارج حماية مبررة، لكنه لا يولد إشارة عند الفشل. إبطال سيناريو موثوق يمكن أن يطلب إغلاقًا كاملًا.
- أول lint Flutter كشف قوسًا مطلوبًا؛ ثم اختبار drawer احتاج بدء/اكتمال الحركة؛ ثم Dart كشف conditional ملتبسًا. أُصلحت قبل نجاح بوابات دفعة الجلسات.
- عند 055f فشل اختبار widget واحد على المنصتين لأن إشعار الالتقاط خارج نافذة ListView الكسولة. طلب POST نفسه نجح؛ حُفظ السجل ثم صُحح التمرير في 67ddb6e واجتازت خطوة الاختبار على المنصتين.
- فشل fixtures التقويم الأول (mark ناقص واسم reason خاطئ) موثق ثم صُحح دون تخفيف فحوص runtime. لا نعد المحاولات الفاشلة نجاحًا.

## روابط تشغيلات القبول

- [الخادم وPostgreSQL وCompose — 055f](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38118532583).
- [Android وFlutter — 67ddb6e](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38118890108).
- [iOS وFlutter — 67ddb6e](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38118890095).
- [الأمان — 67ddb6e](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38118890093).

## حدود القبول

لا اختبار هاتف/محاكي تثبيت أو ترقية أو أداء فعلي؛ لا IBKR أو بيانات سوق أو ربحية OOS حقيقية؛ لا ممارسة/تخصيص واقعيين؛ لا تشغيل إنتاج طويل أو pentest. اختبارات decode/store وmigration وإعادة الخدمة تثبت الحالات المسماة فقط، لا ضمان ترقية تطبيق موقع بمفتاح مختلف. تعليمات الهاتف وIBKR في تقريريها المستقلين.

## ملحق بناء الهاتف المتحقق

Android run `38118890108` اكتمل بنجاح، artifact `11694930290`. APK معاينة 1.0.0 build 13، 154956640 بايت؛ SHA-256 `07bb0061172e0cd8de62a03b5e05faf9639d3541f56fdccd2430e5b5b6c700f3`. اجتاز CRC وطابق checksum من CI، وسجل `apksigner` يؤكد v2 وشهادة Debug مؤقتة. هوية المعاينة مستقلة؛ لا مفتاح ثابت متاح.

iOS run `38118890095` ناجح، artifact `11694368985`؛ فحص Info.plist يؤكد 1.0.0 build 13 وminimum iOS 15.0، ولا يوجد `_CodeSignature` للتطبيق. SHA-256 لأرشيف التنزيل `00533a0a6b17350ee52aeed53cbc05562afd41fcd67cc9b6e6d5015f3e6c92a4`. ليس IPA موقعًا أو TestFlight.

ملفات `*-build13-verification.json` و`flutter-*-build13-summary.json` و`acceptance-runs.json` تحفظ الأعداد والبصمات وربط المصدر. لا تُحسب اختبارات جهاز من هذه النتائج.

## قبول حماية الانتهاء بعد الرفع

المصدر `381eec3cf2ed1454764d75ab51683dcf3634e453`: [Mock safety checks](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38126076027) و[Security](https://github.com/1stsaad-beep/options-ai-trader/actions/runs/38126076071) نجحا. ملفات artifacts نُزلت وفُحص CRC وJUnit/JSON فعلًا: 850 Python بلا فشل/تجاوز، PostgreSQL V1 عدد22، backup/restore عدد10، Compose عدد12، وHTTP وعامل مستقل ناجحان. الأدلة `evidence/expiry-20261011/cloud-*`. هذا تحقق PostgreSQL فعلي مستقل عن dry-run SQLite المسمى بوضوح.
