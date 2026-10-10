# مراجعة واجهة IBKR المستقبلية — V1

تاريخ التحقق: **2026-10-10**. نقطة البداية: V0.5، Commit `ccd1d2c181de3968e9042ce7c1435571c1f3301a`.

هذه مراجعة لوثائق IBKR العامة فقط. لم يحدث تسجيل دخول أو اتصال بحساب، بما فيه Paper، ولم تُرسل أوامر أو طلبات بيانات سوق. وصف واجهة مستقبلية لا يعني أن التكامل منفذ أو مجاز للتشغيل. يبقى `IBKRAdapter` معطلًا و`GenericAnalysisAdapter` معطلًا وللقراءة المستقبلية فقط.

## القرار المعماري المقترح

للنسخة الشخصية الأولى بعد موافقة منفصلة، نوصي بتطوير Adapter لـ **TWS Socket API عبر IB Gateway** باستخدام مكتبة Python الرسمية وإصدارات متوافقة مثبتة. هذا استنتاج هندسي من نمط الحساب الشخصي والحاجة إلى أحداث الأوامر والتنفيذ؛ ليس ادعاءً بأن IBKR يفضله لكل المستخدمين. يمكن إبقاء Web API كتنفيذ لاحق للواجهة نفسها عند ثبوت أهلية الحساب وطريقة المصادقة.

| البند | TWS API / IB Gateway | Web API / Client Portal Gateway |
|---|---|---|
| طريقة الاتصال | TCP socket إلى TWS أو IB Gateway؛ مكتبة Python رسمية | REST وWebSocket؛ Client Portal Gateway تطبيق Java للمستخدم الفردي |
| المتطلبات الحالية | حساب IBKR Pro مفتوح وممول، إصدار Stable أو Latest متوافق من المنصة وAPI؛ الوثائق تذكر Python 3.11 على الأقل [1] | الوثائق الحالية تشترط IBKR Pro؛ الصفحة العامة تشترط حسابًا مفتوحًا وممولًا حتى لاستخدام Paper المرتبط [3][4] |
| المصادقة | تسجيل دخول إلى المنصة؛ إعادة تشغيل يومية متاحة وفق إعدادات المنصة، وإعادة مصادقة أسبوعية قد تتطلب تدخلًا يدويًا [2] | المصادقة بالمتصفح على جهاز Gateway نفسه؛ API على الجهاز نفسه. إعادة مصادقة يومية؛ أتمتة مصادقة Gateway غير مدعومة رسميًا [5][6] |
| OAuth | ليس شرط مسار socket | OAuth 1.0a و2.0 متاحان وفق نوع الحساب والموافقة؛ صفحة المصادقة تسرد أنواعًا مؤسسية، ولا تمنح الفرد أهلية OAuth تلقائيًا [4] |
| استمرارية التشغيل | العامل مستقل عن الهاتف، لكنه يتوقف عن فتح مراكز عند فقدان الجلسة أو الثقة | جلسة الوساطة stateful؛ إعادة الدخول والمهل والصيانة قد تقطع الخدمة. إبقاء الجلسة حية لا يلغي المصادقة اليومية [7] |
| حدود الطلبات | الحد العام الحالي مرتبط بعدد خطوط بيانات السوق: الخطوط ÷ 2 في الثانية؛ الافتراضي 100 خط يعني 50 طلبًا/ثانية، مع حدود إضافية لبعض البيانات [8] | 10 طلبات/ثانية إجمالًا مع حدود أدق؛ الأوامر المفتوحة والصفقات مثلًا طلب واحد كل 5 ثوانٍ؛ تجاوز الحد قد يسبب حظرًا مؤقتًا [9] |

ظهرت أثناء المراجعة إعادة توجيه وثائق Campus القديمة إلى `/docs/`. صفحة Web API العامة القديمة تصف OAuth 2.0 بأنه beta، بينما صفحات المصادقة الجديدة تفصل الأهلية حسب نوع الحساب. لهذا لا نعتمد مصادقة OAuth للفرد دون تأكيد IBKR لاحقًا. لا نطلب تمويل حساب أو اشتراك أو بيانات اعتماد في هذه المهمة.

## المصادقة والحسابات ومشاركة البيانات

- توثيق TWS يحدد بداية دورة إعادة المصادقة الأسبوعية يوم الاثنين؛ وجود Auto Restart لا يثبت تشغيلًا دائمًا دون تدخل [2].
- توثيق Web API يميز الاتصال عن المصادقة؛ قد تكون `connected=true` مع `authenticated=false`. يعرض مهل خمول تقارب 5–6 دقائق ويوصي بتجديد دوري، لكن الصيانة قد تقطع الجلسة قبل 24 ساعة. يجب الاعتماد على الحالة الفعلية ووقت آخر تحديث، لا مؤقت محلي وحده [7].
- توجد جلسة وساطة نشطة واحدة لكل username عبر منتجات IBKR؛ فتح تطبيق آخر قد يؤثر في الجلسة. الحسابات الفرعية ليست usernames جديدة تلقائيًا. خدمة بيانات السوق مرتبطة بالمستخدم، وقد تتطلب أسماء مستخدمين إضافية اشتراكات إضافية [10].
- في Web API يعيد `/iserver/accounts` الحسابات المسموح بها، ويجب استدعاؤه قبل الاستعلام عن الأوامر المفتوحة أو تعديلها. يحتفظ الخادم بربط واضح بين معرّف حساب التطبيق ومعرّف حساب الوسيط المصرح به، دون افتراض أول حساب أو الاعتماد على الحساب المحدد ضمن الجلسة [11].
- في TWS يجب فصل `clientId` الخاص باتصال API عن account ID. صلاحيات مشاهدة الأوامر تختلف بين العميل العادي وMaster ClientId وClientId 0؛ اكتمال المصالحة لا يُفترض عند غياب أوامر عملاء آخرين [12].
- مشاركة بيانات السوق بين Live وPaper موثقة ضمن قيود محددة: مستخدم Live واحد مع Paper واحد. هذا لا يجيز إعادة توزيع البيانات بين أي حسابات أو مستخدمين. التخزين المشترك في المنصة يجب أن يكون مفهرسًا بصلاحية المستخدم/المصدر ونوع البيانات [13].

## تأهيل الرمز وعقد الخيار قبل المراقبة والتنفيذ

سير العمل التالي تصميم مقترح، ولم يُنفذ ضد وسيط:

1. تأهيل الأصل الأساسي بواسطة `reqContractDetails`، مع `symbol`, `secType=STK`, exchange وcurrency، ورفض الغموض أو عدم التطابق. احتفظ بـ`conId` وprimary exchange ووقت التأهيل [14].
2. طلب معاملات سلسلة الخيارات بواسطة `reqSecDefOptParams` باستخدام `underlyingConId`. المخرجات تتضمن exchange وtradingClass وmultiplier وexpirations وstrikes [15].
3. تأهيل كل عقد مختار وحده: underlying، `secType=OPT`، CALL/PUT، strike، expiry، currency، exchange، tradingClass وmultiplier. وجود strike وexpiry في قائمتين لا يكفي لإثبات وجود تركيبهما. لا تفترض multiplier=100 لجميع العقود المعدلة.
4. التحقق من صلاحية حساب الوسيط للتداول ومن اشتراك بيانات السوق وبيانات الخيار والأصل. معظم الأدوات تتطلب Level 1 API subscription؛ Greeks مرتبطة بطلب بيانات الخيار، وقد تحتاج اشتراك الأصل الأساسي أيضًا [16][17].
5. حفظ نوع التغذية `live/delayed/frozen/synthetic` ووقت الوسيط ووقت الاستلام لكل سعر. البيانات الناقصة أو المؤجلة أو المتجمدة لا تمنح إذن دخول آلي في وضع يحتاج أسعارًا حية.
6. تحقق كمي مستقل من Bid/Ask غير المعكوس، spread، عمر السعر، sizes، volume/open interest المتاحين، Greeks/IV إن كانت الاستراتيجية تتطلبها، min tick، مواعيد التداول والانتهاء، العمولة والانزلاق والسيولة. غياب البيانات المطلوبة سبب رفض معلن، وليس صفرًا صالحًا.

يُفصل تفعيل الرمز في قائمة المراقبة عن إذن تداول عقد بعينه. Demo يظل كتالوجًا اصطناعيًا ولا يضع علامة «تم التحقق لدى IBKR». أي اختيار لاحق لخدمات البيانات أو تفعيل API يجب أن يراجع متطلبات اشتراكات وتوصيف استعمال API والأتمتة المنشورة آنذاك [18].

## هوية الأوامر والمصالحة

TWS يستخدم order ID متزايدًا يديره العميل، ويقدم `nextValidId` عند الاتصال؛ هذا الرقم ليس بديلًا عن مفتاح طلب دائم في قاعدة بيانات التطبيق [19]. يقترح التصميم حفظ:

`application_account_id + broker_account_id + connection_id + client_id + local_request_key + broker_order_id + perm_id + execution_id`

يُحفظ الأمر وحجز التعرض ومحتواه وبصمته **قبل** محاولة الإرسال. ضياع الرد ينتج حالة `SUBMISSION_UNKNOWN` ولا ينتج إعادة إرسال تلقائية بمعرّف جديد. رقم `orderRef`، إذا استُخدم لاحقًا، وسيلة ربط إضافية وليس ضمان idempotency من الوسيط.

عند الانقطاع، يُغلق باب الدخول والتعزيز والعكس. بعد الاتصال، تُجمع الحسابات والأرصدة والمراكز والأوامر المفتوحة والتنفيذات والأوامر المكتملة المتاحة، وتُنتظر علامات نهاية الاستجابة لكل طلب. استعلام الأوامر النشطة لا يعيد بالضرورة الأوامر المكتملة أو الملغاة [20]. التنفيذات المتاحة عبر callback موثقة ضمن نافذة محدودة؛ لا يجوز استنتاج «لم يُرسل» لمجرد غياب أمر قديم عن استعلام واحد [21].

قد تتكرر `orderStatus`، وقد تصل تصحيحات تنفيذ بـ`execID` مختلف بعد آخر نقطة. يعالج دفتر أحداث الوسيط التكرار والتصحيح دون مضاعفة الكمية أو النقد، مع حفظ النسخة السابقة والتصحيح [22][23]. حالة `PendingCancel` لا تعني الإلغاء؛ قد يصل تنفيذ قبل تأكيد الإلغاء [24].

**سياسة عكس الاتجاه المقترحة:** إلغاء المتبقي القديم وانتظار حسمه، إغلاق الكمية المملوكة فقط، انتظار اكتمال التنفيذ، ثم مصالحة جديدة تثبت عدم وجود مركز أو دخول غير محسوم للسهم داخل الحساب، ثم إعادة فحص صلاحية الإشارة والعقد والمخاطر قبل الدخول المعاكس. أي شك يبقي الاتجاه الجديد مقفلًا. لا يُستخدم إلغاء شامل في الوسيط بديلًا عن إلغاء الأوامر الخاصة بالحساب والتطبيق.

## الواجهة المستهدفة وحدود التنفيذ

أضيفت إلى `backend/app/adapters.py` عقود Python ثابتة قابلة للتحقق للهوية والرصيد والأداة المؤهلة والأسعار وأمر Limit والإيصال والمركز ولقطة المصالحة. هي حدود بيانات وليست تنفيذًا لاتصال IBKR أو مصدرًا لصلاحية التداول. اكتمل تأهيل كتالوج Mock فقط؛ قراءة الأرصدة والأسعار وإرسال/إلغاء/مصالحة الأوامر في هذه الواجهة ترفض الاستخدام صراحةً وتوجّه إلى `TradingService`، مالك دفتر المحاكاة الحالي. جميع وظائف IBKR ترفض دون شبكة.

الجدول التالي يفصل الواجهة المستهدفة عن تشغيل الوسيط غير المنفذ:

| مجموعة الواجهة | المدخلات/المخرجات المطلوبة | شرط الأمان |
|---|---|---|
| Capabilities / session status | mode، نوع النقل، authenticated، needs-human-auth، زمن التحديث | الإعداد الافتراضي disabled؛ Live غير قابل للتفعيل |
| Account snapshot | حساب وسيط مصرح، Net Liquidation، Buying Power، cash، عملة، complete/as-of | اللقطة الناقصة/القديمة لا تجيز دخولًا |
| Qualification / quotes | هوية عقد كاملة، بيانات entitlement، مصدر ووقت وأسعار | لا تأهيل بمجرد تطابق ticker |
| Order intent | قرار كمي محفوظ، account، contract، limit، quantity، request key | المرور عبر محرك المخاطر وحده؛ BUY_TO_OPEN أو SELL_TO_CLOSE للمملوك |
| Order events / reconciliation | receipt، status، cumulative fill، executions، corrections، end markers | append-only events + حسم متسق قبل استعادة الثقة |
| Cancel / replace | account + هوية أمر مملوك للتطبيق + revision | لا تحويل PendingCancel إلى Cancelled دون إثبات |

أبقِ session coordinator واحدًا لكل اتصال مشترك لمنع تنافس معرّفات الطلبات وتبديل الحساب. استخدم طابورًا محدودًا مع pacing/backoff، ولا تجعل retry عامًا يعيد أوامر مالية. فشل auth أو pacing أو الأسعار لا يُعوض بدرجة Trust Score عالية.

## ما يلزم قبل تجربة Paper منفصلة

تبقى الاختبارات التالية غير منفذة ضد IBKR: أهلية الحساب والمصادقة و2FA وإعادة التشغيل الأسبوعي؛ التأهيل والأسعار المرخصة؛ حدود pacing الواقعية؛ أوامر limit والإلغاء أثناء fill؛ الأحداث المتأخرة والتصحيحات؛ المصالحة بعد restart؛ اختلاف cash/buying power؛ انتهاء العقود والممارسة؛ القيود الإقليمية؛ تشغيل ممتد ونسخ احتياطي واستعادة. لا ينتج Mock أو نجاح CI دليلًا على هذه النقاط.

## المصادر الرسمية التي قُرئت

جميعها وثائق عامة من IBKR، تم الوصول إليها في 2026-10-10. لم تُستدعَ endpoints الواردة داخل أمثلتها.

1. [TWS API requirements](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/requirements)
2. [Daily and weekly reauthentication](https://www.interactivebrokers.com/docs/tws-api/doc/tws-settings/daily-weekly-reauthentication)
3. [Web API overview / individual access](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/)
4. [Web API authentication methods and eligible account types](https://www.interactivebrokers.com/docs/web-api/authentication/introduction)
5. [Client Portal Gateway limitations](https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/limitations-of-the-client-portal-gateway)
6. [Client Portal Gateway FAQ](https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/client-portal-gateway-faq)
7. [Authentication FAQ](https://www.interactivebrokers.com/docs/web-api/authentication/faq)
8. [TWS pacing](https://www.interactivebrokers.com/docs/tws-api/doc/pacing-limitations/introduction)
9. [Web API pacing](https://www.interactivebrokers.com/docs/web-api/v1/pacing-limitations)
10. [Multiple sessions](https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions)
11. [Receive brokerage accounts](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/accounts/receive-brokerage-accounts)
12. [ClientId 0 and Master ClientId](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/client-id-0-and-the-master-client-id)
13. [Market data sharing](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/market-data-users/market-data-sharing)
14. [Request contract details](https://www.interactivebrokers.com/docs/tws-api/doc/contracts-financial-instruments/contract-details/request-contract-details)
15. [Request option chains](https://www.interactivebrokers.com/docs/tws-api/doc/contracts-financial-instruments/option-chains/request-option-chains) and [receive parameters](https://www.interactivebrokers.com/docs/tws-api/doc/contracts-financial-instruments/option-chains/receive-option-chains)
16. [Market data subscriptions](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/introduction)
17. [Request option Greeks](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-live/option-greeks/request-options-greeks)
18. [Automation and software disclosure](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/compliance-requirements-for-api-market-data/api-user-activity-certification/automation-and-software-disclosure)
19. [Order IDs](https://www.interactivebrokers.com/docs/tws-api/doc/quick-start/order-id)
20. [Active orders](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/requesting-currently-active-orders/introduction)
21. [Receive execution details](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/execution-details/receive-execution-details)
22. [Order status callbacks](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/order-status/introduction)
23. [Execution corrections](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/execution-details/exec-id-behavior)
24. [Order status meanings](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/order-status/understanding-order-status-message)
