import 'dart:convert';

/// Checked before allocating the decoded object graph. Syntax remains Dart's
/// JSON contract; duplicate keys are refused instead of silently losing data.
class JsonBoundsException extends FormatException {
  const JsonBoundsException() : super('JSON exceeds structural bounds');
}

class JsonDuplicateKeyException extends FormatException {
  const JsonDuplicateKeyException() : super('Duplicate JSON key');
}

Object? decodeBoundedJson(String text, {required int maxBytes,
    required int maxNodes, required int maxDepth}) {
  if (text.length > maxBytes) throw const JsonBoundsException();
  var bytes = 0;
  for (final rune in text.runes) {
    bytes += rune <= 0x7f ? 1 : rune <= 0x7ff ? 2 : rune <= 0xffff ? 3 : 4;
    if (bytes > maxBytes) throw const JsonBoundsException();
  }
  _JsonPreflight(text, maxNodes, maxDepth).check();
  return jsonDecode(text);
}

class _JsonPreflight {
  final String text;
  final int maxNodes, maxDepth;
  int offset = 0, nodes = 0;
  _JsonPreflight(this.text, this.maxNodes, this.maxDepth);
  Never invalid() => throw const FormatException('Invalid JSON structure');
  int get current => offset < text.length ? text.codeUnitAt(offset) : -1;
  void spaces() {
    while (current == 32 || current == 9 || current == 10 || current == 13) {
      offset++;
    }
  }
  bool take(int code) {
    if (current != code) return false;
    offset++;
    return true;
  }
  void check() {
    value(0);
    spaces();
    if (offset != text.length) invalid();
  }
  void string() {
    if (!take(34)) invalid();
    while (offset < text.length) {
      final c = current;
      offset++;
      if (c == 34) return;
      if (c < 32) invalid();
      if (c == 92) {
        final escape = current;
        offset++;
        if (escape == 117) {
          for (var i = 0; i < 4; i++) {
            final h = current;
            if (!(h >= 48 && h <= 57 || h >= 65 && h <= 70 || h >= 97 && h <= 102)) invalid();
            offset++;
          }
        } else if (![34, 92, 47, 98, 102, 110, 114, 116].contains(escape)) {
          invalid();
        }
      }
    }
    invalid();
  }
  void value(int depth) {
    if (++nodes > maxNodes || depth > maxDepth) throw const JsonBoundsException();
    spaces();
    if (take(123)) {
      final keys = <String>{};
      spaces();
      if (take(125)) return;
      while (true) {
        spaces();
        final start = offset;
        string();
        final key = jsonDecode(text.substring(start, offset)) as String;
        if (!keys.add(key)) throw const JsonDuplicateKeyException();
        spaces();
        if (!take(58)) invalid();
        value(depth + 1);
        spaces();
        if (take(125)) return;
        if (!take(44)) invalid();
      }
    }
    if (take(91)) {
      spaces();
      if (take(93)) return;
      while (true) {
        value(depth + 1);
        spaces();
        if (take(93)) return;
        if (!take(44)) invalid();
      }
    }
    if (current == 34) { string(); return; }
    for (final literal in ['true', 'false', 'null']) {
      if (text.startsWith(literal, offset)) { offset += literal.length; return; }
    }
    take(45);
    if (!take(48)) {
      if (current < 49 || current > 57) invalid();
      while (current >= 48 && current <= 57) { offset++; }
    }
    if (take(46)) {
      if (current < 48 || current > 57) invalid();
      while (current >= 48 && current <= 57) { offset++; }
    }
    if (take(101) || take(69)) {
      if (!take(43)) take(45);
      if (current < 48 || current > 57) invalid();
      while (current >= 48 && current <= 57) { offset++; }
    }
  }
}
