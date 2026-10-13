import 'dart:convert';
import 'package:flutter/services.dart';
import 'demo/chart_analysis.dart';

class DirectSettings {
  final bool real;
  final String feed, session;
  final List<String> symbols;
  const DirectSettings({this.real=false,this.feed='iex',this.session='regular',this.symbols=const ['NVDA','AAPL','TSLA']});
  factory DirectSettings.parse(String text){final j=jsonDecode(text) as Map<String,dynamic>;
    return DirectSettings(real:j['real'] as bool,feed:j['feed'] as String,session:j['session'] as String,symbols:(j['symbols'] as List).cast<String>());}
  String encode()=>jsonEncode({'real':real,'feed':feed,'session':session,'symbols':symbols});
}

String directMessage(String code)=>const {
  'KEYS_MISSING':'لا توجد مفاتيح محفوظة. أدخل المفتاح والسر واحفظهما أولًا.',
  'KEYSTORE_UNAVAILABLE':'ملف المفاتيح موجود لكن تعذرت قراءته أو فك تشفيره. أعد إدخال المفاتيح على الهاتف.',
  'KEY_SAVE_FAILED':'لم يتأكد الحفظ والقراءة من المخزن المشفر. لم نعرض نجاحًا؛ أعد المحاولة.',
  'INVALID_KEYS':'المفتاح والسر مطلوبان بصيغة صحيحة دون مسافات أو أحرف غير لاتينية.',
  'SETTINGS_UNAVAILABLE':'تعذرت قراءة إعدادات الاتصال. لم يبدأ اتصال تلقائي؛ أعد حفظ الإعدادات.',
  'SETTINGS_SAVE_FAILED':'تعذر حفظ إعدادات الاتصال. لم يُعتمد التغيير.',
  'INVALID_SETTINGS':'اختر Feed وجلسة صحيحين ومن 1 إلى 10 رموز دون تكرار.',
  'REAL_DATA_OFF':'فعّل Real Market Data ثم اضغط فحص الاتصال. التفعيل وحده لا يبدأ الشبكة.',
  'CONSENT_REQUIRED':'يلزم الضغط على فحص الاتصال للموافقة على قراءة بيانات Alpaca.',
  'FOREGROUND_REQUIRED':'أبقِ صفحة التطبيق في المقدمة ثم أعد فحص الاتصال.',
  'HTTP_401':'HTTP 401: رفض Alpaca المصادقة. تحقق من المفتاح والسر على الهاتف.',
  'HTTP_403':'HTTP 403: لا تسمح الصلاحيات أو اشتراك البيانات بطلب هذا Feed.',
  'HTTP_429':'HTTP 429: تم بلوغ حد الطلبات؛ ننتظر مهلة Alpaca دون تجاوزها.',
  'WS_ERROR_401':'WebSocket 401: لم تكتمل المصادقة قبل الاشتراك.',
  'WS_ERROR_402':'WebSocket 402: رفض Alpaca المفتاح أو السر.',
  'WS_ERROR_403':'WebSocket 403: مصادقة مكررة على الاتصال نفسه؛ ليست HTTP 403.',
  'WS_ERROR_405':'WebSocket 405: عدد الرموز يتجاوز صلاحية الاشتراك.',
  'WS_ERROR_407':'WebSocket 407: تعذر مواكبة تدفق البيانات.',
  'WS_ERROR_409':'WebSocket 409: الاشتراك لا يسمح بالـFeed المختار.',
  'OTHER_APP_CONNECTION_LIMIT':'WebSocket 406: اتصال مستخدم في تطبيق آخر؛ توقفنا دون قطع اتصاله.',
  'CONNECTION_LIMIT':'WebSocket 406: حد الجلسات لدى Alpaca. نغلق مقبس هذا التطبيق وننتظر قبل إعادة محاولة محدودة؛ لا يثبت ذلك وجود تطبيق آخر.',
  'CONNECTION_LIMIT_EXHAUSTED':'تكرر WebSocket 406 بعد 3 محاولات استعادة. توقف الاتصال؛ انتظر المهلة ثم أعد الفحص. لا يمكننا إغلاق جلسة يملكها تطبيق آخر.',
  'PAUSED_BACKGROUND':'توقف مؤقت عند إطفاء الشاشة أو انتقال التطبيق للخلفية دون خدمة المراقبة. تستأنف الجلسة المصرّح بها عند الرجوع.',
  'RESUMING':'جارٍ استئناف الجلسة المصرّح بها بعد العودة للتطبيق…',
  'NETWORK_ERROR':'تعذر الوصول إلى Alpaca. تحقق من الإنترنت وDNS أو VPN؛ ستتم إعادة محاولة محدودة.',
  'DISCONNECTED':'انقطع الاتصال؛ ستتم إعادة محاولة محدودة.',
  'TIMEOUT':'انتهت مهلة طلب البيانات من Alpaca. تحقق من الشبكة ثم أعد الفحص.',
  'AUTH_TIMEOUT':'انتهت مهلة مصادقة WebSocket دون نتيجة ناجحة.',
  'TLS_ERROR':'تعذر التحقق من اتصال HTTPS الآمن. تحقق من وقت الهاتف والشبكة؛ لن نتجاوز التحقق من الشهادة.',
  'INVALID_DATA':'وصل رد غير صالح من مصدر البيانات؛ لا أسعار بديلة أو اصطناعية.',
  'REQUEST_BUDGET':'ننتظر ميزانية الطلبات المحلية قبل المحاولة التالية.',
  'RETRY_EXHAUSTED':'انتهت إعادة المحاولة؛ عالج السبب ثم اضغط فحص الاتصال مجددًا.',
  'CONNECTING':'جارٍ فتح اتصال Alpaca ومصادقة المفاتيح…',
  'AUTHENTICATED_LOADING':'نجحت مصادقة WebSocket؛ جارٍ طلب شموع الأسهم عبر HTTPS…',
  'CONNECTED_DATA':'نجح فحص المصادقة وطلب البيانات. أهلية LIVE تعتمد على حداثة كل سلسلة.',
  'CONNECTED_NO_BARS':'نجحت المصادقة وطلب البيانات، لكن لا توجد شموع ضمن الاختيار والجلسة الحالية.',
  'CONNECTED':'متصل بمصدر Alpaca؛ راجع نتيجة الطلب وحداثة الأسعار.',
  'DISABLED':'الاتصال متوقف. حفظ الإعداد لا يشغله تلقائيًا.',
  'STOPPED':'أُلغي الفحص عند إيقاف الاتصال أو مغادرة الصفحة.',
  'NOT_TESTED':'لم يُجرَ فحص اتصال في هذه الجلسة.',
  'CHANNEL_UNAVAILABLE':'تعذر التواصل مع مكوّن Android. أعد فتح التطبيق؛ لم يُؤكد الاتصال.',
  'BRIDGE_TIMEOUT':'انتهت مهلة استجابة مكوّن Android. لم يُؤكد الاتصال.',
}[code]??(RegExp(r'^(HTTP|WS_ERROR)_\d{3}$').hasMatch(code)?'رفض مصدر البيانات الطلب ($code). لا تُشارك المفاتيح.':'تعذر تنفيذ العملية بأمان؛ أعد المحاولة دون مشاركة المفاتيح.');

class MarketBar {
  final DateTime time;
  final double open, high, low, close, volume;
  const MarketBar(this.time,this.open,this.high,this.low,this.close,this.volume);
  factory MarketBar.parse(Map<String,dynamic> j) {
    final v=[for(final k in ['o','h','l','c','v']) (j[k] as num).toDouble()];
    if(v.any((n)=>!n.isFinite)||v[2]<=0||v[1]<v[0]||v[1]<v[3]||v[2]>v[0]||v[2]>v[3]||v[4]<0) {
      throw const FormatException('Invalid OHLCV');
    }
    final t=DateTime.fromMillisecondsSinceEpoch(j['t'] as int,isUtc:true);
    if(t.millisecondsSinceEpoch%60000!=0) throw const FormatException('Invalid minute');
    return MarketBar(t,v[0],v[1],v[2],v[3],v[4]);
  }
  DemoCandle candle(int index)=>DemoCandle(index,open,high,low,close,volume);
}

class DirectSnapshot {
  final bool connected, enabled;
  final String feed, session, source, reason;
  final DateTime received;
  final Map<String,List<MarketBar>> series;
  final List<Map<String,dynamic>> events;
  final List<String> symbols;
  final String testStatus,testCode;
  final int testAt;
  final String state,lastError;
  final int lastMessageAt,lastBarAt,lastErrorAt,retryAt,connectionsCreated;
  DirectSnapshot({this.connected=false,this.enabled=false,this.feed='iex',this.session='regular',
    this.source='none',this.reason='DISABLED',DateTime? received,this.series=const {},this.events=const [],this.symbols=const [],
    this.testStatus='idle',this.testCode='NOT_TESTED',this.testAt=0,this.state='IDLE',this.lastError='',
    this.lastMessageAt=0,this.lastBarAt=0,this.lastErrorAt=0,this.retryAt=0,this.connectionsCreated=0})
      :received=received??DateTime.fromMillisecondsSinceEpoch(0,isUtc:true);
  factory DirectSnapshot.parse(String text) {
    final j=jsonDecode(text) as Map<String,dynamic>;
    if(!['iex','sip'].contains(j['feed'])||!['regular','extended'].contains(j['session']))throw const FormatException('Unknown feed');
    final series=<String,List<MarketBar>>{};
    for(final entry in (j['bars'] as Map<String,dynamic>).entries) {
      final byTime=<DateTime,MarketBar>{};
      for(final raw in entry.value as List) {final bar=MarketBar.parse(Map<String,dynamic>.from(raw as Map));byTime[bar.time]=bar;}
      series[entry.key]=byTime.values.toList()..sort((a,b)=>a.time.compareTo(b.time));
    }
    return DirectSnapshot(connected:j['connected']==true,enabled:j['enabled']==true,feed:j['feed'] as String,
      session:j['session'] as String,source:j['source'] as String,reason:j['reason'] as String,
      received:DateTime.fromMillisecondsSinceEpoch(j['asOf'] as int,isUtc:true),series:series,
      symbols:(j['symbols'] as List? ?? []).cast<String>(),
      testStatus:j['testStatus'] as String? ?? 'idle',testCode:j['testCode'] as String? ?? 'NOT_TESTED',testAt:j['testAt'] as int? ?? 0,
      state:j['state'] as String? ?? (j['connected']==true?'CONNECTED':'IDLE'),lastError:j['lastError'] as String? ?? '',
      lastMessageAt:j['lastMessageAt'] as int? ?? 0,lastBarAt:j['lastBarAt'] as int? ?? 0,lastErrorAt:j['lastErrorAt'] as int? ?? 0,
      retryAt:j['retryAt'] as int? ?? 0,connectionsCreated:j['connectionsCreated'] as int? ?? 0,
      events:(j['events'] as List).map((e)=>Map<String,dynamic>.from(e as Map)).toList());
  }
  bool live(String symbol,DateTime now) {
    final rows=series[symbol];if(rows==null||rows.isEmpty)return false;
    final age=now.difference(rows.last.time).inMilliseconds,receipt=now.difference(received).inMilliseconds;
    return connected&&enabled&&source=='alpaca'&&age>=60000&&age<=150000&&receipt>=0&&receipt<=8000;
  }
  String label(String symbol,DateTime now)=>source=='mock'?'Mock • اصطناعية':
    live(symbol,now)?'LIVE • Alpaca ${feed.toUpperCase()}':source=='alpaca'?'Alpaca ${feed.toUpperCase()} • تاريخية/قديمة — ليست LIVE':'لا بيانات';
  bool validForDecision(String symbol,DateTime now) {
    final rows=series[symbol]??[];
    if(!live(symbol,now)||rows.length<35)return false;
    for(var i=rows.length-34;i<rows.length;i++) {
      if(rows[i].time.difference(rows[i-1].time).inSeconds!=60)return false;
    }
    return true;
  }
}

class OptionQuote {
  final String contract, feed;
  final DateTime time;
  final int bid,ask,bidSize,askSize;
  const OptionQuote(this.contract,this.feed,this.time,this.bid,this.ask,this.bidSize,this.askSize);
  factory OptionQuote.parse(String text){final j=jsonDecode(text) as Map<String,dynamic>;
    return OptionQuote(j['contract'] as String,j['feed'] as String,DateTime.fromMillisecondsSinceEpoch(j['t'] as int,isUtc:true),
      ((j['bid'] as num)*100).round(),((j['ask'] as num)*100).round(),j['bidSize'] as int,j['askSize'] as int);}
  static final pattern=RegExp(r'^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$');
  String get underlying=>pattern.firstMatch(contract)?.group(1)??'';
  String get direction=>pattern.firstMatch(contract)?.group(5)=='C'?'CALL':'PUT';
  bool valid(DateTime now,{int quantity=1}) {
    final match=pattern.firstMatch(contract);if(match==null)return false;
    final expiry=DateTime.utc(2000+int.parse(match[2]!),int.parse(match[3]!),int.parse(match[4]!));
    final today=DateTime.utc(now.year,now.month,now.day);
    final age=now.difference(time).inMilliseconds;
    return int.parse(match[3]!)==expiry.month&&int.parse(match[4]!)==expiry.day&&int.parse(match[6]!)>0&&
      feed=='opra'&&expiry.compareTo(today)>=0&&age>=0&&age<=30000&&bid>0&&ask>=bid&&
      ask-bid<=ask*.2&&quantity>0&&bidSize>=quantity&&askSize>=quantity;
  }
}

class DirectAlpaca {
  static const channel=MethodChannel('oat/alpaca_data');
  Future<String> keyState() async=>await channel.invokeMethod<String>('keyState')??'unreadable';
  Future<bool> hasKeys() async=>await keyState()=='readable';
  Future<DirectSettings> settings() async=>DirectSettings.parse((await channel.invokeMethod<String>('getSettings'))!);
  Future<void> saveSettings(DirectSettings settings) async {
    if(await channel.invokeMethod<bool>('saveSettings',{'settings':settings.encode()})!=true)throw PlatformException(code:'SETTINGS_SAVE_FAILED');
  }
  Future<void> saveKeys(String id,String secret) async {
    if(await channel.invokeMethod<bool>('saveKeys',{'key':id,'secret':secret})!=true)throw PlatformException(code:'KEY_SAVE_FAILED');
  }
  Future<void> secureScreen(bool enabled) async {await channel.invokeMethod<bool>('secureScreen',{'enabled':enabled});}
  Future<void> start(String feed,String session,List<String> symbols) async {
    if(await channel.invokeMethod<bool>('start',{'confirmed':true})!=true)throw PlatformException(code:'CHANNEL_UNAVAILABLE');
  }
  Future<void> stop() async {await channel.invokeMethod<bool>('stop');}
  Future<DirectSnapshot> snapshot() async=>DirectSnapshot.parse((await channel.invokeMethod<String>('snapshot'))!);
  Future<bool> background() async=>await channel.invokeMethod<bool>('backgroundStatus')??false;
  Future<void> startBackground() async {await channel.invokeMethod<bool>('backgroundStart');}
  Future<OptionQuote?> quote(String contract) async {final text=await channel.invokeMethod<String>('quote',{'contract':contract});return text==null?null:OptionQuote.parse(text);}
}
