/// One automation cycle as it happened: market state, what each symbol's
/// analysis said, the decision taken and why, orders, fills and errors.
/// Recorded even when routine "no trade" notes are rate-limited in the journal.
library;

class CycleSymbolNote {
  final String symbol;
  double? score;
  String? bias;

  /// Last decision for the symbol in this cycle (JournalAction name), e.g.
  /// `entry`, `exit`, `skip`, `blocked`, `error`; `analysed` when only scored.
  String action;
  String reasonAr;

  CycleSymbolNote(this.symbol, {this.score, this.bias, this.action = 'analysed', this.reasonAr = ''});

  Map<String, Object?> toJson() => {
        's': symbol,
        if (score != null) 'sc': double.parse(score!.toStringAsFixed(1)),
        if (bias != null) 'b': bias,
        'a': action,
        'r': reasonAr,
      };

  factory CycleSymbolNote.fromJson(Map<String, dynamic> j) => CycleSymbolNote(
        j['s'] as String,
        score: (j['sc'] as num?)?.toDouble(),
        bias: j['b'] as String?,
        action: j['a'] as String? ?? 'analysed',
        reasonAr: j['r'] as String? ?? '',
      );
}

class CycleRecord {
  final int cycle;
  final DateTime start;
  DateTime? end;
  bool ran;
  String? marketPhase;
  String? marketSummaryAr;
  final Map<String, CycleSymbolNote> symbols;
  final List<String> orders;
  int fills;
  final List<String> errors;
  String noteAr;

  CycleRecord({
    required this.cycle,
    required this.start,
    this.end,
    this.ran = false,
    this.marketPhase,
    this.marketSummaryAr,
    Map<String, CycleSymbolNote>? symbols,
    List<String>? orders,
    this.fills = 0,
    List<String>? errors,
    this.noteAr = '',
  })  : symbols = symbols ?? {},
        orders = orders ?? [],
        errors = errors ?? [];

  CycleSymbolNote symbol(String s) => symbols.putIfAbsent(s, () => CycleSymbolNote(s));

  bool get hasOrders => orders.isNotEmpty;
  bool get hasErrors => errors.isNotEmpty;
  bool get marketClosed => marketPhase != null && marketPhase != 'open';

  Map<String, Object?> toJson() => {
        'c': cycle,
        't': start.toIso8601String(),
        if (end != null) 'e': end!.toIso8601String(),
        'ran': ran,
        if (marketPhase != null) 'mp': marketPhase,
        if (marketSummaryAr != null) 'ms': marketSummaryAr,
        'sy': [for (final n in symbols.values) n.toJson()],
        if (orders.isNotEmpty) 'o': orders,
        if (fills > 0) 'f': fills,
        if (errors.isNotEmpty) 'er': errors,
        if (noteAr.isNotEmpty) 'n': noteAr,
      };

  factory CycleRecord.fromJson(Map<String, dynamic> j) => CycleRecord(
        cycle: j['c'] as int,
        start: DateTime.parse(j['t'] as String),
        end: j['e'] == null ? null : DateTime.parse(j['e'] as String),
        ran: j['ran'] as bool? ?? false,
        marketPhase: j['mp'] as String?,
        marketSummaryAr: j['ms'] as String?,
        symbols: {
          for (final n in (j['sy'] as List? ?? const []).map((e) => CycleSymbolNote.fromJson((e as Map).cast())))
            n.symbol: n
        },
        orders: [for (final o in (j['o'] as List? ?? const [])) o as String],
        fills: j['f'] as int? ?? 0,
        errors: [for (final o in (j['er'] as List? ?? const [])) o as String],
        noteAr: j['n'] as String? ?? '',
      );
}
