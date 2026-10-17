const greekFields = ['delta', 'gamma', 'theta', 'vega', 'rho'];

Map<String, dynamic>? providerGreeks(dynamic raw, String right) {
  if (!['C', 'P'].contains(right) || raw != null && raw is! Map) {
    throw const FormatException('Invalid provider Greeks');
  }
  if (raw == null) return null;
  final values = <String, dynamic>{for (final key in greekFields) key: raw[key]};
  for (final entry in values.entries) {
    final value = entry.value;
    if (value == null) continue;
    if (value is! num || !value.isFinite) throw const FormatException('Invalid provider Greeks');
    if (entry.key == 'delta' && !(right == 'C' ? value >= 0 && value <= 1 : value >= -1 && value <= 0)) {
      throw const FormatException('Invalid provider delta');
    }
    if (['gamma', 'vega'].contains(entry.key) && value < 0) throw const FormatException('Invalid long option sensitivity');
  }
  return values;
}

Map<String, dynamic> providerGreeksQuality(Map<String, dynamic>? values) {
  final status = values == null ? 'MISSING' : greekFields.any((key) => values[key] == null) ? 'PARTIAL' : 'VALUES_ONLY';
  return {'contract': 'option-greeks-quality-v1', 'valuesStatus': status,
    'providerTimestampAvailable': false, 'freshnessVerified': false, 'entryEligible': false,
    'reasons': [if (status != 'VALUES_ONLY') 'GREEKS_MISSING_VALUES',
      'GREEKS_PROVIDER_TIME_UNAVAILABLE', 'CONTRACT_TERMS_UNAVAILABLE', 'INDICATIVE_OPTIONS_NOT_EXECUTABLE']};
}
