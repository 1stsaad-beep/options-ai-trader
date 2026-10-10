# مراجعة الأمان المستقلة — V0.3

تاريخ المراجعة: 2026-10-09. النطاق: مصدر الخادم والمحركات والمحاكاة والترحيلات وعميل Flutter وإعدادات البناء والحاويات، مع قراءة تقرير تسليم V0.2. هذه مراجعة تطوير للمحاكاة وليست اعتمادًا للتداول الحقيقي أو اختبار اختراق إنتاجي.

## النتائج المُصلحة

| المشكلة | الإصلاح المرصود | دليل التحقق |
| --- | --- | --- |
| إعادة محاولة أمر محفوظ بعد انتهاء العقد قد تُرفض قبل البحث عن الطلب السابق | البحث الدائم بمفتاح الطلب وبصمة الحمولة قبل إعادة التحقق من أهلية أمر جديد؛ لا إعادة إرسال | إعادة الاستجابة المفقودة بعد الانقطاع والاستحقاق تبقي معرفًا واحدًا وأمرًا واحدًا؛ تغيير الحمولة مرفوض |
| المصالحة قد تثق بدفتر غير متسق | مقارنة الأوامر والتنفيذ والمراكز والربح اليومي والمحقق ورصيد الإنشاء؛ إبقاء الحالة مقفلة عند الخطأ | حالات فساد الهوية والحالة والمراكز والتكلفة والربح والرصيد |
| تنفيذ شراء سبق قبوله قد يتجاوز إعدادات مخاطر تغيرت لاحقًا | إعادة التحقق من المخاطر الحالية والحالة والبيانات والمراقبة قبل تنفيذ Mock BUY | خفض مخاطرة الصفقة أو عدد العقود، حذف/إيقاف السهم وانقطاع البيانات تمنع التنفيذ |
| خسارة حساب مرتبط قد لا تمنع تنفيذ أمر حساب آخر سبق قبوله | بوابة جماعية وعالمية عند التنفيذ وإلغاء أوامر الشراء غير الآمنة بعد تحديث الخسائر | خسارة المجموعة تُلغي أمر الحساب الآخر ولا تنشئ مركزًا |
| رصيد حساب غير موثوق قد يخفف نسبة التعرض العالمي | استبعاد رأس المال غير الموثوق مع إبقاء تعرضه وخسائره؛ المجموعة المرتبطة تتطلب حالة موثوقة لجميع أعضائها | 15 حجزًا في الحساب المنقطع لا يسمح بتخفيف التعرض برصيده غير الموثوق |
| انقطاع/قدم بيانات السوق لا يمنع جميع المداخل | مشاهدات Mock لكل حساب وسهم مع حد عمر وفحص المستقبل؛ منع الشراء عند انقطاع البيانات | مشاهدات قديمة ومستقبلية وانقطاع بعد قبول الأمر |
| الإيقاف يمنع إدارة المركز المملوك | السماح بإغلاق المملوك بعد المصالحة الموثوقة، حتى مع الإيقاف وغياب بيانات السوق | الإغلاق مرفوض أثناء فقدان الحالة؛ مسموح بعد المصالحة؛ لا بيع مكشوف |
| الاستحقاق قد يكتب تسوية اعتمادًا على مركز فاسد | التحقق قبل أي كتابة تسوية؛ التراجع عن المعاملة وقفل الحساب عند الفشل | فساد التكلفة قبل الاستحقاق لا يكتب خسارة أو حدث تسوية |
| سجلات يتيمة أو أخطاء FK قد تتحول إلى أخطاء API داخلية | علاقات وترحيلات إضافية، وسجل رفض عام عند غياب الحساب | طلب أمر/مصالحة لحساب غير موجود يرجع 409 وتبقى قاعدة البيانات قابلة للاستخدام |
| حقول أو أنواع قد توحي بسلطة للذكاء الاصطناعي | نماذج API صارمة، منع الحقول الإضافية، شرح النموذج دون سلطة تنفيذ | رفض force وai_approved وlegs والأعداد النصية والمنطقية |

المصادقة مطلوبة لمسارات الحسابات والمخاطر والمراقبة والأوامر والتنفيذ والمصالحة والأداء والإيقاف. مسار الصحة يعرض معلومات عامة فقط. IBKR وLive وموج لا يملكون مسار اتصال أو تنفيذ فعالًا. لم تتضمن المراجعة اتصالًا بوسيط أو أموالًا حقيقية.

## نتائج الاختبارات الفعلية لهذه المراجعة

الأمر: `python -m pytest tests/test_adversarial_v03.py -q` من `backend` باستخدام بيئة Python المحلية.

- 25 ناجحًا، 0 فاشل، 0 متجاوز؛ الزمن 0.55 ثانية في التشغيل الأخير لهذه المجموعة.
- التشغيل الكامل اللاحق: `python -m pytest -q`؛ 117 ناجحًا، 0 فاشل، 0 متجاوز؛ الزمن 1.13 ثانية.
- تحذير واحد من Starlette/AnyIO عن واجهة deprecated؛ لم يؤثر على نتائج الاختبارات.
- هذه لقطة نتائج أثناء التطوير؛ تقرير الاختبارات النهائي يوثق آخر تشغيل بعد اكتمال بقية تغييرات الفريق.

تم فحص العميل ساكنًا: الطلبات تحدد الحساب صراحة، النماذج تحتفظ بالحساب المستهدف، الاستجابات وأخطاء التحميل المتأخرة محمية بجيل التحميل، إعادة التوجيه مرفوضة، وعمليات التعديل لا تعاد تلقائيًا. عولجت ملاحظات المراجعة عن تكرار/غياب معرف الحساب قبل عرضه في القائمة وعن بيانات أداء ناقصة كان يمكن تحويلها إلى إجمالي صفري؛ صار الإجمالي غير متاح بدل اختلاق قيمة. توجد اختبارات مصدر لهذه الحالات. تحليل Flutter واختباراته وبناء APK يخضعون لتقرير البناء الفعلي المنفصل؛ الفحص الساكن لا يعادل تشغيلها.

## قيود متبقية

| القيد | أثره وخطوة لاحقة |
| --- | --- |
| مصدر حقيقة Mock ودفتر التطبيق يستخدمان مخزنًا واحدًا | لا يثبت سلامة مصالحة وسيط خارجي أو acknowledgements/cancel-races؛ يلزم تنفيذ Broker Adapter وتجارب Paper مستقلة قبل أي تشغيل خارجي |
| المخاطر مبنية على علاوة الشراء والتعرض بتكلفة الاقتناء وP&L المحقق | لا توجد أسعار علامة موثوقة لحساب خسائر غير محققة أو buying power/net liquidation حقيقي؛ لا اعتماد لمخاطر تداول حقيقي |
| الخسارة اليومية تعتمد يوم UTC | تقويم جلسات السوق الأمريكية وإجازات السوق وتوقيت التصفية يحتاجان تصميمًا واختبارًا |
| الاستحقاق يشطب العلاوة بصورة محافظة | لا يحاكي exercise/assignment أو تسوية قيمة جوهرية؛ النتائج محاكاة وليست كشوف وسيط |
| السجل قابل للتعديل بواسطة صاحب قاعدة البيانات | اختبارات الاتساق تكشف فسادًا عرضيًا؛ لا حماية تشفيرية ضد مهاجم يملك قاعدة البيانات ويعيد كتابة جميع السجلات |
| مصادقة رمز واحد لمستخدم شخصي | العزل بين حسابات التداول منطقي وذري؛ لا توجد هوية متعددة المستخدمين أو RBAC أو تخزين أسرار محمول دائم |
| لا يوجد مصدر سوق مرخص ولا بيانات تاريخية حقيقية | التحقق من الرمز entitlement اصطناعي فقط؛ لا ادعاء تحقق IBKR أو ربحية استراتيجية |
| أوامر الإغلاق في الطوارئ تتطلب ثقة بالمخزون | لا تجاوز عند فقدان حالة الحساب؛ إغلاق خارجي فعلي غير مطبق |
| اختبارات قواعد البيانات/الحاويات/الهواتف تحتاج بيئاتها | نتائج SQLite لا تثبت PostgreSQL أو Docker أو أجهزة فعلية؛ راجع الأدلة النهائية لكل بيئة |

تبقى V0.3 نسخة تطوير ومحاكاة. نجاح اختبارات البرمجيات لا يجعلها صالحة للتداول الحقيقي.

## فحص ثغرات الاعتماديات

شُغّل pip-audit 2.10.1 فعليًا في بيئة مستقلة على 24 اعتمادًا مثبتًا في requirements.lock. كشف التشغيل الأول 12 سجلًا مكررًا تخص 6 معرفات ثغرات مختلفة في Starlette 0.48.0. رُقّي الاعتماد وأُثبت إلى Starlette 1.7.0؛ أعيد الفحص ونجح برمز خروج 0، مع 0 سجل ثغرة معروف و0 اعتماد متجاوز. الأدلة قبل وبعد المعالجة والتفاصيل وروابط التنبيهات في DEPENDENCY_AUDIT_V03.md وdocs/evidence/v03-dependency-audit-before.json وdocs/evidence/v03-dependency-audit-after.json. هذا فحص تنبيهات الحزم المثبتة، ولا يشمل نظام التشغيل أو اعتماديات الهاتف أو الثغرات غير المعلنة.


---

# Dependency vulnerability audit — V0.3

Run date: 2026-10-09. Tool: pip-audit 2.10.1 in an isolated scratch virtual environment.

Actual command: `python -m pip_audit --no-deps --disable-pip -r backend/requirements.lock -f json -o docs/evidence/v03-dependency-audit.json`

Initial result: exit code 1; 24 explicitly locked distributions checked, 0 skipped, 12 advisory rows affecting Starlette 0.48.0. The advisory service returned duplicate entries: these are **6 distinct vulnerability IDs**, not 12 distinct CVEs.

| ID | CVE | Advisory | Fixed version |
| --- | --- | --- | --- |
| PYSEC-2026-1942 | CVE-2025-62727 | [official advisory](https://github.com/advisories/GHSA-7f5h-v6xp-fcq8) | 0.49.1 |
| PYSEC-2026-161 | CVE-2026-48710 | [official advisory](https://github.com/advisories/GHSA-86qp-5c8j-p5mr) | 1.0.1 |
| PYSEC-2026-2281 | CVE-2026-48818 | [official advisory](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r) | 1.1.0 |
| PYSEC-2026-2280 | CVE-2026-48817 | [official advisory](https://github.com/advisories/GHSA-x746-7m8f-x49c) | 1.1.0 |
| PYSEC-2026-249 | CVE-2026-54283 | [official advisory](https://github.com/advisories/GHSA-82w8-qh3p-5jfq) | 1.3.1 |
| PYSEC-2026-248 | CVE-2026-54282 | [official advisory](https://github.com/advisories/GHSA-jp82-jpqv-5vv3) | 1.3.0 |

The product API does not currently use StaticFiles, FileResponse, request.form(), or HTTPEndpoint subclasses, and bearer authorization does not rely on reconstructed request URLs. This limits applicability of several findings; it does not turn a vulnerable dependency into a patched dependency.

Recommended remediation: upgrade Starlette to at least 1.3.1 (the maximum fixed version reported across these advisories), rerun the complete backend tests and HTTP smoke, and rerun the audit. FastAPI 0.143.0 installed metadata specifies starlette>=0.46.0 with no upper version bound. Compatibility still requires actual testing.

## Remediation and verified rescan

The project owner upgraded the actual runtime and pinned product dependency to **Starlette 1.7.0** in requirements.lock and pyproject.toml. The audit reviewer did not change the runtime environment or product dependencies.

The same audit command was rerun against the updated requirements.lock, writing `docs/evidence/v03-dependency-audit-after.json`. Actual result: **exit code 0; 24 locked packages checked; 0 skipped; 0 known vulnerability records reported**. Starlette 1.7.0 is present in the rescan evidence. The original result is preserved in `docs/evidence/v03-dependency-audit-before.json` (and the original initial filename). Application regression tests after the upgrade are recorded by the owner in the final test report.

The six distinct findings above are therefore remediated for the final pinned dependency set according to this audit service at scan time. This is a dependency-advisory check, not a guarantee that undisclosed vulnerabilities do not exist.

Scope limits: --disable-pip/--no-deps audits the 24 pinned entries directly; it does not resolve missing transitive dependencies, verify package integrity/hashes, audit the operating system, Flutter/Dart packages, Android libraries, or application logic. No zero-vulnerability or production-safety claim follows from this initial scan.


## تحقق نهائي بعد معالجة الاعتماد

أعيد تشغيل121 اختبارًا:121 ناجح،0 فاشل،0 متجاوز؛ أعيد فحصHTTP الفعلي وpip check بنجاح. فحصFlutter والبناء موثق في تقرير الاختبارات النهائي. لا اتصالMawj أوIBKR، ولا تنفيذLive. مستودعGit محلي؛ لا أسرار أو بيانات حسابات فعلية ضمن المصدر. توافق أدوات المضيف المؤقت الخاص ببيئةWork لا يدخل في المصدر أو التطبيق.
