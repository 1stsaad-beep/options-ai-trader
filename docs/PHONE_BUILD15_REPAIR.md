# RC2 Build 14 phone findings — repair checkpoint

Baseline: `615576768612c1c7cbd008632b325be05c57c774`, branch `recovery/v1.0-20261011`.

The user supplied four Android screenshots and reported successful launch/safety, synthetic buy, owned manual close, rejection of unsupported reversal, restart persistence and clipboard export. These are user-reported physical-device observations; they are not new automated results.

## Inspection before modification

- The baseline Demo underlying series rises/falls monotonically within each 300-observation segment (12 cents of drift exceeds the sinusoidal increment). No Elliott or harmonic pattern in the pictured rising prefix is a legitimate possible result, not permission to invent labels.
- The pivot detector uses strict comparison on both sides. Continuous OHLC candles share the prior close/open, creating equal adjacent extrema. This can suppress valid turning points. Regression needed for a rightmost plateau pivot with a full confirmation delay.
- The painter contains only RSI; MACD is a text statistic, and divergence strings are not drawn. Confirmed rendering gaps.
- The canvas is at least nine pixels per observation and initially wider than the phone. Right-edge labels and recent candles can be outside the viewport. Support/resistance have no labels and there is no observation axis.
- Chart end is stored in State and is not advanced when the same mutable DemoEngine receives a tick. Replay needs a distinct pinned mode so fixing follow mode cannot leak future observations into a historical decision.
- Wave candidate absence is explained only below the large chart and replay controls. Empty states must be visible before the chart.

No runtime change or new acceptance result at this checkpoint. The intended preview uses a new application identifier so Build 14 and its private data remain installed. No storage schema change is planned.

## Pending

Controlled synthetic chart fixtures; causal pivot regression; RSI/MACD/divergence layers; primary/alternate and honest empty-state display; viewport controls; widget/golden/integration checks; isolated deterministic exit/reversal exercises; CI verification and a separately installable APK. No phone test of a new build has occurred.
## Verified implementation results (before final packaging)

- Baseline phone report recovered and checkpointed at `a3b8439212a57393d3f4332d665c9a4099260e11`.
- Chart semantic gate: run `38178794977`, **196 successful visible Flutter tests**.
- Chart plus isolated safety gate: run `38179195664`, **203 successful visible Flutter tests**, zero failures/errors/skips. Analyze passed. Evidence: `docs/evidence/phone-build15/safety-semantic-pass.jsonl`.
- Five deterministic phone exercises run the actual local engine; the seven tests include deliberately disabled execution (must report failure) and a no-network phone route that preserves the original serialized user accounts and unusual user risk settings exactly.
- Readable golden drafts use the pinned Flutter SDK's Roboto, not default square test glyphs. Drafts are reviewed before baseline commit; golden comparison and native packaging status must be read from the final acceptance section below when available.

## تمييز النتائج

| الفئة | النتيجة والدليل |
|---|---|
| خلل مثبت تم إصلاحه | كشف القمم كان يستبعد القمتين/القاعين المتساويين في OHLC المتصل. صار يختار الطرف الأيمن بعد اكتمال نافذة التأكيد، دون تحويل سطح طويل مسطح إلى موجة. اختبار كل بادئة يثبت عدم ظهور القمة مبكرًا. |
| خلل مثبت تم إصلاحه | المؤشر المخزن في الشاشة لم يتابع تغير `tick` داخل كائن المحرك نفسه. متابعة السوق الآن مستقلة عن Replay المثبت؛ بيانات الصفقة التاريخية لا تتقدم إلى المستقبل. |
| خلل مثبت تم إصلاحه | MACD والإشارة وHistogram والدايفرجنس كانت غير مرسومة. أضيفت حسابات وطبقات بمقاييس مستقلة ووصلات بين القمم السعرية والمؤشر، مع إحماء واضح. RSI المحلي يستخدم نافذة حساب متحركة، ولا يدّعي مطابقة Wilder. |
| خلل مثبت تم إصلاحه | عرض أكبر من الهاتف وتسميات أفقية ناقصة. الرسم يلائم الشاشة افتراضيًا، ويعرض محور الملاحظات وقيم S/R/Fib والتكبير والتحريك والملاءمة. طبقة PRZ الآن نطاق نسب بحثي منفصل عن مستوى الإلغاء. |
| خلل اكتشفته اختبارات الإصلاح | اختيار 5× اصطدم بتحقق سجل موجي مخصص لـ1×. أضيف عامل تجميع صريح مع استعادة متحققة ومنع فجوات المصدر؛ أُعيد الاختبار بنجاح. |
| نتيجة تحليل غير متاحة بصورة مشروعة | عينة الهاتف الصاعدة لا تحتوي انعطافات كافية. عدم ظهور Elliott أو XABCD أو دايفرجنس صالح فيها ليس دليل تعطل الواجهة. تظهر رسالة صريحة فوق الشارت، ولا تضاف أرقام مختلقة. |
| نتيجة تحليل غير متاحة بصورة مشروعة | نقص إحماء RSI/MACD أو نقص الشموع المجمعة المكتملة يُعرض كما هو. العينات المضبوطة منفصلة عن السوق والحسابات والأوامر. |
| ميزة غير مكتملة | الكشف الشامل عن النماذج الكلاسيكية، جميع قواعد Elliott، توحيد جميع تحليلات Demo مع الخادم، وتفسير جميع صفقات الخادم على الشارت ما زالت حدودًا معروفة. المؤشرات والموجات المحلية بحثية ولا تتحول إلى أوامر. |
| ميزة غير مكتملة | التوقيع المستقر الدائم وترقية تطبيق بتوقيع مختلف دون فقد البيانات ليسا مثبتين. الحل هنا تطبيق Lab 15 منفصل؛ لا حذف أو ترقية قسرية لـBuild 14. |
| اختبار لم يُنفذ | تثبيت/تعايش Build 14 و15 على هاتف أو محاكي، الإيماءات على عتاد فعلي، استيراد/استعادة على جهاز جديد، والتوزيع عبر TestFlight. لا يُنسب تقرير الهاتف السابق إلى Build 15. |
| خارج النطاق المأذون | لا IBKR/Paper أو Live أو أوامر مالية خارجية، ولا بيانات مالية خارجية. لا ادعاء بتكامل وسيط أو إثبات ربحية من هذه العينات. |

## حدود العرض والاختبار

- شموع المحاكاة الأصلية ومعادلة الأسعار ودفتر الأوامر والرسوم ومحرك المخاطر ومفتاح حفظ Demo لم تتغير. يختبر مسار الشاشة بقاء bytes حساب المستخدم كما هي.
- يعرض الشارت آخر 180 شمعة إلى مؤشر Replay؛ يمكن الرجوع بالمؤشر إلى أزمنة أقدم. محور `#` اصطناعي، وليس توقيت بورصة. الفواصل 1/5/15× تجميعات ملاحظات مكتملة فقط.
- الموجات الأساسية والبديلة احتمالات هندسية على قمم مؤكدة، وليست حقيقة موجية نهائية أو ضمانًا للتوقع. عينات 1–5 وABC وBat والدايفرجنس تُحسب من شموع مضبوطة ولا تتجاوز الكشف لإجبار نتيجة.
- اختبار انعكاس Call→Put يستخدم AAPL الاصطناعي الهابط، وPut→Call يستخدم NVDA الاصطناعي الصاعد. يعود القرار إلى الإشارة الكمية الفعلية لكل سلسلة. نجاحه لا يجعل إشارة Put متاحة في عينة NVDA الصاعدة المصوّرة.
- الاختبارات المرئية مرجع رسم ثابت على Linux/Flutter 3.47.7 وخط Roboto؛ لا تحل محل تحقق هاتف المستخدم. اختبارات Widget تتضمن RTL وعرض 360 بكسل وتغيير الطبقات والتجميع وReplay.
- لم تُختبر ربحية استراتيجية أو بيانات تاريخية خارج العينة. هذه اختبارات سببية وتنفيذ محلي اصطناعي فقط؛ لا أسعار مستقبلية ولا تفسيرات بعد وقوع الصفقة.

دليل الهاتف: [PHONE_BUILD15_INSTALL_AR.md](PHONE_BUILD15_INSTALL_AR.md). مصدر وتقارير V1.0 الأوسع يبقيان مرشحين وغير مكتملين.
