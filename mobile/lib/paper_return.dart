import 'paper_execution.dart';

/// Compare whole-position liquidation after entry/exit fees and adverse bid
/// slippage. BigInt keeps exact thresholds even near the JSON money limit.
/// This is an observed stress value, never a promise to fill the entire size.
class PaperReturn {
  final BigInt basis, liquidation, peak;
  PaperReturn(Map account, Map position, int bid)
      : basis = BigInt.from(position['cost'] as int) + BigInt.from((position['entryFees'] ?? (position['quantity'] as int) * 65) as int),
        liquidation = _value(account, position, bid),
        peak = _value(account, position, (position['highBid'] as num).toInt());

  static BigInt _value(Map account, Map position, int bid) =>
      (BigInt.from(bid - executionSlippage(account)) * BigInt.from(100) - BigInt.from(executionFee(account))) *
      BigInt.from(position['quantity'] as int);

  bool gainAtLeast(int percent) => liquidation * BigInt.from(100) >= basis * BigInt.from(100 + percent);
  bool lossAtLeast(int percent) => liquidation * BigInt.from(100) <= basis * BigInt.from(100 - percent);
  bool trailingAtLeast(int percent) => peak > basis && liquidation * BigInt.from(100) <= peak * BigInt.from(100 - percent);
}
