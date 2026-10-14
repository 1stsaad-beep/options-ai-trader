import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'direct_alpaca.dart';
import 'direct_labs.dart';
import 'market_monitor.dart';
import 'market_paper.dart';
import 'paper_execution.dart';
import 'market_paper_reports.dart';
import 'market_paper_backup.dart';
import 'direct_replay.dart';
import 'direct_decision_view.dart';
import 'paper_settlement_dialog.dart';
import 'market_indicators.dart';
import 'market_geometry.dart';

class DirectAlpacaScreen extends StatefulWidget {
  final DirectAlpaca? api;
  final PaperStore? paperStore;
  final int initialPage;
  const DirectAlpacaScreen({super.key,this.api,this.paperStore,this.initialPage=0});
  @override State<DirectAlpacaScreen> createState()=>_DirectAlpacaScreenState();
}
class _DirectAlpacaScreenState extends State<DirectAlpacaScreen> with WidgetsBindingObserver {
  late final DirectAlpaca api;
  late final MarketPaper paper;
  final keyId=TextEditingController(),secret=TextEditingController(),symbols=TextEditingController(text:'NVDA,AAPL,TSLA');
  final accountName=TextEditingController(),contract=TextEditingController();
  DirectSnapshot snapshot=DirectSnapshot();
  bool hasKeys=false,real=false,working=false,polling=false,background=false,visible=true,ready=false,awaitingTest=false,snapshotKnown=false;
  String keyState='checking';
  String feed='iex',session='regular',selectedSymbol='NVDA',direction='CALL';
  String? selectedAccount,notice;
  Timer? timer,cycle,testDeadline;
  int page=0,connectEpoch=0,refreshEpoch=0;
  List<String> get watch=>symbols.text.toUpperCase().split(',').map((s)=>s.trim()).where((s)=>s.isNotEmpty).toSet().toList();
  @override void initState(){super.initState();WidgetsBinding.instance.addObserver(this);
    api=widget.api??DirectAlpaca();paper=widget.paperStore==null?MarketPaper.device:MarketPaper(widget.paperStore!);
    page=widget.initialPage;
    paper.addListener(changed);
    initialize();timer=Timer.periodic(const Duration(seconds:1),(_){if(visible)refresh();});
    cycle=Timer.periodic(const Duration(seconds:30),(_){if(visible)paperCycle();});
  }
  void changed(){if(mounted)setState((){selectedAccount??=paper.accounts.isEmpty?null:paper.accounts.first['id'] as String;});}
  void message(String value,{bool toast=true}) {
    if(!mounted)return;
    setState(()=>notice=value);
    if(toast){ScaffoldMessenger.of(context).hideCurrentSnackBar();ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text(value)));}
  }
  Future<void> initialize() async {
    unawaited(paper.load().then((_){changed();}));
    await run(()async{
      await api.secureScreen(true);
      keyState=await api.keyState();hasKeys=keyState=='readable';
      final config=await api.settings();
      if(!mounted)return;
      real=config.real;feed=config.feed;session=config.session;symbols.text=config.symbols.join(',');
      selectedSymbol=config.symbols.isEmpty?'NVDA':config.symbols.first;
      await refresh();ready=true;
      if(real&&!snapshot.enabled)notice='Real Market Data محفوظ على ON؛ الاتصال متوقف. اضغط فحص الاتصال للبدء.';
    });
  }
  Future<void> run(Future<void> Function() action) async {
    if(working||!mounted)return;setState(()=>working=true);
    try{await action().timeout(const Duration(seconds:15));}
    on PlatformException catch(e){message(directMessage(e.code));}
    on TimeoutException {connectEpoch++;message(directMessage('BRIDGE_TIMEOUT'));}
    catch(_){message(directMessage('CHANNEL_UNAVAILABLE'));}
    finally{if(mounted)setState(()=>working=false);}
  }
  Future<void> refresh() async {
    if(polling||!mounted)return;polling=true;final epoch=refreshEpoch;
    try{
      final s=await api.snapshot().timeout(const Duration(seconds:8));
      final bg=await api.background().timeout(const Duration(seconds:8));
      if(!mounted||epoch!=refreshEpoch)return;
      setState((){snapshot=s;background=bg;snapshotKnown=true;});
      if(visible&&paper.ready&&!paper.busy&&['alpaca','mock'].contains(s.source)) {
        for(final entry in s.series.entries) {
          if(!mounted||!visible||epoch!=refreshEpoch)break;
          await paper.observeWaves(entry.key,'${s.source=='alpaca'?'alpaca':'fixture'}|${s.feed}|${s.session}',entry.value);
        }
      }
      if(awaitingTest&&['succeeded','failed','cancelled'].contains(s.testStatus)){
        awaitingTest=false;testDeadline?.cancel();message(directMessage(s.testCode));
      }
    }catch(e){
      if(mounted&&epoch==refreshEpoch){setState((){snapshot=DirectSnapshot();snapshotKnown=false;});
        if(awaitingTest){awaitingTest=false;testDeadline?.cancel();
          message(directMessage(e is TimeoutException?'BRIDGE_TIMEOUT':'CHANNEL_UNAVAILABLE'));}
      }
    }finally{polling=false;}
  }
  Future<void> disconnect() async {
    connectEpoch++;refreshEpoch++;awaitingTest=false;testDeadline?.cancel();await api.stop();await paper.pauseAll();await refresh();
  }
  Future<void> persist({bool? enabled,String? selectedFeed,String? selectedSession}) async {
    final config=DirectSettings(real:enabled??real,feed:selectedFeed??feed,session:selectedSession??session,symbols:watch);
    await api.saveSettings(config);
    if(!mounted)return;
    setState((){real=config.real;feed=config.feed;session=config.session;});
  }
  Future<void> connect() async {
    final epoch=++connectEpoch;refreshEpoch++;
    if(!ready){message('لم تكتمل قراءة الإعدادات؛ اضغط إعادة قراءة حالة الحفظ أولًا.');return;}
    keyState=await api.keyState();hasKeys=keyState=='readable';
    if(!hasKeys){message(directMessage(keyState=='missing'?'KEYS_MISSING':'KEYSTORE_UNAVAILABLE'));return;}
    if(!real){message(directMessage('REAL_DATA_OFF'));return;}
    await refresh();
    if(snapshotKnown&&snapshot.enabled){message(directMessage(snapshot.reason));return;}
    if(watch.isEmpty||watch.length>10||watch.any((s)=>!RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(s))){message(directMessage('INVALID_SETTINGS'));return;}
    message(directMessage('CONNECTING'));
    await persist();await paper.pauseAll();
    if(!mounted||!visible||epoch!=connectEpoch)return;
    // Only this explicit button (or an already opted-in monitor button) can start transport.
    try {await api.start(feed,session,watch).timeout(const Duration(seconds:10));}
    catch(_){unawaited(api.stop().catchError((_){ }));rethrow;}
    if(!mounted||!visible||epoch!=connectEpoch)return;
    refreshEpoch++;
    selectedSymbol=watch.contains(selectedSymbol)?selectedSymbol:watch.first;
    awaitingTest=true;testDeadline?.cancel();
    testDeadline=Timer(const Duration(seconds:35),(){
      if(!mounted||!awaitingTest)return;
      awaitingTest=false;unawaited(api.stop().catchError((_){ }));message(directMessage('TIMEOUT'));
    });
    await refresh();
  }
  Future<void> paperCycle({bool forceClose=false,String? closeAccount,String? closeSymbol}) async {
    if(!visible||!snapshot.enabled||paper.busy)return;
    final quoteCache=<String,OptionQuote?>{};
    Future<OptionQuote?> observedQuote(String contract) async {
      if(!quoteCache.containsKey(contract))quoteCache[contract]=await api.quote(contract);
      return quoteCache[contract];
    }
    for(final a in paper.accounts) {
      if(!forceClose&&a['enabled']!=true)continue;
      if(forceClose&&a['id']!=closeAccount)continue;
      final targets=forceClose?[closeSymbol!]:{...(a['watchlist'] as List? ?? watch).cast<String>(),...(a['positions'] as Map).keys.cast<String>()}.toList();
      for(final symbol in targets) {
        if(!visible||!mounted)return;
        final rows=snapshot.series[symbol]??[];
        MarketSignal readSignal(){
          try{return MarketSignal.analyze(snapshot.series[symbol]??[],strategy:a['strategy'] as String? ?? 'confluence');}
          catch(_){return const MarketSignal('WAIT',false,reason:'OPTIONAL_ANALYSIS_UNAVAILABLE');}
        }
        final signal=readSignal();
        PaperRow research;try{
          final source='${snapshot.source=='alpaca'?'alpaca':'fixture'}|${snapshot.feed}|${snapshot.session}';
          final archive=paper.waveArchive,epoch=archive?.latest(symbol,source);
          final matches=rows.isNotEmpty&&epoch!=null&&(epoch['times'] as List).last==rows.last.time.millisecondsSinceEpoch;
          research=directResearchSnapshot(rows,archivedWaves:matches?archive?.view(symbol,source):null,
            archiveOrigin:matches?{'sequence':epoch['sequence'],'source':source,'boundary':epoch['boundary'],
              'firstAt':DateTime.fromMillisecondsSinceEpoch((epoch['times'] as List).first as int,isUtc:true).toIso8601String(),
              'observations':(epoch['times'] as List).length}:null);
        }
        catch(_){research={'version':'direct-research-v5','indicatorContract':marketIndicatorContract,'geometryContract':marketGeometryContract,'divergenceContract':marketDivergenceContract,'status':'OPTIONAL_RESEARCH_UNAVAILABLE','executable':false};}
        await paper.evaluate(id:a['id'] as String,symbol:symbol,signal:signal.direction,confirmedReverse:signal.confirmedReverse,
          dataValid:()=>visible&&snapshot.validForDecision(symbol,DateTime.now()),
          observation:rows.isEmpty?'none':rows.last.time.toIso8601String(),quotes:observedQuote,forceClose:forceClose,
          currentSignal:()=>readSignal().direction,currentReverse:()=>readSignal().confirmedReverse,
          scenarioInvalidated:(){final p=paper.account(a['id'] as String)['positions'][symbol];final price=snapshot.series[symbol]?.lastOrNull?.close;
            if(p==null||p['scenarioLevel'] is! num||price==null)return false;
            return p['direction']=='CALL'?price<p['scenarioLevel']:price>p['scenarioLevel'];},evidence:{'source':snapshot.source=='alpaca'?'alpaca':'fixture',
            'feed':snapshot.feed,'session':snapshot.session,'rule':signal.reason,'research':research,
            'scenarioLevel':research['indicators']?[signal.direction=='CALL'?'support':'resistance'],'recordedAt':DateTime.now().toUtc().toIso8601String(),
            ...directBarEvidence(rows)});
      }
    }
    if(!forceClose&&visible&&mounted&&['alpaca','mock'].contains(snapshot.source)) {
      await paper.observeRecentOptions(source:snapshot.source=='alpaca'?'alpaca':'fixture',quotes:observedQuote,
        active:()=>visible&&mounted&&snapshot.enabled);
      // Owned option protection above takes priority over optional share marks.
      if(snapshot.source=='alpaca') {
        await paper.observeDeliveries(source:'alpaca',quotes:api.stockQuote,
          active:()=>visible&&mounted&&snapshot.enabled&&snapshot.source=='alpaca');
      }
    }
  }
  @override void didChangeAppLifecycleState(AppLifecycleState state){visible=state==AppLifecycleState.resumed;
    if(!visible){connectEpoch++;unawaited(paper.pauseAll());}else{refresh();}}
  @override void dispose(){connectEpoch++;refreshEpoch++;timer?.cancel();cycle?.cancel();testDeadline?.cancel();WidgetsBinding.instance.removeObserver(this);
    paper.removeListener(changed);unawaited(paper.pauseAll());
    unawaited(api.secureScreen(false).catchError((_){ }));
    // Page disposal releases only UI resources. Native app lifecycle owns the shared connection.
    for(final c in [keyId,secret,symbols,accountName,contract]){c.clear();c.dispose();}
    super.dispose();
  }
  String reason(String code)=>directMessage(code);
  String stamp(int value)=>value==0?'لم يصل بعد':DateTime.fromMillisecondsSinceEpoch(value,isUtc:true).toIso8601String();
  String get connectionLabel=>!snapshotKnown?'جارٍ قراءة حالة الاتصال الأصلية':snapshot.connected?'Connected':
    snapshot.state=='RETRY_WAIT'?'Reconnecting':snapshot.state=='PAUSED_BACKGROUND'?'Paused':
    ['CONNECTING','AUTHENTICATING'].contains(snapshot.state)?'Connecting':'Disconnected';
  @override Widget build(BuildContext context)=>Scaffold(
    appBar:AppBar(title:const Text('Alpaca مباشر • Market Data'),actions:[IconButton(tooltip:'إيقاف الاتصال',onPressed:()=>run(disconnect),icon:const Icon(Icons.stop_circle_outlined))]),
    bottomNavigationBar:NavigationBar(selectedIndex:page,onDestinationSelected:(i)=>setState(()=>page=i),destinations:const [
      NavigationDestination(icon:Icon(Icons.settings),label:'الاتصال'),NavigationDestination(icon:Icon(Icons.candlestick_chart),label:'السوق والمختبرات'),
      NavigationDestination(icon:Icon(Icons.account_balance_wallet),label:'Market Paper'),NavigationDestination(icon:Icon(Icons.notifications),label:'الأحداث')]),
    body:SafeArea(child:ListView(padding:const EdgeInsets.all(16),children:[
      const Text('وضع الهاتف مستقل عن الخادم وDemo Synthetic • لا Live Trading أو IBKR'),
      Text('$connectionLabel • ${snapshotKnown?reason(snapshot.reason):"الحالة غير مؤكدة؛ لا نستنتج انقطاع الشبكة من غياب الواجهة"}',key:const Key('direct-status')),
      Text('آخر رسالة WebSocket UTC: ${stamp(snapshot.lastMessageAt)} • آخر استلام OHLCV: ${stamp(snapshot.lastBarAt)}',key:const Key('direct-updated')),
      if(snapshot.lastError.isNotEmpty)Text('آخر خطأ: ${reason(snapshot.lastError)} • ${stamp(snapshot.lastErrorAt)}',key:const Key('direct-last-error')),
      if(snapshot.retryAt>DateTime.now().millisecondsSinceEpoch)Text('إعادة المحاولة بعد UTC: ${stamp(snapshot.retryAt)}'),
      if(notice!=null)Text(notice!,key:const Key('direct-notice')),
      if(working)const LinearProgressIndicator(),
      if(page==0)...settings(),
      if(page==1)...market(),
      if(page==2)...paperWidgets(),
      if(page==3)...[
        const Text('آخر 100 حدث اتصال في الذاكرة؛ سجل قرارات Market Paper محفوظ منفصلًا.'),
        for(final e in snapshot.events.reversed)ListTile(title:Text(reason(e['code'] as String)),subtitle:Text(DateTime.fromMillisecondsSinceEpoch(e['at'] as int,isUtc:true).toIso8601String())),
      ],
    ])));
  List<Widget> settings()=>[
    const SizedBox(height:12),
    const Text('تُشفّر المفاتيح بمفتاح Android Keystore. الجهاز المخترق أو تطبيق مُعدّل قد يستخرجها أثناء الاستخدام؛ ليست حماية مطلقة. تقييد التطبيق للبيانات لا يغيّر صلاحيات المفتاح لدى Alpaca. لا تشارك المفاتيح في Work، ولا تستخدم إعدادات التطبيق الآخر تلقائيًا.'),
    Text(switch(keyState){
      'readable'=>'المفاتيح محفوظة ويمكن فك تشفيرها محليًا. صلاحيتها لدى Alpaca تُفحص بزر الاتصال؛ السر لا يُعرض.',
      'missing'=>'لا توجد مفاتيح محفوظة على هذا الهاتف.',
      'unreadable'=>'تعذرت قراءة المفاتيح المشفرة؛ أعد إدخالها دون مسح بيانات التطبيق.',
      _=>'جارٍ التحقق من حالة الحفظ…',
    },key:const Key('alpaca-key-state')),
    OutlinedButton(key:const Key('alpaca-reload'),onPressed:working?null:initialize,child:const Text('إعادة قراءة حالة الحفظ والإعدادات')),
    TextField(key:const Key('alpaca-key'),controller:keyId,enableSuggestions:false,autocorrect:false,enableIMEPersonalizedLearning:false,
      decoration:const InputDecoration(labelText:'API Key ID',helperText:'اترك الحقول فارغة لاستخدام القيم المحفوظة')),
    TextField(key:const Key('alpaca-secret'),controller:secret,obscureText:true,enableSuggestions:false,autocorrect:false,enableIMEPersonalizedLearning:false,
      decoration:const InputDecoration(labelText:'API Secret — لا يمكن عرضه بعد الحفظ')),
    FilledButton(key:const Key('alpaca-save'),onPressed:working?null:()=>run(()async{
      await disconnect();await api.saveKeys(keyId.text.trim(),secret.text.trim());
      keyState=await api.keyState();hasKeys=keyState=='readable';
      if(!hasKeys)throw PlatformException(code:'KEY_SAVE_FAILED');
      if(!mounted)return;
      keyId.clear();secret.clear();
      message('تم الحفظ والتحقق من القراءة المشفرة. إفراغ الحقول لحماية السر؛ لم يبدأ اتصال Alpaca.');
    }),child:const Text('حفظ المفاتيح المشفرة')),
    DropdownButtonFormField<String>(key:ValueKey('feed-$feed'),initialValue:feed,decoration:const InputDecoration(labelText:'Feed'),items:const [
      DropdownMenuItem(value:'iex',child:Text('IEX — تداولات بورصة واحدة')),DropdownMenuItem(value:'sip',child:Text('SIP — يتطلب صلاحية الاشتراك'))],
      onChanged:working?null:(v){if(v!=null)run(()async{await disconnect();await persist(selectedFeed:v);});}),
    DropdownButtonFormField<String>(key:ValueKey('session-$session'),initialValue:session,decoration:const InputDecoration(labelText:'Session — توقيت New York'),items:const [
      DropdownMenuItem(value:'regular',child:Text('Regular 09:30–16:00')),DropdownMenuItem(value:'extended',child:Text('Extended 04:00–20:00 ضمن تغطية Feed'))],
      onChanged:working?null:(v){if(v!=null)run(()async{await disconnect();await persist(selectedSession:v);});}),
    const Text('مرشح الجلسة يتبع التوقيت الصيفي. العطلات والإغلاق المبكر وغياب التداول لا يولّدون شموعًا؛ الأسعار القديمة لا تصبح LIVE.'),
    TextField(controller:symbols,enabled:!snapshot.enabled,decoration:const InputDecoration(labelText:'الأسهم — حتى 10 رموز',hintText:'NVDA,AAPL,TSLA')),
    SwitchListTile(key:const Key('alpaca-real'),title:const Text('Real Market Data'),subtitle:const Text('التفعيل يجهّز الاتصال؛ زر Test Connection يبدأ الاتصال بـAlpaca فقط.'),value:real,
      onChanged:working?null:(v)=>run(()async{if(!v)await disconnect();await persist(enabled:v);message(v?'حُفظ Real Market Data على ON. اضغط فحص الاتصال؛ لم يبدأ اتصال تلقائي.':'حُفظ Real Market Data على OFF وتوقف الاتصال.');})),
    FilledButton(key:const Key('alpaca-test'),onPressed:working||awaitingTest?null:()=>run(connect),child:Text(awaitingTest?'جارٍ الفحص…':'فحص الاتصال • Test Connection')),
    if(!hasKeys)Text(directMessage(keyState=='unreadable'?'KEYSTORE_UNAVAILABLE':'KEYS_MISSING')),
    if(!real)Text(directMessage('REAL_DATA_OFF')),
    if(notice!=null)Text(notice!,key:const Key('alpaca-test-feedback')),
    Text('نتيجة آخر محاولة: ${directMessage(snapshot.testCode)}',key:const Key('alpaca-test-result')),
    if(snapshot.testAt>0)Text('وقت النتيجة UTC: ${DateTime.fromMillisecondsSinceEpoch(snapshot.testAt,isUtc:true).toIso8601String()}'),
    Text('الاتصال الحالي: $connectionLabel • ${directMessage(snapshot.reason)}'),
    FilledButton.tonal(key:const Key('alpaca-open-chart'),onPressed:()=>setState(()=>page=1),child:const Text('عرض شارت Alpaca — البيانات الفعلية فقط')),
    const Text('الجلسة مشتركة داخل التطبيق وتبقى عند مغادرة هذه الصفحة. لا تُفتح جلسة إضافية عند العودة. 406 يعني بلوغ حد الجلسات، وليس دليلًا على تطبيق آخر؛ نغلق جلساتنا فقط وننتظر 15 ثم 30 ثم 60 ثانية، وبعد تكراره نتوقف. إعادة الفحص لا تتجاوز المهلة.'),
    const Divider(),
    Text('مراقبة الخلفية: ${background?'تعمل مؤقتًا':'متوقفة'}'),
    const Text('خدمة اختيارية لمدة ≤30 دقيقة للأسعار وRSI/MACD مع إشعار دائم. بدونها تتوقف الجلسة عند إطفاء الشاشة أو مغادرة التطبيق وتستأنف عند الرجوع ضمن العملية نفسها. قد يقيّدها Android والبطارية؛ لا تعمل عند إطفاء الهاتف ولا تعيد تشغيل نفسها. Market Paper يتوقف خارج التطبيق؛ لا حماية مراكز مضمونة في الخلفية.'),
    OutlinedButton(onPressed:working||!snapshot.connected?null:()=>run(()async{
      final allowed=await MarketMonitor.channel.invokeMethod<bool>('permission')??false;
      if(!allowed){notice='اسمح بالإشعارات من إعدادات Android أولًا.';return;}
      await Future<void>.delayed(const Duration(milliseconds:250));
      if(!mounted)return;
      if(!(await api.snapshot()).enabled)await api.start(feed,session,watch);
      await api.startBackground();await refresh();
    }),child:const Text('بدء مراقبة Android التجريبية')),
  ];
  List<Widget> market()=>[
    const Text('الأسعار أدناه إغلاق آخر شمعة دقيقة مكتملة، وليست آخر صفقة tick.'),
    for(final s in watch) ListTile(title:Text('$s • ${snapshot.series[s]?.lastOrNull?.close.toStringAsFixed(2)??"—"} USD'),
      subtitle:Text('${snapshot.label(s,DateTime.now())} • ${snapshot.series[s]?.lastOrNull?.time.toIso8601String()??"لا تحديث"}'),
      onTap:()=>setState(()=>selectedSymbol=s)),
    DropdownButtonFormField<String>(key:ValueKey('market-symbol-$selectedSymbol'),initialValue:selectedSymbol,decoration:const InputDecoration(labelText:'السهم'),
      items:{selectedSymbol,...watch,...snapshot.series.keys,
        for(final a in paper.accounts)...(a['positions'] as Map).keys.cast<String>()}.map((s)=>DropdownMenuItem(value:s,child:Text(s))).toList(),
      onChanged:(s){if(s!=null)setState(()=>selectedSymbol=s);}),
    if(paper.waveArchiveError!=null)Text(paper.waveArchiveError!),
    OutlinedButton(onPressed:paper.busy?null:()async {
      final archive=paper.waveArchive;if(archive==null){message('أرشيف الموجات غير متحقق.');return;}
      final epochs=archive.epochs(selectedSymbol);
      await Clipboard.setData(ClipboardData(text:const JsonEncoder.withIndent('  ').convert({'symbol':selectedSymbol,'epochs':epochs,
        'policy':'Original observation/capture boundaries; no broker execution evidence'})));
      message('نُسخ أرشيف ${epochs.length} مقطع محفوظ مع المصدر وأوقات الرصد والإلغاء.');
    },child:const Text('نسخ أرشيف الموجات ومقاطع المصدر')),
    DirectLabs(rows:snapshot.series[selectedSymbol]??[],symbol:selectedSymbol,source:snapshot.label(selectedSymbol,DateTime.now()),
      waveEpoch:paper.waveArchive?.latest(selectedSymbol,'${snapshot.source=='alpaca'?'alpaca':'fixture'}|${snapshot.feed}|${snapshot.session}'),
      decisions:paper.journal.where((e)=>e['account']==selectedAccount).toList()),
  ];
  Future<void> restorePaper() async {
    final input=TextEditingController();String? validation;
    try {
      final accepted=await showDialog<String>(context:context,builder:(context)=>StatefulBuilder(builder:(context,setDialog)=>AlertDialog(
        title:const Text('استعادة دفتر Market Paper إلى دفتر فارغ'),
        content:SizedBox(width:520,child:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,children:[
          const Text('الصق نسخة الدفتر فقط. لن تُحذف حسابات قائمة. لا مفاتيح أو إعدادات اتصال في النسخة؛ تبدأ الحسابات متوقفة. النسخة غير موقعة ولا تثبت صحة التاريخ.'),
          TextField(key:const Key('paper-backup-input'),controller:input,maxLines:6,enableSuggestions:false,autocorrect:false),
          if(validation!=null)Text(validation!),
        ]))),actions:[TextButton(onPressed:()=>Navigator.pop(context),child:const Text('إلغاء')),
          FilledButton(onPressed:(){try{final book=PaperBackup.inspect(input.text);if((book['accounts'] as List).isEmpty)throw const FormatException();Navigator.pop(context,input.text);}
            catch(_){setDialog(()=>validation='نسخة غير صالحة أو تحتوي حقولًا غير مسموحة؛ لم تتغير البيانات.');}},child:const Text('التحقق والاستعادة'))],
      )));
      if(accepted!=null){try{await paper.restoreBackup(accepted);message('استُعيد الدفتر وتحققت قراءة الحفظ؛ كل الحسابات متوقفة.');}
        catch(_){message('لم تُعتمد الاستعادة؛ قد يكون الدفتر غير فارغ أو الحفظ غير مؤكد. لم تُحذف البيانات.');}}
    }finally{input.dispose();}
  }
  List<Widget> paperWidgets(){
    final a=selectedAccount==null?null:paper.account(selectedAccount!);
    final report=a==null?null:paper.performance(selectedAccount!);
    String money(Object? cents)=>cents is num?'${(cents/100).toStringAsFixed(2)} USD':'غير متاح — تنقص بيانات موثقة';
    return [
      const Text('Market Paper • أموال افتراضية مستقلة • OPRA مؤهل فقط. النموذج المحافظ: Ask + سنت للشراء وBid − سنت للإغلاق؛ رسوم مفترضة 0.70 USD للعقد لكل جهة، وحد أقصى 25% من أصغر حجم معروض. لا يحاكي موضعًا حقيقيًا في طابور السوق أو يضمن التنفيذ.'),
      const Text('بدون OPRA حديث وصالح: إشارات فقط، لا تعبئة Call/Put. IEX/SIP للأسهم لا يمنحان بيانات الخيارات. لا استخدام للأسعار الإرشادية indicative.'),
      const Text('معامل العقد القياسي 100 فقط. لا ممارسة أو تخصيص تلقائي؛ بعد الانتهاء يبقى التعرض للمراجعة دون تسوية مختلقة. التعبئات ضمن جلسات الخيارات المحافظة 2026–2027 فقط، مع منع دخول يوم الانتهاء وإغلاق Intraday قبل نهاية الجلسة بـ15 دقيقة.'),
      const Text('يمكن للحساب المتوقف تسجيل إيصال ورقي يدوي للممارسة أو الانتهاء أو بيع أسهم التسليم. هذه الإيصالات لا تُحسب تنفيذًا سوقيًا موثقًا أو رصد OPRA.'),
      if(paper.error!=null)Text(paper.error!),
      if(paper.waveArchiveError!=null)Text(paper.waveArchiveError!),
      FilledButton(key:const Key('paper-experiment'),onPressed:paper.busy||!paper.ready?null:()=>paper.createComparisonExperiment(executionPolicy:conservativeExecution),
        child:const Text('تجهيز 4 حسابات مستقلة × 1,000 USD')),
      const Text('اتجاه، اختراق، تراجع، دايفرجنس. الحسابات تبدأ متوقفة؛ لا نتائج قبل الرصد، ولا تُحسب Fixtures جلسات سوق فعلية.'),
      OutlinedButton(key:const Key('paper-comparison'),onPressed:!paper.ready?null:()async{
        await Clipboard.setData(ClipboardData(text:const JsonEncoder.withIndent('  ').convert(paper.comparison())));
        message('نُسخ تقرير المقارنة وأسباب القرارات الأصلية. الجلسات غير المرصودة موسومة NOT_RUN.');
      },child:const Text('نسخ تقرير الحسابات وثلاث جلسات بصيغة JSON')),
      Wrap(spacing:8,children:[
        OutlinedButton(key:const Key('paper-backup-export'),onPressed:paper.busy||!paper.ready?null:()async{
          try{await Clipboard.setData(ClipboardData(text:paper.exportBackup()));message('نُسخت نسخة دفتر Market Paper دون مفاتيح. احفظها في مكان خاص؛ تحتوي تاريخ الحسابات الافتراضية.');}
          catch(_){message('تعذر تصدير نسخة متحققة؛ لم تتغير البيانات.');}
        },child:const Text('نسخ احتياطي للدفتر')),
        OutlinedButton(key:const Key('paper-backup-restore'),onPressed:paper.busy||!paper.ready||paper.accounts.isNotEmpty?null:restorePaper,
          child:const Text('استعادة إلى دفتر فارغ')),
      ]),
      TextField(controller:accountName,decoration:const InputDecoration(labelText:'اسم حساب Market Paper جديد')),
      OutlinedButton(onPressed:paper.busy||!paper.ready?null:()=>paper.add(accountName.text,executionPolicy:conservativeExecution),child:const Text('إنشاء حساب افتراضي 10,000 USD')),
      if(a!=null)...[
        DropdownButtonFormField<String>(isExpanded:true,initialValue:selectedAccount,items:paper.accounts.map((x)=>DropdownMenuItem(value:x['id'] as String,child:Text(x['name'] as String))).toList(),
          onChanged:(v)=>setState(()=>selectedAccount=v),decoration:const InputDecoration(labelText:'الحساب المستقل')),
        DropdownButtonFormField<String>(key:ValueKey('execution-policy-${a['id']}-${a['executionPolicy']}'),
          initialValue:a['executionPolicy'] as String? ?? legacyExecution,isExpanded:true,
          decoration:const InputDecoration(labelText:'نموذج التعبئة اللاحقة — التغيير للحساب المتوقف'),
          items:const [DropdownMenuItem(value:conservativeExecution,child:Text('محافظ: انزلاق ورسوم وحد سيولة')),
            DropdownMenuItem(value:legacyExecution,child:Text('سابق: سعر العرض وعمولة 0.65 USD'))],
          onChanged:paper.busy||a['enabled']==true?null:(v)=>paper.configure(a['id'] as String,{'executionPolicy':v})),
        Text('النقد الافتراضي: ${(a['cash']/100).toStringAsFixed(2)} USD'),
        Text('P&L محقق: ${money(report!['realizedPnlCents'])} • غير محقق: ${money(report['unrealizedPnlCents'])}'),
        Text('الرسوم: ${money(report['totalFeesCents'])} • الصفقات المغلقة: ${report['closedTrades']??"غير متاح"} • النجاح: ${report['winRatePercent']??"—"}%'),
        if((report['settlementEvents'] as int)>0)Text('إيصالات التسوية: ${report['settlementEvents']} • الربح المحقق منها: ${money(report['settlementRealizedPnlCents'])}. معدل نجاح مختلط للتحويلات والصفقات غير محسوب.'),
        Text('العائد: ${report['returnPercent']??"غير متاح"}% • التراجع المرصود: ${money(report['sampledMaxDrawdownCents'])}؛ لا تقدير خلال انقطاع الأسعار.'),
        DropdownButtonFormField<String>(isExpanded:true,key:ValueKey('paper-strategy-$selectedAccount-${a['strategy']}'),
          initialValue:a['strategy'] as String? ?? 'confluence',decoration:const InputDecoration(labelText:'استراتيجية هذا الحساب'),
          items:paperStrategyLabels.entries.map((e)=>DropdownMenuItem(value:e.key,child:Text(e.value))).toList(),
          onChanged:paper.busy?null:(v){if(v!=null)paper.configure(selectedAccount!,{'strategy':v});}),
        TextFormField(key:ValueKey('paper-watchlist-$selectedAccount'),initialValue:(a['watchlist'] as List? ?? watch).join(','),
          decoration:const InputDecoration(labelText:'قائمة هذا الحساب — Enter للحفظ',helperText:'يجب أن تكون الرموز مشمولة باتصال البيانات للحصول على أسعار.'),
          onFieldSubmitted:(v)=>run(()async{await paper.configure(selectedAccount!,{'watchlist':v.toUpperCase().split(',').map((s)=>s.trim()).toList()});})),
        SwitchListTile(title:const Text('تشغيل تقييم هذا الحساب'),subtitle:const Text('دورة كل 30 ثانية داخل التطبيق. يتوقف عند مغادرته أو تغيير الاتصال.'),value:a['enabled']==true,
          onChanged:snapshot.connected?(v)=>paper.configure(selectedAccount!,{'enabled':v}):null),
        Text('المخاطرة القصوى للمركز ${a['riskPercent']}% • العقود ${a['quantity']} • SL ${a['stopPercent']}% • TP ${a['takePercent']}% • Trailing ${a['trailPercent']}%'),
        for(final entry in {'riskPercent':'نسبة حد التكلفة','quantity':'عدد العقود','stopPercent':'وقف الخسارة %','takePercent':'جني الربح %','trailPercent':'وقف متحرك %'}.entries)
          Row(children:[Expanded(child:Text(entry.value)),IconButton(onPressed:paper.busy?null:()=>paper.configure(selectedAccount!,{entry.key:((a[entry.key] as int)-1).clamp(1,entry.key=='quantity'?10:50)}),icon:const Icon(Icons.remove)),
            Text('${a[entry.key]}'),IconButton(onPressed:paper.busy?null:()=>paper.configure(selectedAccount!,{entry.key:((a[entry.key] as int)+1).clamp(1,entry.key=='quantity'?10:50)}),icon:const Icon(Icons.add))]),
        for(final entry in {'allocationPercent':30,'dailyLossPercent':3,'maxPositions':4,'maxContracts':10}.entries)
          Row(children:[Expanded(child:Text({'allocationPercent':'تخصيص رأس المال %','dailyLossPercent':'خسارة اليوم %','maxPositions':'عدد المراكز الأقصى','maxContracts':'إجمالي العقود الأقصى'}[entry.key]!)),
            IconButton(onPressed:paper.busy?null:()=>paper.configure(selectedAccount!,{entry.key:((a[entry.key] as int? ?? entry.value)-1).clamp(entry.key.endsWith('Percent')?0:1,100)}),icon:const Icon(Icons.remove)),
            Text('${a[entry.key]??entry.value}'),
            IconButton(onPressed:paper.busy?null:()=>paper.configure(selectedAccount!,{entry.key:((a[entry.key] as int? ?? entry.value)+1).clamp(entry.key.endsWith('Percent')?0:1,100)}),icon:const Icon(Icons.add))]),
        DropdownButtonFormField<String>(isExpanded:true,key:ValueKey('paper-holding-$selectedAccount-${a['holdingMode']}'),
          initialValue:a['holdingMode'] as String? ?? 'swing',decoration:const InputDecoration(labelText:'سياسة الاحتفاظ'),
          items:const [DropdownMenuItem(value:'intraday',child:Text('Intraday — إغلاق قبل نهاية الجلسة')),DropdownMenuItem(value:'swing',child:Text('Swing — مدة محدودة وحماية انتهاء'))],
          onChanged:paper.busy?null:(v){if(v!=null)paper.configure(selectedAccount!,{'holdingMode':v});}),
        for(final entry in {'partialPercent':20,'maxHoldingDays':3}.entries)
          Row(children:[Expanded(child:Text(entry.key=='partialPercent'?'ربح إغلاق نصف الكمية % (0 معطّل)':'مدة الاحتفاظ القصوى بالأيام')),
            IconButton(onPressed:paper.busy?null:()=>paper.configure(selectedAccount!,{entry.key:((a[entry.key] as int? ?? entry.value)-1).clamp(entry.key=='partialPercent'?0:1,entry.key=='partialPercent'?100:30)}),icon:const Icon(Icons.remove)),
            Text('${a[entry.key]??entry.value}'),
            IconButton(onPressed:paper.busy?null:()=>paper.configure(selectedAccount!,{entry.key:((a[entry.key] as int? ?? entry.value)+1).clamp(entry.key=='partialPercent'?0:1,entry.key=='partialPercent'?100:30)}),icon:const Icon(Icons.add))]),
        SwitchListTile(title:const Text('خروج عند كسر مستوى إلغاء السيناريو الأصلي'),subtitle:const Text('يتطلب سعر سهم حديثًا وكسر الدعم/المقاومة المحفوظة عند الدخول؛ فشل التحليل وحده لا يشغله.'),
          value:a['scenarioExit']==true,onChanged:paper.busy?null:(v)=>paper.configure(selectedAccount!,{'scenarioExit':v})),
        SwitchListTile(title:const Text('تعزيز واحد بعد ربح 10% ضمن حد المخاطرة'),value:a['addEnabled']==true,onChanged:paper.busy?null:(v)=>paper.configure(selectedAccount!,{'addEnabled':v})),
        DropdownButtonFormField<String>(initialValue:direction,items:const [DropdownMenuItem(value:'CALL',child:Text('Call')),DropdownMenuItem(value:'PUT',child:Text('Put'))],onChanged:(v){if(v!=null)setState(()=>direction=v);}),
        TextField(controller:contract,decoration:InputDecoration(labelText:'عقد OCC لـ $selectedSymbol $direction',helperText:'اختر السهم من صفحة السوق؛ أدخل عقدًا تعرفه دون جلب حساب التداول')),
        OutlinedButton(onPressed:paper.busy?null:()async{
          final value=contract.text.trim().toUpperCase(),match=OptionQuote.pattern.firstMatch(contract.text.trim().toUpperCase());
          if(match==null||match[1]!=selectedSymbol||match[5]!=(direction=='CALL'?'C':'P')){setState(()=>notice='العقد لا يطابق السهم والاتجاه.');return;}
          await paper.configure(selectedAccount!,{'contracts':{...Map<String,dynamic>.from(a['contracts'] as Map),'$selectedSymbol:$direction':value}});contract.clear();
        },child:const Text('تعيين عقد للمحاكاة المشروطة بـOPRA')),
        Text('العقود المحددة: ${a['contracts']}'),
        OutlinedButton(onPressed:paper.busy?null:()=>paperCycle(),child:const Text('تقييم الحسابات المفعلة الآن')),
        for(final p in (a['positions'] as Map).entries)...[
          ListTile(key:ValueKey('paper-position-${a['id']}-${p.key}'),
            title:Text('${p.key} ${p.value['direction']} × ${p.value['quantity']}'),
            subtitle:Text('${p.value['contract']} • تكلفة ${(p.value['cost']/100).toStringAsFixed(2)} USD${p.value['closeIntent']==null?'':' • إغلاق غير محسوم: ${p.value['closeIntent']['remaining']} (${p.value['closeIntent']['reason']})'}'),
            onTap:()=>setState((){selectedSymbol=p.key as String;page=1;})),
          OutlinedButton(key:ValueKey('paper-close-${a['id']}-${p.key}'),
            onPressed:paper.busy||!paper.ready||!snapshot.enabled?null:
              ()=>paperCycle(forceClose:true,closeAccount:a['id'] as String,closeSymbol:p.key as String),
            child:Text('إغلاق ${p.key} افتراضيًا بعرض صالح')),
          OutlinedButton(key:ValueKey('paper-settle-${a['id']}-${p.key}'),
            onPressed:paper.busy||!paper.ready||a['enabled']==true?null:()=>showDialog<bool>(context:context,
              builder:(_)=>PaperSettlementDialog(paper:paper,accountId:a['id'] as String,contract:p.value['contract'] as String)),
            child:const Text('تسجيل إيصال ممارسة / انتهاء ورقي')),
        ],
        if((a['deliveryPositions'] as Map? ?? {}).isNotEmpty)const Text('تقييم الأسهم بسعر Bid مرصود ورسوم خروج مفترضة صفر، دون ضمان تعبئة. IEX للعرض فقط؛ مخاطرة جديدة تتطلب SIP حديثًا واجتياز حدود الحساب. غياب السعر أو قدمه يبقي القيمة غير متاحة.'),
        for(final p in (a['deliveryPositions'] as Map? ?? {}).entries)...[
          Text('${p.key}: ${p.value['quantity']} سهم مستلم • أساس تكلفة ${money(p.value['cost'])} • Bid مرصود ${money((report['deliveryValuation']['positions'] as List).firstWhere((r)=>r['symbol']==p.key)['valueCents'])}.'),
          OutlinedButton(onPressed:paper.busy||!paper.ready||a['enabled']==true?null:()=>showDialog<bool>(context:context,
            builder:(_)=>PaperSettlementDialog(paper:paper,accountId:a['id'] as String,delivery:true,
              contract:paper.journal.lastWhere((e)=>e['account']==a['id']&&e['symbol']==p.key&&e['settlement'] is Map)['settlement']['request']['contract'] as String)),
            child:const Text('تسجيل بيع الأسهم المستلمة ورقيًا')),
        ],
        const Text('الإغلاق اليدوي يعمل للحساب المتوقف أيضًا، دون تشغيل التقييم أو فتح مركز جديد. يحتاج اتصال بيانات وعرض خيار مؤهلًا.'),
        const Text('آخر القرارات — دفتر هذا الحساب فقط'),
        const Text('أثناء اتصال الواجهة تُحفظ عروض الخيار لخمس دقائق بعد الدخول، حتى بعد الإغلاق، لإعادة حساب بحثية منفصلة عن الرصيد. لا رصد عند إغلاق التطبيق.'),
        if(paper.optionArchiveError!=null)Text(paper.optionArchiveError!),
        if(paper.barArchiveError!=null)Text(paper.barArchiveError!),
        for(final e in paper.journal.where((e)=>e['account']==selectedAccount).toList().reversed.take(30))ListTile(
          title:Text('${e['symbol']} • ${e['decision']}'),subtitle:Text('${e['at']}'),
          trailing:const Icon(Icons.history),onTap:()=>Navigator.push(context,MaterialPageRoute<void>(
            builder:(_)=>DirectDecisionView(event:e,observations:paper.optionObservations(a['id'] as String),barArchive:paper.barArchive)))),
      ],
    ];
  }
}
