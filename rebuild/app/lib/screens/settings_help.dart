/// Arabic explanation and a conservative suggestion for each setting.
/// Allowed ranges come from `AccountSettings.allowedRanges` (enforced on save).
class SettingHelp {
  final String label;
  final String explain;
  final String? suggested;
  final String suffix;
  const SettingHelp(this.label, this.explain, {this.suggested, this.suffix = ''});
}

const settingsHelp = <String, SettingHelp>{
  // المخاطرة
  'riskPerTradePercent': SettingHelp('نسبة المخاطرة لكل صفقة',
      'أقصى خسارة مقبولة للصفقة الواحدة كنسبة من قيمة الحساب (سعر العقد × نسبة وقف الخسارة). تحدد عدد العقود.',
      suggested: '0.5–2', suffix: '%'),
  'maxPositionPercent': SettingHelp('أقصى حجم للمركز الواحد', 'أقصى تكلفة لمركز واحد من قيمة الحساب، مهما كانت المخاطرة.',
      suggested: '5–15', suffix: '%'),
  'maxContractsPerTrade': SettingHelp('أقصى عدد عقود للصفقة', 'سقف صريح لعدد العقود في أمر الدخول الواحد.', suggested: '1–5'),
  'maxTotalExposurePercent': SettingHelp('أقصى تعرض كلي', 'مجموع تكلفة كل المراكز المفتوحة كنسبة من قيمة الحساب.',
      suggested: '20–50', suffix: '%'),
  'dailyLossLimitPercent': SettingHelp('حد الخسارة اليومي',
      'إذا انخفضت قيمة الحساب بهذه النسبة عن بداية يوم نيويورك يتوقف الدخول الجديد لبقية اليوم.', suggested: '2–5', suffix: '%'),
  // حدود الأمان
  'maxOpenPositions': SettingHelp('أقصى عدد صفقات مفتوحة', 'لا يُفتح مركز جديد إذا بلغ عدد المراكز (مع الأوامر المعلقة) هذا الحد.',
      suggested: '1–5'),
  'maxOrdersPerDay': SettingHelp('أقصى أوامر فتح يوميًا',
      'يشمل الدخول والتعزيز، ويُصفَّر مع بداية يوم نيويورك. أوامر الخروج غير محدودة دائمًا.', suggested: '3–10'),
  'symbolCooldownMinutes': SettingHelp('فترة التهدئة لكل سهم',
      'لا دخول جديد على نفس السهم خلال هذه المدة بعد أي دخول أو خروج عليه (0 = تعطيل). تؤخر أيضًا الانتقال من Call إلى Put.',
      suggested: '30–120', suffix: 'دقيقة'),
  // الدخول
  'minScore': SettingHelp('الحد الأدنى للنتيجة المركبة',
      'النتيجة من 0 إلى 100 تجمع إشارات المحركات بأوزانها. كلما ارتفع الحد قلت الصفقات وزادت انتقائيتها.', suggested: '35–60'),
  'minAgreeingEngines': SettingHelp('أقل عدد محركات متوافقة', 'عدد المحركات التي يجب أن تتفق على الاتجاه قبل الدخول.',
      suggested: '2–3'),
  // اختيار العقد
  'minDaysToExpiry': SettingHelp('أقل أيام حتى الانتهاء', 'تجنب العقود القريبة جدًا من الانتهاء (تآكل زمني سريع).',
      suggested: '7–14'),
  'maxDaysToExpiry': SettingHelp('أقصى أيام حتى الانتهاء', 'يجب أن يكون أكبر من أو يساوي أقل أيام الانتهاء.', suggested: '30–60'),
  'targetDelta': SettingHelp('الدلتا المستهدفة',
      'حساسية سعر العقد لحركة السهم. 0.5 تقريبًا = عند سعر التنفيذ (ATM)؛ الأقل أرخص وأكثر مخاطرة.', suggested: '0.35–0.55'),
  'maxSpreadPercent': SettingHelp('أقصى فرق بين العرض والطلب',
      'يرفض العقود ذات السيولة الضعيفة؛ الفرق الكبير يعني خسارة فورية عند الدخول والخروج.', suggested: '5–15', suffix: '%'),
  'minOpenInterest': SettingHelp('أقل عدد عقود مفتوحة (OI)', 'مؤشر سيولة للعقد.', suggested: '100 أو أكثر'),
  'entryAggressiveness': SettingHelp('جرأة التسعير',
      '0 = الشراء بسعر العرض (قد لا يُنفذ)، 1 = بسعر الطلب (تنفيذ أسرع وتكلفة أعلى).', suggested: '0.4–0.7'),
  'orderTimeoutCycles': SettingHelp('إلغاء الأمر غير المنفذ بعد (دورات)', 'كل دورة دقيقة تقريبًا؛ بعدها يُلغى الأمر ويعاد تسعيره.',
      suggested: '2–5'),
  // الخروج
  'stopLossPercent': SettingHelp('وقف الخسارة', 'يُغلق المركز إذا انخفض سعر العقد بهذه النسبة من سعر الشراء.',
      suggested: '25–50', suffix: '%'),
  'partialTakeProfitPercent': SettingHelp('جني ربح جزئي عند', 'عند هذا الربح يُباع جزء من الكمية. يجب أن يكون أقل من الهدف الكامل.',
      suggested: '30–60', suffix: '%'),
  'partialTakeProfitFraction': SettingHelp('نسبة الكمية المباعة جزئيًا', '0 = تعطيل الجني الجزئي، 0.5 = نصف الكمية.',
      suggested: '0.3–0.5'),
  'takeProfitPercent': SettingHelp('هدف الربح الكامل', 'يُغلق المركز بالكامل عند هذا الربح.', suggested: '60–150', suffix: '%'),
  'trailingActivationPercent': SettingHelp('تفعيل الوقف المتحرك عند ربح', 'بعد هذا الربح يبدأ الوقف المتحرك بتتبع أعلى سعر.',
      suggested: '20–40', suffix: '%'),
  'trailingStopPercent': SettingHelp('الوقف المتحرك: تراجع من القمة', 'يُغلق المركز إذا تراجع سعر العقد بهذه النسبة من أعلى سعر بلغه.',
      suggested: '15–30', suffix: '%'),
  'maxHoldingDays': SettingHelp('أقصى مدة احتفاظ (أيام)', 'يُغلق المركز بعد هذه المدة مهما كانت النتيجة.', suggested: '5–15'),
  'exitDaysBeforeExpiry': SettingHelp('الإغلاق قبل الانتهاء بـ (أيام)', 'يتجنب مخاطر يوم الانتهاء والتنفيذ.', suggested: '1–3'),
  // التعزيز
  'maxScaleIns': SettingHelp('أقصى عدد تعزيزات', 'مرات إضافة عقود لمركز رابح.', suggested: '0–1'),
  'scaleInMinProfitPercent': SettingHelp('أقل ربح للتعزيز', 'لا تعزيز قبل أن يربح المركز هذه النسبة.', suggested: '15–30', suffix: '%'),
  'scaleInMinScore': SettingHelp('أقل نتيجة للتعزيز', 'نتيجة التحليل في نفس الاتجاه المطلوبة للتعزيز.', suggested: '50–70'),
  'scaleInFraction': SettingHelp('حجم التعزيز', 'نسبة من الكمية الأولى (0.5 = نصفها).', suggested: '0.25–0.5'),
  'maxIvRvRatio': SettingHelp('حد IV/RV',
      'التقلب الضمني للعقد مقسومًا على التقلب المحقق للسهم. فوق الحد يكون العقد غاليًا مقارنة بحركة السهم الفعلية فيُمنع الشراء. يعمل فقط عند تفعيل الفلتر.',
      suggested: '1.3–1.8'),
  'rvLookbackDays': SettingHelp('فترة التقلب المحقق',
      'عدد أيام التداول المستخدمة لحساب التقلب المحقق (انحراف العوائد اليومية × √252).',
      suggested: '20', suffix: 'يوم'),
  'maxBreakevenToExpectedMove': SettingHelp('حد حركة التعادل',
      'يمنع الشراء إذا كانت الحركة اللازمة للتعادل عند الانتهاء أكبر من هذا المضاعف للحركة المتوقعة (السعر × RV × √الزمن). 0 = تعطيل هذا الشرط.',
      suggested: '1.0'),
};
