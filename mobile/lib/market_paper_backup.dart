import 'dart:convert';
import 'market_paper_validation.dart';
import 'direct_wave_archive.dart';
import 'option_observation_archive.dart';
import 'observed_bar_archive.dart';
import 'observed_option_replay.dart' show observationStamp;

/// Manual, unsigned local ledger portability. No keys, transport settings or
/// execution permission are exported. Validation is not proof of provenance.
class PaperBackup {
  static const format='options-ai-trader-market-paper-backup-v1';
  static const maxBytes=16*1024*1024;
  static Map<String,dynamic> inspect(String text) {
    if(text.length>maxBytes||utf8.encode(text).length>maxBytes)throw const FormatException('Backup too large');
    final envelope=jsonDecode(text);
    if(envelope is! Map<String,dynamic>||envelope.length!=2||envelope['format']!=format||envelope['ledger'] is! Map<String,dynamic>) {
      throw const FormatException('Not a Market Paper backup');
    }
    final book=envelope['ledger'] as Map<String,dynamic>;
    const rootKeys={'version','accounts','journal','journalArchive','experiment','waveArchive','optionArchive','barArchive'};
    if(book.keys.any((k)=>!rootKeys.contains(k)))throw const FormatException('Unknown ledger fields');
    const accountKeys={'id','name','cash','initialCash','enabled','positions','contracts','riskPercent','quantity',
      'stopPercent','takePercent','trailPercent','addEnabled','lastSignal','ledgerPolicy','strategy','watchlist','fees',
      'closedTrades','winningTrades','peakEquity','maxDrawdown','dailyRealized','allocationPercent','dailyLossPercent',
      'maxPositions','maxContracts','holdingMode','maxHoldingDays','partialPercent','scenarioExit',
      'deliveryPositions','settlementCount','settlementRealizedPnl'};
    validatePaper(book);
    final bars=ObservedBarArchive.read(book['barArchive']);
    for(final event in [for(final segment in book['journalArchive'] as List? ?? [])...(segment as List),...(book['journal'] as List)]) {
      final evidence=event['evidence'];
      if(evidence is Map&&evidence.containsKey('barReference')) {
        bars.resolve(event['symbol'] as String,Map<String,dynamic>.from(evidence),observationStamp(event['at']));
      }
    }
    if(book.containsKey('waveArchive'))DirectWaveArchive.read(book['waveArchive']);
    if(book.containsKey('optionArchive')) {
      final ids={for(final a in book['accounts'] as List)a['id']};
      if(OptionObservationArchive.read(book['optionArchive']).observations.any((o)=>!ids.contains(o['account'])))throw const FormatException('Unknown option observation account');
    }
    for(final a in book['accounts'] as List) {
      if((a as Map).keys.any((k)=>!accountKeys.contains(k)))throw const FormatException('Unknown account fields');
    }
    var count=0;
    void check(Object? value,int depth) {
      if(++count>500000||depth>40)throw const FormatException('Backup exceeds structural bounds');
      if(value is Map) {
        for(final e in value.entries) {
          final key='${e.key}'.toLowerCase().replaceAll(RegExp(r'[^a-z]'),'');
          if(const {'apikey','keyid','secret','apisecret','password','token','accesstoken','refreshtoken','authorization','privatekey','baseurl','serverurl'}.contains(key)) {
            throw const FormatException('Credentials or connection settings are prohibited');
          }
          check(e.value,depth+1);
        }
      }else if(value is List){for(final item in value){check(item,depth+1);}}
      else if(value is String&&(value.trimLeft().startsWith('{')||value.trimLeft().startsWith('['))) {
        Object? nested;try{nested=jsonDecode(value);}on FormatException{return;}check(nested,depth+1);
      }
    }
    check(book,0);
    return copyPaper(book);
  }
  static String export(Map<String,dynamic> book) {
    final safe=copyPaper(book);
    for(final a in safe['accounts'] as List){a['enabled']=false;}
    final text=jsonEncode({'format':format,'ledger':safe});inspect(text);return text;
  }
  static Map<String,dynamic> prepare(String text) {
    final book=inspect(text);
    for(final a in book['accounts'] as List){a['enabled']=false;}
    return book;
  }
}
