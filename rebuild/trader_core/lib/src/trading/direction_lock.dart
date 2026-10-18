/// Opposite-direction lock — the strict rule of this app:
///
///   Inside one account, a Call and a Put on the same underlying may never be
///   open at the same time. The existing side must be **fully** closed (no
///   remaining quantity AND no working orders of any kind on that symbol)
///   before the other side may be opened.
///
/// The check counts both held positions and working orders, so a pending
/// buy, a partially filled order or an unfinished closing order all keep the
/// lock engaged. The trading engine evaluates it twice: once when deciding and
/// again on freshly fetched broker state immediately before submitting.
library;

import '../models.dart';

class LockResult {
  final bool allowed;
  final String? reasonAr;
  const LockResult.allow()
      : allowed = true,
        reasonAr = null;
  const LockResult.block(this.reasonAr) : allowed = false;
}

class DirectionLock {
  /// May the account open (or add to) [right] on [symbol]?
  static LockResult canOpen({
    required String symbol,
    required OptionRight right,
    required List<Position> positions,
    required List<BrokerOrder> openOrders,
  }) {
    final opposite = right.opposite;
    final heldOpposite = positions
        .where((p) => p.contract.underlying == symbol && p.contract.right == opposite)
        .fold<int>(0, (s, p) => s + p.quantity);
    if (heldOpposite > 0) {
      return LockResult.block('قفل الاتجاه: يوجد ${opposite.arabic} مفتوح على $symbol ($heldOpposite عقد) — يجب إغلاقه بالكامل أولًا');
    }
    final workingOpposite =
        openOrders.where((o) => o.status.isOpen && o.contract.underlying == symbol && o.contract.right == opposite);
    if (workingOpposite.isNotEmpty) {
      return LockResult.block('قفل الاتجاه: يوجد أمر ${opposite.arabic} قيد التنفيذ على $symbol');
    }
    // A closing order in progress on the same side means a flip may be underway;
    // do not add to that side until it resolves.
    final closingSame = openOrders.where((o) =>
        o.status.isOpen && o.contract.underlying == symbol && o.contract.right == right && o.side == OrderSide.sellToClose);
    if (closingSame.isNotEmpty) {
      return LockResult.block('يوجد أمر إغلاق قيد التنفيذ على $symbol — انتظار اكتماله');
    }
    return const LockResult.allow();
  }

  /// Direction currently held or working on [symbol], or null when flat.
  static OptionRight? activeRight(String symbol, List<Position> positions, List<BrokerOrder> openOrders) {
    for (final p in positions) {
      if (p.contract.underlying == symbol && p.quantity > 0) return p.contract.right;
    }
    for (final o in openOrders) {
      if (o.status.isOpen && o.contract.underlying == symbol) return o.contract.right;
    }
    return null;
  }
}
