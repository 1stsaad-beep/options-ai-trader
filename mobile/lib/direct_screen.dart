import 'dart:async';
import 'package:flutter/material.dart';
import 'direct_alpaca.dart';
import 'direct_labs.dart';
import 'market_monitor.dart';
import 'market_paper.dart';

class DirectAlpacaScreen extends StatefulWidget {
  final DirectAlpaca? api;
  final PaperStore? paperStore;
  const DirectAlpacaScreen({super.key,this.api,this.paperStore});
  @override State<DirectAlpacaScreen> createState()=>_DirectAlpacaScreenState();
}
class _DirectAlpacaScreenState extends State<DirectAlpacaScreen> with WidgetsBindingObserver {
  late final DirectAlpaca api;
  late final MarketPaper paper;
  final keyId=TextEditingController(),secret=TextEditingController(),symbols=TextEditingController(text:'NVDA,AAPL,TSLA');
  final accountName=TextEditingController(),contract=TextEditingController();
  DirectSnapshot snapshot=DirectSnapshot();
  bool hasKeys=false,real=false,working=false,polling=false,background=false,visible=true;
  String feed='iex',session='regular',selectedSymbol='NVDA',direction='CALL';
  String? selectedAccount,notice;
  Timer? timer,cycle;
  int page=0;
  List<String> get watch=>symbols.text.toUpperCase().split(',').map((s)=>s.trim()).where((s)=>s.isNotEmpty).toSet().toList();
  @override void initState(){super.initState();WidgetsBinding.instance.addObserver(this);
    api=widget.api??DirectAlpaca();paper=MarketPaper(widget.paperStore??PreferencesPaperStore())..addListener(changed);
    initialize();timer=Timer.periodic(const Duration(seconds:1),(_){if(visible)refresh();});
    cycle=Timer.periodic(const Duration(seconds:30),(_){if(visible)paperCycle();});
  }
  void changed(){if(mounted)setState((){selectedAccount??=paper.accounts.isEmpty?null:paper.accounts.first['id'] as String;});}
  Future<void> initialize() async {await paper.load();await run(()async{
    await api.secureScreen(true);hasKeys=await api.hasKeys();await refresh();
    if(snapshot.enabled){real=true;feed=snapshot.feed;session=snapshot.session;if(snapshot.symbols.isNotEmpty)symbols.text=snapshot.symbols.join(',');}
  });}
  Future<void> run(Future<void> Function() action) async {
    if(working||!mounted)return;setState(()=>working=true);
    try{await action();}catch(_){notice='تعذر تنفيذ العملية. راجع الإعدادات والاتصال وصلاحيات Android؛ لم تُرسل أوامر تداول.';}
    finally{if(mounted)setState(()=>working=false);}
  }
  Future<void> refresh() async {
    if(polling)return;polling=true;
    try{final s=await api.snapshot();final bg=await api.background();if(mounted)setState((){snapshot=s;background=bg;});}
    catch(_){if(mounted)setState(()=>snapshot=DirectSnapshot());}finally{polling=false;}
  }
  Future<void> disconnect() async {await paper.pauseAll();await api.stop();await refresh();}
  Future<void> connect() async {
    if(!real||!hasKeys)return;
    if(watch.isEmpty||watch.length>10||watch.any((s)=>!RegExp(r'^[A-Z][A-Z0-9.]{0,9}$').hasMatch(s))){notice='اختر من 1 إلى 10 رموز صحيحة، مفصولة بفاصلة إنجليزية.';return;}
    await paper.pauseAll();await api.start(feed,session,watch);selectedSymbol=watch.contains(selectedSymbol)?selectedSymbol:watch.first;
    notice='بدأ اختبار HTTPS وWebSocket. Connected لا تعني LIVE حتى تصل شموع حديثة.';await refresh();
  }
  Future<void> paperCycle({bool forceClose=false}) async {
    if(!visible||!snapshot.enabled||paper.busy)return;
    for(final a in paper.accounts) {
      if(a['enabled']!=true)continue;
      if(forceClose&&a['id']!=selectedAccount)continue;
      final targets=forceClose?[selectedSymbol]:{...watch,...(a['positions'] as Map).keys.cast<String>()}.toList();
      for(final symbol in targets) {
        if(!visible||!mounted)return;
        final rows=snapshot.series[symbol]??[],signal=MarketSignal.analyze(rows);
        await paper.evaluate(id:a['id'] as String,symbol:symbol,signal:signal.direction,confirmedReverse:signal.confirmedReverse,
          dataValid:()=>visible&&snapshot.validForDecision(symbol,DateTime.now()),
          observation:rows.isEmpty?'none':rows.last.time.toIso8601String(),quotes:api.quote,forceClose:forceClose);
      }
    }
  }
  @override void didChangeAppLifecycleState(AppLifecycleState state){visible=state==AppLifecycleState.resumed;
    if(!visible){unawaited(paper.pauseAll());}else{refresh();}}
  @override void dispose(){timer?.cancel();cycle?.cancel();WidgetsBinding.instance.removeObserver(this);
    paper.removeListener(changed);unawaited(paper.pauseAll());
    unawaited(api.secureScreen(false).catchError((_){ }));
    if(!background)unawaited(api.stop().catchError((_){ }));
    for(final c in [keyId,secret,symbols,accountName,contract]){c.clear();c.dispose();}
    super.dispose();
  }
  String reason(String code)=>const {
    'OTHER_APP_CONNECTION_LIMIT':'اتصال مستخدم في تطبيق آخر؛ توقفنا دون قطع اتصاله. لا تغيّر مفاتيحه.',
    'AUTH_OR_ENTITLEMENT_401':'بيانات المصادقة مرفوضة.',
    'AUTH_OR_ENTITLEMENT_402':'مصادقة WebSocket مرفوضة.',
    'AUTH_OR_ENTITLEMENT_403':'الصلاحية أو الاشتراك لا يسمحان بهذا المصدر.',
    'AUTH_OR_ENTITLEMENT_409':'الاشتراك لا يسمح بهذا Feed.',
    'RATE_LIMIT':'بلغت حصة الطلبات؛ انتظار المهلة دون تجاوزها.',
    'HISTORY_UNAVAILABLE':'التاريخ غير متاح الآن؛ ستُعاد المحاولة دون بيانات بديلة.',
    'DISCONNECTED':'انقطع الاتصال؛ إعادة المحاولة تدريجيًا.',
    'RETRY_EXHAUSTED':'توقفت إعادة المحاولة؛ اختبر الاتصال يدويًا بعد معالجة السبب.',
    'KEYSTORE_UNAVAILABLE':'تعذرت قراءة المخزن المشفر؛ أدخل المفاتيح بنفسك مجددًا.',
  }[code]??code;
  @override Widget build(BuildContext context)=>Scaffold(
    appBar:AppBar(title:const Text('Alpaca مباشر • Market Data'),actions:[IconButton(tooltip:'إيقاف الاتصال',onPressed:()=>run(disconnect),icon:const Icon(Icons.stop_circle_outlined))]),
    bottomNavigationBar:NavigationBar(selectedIndex:page,onDestinationSelected:(i)=>setState(()=>page=i),destinations:const [
      NavigationDestination(icon:Icon(Icons.settings),label:'الاتصال'),NavigationDestination(icon:Icon(Icons.candlestick_chart),label:'السوق والمختبرات'),
      NavigationDestination(icon:Icon(Icons.account_balance_wallet),label:'Market Paper'),NavigationDestination(icon:Icon(Icons.notifications),label:'الأحداث')]),
    body:SafeArea(child:ListView(padding:const EdgeInsets.all(16),children:[
      const Text('وضع الهاتف مستقل عن الخادم وDemo Synthetic • لا Live Trading أو IBKR'),
      Text('${snapshot.connected?'Connected':'Disconnected'} • ${reason(snapshot.reason)}',key:const Key('direct-status')),
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
    Text(hasKeys?'المفاتيح محفوظة • لا تُعرض القيم بعد الحفظ':'أدخل المفاتيح على هذا الهاتف فقط'),
    TextField(key:const Key('alpaca-key'),controller:keyId,enableSuggestions:false,autocorrect:false,enableIMEPersonalizedLearning:false,
      decoration:const InputDecoration(labelText:'API Key ID',helperText:'اترك الحقول فارغة لاستخدام القيم المحفوظة')),
    TextField(key:const Key('alpaca-secret'),controller:secret,obscureText:true,enableSuggestions:false,autocorrect:false,enableIMEPersonalizedLearning:false,
      decoration:const InputDecoration(labelText:'API Secret — لا يمكن عرضه بعد الحفظ')),
    FilledButton(onPressed:working?null:()=>run(()async{
      try{await paper.pauseAll();await api.saveKeys(keyId.text.trim(),secret.text.trim());hasKeys=await api.hasKeys();notice='حُفظت المفاتيح في الهاتف فقط.';}
      finally{keyId.clear();secret.clear();}
    }),child:const Text('حفظ المفاتيح المشفرة')),
    DropdownButtonFormField<String>(initialValue:feed,decoration:const InputDecoration(labelText:'Feed'),items:const [
      DropdownMenuItem(value:'iex',child:Text('IEX — تداولات بورصة واحدة')),DropdownMenuItem(value:'sip',child:Text('SIP — يتطلب صلاحية الاشتراك'))],
      onChanged:working?null:(v){if(v!=null)run(()async{await disconnect();feed=v;});}),
    DropdownButtonFormField<String>(initialValue:session,decoration:const InputDecoration(labelText:'Session — توقيت New York'),items:const [
      DropdownMenuItem(value:'regular',child:Text('Regular 09:30–16:00')),DropdownMenuItem(value:'extended',child:Text('Extended 04:00–20:00 ضمن تغطية Feed'))],
      onChanged:working?null:(v){if(v!=null)run(()async{await disconnect();session=v;});}),
    const Text('مرشح الجلسة يتبع التوقيت الصيفي. العطلات والإغلاق المبكر وغياب التداول لا يولّدون شموعًا؛ الأسعار القديمة لا تصبح LIVE.'),
    TextField(controller:symbols,enabled:!snapshot.enabled,decoration:const InputDecoration(labelText:'الأسهم — حتى 10 رموز',hintText:'NVDA,AAPL,TSLA')),
    SwitchListTile(title:const Text('Real Market Data'),subtitle:const Text('التفعيل يجهّز الاتصال؛ زر Test Connection يبدأ الاتصال بـAlpaca فقط.'),value:real,
      onChanged:working?null:(v)=>run(()async{real=v;if(!v)await disconnect();})),
    FilledButton(key:const Key('alpaca-test'),onPressed:working||!real||!hasKeys?null:()=>run(connect),child:const Text('Test Connection')),
    const Text('احتمال وجود حد WebSocket واحد للحساب. عند 406 يتوقف هذا التطبيق دون إيقاف التطبيق الآخر. لا نغيّر الاشتراك أو نشتري خدمات.'),
    const Divider(),
    Text('مراقبة الخلفية: ${background?'تعمل مؤقتًا':'متوقفة'}'),
    const Text('خدمة اختيارية لمدة ≤30 دقيقة للأسعار وRSI/MACD مع إشعار دائم. قد يقيّدها توفير البطارية أو الشبكة أو Android. لا تعمل عند إطفاء الهاتف ولا تعيد تشغيل نفسها. Market Paper يتوقف عند مغادرة التطبيق؛ لا حماية مراكز مضمونة في الخلفية.'),
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
    DropdownButtonFormField<String>(initialValue:selectedSymbol,decoration:const InputDecoration(labelText:'السهم'),
      items:{selectedSymbol,...watch,...snapshot.series.keys}.map((s)=>DropdownMenuItem(value:s,child:Text(s))).toList(),
      onChanged:(s){if(s!=null)setState(()=>selectedSymbol=s);}),
    DirectLabs(rows:snapshot.series[selectedSymbol]??[],symbol:selectedSymbol,source:snapshot.label(selectedSymbol,DateTime.now())),
  ];
  List<Widget> paperWidgets(){
    final a=selectedAccount==null?null:paper.account(selectedAccount!);
    return [
      const Text('Market Paper • أموال افتراضية مستقلة • تعبئة بحثية تقريبية فقط بعرض OPRA مؤهل (شراء ask / إغلاق bid، عمولة افتراضية 0.65 USD للعقد لكل جهة). لا تحاكي طابور السوق أو الانزلاق أو التنفيذ الفعلي.'),
      const Text('بدون OPRA حديث وصالح: إشارات فقط، لا تعبئة Call/Put. IEX/SIP للأسهم لا يمنحان بيانات الخيارات. لا استخدام للأسعار الإرشادية indicative.'),
      const Text('المحاكاة تفترض معامل عقد قياسي 100؛ لا تدعم العقود المعدلة/mini أو التمرين والتخصيص. انتهاء الصلاحية أو فقد الأسعار لا يُنشئ إغلاقًا وهميًا.'),
      if(paper.error!=null)Text(paper.error!),
      TextField(controller:accountName,decoration:const InputDecoration(labelText:'اسم حساب Market Paper جديد')),
      OutlinedButton(onPressed:paper.busy||!paper.ready?null:()=>paper.add(accountName.text),child:const Text('إنشاء حساب افتراضي 10,000 USD')),
      if(a!=null)...[
        DropdownButtonFormField<String>(initialValue:selectedAccount,items:paper.accounts.map((x)=>DropdownMenuItem(value:x['id'] as String,child:Text(x['name'] as String))).toList(),
          onChanged:(v)=>setState(()=>selectedAccount=v),decoration:const InputDecoration(labelText:'الحساب المستقل')),
        Text('النقد الافتراضي: ${(a['cash']/100).toStringAsFixed(2)} USD'),
        SwitchListTile(title:const Text('تشغيل تقييم هذا الحساب'),subtitle:const Text('دورة كل 30 ثانية داخل التطبيق. يتوقف عند مغادرته أو تغيير الاتصال.'),value:a['enabled']==true,
          onChanged:snapshot.connected?(v)=>paper.configure(selectedAccount!,{'enabled':v}):null),
        Text('المخاطرة القصوى للمركز ${a['riskPercent']}% • العقود ${a['quantity']} • SL ${a['stopPercent']}% • TP ${a['takePercent']}% • Trailing ${a['trailPercent']}%'),
        for(final entry in {'riskPercent':'نسبة حد التكلفة','quantity':'عدد العقود','stopPercent':'وقف الخسارة %','takePercent':'جني الربح %','trailPercent':'وقف متحرك %'}.entries)
          Row(children:[Expanded(child:Text(entry.value)),IconButton(onPressed:paper.busy?null:()=>paper.configure(selectedAccount!,{entry.key:((a[entry.key] as int)-1).clamp(1,entry.key=='quantity'?10:50)}),icon:const Icon(Icons.remove)),
            Text('${a[entry.key]}'),IconButton(onPressed:paper.busy?null:()=>paper.configure(selectedAccount!,{entry.key:((a[entry.key] as int)+1).clamp(1,entry.key=='quantity'?10:50)}),icon:const Icon(Icons.add))]),
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
        for(final p in (a['positions'] as Map).entries)ListTile(title:Text('${p.key} ${p.value['direction']} × ${p.value['quantity']}'),subtitle:Text('${p.value['contract']} • تكلفة ${(p.value['cost']/100).toStringAsFixed(2)} USD')),
        OutlinedButton(onPressed:paper.busy?null:()=>paperCycle(forceClose:true),child:Text('طلب إغلاق افتراضي لـ $selectedSymbol بعرض صالح')),
        const Text('آخر القرارات — دفتر هذا الحساب فقط'),
        for(final e in paper.journal.where((e)=>e['account']==selectedAccount).toList().reversed.take(30))Text('${e['at']} • ${e['symbol']} • ${e['decision']}'),
      ],
    ];
  }
}
