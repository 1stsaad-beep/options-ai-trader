import 'direct_alpaca.dart';

/// Same versioned conservative US equity-option calendar as the server.
/// Unsupported years fail closed; no product-specific late session or halt claim.
const paperCalendarVersion = 'us-equity-options-2026-2027-v1';
const _holidays = {
  '2026-01-01','2026-01-19','2026-02-16','2026-04-03','2026-05-25','2026-06-19','2026-07-03','2026-09-07','2026-11-26','2026-12-25',
  '2027-01-01','2027-01-18','2027-02-15','2027-03-26','2027-05-31','2027-06-18','2027-07-05','2027-09-06','2027-11-25','2027-12-24',
};
const _early = {'2026-11-27','2026-12-24','2027-11-26'};
String paperDate(DateTime d) => d.toIso8601String().substring(0,10);
DateTime paperNewYork(DateTime instant) {
  final utc=instant.toUtc(),year=instant.toUtc().year;
  int sunday(int month,int nth) => 1+(7-DateTime.utc(year,month,1).weekday)%7+(nth-1)*7;
  final start=DateTime.utc(year,3,sunday(3,2),7),end=DateTime.utc(year,11,sunday(11,1),6);
  return utc.subtract(Duration(hours:!utc.isBefore(start)&&utc.isBefore(end)?4:5));
}
class PaperSession {
  final String status,date;
  final DateTime? closes;
  final bool entry,fill,exitDue;
  const PaperSession(this.status,this.date,this.closes,this.entry,this.fill,this.exitDue);
}
PaperSession paperSession(DateTime instant) {
  final now=instant.toUtc(),local=paperNewYork(now),date=paperDate(local);
  if(![2026,2027].contains(local.year))return PaperSession('UNSUPPORTED_DATE',date,null,false,false,false);
  if(local.weekday>=6||_holidays.contains(date))return PaperSession('NO_SESSION',date,null,false,false,false);
  final offset=now.difference(local),open=DateTime.utc(local.year,local.month,local.day,9,30).add(offset);
  final close=DateTime.utc(local.year,local.month,local.day,_early.contains(date)?13:16).add(offset);
  final cutoff=close.subtract(const Duration(minutes:15));
  final fill=!now.isBefore(open)&&now.isBefore(close),entry=fill&&now.isBefore(cutoff);
  return PaperSession(now.isBefore(open)?'PREOPEN':entry?'OPEN':fill?'EXIT_WINDOW':'CLOSED',date,close,entry,fill,!now.isBefore(cutoff));
}
class PaperExpiry {
  final String status;
  final bool entry,close;
  const PaperExpiry(this.status,this.entry,this.close);
}
PaperExpiry paperExpiry(String contract,DateTime now) {
  final m=OptionQuote.pattern.firstMatch(contract);
  if(m==null)return const PaperExpiry('INVALID_CONTRACT',false,false);
  final nominal=DateTime.utc(2000+int.parse(m[2]!),int.parse(m[3]!),int.parse(m[4]!),12);
  if(nominal.month!=int.parse(m[3]!)||nominal.day!=int.parse(m[4]!))return const PaperExpiry('INVALID_CONTRACT',false,false);
  for(var back=0;back<8;back++) {
    final s=paperSession(nominal.subtract(Duration(days:back)));
    if(s.status=='NO_SESSION')continue;
    if(s.closes==null)return const PaperExpiry('CALENDAR_UNAVAILABLE',false,false);
    if(!now.toUtc().isBefore(s.closes!))return const PaperExpiry('EXPIRY_REVIEW_REQUIRED',false,false);
    final entry=paperDate(paperNewYork(now)).compareTo(s.date)<0;
    return PaperExpiry(entry?'ACTIVE':'CLOSE_ONLY',entry,true);
  }
  return const PaperExpiry('CALENDAR_UNAVAILABLE',false,false);
}
