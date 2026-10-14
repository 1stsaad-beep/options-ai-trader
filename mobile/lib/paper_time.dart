DateTime observationStamp(dynamic value) {
  if(value is! String||!RegExp(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$').hasMatch(value))throw const FormatException('Invalid timestamp');
  final local=value.substring(0,19),parsed=DateTime.parse('${local}Z');
  if(parsed.year<1||parsed.toIso8601String().substring(0,19)!=local)throw const FormatException('Invalid calendar timestamp');
  if(!value.endsWith('Z')) {
    final offset=value.substring(value.length-5);
    if(int.parse(offset.substring(0,2))>23||int.parse(offset.substring(3))>59)throw const FormatException('Invalid offset');
  }
  return DateTime.parse(value).toUtc();
}

