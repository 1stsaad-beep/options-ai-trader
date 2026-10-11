# مصفوفة اختبارات أمان التداول — V1.0 RC2

تاريخ التشغيل: 2026-10-10. هذه النتائج تشغيل فعلي محلي باستخدام Python 3.12 وSQLite وMock وبيانات اصطناعية فقط. لم يحدث اتصال بوسيط أو إرسال أمر مالي خارجي.

النتيجة بعد الإصلاح: **51 ناجحًا، 0 فاشل، 0 أخطاء، 0 متجاوز** في المجموعة المنتقاة أدناه. تتضمن المجموعة **8 حالات جديدة** في `backend/tests/test_rc2_safety.py`. ظهر تحذير واحد موجود من قبل حول استخدام `httpx` مع `Starlette TestClient`؛ لم يتسبب في فشل اختبار. هذه المجموعة ليست عدد اختبارات المشروع الكامل ولا نتيجة Flutter أو PostgreSQL؛ تقارير التشغيل الشامل توثق تلك النتائج بصورة منفصلة.

الأدلة القابلة لإعادة التشغيل:

- `docs/evidence/rc2/safety-selected-command.json`: الأمر الكامل ومعرّفات الاختبارات المنتقاة.
- `docs/evidence/rc2/safety-selected.xml`: نتائج JUnit الفعلية لكل حالة، بما فيها الحالات المعلّمة بالمعلمات.
- `docs/evidence/rc2/safety-selected.log`: مخرجات التنفيذ الفعلية.
- `docs/evidence/rc2/safety-selected-summary.json`: العدد المستخرج من JUnit.

## المشكلة المثبتة والإصلاح

أنتج أول تشغيل للاختبارات الجديدة **6 نجاحات وفشلًا واحدًا** قبل الإصلاح: حقن `RuntimeError` داخل مشرف المخاطر عند إعادة تقييم أمر شراء معلق في حساب آخر أدى إلى التراجع عن تنفيذ `SELL_TO_CLOSE` صحيح ومملوك. السبب أن `_cancel_unsafe_pending_buys` كان يتعامل مع الرفض المعتاد `Rejected` فقط، رغم استدعائه بعد تسجيل إغلاق المركز داخل المعاملة.

الإصلاح المحدود في `backend/app/service.py` يلغي حجوزات شراء Mock التي تعذر التحقق منها، ويسجل سببًا عامًا خاليًا من تفاصيل الاستثناء. يسمح بذلك باستكمال الإغلاق المملوك الذي اجتاز تحقق الحساب والمخزون. لا يحول الاستثناء إلى موافقة مخاطرة، ولا يجدد حالة الحساب، ولا يتجاوز فحوص قبول أو تنفيذ أي شراء لاحق. إذا كانت قاعدة البيانات نفسها غير صالحة لإتمام المعاملة، تبقى آلية التراجع قائمة.

أضيفت حالة الإغلاق الآلي إلى حالة الإغلاق اليدوي، فأصبحت الحالات الجديدة ثماني حالات. تؤكد الاختبارات أن الإغلاق لا يكرر الربح والخسارة عند إعادة قراءة الإيصال، وأن تفاصيل الاستثناء لا تدخل سجل التدقيق، وأن شراءً جديدًا أثناء العطل يظل ممنوعًا، وأن بيع كمية غير مملوكة يظل مرفوضًا. المخزون غير الموثوق لا يحصل على استثناء للإغلاق.

## المتطلبات الإلزامية السبعة عشر

جميع أسماء الملفات في الجدول تقع داخل `backend/tests/`. كل المعرفات المذكورة شُغّلت ضمن ملف الأمر أعلاه؛ تعني «نجح» اجتياز الحالة الاصطناعية المحددة، ولا تعني اعتماد التشغيل عند وسيط خارجي.

| # | المتطلب | دليل الاختبار المنفذ | النتيجة والنطاق |
|---|---|---|---|
| 1 | الدخول الآلي الوهمي | `test_automation_v04.py::test_actual_quantitative_breakout_enters_single_call_with_risk_admission` و`test_automatic_put_uses_quantitative_downtrend_signal` | نجح Call وPut من قواعد كمية إلى أمر وتعبئة Mock |
| 2 | الإغلاق اليدوي | `test_rc2_safety.py::test_owned_close_survives_risk_outage_and_cancels_uncheckable_pending_buys[False]` و`test_v1_execution.py::test_lowered_entry_cap_does_not_strand_owned_close` | نجح إغلاق مملوك حتى مع خفض حد الدخول أو عطل حساب المخاطر؛ المخزون المجهول يبقى محظورًا |
| 3 | وقف الخسارة الآلي | `test_automation_v04.py::test_stop_loss_cancels_partial_entry_remainder_before_owned_exit` وحالة الإغلاق الآلي الجديدة `[True]` | أُلغي باقي الدخول الجزئي وأُغلقت الكمية المملوكة فقط |
| 4 | جني الربح الآلي | `test_automation_v04.py::test_take_profit_closes_owned_contract_and_same_day_never_reenters` | أُغلق المركز وسُجل الربح دون إعادة الدخول في اليوم نفسه |
| 5 | الوقف المتحرك | `test_v1_execution.py::test_adaptive_exit_rules`، الحالة `TRAILING_STOP` | نجح تحديث أعلى سعر ثم الخروج عند التراجع المحدد |
| 6 | الخروج قبل نهاية الجلسة | `test_v1_execution.py::test_adaptive_exit_rules`، الحالة `INTRADAY_EXIT` | نجح الخروج عند ساعة UTC المكونة؛ لا يُدّعى وجود تقويم بورصة كامل |
| 7 | إغلاق Call قبل فتح Put | `test_rc2_safety.py::test_reversal_both_directions_restart_partial_close_lost_reply_and_fees[CALL-PUT]` | إغلاق جزئي ثم إعادة تشغيل ومصالحة ثم إغلاق كامل وإعادة تقييم ودخول Put |
| 8 | إغلاق Put قبل فتح Call | الاختبار السابق، الحالة `[PUT-CALL]` | تحقق التسلسل المقابل، دون استنتاج التناظر من حالة Call فقط |
| 9 | منع الاتجاهين المتعاكسين | `test_v1_execution.py::test_opposite_pending_partial_owned_and_other_account` و`test_simultaneous_opposing_entries_are_serialized` و`test_reversal_flat_interval_is_locked_against_manual_old_entry` | نجح القفل أثناء الأمر المعلق والتنفيذ الجزئي والمركز المملوك وفترة الانعكاس، مع عزل الحساب الآخر |
| 10 | منع الأوامر المكررة | `test_automation_v04.py::test_parallel_repeated_cycles_and_lost_response_do_not_duplicate` وحالتي الانعكاس الجديدتين | التكرار المتزامن وفقدان الرد لا ينشئان أمرًا ثانيًا أو تعبئة ثانية |
| 11 | التنفيذ الجزئي | `test_automation_v04.py::test_partial_fills_advance_only_on_new_observation` و`test_v1_execution.py::test_partial_scale_reduction_preserves_fill_receipt_and_blocks_remainder` | لكل ملاحظة جديدة حصة تنفيذ؛ تضييق التعزيز يحفظ الإيصال السابق ويمنع الباقي |
| 12 | الانقطاع والمصالحة | `test_automation_v04.py::test_restart_requires_reconciliation_then_resumes_partial_without_resubmit` و`test_disconnect_and_market_outage_do_not_fill_or_self_restore` وحالتي الانعكاس الجديدتين | إعادة التشغيل لا تثبت الثقة تلقائيًا؛ المصالحة لا تعيد إرسال الأمر |
| 13 | عزل الحسابات | `test_adversarial_v04.py::test_cross_account_fill_identifier_collision_cannot_transfer_inventory` وحالتي الانعكاس الجديدتين | منع نقل التعبئة، وحفظ أوامر ومراكز وقرارات الحساب الآخر دون تغيير |
| 14 | العمولات والربح والخسارة | `test_v1_execution.py::test_commission_reservation_cost_basis_close_pnl_and_replay` وحالتي الانعكاس الجديدتين | احتساب صحيح بالسنت، وتثبيت عمولة الأمر المقبول، وعدم احتساب الربح والخسارة مرتين |
| 15 | عدم استخدام المستقبل | `test_v05_backtest.py::test_future_append_preserves_equity_prefix_and_entry` و`test_exit_trigger_cannot_fill_until_next_fresh_observation` و`test_research_v1.py::test_walk_forward_selection_does_not_look_at_test_outcomes` و`test_walk_forward_appending_future_does_not_repaint_completed_folds` | نجحت ثبات بادئة النتائج وفصل الاختيار عن الاختبار والتنفيذ في الملاحظة اللاحقة؛ لا يثبت ذلك ربحية استراتيجية |
| 16 | التوقف عند فقد البيانات أو فشل المخاطر | `test_adversarial_v03.py::test_market_outage_blocks_new_entry_and_pending_buy_fill` وحالتا `test_unexpected_risk_failure_blocks_manual_new_exposure_atomically` وحالتا `test_risk_exception_cannot_create_or_fill_automatic_entry` | لا دخول ولا زيادة تعبئة عند العطل؛ الإغلاق يظل مقيدًا بالمخزون والحساب الموثوقين |
| 17 | استمرار قفل Live | `test_adversarial_v03.py::test_live_environment_refuses_startup` للحالتين `live` و`LIVE` و`test_execution.py::ExecutionTests::test_caps_and_live_external_broker_locked` | رفض وضع Live والوسيط الخارجي والتكامل العام المعطل |

اختُبرت أيضًا حدود المجموعات المالية، وتعطل رأس مال حساب آخر أمام المشرف العام، ومنع تكرار حجز كمية الإغلاق، وكتابة انتهاء العقد مرة واحدة دون بيع وهمي، والخروج الزمني Swing، والتعزيز مع التهدئة، وثبات القمم المؤكدة وسجل الموجات عند إعادة العرض. تفاصيل كل حالة في JUnit.

## حدود النتيجة وما يلزم قبل IBKR Paper

- جميع الأوامر معاملات في دفتر Mock محلي؛ فقدان الرد يعني فقدان استجابة بعد تسجيل المعاملة. لم يُختبر فقدان رد IBKR، أو تأخر إقرار إلغاء خارجي، أو رفض جزئي من بورصة.
- الإلغاء الداخلي فوري ومؤكد داخل SQLite. يجب أن يحافظ أي وسيط مستقبلي على حالة «غير محسوم» حتى يصل إقرار الوسيط وتتم المصالحة؛ لا يجوز نقل افتراض الإلغاء الفوري إلى IBKR.
- الوقف وجني الربح والوقف المتحرك محفزات تولد أوامر Limit؛ لا تضمن سعر التنفيذ أو نسبة صافي ربح/خسارة بعد عمولة الإغلاق. دفتر التعبئة يحسب العمولات والربح والخسارة فعليًا.
- خروج Intraday يستخدم ساعة UTC مكونة. جداول السوق الصيفية والعطل والإغلاق المبكر تحتاج تقويمًا موثوقًا واختبارات تكامل قبل Paper.
- انتهاء الخيار في المحاكاة سياسة صريحة لكتابة كامل العلاوة كخسارة، دون محاكاة ممارسة أو تسوية حقيقية. ليست نموذجًا معتمدًا لمخاطر التمرين أو التعيين.
- هذه المجموعة استخدمت SQLite. الاختبارات الموازية على PostgreSQL وDocker وFlutter لها أدلة مستقلة؛ لا تُستنتج من نجاح هذه المجموعة.
- لا توجد بيانات سوق فعلية أو نتائج خارج العينة على خيارات حقيقية هنا. لا تثبت النتائج فائدة تجارية أو ربحية موجات أو هارمونيك أو استراتيجية.

## تحديث Engineering في 2026-10-11

الأقسام السابقة سجل تاريخي محفوظ لا يُحذف. المجموعة الكاملة الحالية **782 Python ناجحًا، صفر فشل/خطأ/تجاوز** محليًا وفي CI؛ تشمل المجموعة التاريخية وكل الإضافات أدناه. المرجع الحالي `RECOVERY_TEST_REPORT_V1.md` والأدلة `docs/evidence/engineering-20261011/`.

| الإصلاح/الحالة | اختبار فعلي | النطاق |
|---|---|---|
| الجني الجزئي لا يتحول إلى إغلاق كامل عند استئناف المتبقي؛ فشل التحليل الاختياري | `test_recovery_exit_policy.py` و`test_recovery_protective_exits.py` | كمية الإغلاق المقبولة محفوظة؛ المحفز الكامل الجديد له الأولوية |
| سحب إذن العكس/الأتمتة/الاستراتيجية بعد قبول أمر أو تعبئة جزئية | `test_recovery_entry_permissions.py::test_disabled_policy_blocks_reversal_fill_and_preserves_receipts` ومعادلات Demo في `demo_entry_permissions_test.dart` | الاتجاهان وإعادة التشغيل؛ لا يلغي إيصالًا سابقًا أو يكرر محاسبته |
| تقويم DST/العطل/الإغلاق المبكر | `test_market_sessions_v1.py`؛ 70 حالة نقية | 2026–2027، مصادر رسمية مثبتة؛ لا استنتاج تكامل من الوحدة وحدها |
| إعادة جلسة/وقت عند القبول والتعبئة | `test_session_execution_v1.py` | cutoff وDAY والعكس وتأجيل الإغلاق المملوك خارج ساعات التعبئة |
| عطل التقويم لا يخترع تنفيذًا ولا يمحو نية حماية | `test_calendar_failure_preserves_protective_intent_and_never_fills` | بوابات المخزون/المخاطر تبقى إلزامية |
| لقطات بحث ثابتة وعزل واستعادة خدمة | `test_research_contract_v1.py` و`scripts/smoke_http.py` | HTTP فعلي وإعادة عملية الخادم؛ Python JSON نفسه في Dart fixture |
| عدم إنتاج outcome من مستقبل مولد عند replay | `test_research_observations_v1.py` | capture لاحق فعلي، إعادة الدقيقة idempotent، رفض client time/price، migration v4→v5 |
| PostgreSQL ملاحظات غير قابلة للتعديل | `scripts/postgres_v1_check.py`، آخر أربعة فحوص من 14 | تزامن، عزل، triggers، رؤية من اتصال آخر |
| تاريخ موجي غير معاد رسمه عند restart/append | `test_wave_snapshot_integrity.py` | 13 حالة؛ digest/source/scope/audit، تاريخ أحداث غير فارغ محفوظ |

تطور فحص الخروج اليومي: ما زالت ساعة UTC في السياسة الاصطناعية الافتراضية وDemo، وأضيفت سياسة US اختيارية للخادم فقط. انتهاء العقود ما زال مبسطًا؛ تمرير اختباره لا يثبت ممارسة/تخصيصًا حقيقيًا. لا اتصال وسيط ولا اختبار جهاز.

## Continuation expiry acceptance — 2026-10-11

- `test_option_expiration_policy.py`: 46 pure timing cases (DST, early close, holiday Friday, unknown calendar).
- `test_us_expiry_protection.py`: 22 real SQLite service/automation cases. Saved-source baseline 22 failures; current 22 passes. Partial-close basis/fees and receipts survive cutoff/restart; no phantom flatness, opposite entry, post-cutoff fill, fake valuation, or session-policy downgrade.
- Full local Python gate now 850 passes. PostgreSQL harness extended to 22 checks; actual cloud result must be read before claiming it passed.
- Optional US policy only; default synthetic/mobile writeoff remains artificial. See `OPTION_EXPIRATION_POLICY_V1.md`; no exercise/assignment/settlement or broker connection.
