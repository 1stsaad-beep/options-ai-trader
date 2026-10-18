/// Toggleable chart layers. Order = paint order (later on top).
enum ChartLayer {
  ema('المتوسطات EMA 20/50/200', false),
  levels('الدعوم والمقاومات', true),
  trendLines('خطوط الاتجاه', true),
  zigzag('ZigZag والقمم/القيعان المؤكدة', true),
  classical('الأنماط الكلاسيكية', true),
  harmonic('الهارمونيك XABCD + PRZ', true),
  elliott('موجات إليوت', true),
  divergence('الدايفرجنس', true),
  targets('الأهداف ومستوى الإبطال', true),
  trades('صفقات الحساب', true),
  score('النتيجة المركبة (لوحة سفلية)', true);

  final String labelAr;
  final bool defaultOn;
  const ChartLayer(this.labelAr, this.defaultOn);

  static Set<ChartLayer> get defaults => {for (final l in values) if (l.defaultOn) l};
}
