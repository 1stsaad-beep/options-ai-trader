# نقطة الاستئناف — Engineering RC2، 2026-10-11

> استئناف لاحق من الرأس النظيف `3a72226143944dd8985f14d82cc14afc45acbb8f`: اكتملت محليًا دفعة حماية الانتهاء US (850 Python، HTTP ناجح). الخطوة المباشرة هي التحقق من CI بعد رفعها ثم تحديث هذا التقرير؛ لا تبدأ من 055f أو main. [السياسة والحدود](OPTION_EXPIRATION_POLICY_V1.md). أول دفعة هاتف مقترحة بعد حفظ هذه الدفعة: تصدير/استيراد Demo آمن دون شبكة؛ غير منفذة في هذا checkpoint.

ابدأ من المستودع الخاص `1stsaad-beep/options-ai-trader`، الفرع **recovery/v1.0-20261011**. افحص رأسه الفعلي؛ لا تستخدم main/V0.5. تقرير التسليم الحالي `FINAL_DELIVERY.md`، وتسلسل كل دفعة في `PROGRESS.md`.

## الحالة المحفوظة

بدأت المهمة من رأس نظيف `72abca1c637fbabf55ecf5d30dcb276c9798170c`؛ لم توجد تغييرات غير محفوظة تحتاج Recovery Commit إضافيًا. تاريخ الاستعادة الأقدم وملفاتها باقية. لا ادعاء باستعادة ذاكرة جلسة منتهية.

| Commit | النتيجة |
|---|---|
| `9eba22278054a771a44c4a0e1c8bff9dff29a8b1` | عقد بحث Python/Dart وحفظ/قائمة/replay الهاتف وfixture خدمة حقيقي |
| `6897522becda2db00b1cf6bd58c5867babb5617b` | تصحيح lint Flutter |
| `f896ed324dc1d900c347beb307a6d591c4f92191` | إصلاح الجني الجزئي وصلاحية التعبئة الحالية وفشل التحليل الاختياري |
| `b52af9efcfbd83a61cea3145ebfc4a0bbad1cbb2` | تقويم US اختياري 2026–2027 وتكامل القبول/التعبئة وDAY، وتصحيح Dart |
| `055f42c4aed2d1baaef199a4e38b6873ab1e63b2` | ملاحظات Counterfactual محفوظة فعلًا، migration 5، سلامة تاريخ الموجات، build 13 |
| `67ddb6e7cf58cd59604ab7187a6864d527a69aac` | جعل اختبار الواجهة يظهر إشعار الالتقاط قبل فحصه؛ لا تغيير runtime |

رأس تسليم التقارير اللاحق يظهر من Git؛ لا تخلطه مع commit بناء التطبيق أعلاه. الأدلة الحالية في `docs/evidence/engineering-20261011/`، والأقدم محفوظة في `docs/evidence/recovery-20261011/`.

## أول دفعة تالية

اتبع قائمة `RECOVERY_REQUIREMENTS_V1.md`: الخطر الوظيفي الأعلى هو واقعية الانتهاء والممارسة/التخصيص، ثم توحيد شارتات/بيانات الهاتف والخادم. أنجز دفعة محددة مع إعادة إنتاج وفحص مستهدف؛ لا توصل Shadow بالتنفيذ ولا تعلن اكتمال V1.0.

Counterfactual الحالي يحتاج ملاحظتين لاحقتين محفوظتين؛ لا تعِد توليد التاريخ للحصول على نتيجة. قرارات الموجات القديمة تُعرض بأصلها؛ corruption/source mismatch يجب أن يفشل صراحةً. تقويم US اختياري على الخادم، Demo محلي اصطناعي ولا يملك parity كاملة.

## إعادة إعداد البيئة والاختبارات

تعليمات تثبيت Python والخادم في `RECOVERY_RUN_GUIDE_V1.md`. أوامر القبول:

```bash
python -m pytest -q backend --junitxml=test-results.xml
python scripts/smoke_http.py
python scripts/demo_lifecycle.py
python scripts/research_demo_v1.py
python scripts/security_scan.py --repository . --all-history
```

في `mobile/` وعند توفر Flutter المتوافق مع workflow:

```bash
flutter pub get
flutter analyze
flutter test --machine > flutter-tests.json
```

لا تبنِ Android/iOS ولا تعِد جميع المجموعات لكل تعديل صغير. الاختبارات/البناء الحاليان من GitHub Actions؛ Flutter/PostgreSQL/Docker غير متاحة محليًا في بيئة هذه المهمة. اختبارات PostgreSQL تستخدم قاعدة disposable مصرحًا بها فقط؛ لا تُشغّلها ضد بيانات المستخدم.

Workspace الذي استُخدم: `/workspace/scratch/30bf1042c108/options-ai-trader-rc2`، Python `/workspace/scratch/30bf1042c108/recovery-input/venv/bin/python`. هذه مسارات مؤقتة وليست ضمان استعادة مستقبلية؛ المصدر والتقارير على GitHub هي نقطة الحفظ.

## حفظ كل دفعة والقيود

افحص dirty/unpushed أولًا واحفظها في Recovery مستقل قبل التعديل. بعد الاختبارات: commit ثم رفع غير قسري ثم تحقق من SHA البعيد وحدّث PROGRESS. في هذه البيئة كان Git HTTPS غير مصادق، فاستُخدم Git Data API بشجرة مطابقة وأب معلوم وexpected SHA، ثم مزامنة commit نفسه محليًا دون reset. لا تنشئ تاريخًا محليًا متعارضًا لمجرد توفر واجهة مختلفة.

لا force push أو reset --hard أو clean أو حذف فروع/تاريخ/ملفات مشروع. لا مشاريع أخرى. لا IBKR ولو Paper أو Live أو أوامر مالية أو خدمات مدفوعة. لا أسرار أو مفاتيح خاصة في Git، لا Mawj أو فلتر شرعي أو ربط تحليل خارجي. حافظ على التطبيقات القديمة وبياناتها؛ توقيع build 13 المؤقت لا يضمن الترقية.
