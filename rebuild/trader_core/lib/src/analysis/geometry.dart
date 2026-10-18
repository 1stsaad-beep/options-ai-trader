/// Chart geometry attached to an [EngineSignal] so a UI can draw exactly what
/// the engine saw (pattern points, necklines, boundaries, zones).
///
/// All coordinates are **bar indices into the candle list the engine
/// received** plus prices in dollars. Geometry is descriptive only: it is not
/// serialised into the journal and never influences decisions.
library;

/// A labelled swing point (e.g. X/A/B/C/D, wave 0..5, LS/H/RS).
class GeoPoint {
  final int index;
  final double price;
  final String label;
  const GeoPoint(this.index, this.price, this.label);

  @override
  String toString() => '$label@$index:${price.toStringAsFixed(2)}';
}

/// Role of a line segment, used by the UI to pick a style.
enum GeoRole { pattern, neckline, boundary, divergence, level }

/// A straight segment from (i1, p1) to (i2, p2).
class GeoSegment {
  final int i1;
  final double p1;
  final int i2;
  final double p2;
  final GeoRole role;
  final String? label;
  const GeoSegment(this.i1, this.p1, this.i2, this.p2, {this.role = GeoRole.pattern, this.label});

  /// Price on the (extended) line at bar [i].
  double priceAt(num i) => i2 == i1 ? p2 : p1 + (p2 - p1) * (i - i1) / (i2 - i1);
}

/// A price band between bars [i1] and [i2] (e.g. harmonic PRZ, range box).
class GeoZone {
  final int i1;
  final int i2;
  final double lo;
  final double hi;
  final String label;
  const GeoZone(this.i1, this.i2, this.lo, this.hi, this.label);
}

class ChartGeometry {
  final List<GeoPoint> points;
  final List<GeoSegment> segments;
  final List<GeoZone> zones;

  const ChartGeometry({this.points = const [], this.segments = const [], this.zones = const []});

  static const empty = ChartGeometry();

  bool get isEmpty => points.isEmpty && segments.isEmpty && zones.isEmpty;

  /// Polyline segments joining [points] in order.
  static List<GeoSegment> polyline(List<GeoPoint> pts, {GeoRole role = GeoRole.pattern}) => [
        for (var k = 1; k < pts.length; k++)
          GeoSegment(pts[k - 1].index, pts[k - 1].price, pts[k].index, pts[k].price, role: role)
      ];

  /// Highest bar index referenced (for culling).
  int get maxIndex {
    var m = -1;
    for (final p in points) {
      if (p.index > m) m = p.index;
    }
    for (final s in segments) {
      if (s.i2 > m) m = s.i2;
      if (s.i1 > m) m = s.i1;
    }
    for (final z in zones) {
      if (z.i2 > m) m = z.i2;
    }
    return m;
  }
}
