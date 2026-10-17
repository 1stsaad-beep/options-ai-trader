import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';
import 'direct_alpaca.dart';
import 'direct_labs.dart';
import 'paper_time.dart';
import 'strategy_replay.dart';
import 'observed_server_controls.dart';
import 'observed_server_comparison.dart';
import 'observed_server_valuation.dart';

Map<String,dynamic> observedObject(dynamic value) {
  if(value is! Map||value.keys.any((key)=>key is! String))throw const FormatException('Invalid server object');
  return Map<String,dynamic>.from(value);
}
bool observedInteger(dynamic value,{int minimum=0})=>value is int&&value>=minimum&&value.abs()<=9007199254740991;
bool observedHash(dynamic value)=>value is String&&RegExp(r'^[a-f0-9]{64}$').hasMatch(value);
bool observedId(String value)=>RegExp(r'^[A-Za-z0-9_-]{1,80}$').hasMatch(value);

class ObservedServerAccount {
  final Map<String,dynamic> state;
  final int version;
  final String eventHash;
  ObservedServerAccount._(this.state,this.version,this.eventHash);
  factory ObservedServerAccount.parse(dynamic raw,String account) {
    final root=observedObject(raw),state=observedObject(root['state']);
    if(!observedId(account)||state['id']!=account||!['observed-paper-ledger-v1','observed-paper-ledger-v2'].contains(state['contract'])||
        state['executionContract']!='paper-option-execution-v2'||!['fixture','alpaca'].contains(state['source'])||
        state['name'] is! String||state['enabled'] is! bool||!observedInteger(root['version'])||!observedHash(root['eventHash'])) {
      throw const FormatException('Unqualified server account');
    }
    for(final key in ['cash','initialCash','fees','closedTrades','winningTrades']) {
      if(!observedInteger(state[key]))throw const FormatException('Invalid server balance');
    }
    if(!observedInteger(state['realized'],minimum:-9007199254740991))throw const FormatException('Invalid realized balance');
    var basis=0;
    for(final entry in observedObject(state['positions']).entries) {
      final p=observedObject(entry.value);
      if(p['contract'] is! String||OptionQuote.pattern.firstMatch(p['contract'] as String)?.group(1)!=entry.key||
          !observedInteger(p['quantity'],minimum:1)||!observedInteger(p['cost'])) {
        throw const FormatException('Invalid owned position');
      }
      basis+=p['cost'] as int;
      observationStamp(p['opened']);
      if(p['closeIntent']!=null) {
        final intent=observedObject(p['closeIntent']);
        if(!observedInteger(intent['quantity'],minimum:1)||intent['quantity']>p['quantity']||intent['reason'] is! String) {
          throw const FormatException('Invalid residual close');
        }
      }
    }
    for(final raw in observedObject(state['deliveries']).values) {
      final p=observedObject(raw);
      if(!observedInteger(p['quantity'],minimum:1)||!observedInteger(p['cost']))throw const FormatException('Invalid delivery');
      basis+=p['cost'] as int;
    }
    if(state['cash']+basis!=state['initialCash']+state['realized'])throw const FormatException('Server accounting mismatch');
    final config=observedObject(state['config']);
    if(!marketStrategies.contains(config['strategy'])||config['contracts'] is! Map||
        !observedInteger(config['quantity'],minimum:1)||config['quantity']>100||
        !observedInteger(config['riskPercent'],minimum:1)||config['riskPercent']>20) {
      throw const FormatException('Invalid server policy');
    }
    return ObservedServerAccount._(jsonDecode(jsonEncode(state)) as Map<String,dynamic>,root['version'] as int,root['eventHash'] as String);
  }
}

class ObservedServerEvent {
  final int version;
  final String eventHash;
  final Map<String,dynamic> original;
  ObservedServerEvent._(this.version,this.eventHash,this.original);
  factory ObservedServerEvent.parse(dynamic raw) {
    final root=observedObject(raw),original=observedObject(root['original']);
    final command=observedObject(original['command']),facts=observedObject(original['facts']);
    if(!observedInteger(root['version'])||!observedHash(root['eventHash'])||!observedHash(root['afterHash'])||
        root['at']!=original['at']||jsonEncode(root['facts'])!=jsonEncode(facts)||facts['externalOrder']!=false||
        command['kind']!=facts['kind']) {
      throw const FormatException('Invalid original event');
    }
    observationStamp(original['at']);
    return ObservedServerEvent._(root['version'] as int,root['eventHash'] as String,jsonDecode(jsonEncode(original)) as Map<String,dynamic>);
  }
}

/// Authenticated personal server only. Never imports device balances or uses
/// a provider key. Controls send no prices, observations or broker orders.
class ObservedServerScreen extends StatefulWidget {
  final TraderApi api;
  const ObservedServerScreen({super.key,required this.api});
  @override State<ObservedServerScreen> createState()=>_ObservedServerScreenState();
}
class _ObservedServerScreenState extends State<ObservedServerScreen> {
  bool busy=false;
  String? error,account;
  List<String> ids=[];
  ObservedServerAccount? saved;
  Map<String,dynamic>? runtime;
  List<ObservedServerEvent> events=[];
  int after=-1;
  String path(String id)=>'/api/observed-paper/accounts/${Uri.encodeComponent(id)}';
  @override void initState(){super.initState();load();}
  Future<void> load({String? selected}) async {
    if(busy)return;
    setState((){busy=true;error=null;});
    try {
      final result=observedObject(await widget.api.request('GET','/api/observed-paper/accounts'));
      if(result['mode']!='observed_market_virtual'||result['externalOrder']!=false||result['accounts'] is! List)throw const FormatException();
      final values=(result['accounts'] as List).cast<String>();
      if(values.toSet().length!=values.length||values.any((id)=>!observedId(id)))throw const FormatException();
      final status=observedObject(await widget.api.request('GET','/api/observed-paper/status'));
      if(status['mode']!='observed_market_virtual'||status['externalOrder']!=false||status['newMarketEntryAllowed']!=false||status['heartbeatFresh'] is! bool)throw const FormatException();
      observationStamp(status['serverTime']);
      final target=values.contains(selected??account)?selected??account:values.firstOrNull;
      final value=target==null?null:ObservedServerAccount.parse(await widget.api.request('GET','${path(target)}/state'),target);
      if(!mounted)return;
      setState((){ids=values;account=target;saved=value;runtime=status;events=[];after=-1;});
    }catch(_){if(mounted)setState((){saved=null;runtime=null;events=[];error='تعذر التحقق من حالة الخادم؛ أعد التحديث. لم يُنفّذ إجراء تلقائي.';});}
    finally{if(mounted)setState(()=>busy=false);}
  }
  Future<void> control(Map<String,dynamic> command) async {
    final current=saved,id=account;if(busy||current==null||id==null)return;
    setState((){busy=true;error=null;});
    try {
      await widget.api.request('POST','${path(id)}/control',{'request_key':'mobile:${DateTime.now().microsecondsSinceEpoch}',
        'expected_version':current.version,'command':command});
    }catch(_){if(mounted)setState(()=>error='لم يتأكد الإجراء؛ لا نعيد إرسال الكتابة تلقائيًا. حدّث الحالة قبل اتخاذ إجراء آخر.');}
    finally{if(mounted)setState((){busy=false;saved=null;events=[];});}
    if(mounted&&error==null)await load(selected:id);
  }
  Future<void> create() async {
    final name=TextEditingController(),capital=TextEditingController(text:'1000');
    final accepted=await showDialog<bool>(context:context,builder:(context)=>AlertDialog(title:const Text('حساب افتراضي مستقل على الخادم'),
      content:Column(mainAxisSize:MainAxisSize.min,children:[TextField(controller:name,decoration:const InputDecoration(labelText:'اسم الحساب')),
        TextField(controller:capital,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'الرصيد الافتراضي بالدولار'))]),
      actions:[TextButton(onPressed:()=>Navigator.pop(context,false),child:const Text('إلغاء')),
        FilledButton(onPressed:()=>Navigator.pop(context,true),child:const Text('إنشاء متوقف'))]));
    final label=name.text.trim(),amount=int.tryParse(capital.text);name.dispose();capital.dispose();
    if(accepted!=true||!mounted||busy)return;
    if(label.isEmpty||amount==null||amount<100||amount>1000000){setState(()=>error='أدخل اسمًا ورصيدًا صحيحًا من 100 إلى 1000000 دولار.');return;}
    final id='observed-${DateTime.now().microsecondsSinceEpoch}';setState((){busy=true;error=null;});
    try{await widget.api.request('POST','/api/observed-paper/accounts',{'id':id,'name':label,'initial_cash_cents':amount*100,'source':'alpaca'});}
    catch(_){if(mounted)setState(()=>error='لم يتأكد إنشاء الحساب؛ حدّث قائمة الخادم قبل المحاولة مجددًا.');}
    finally{if(mounted)setState(()=>busy=false);}
    if(mounted&&error==null)await load(selected:id);
  }
  Future<void> loadEvents() async {
    final id=account;if(busy||saved==null||id==null)return;
    setState(()=>busy=true);
    try {
      final page=observedObject(await widget.api.request('GET','${path(id)}/events?after=$after&limit=20'));
      if(page['account']!=id||page['mode']!='observed_market_virtual'||page['externalOrder']!=false||page['events'] is! List)throw const FormatException();
      final rows=(page['events'] as List).map(ObservedServerEvent.parse).toList();
      var cursor=after;
      for(final row in rows){if(row.version!=cursor+1)throw const FormatException();cursor=row.version;}
      if(page['nextAfter']!=cursor)throw const FormatException();
      // A bounded page, not an ever-growing in-memory history.
      if(mounted)setState((){events=rows;after=cursor;});
    }catch(_){if(mounted)setState(()=>error='تعذر التحقق من صفحة القرارات؛ لم تُعرض بيانات بديلة.');}
    finally{if(mounted)setState(()=>busy=false);}
  }
  Future<void> experiment() async {
    if (busy) return;
    final accepted = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
      title: const Text('أربعة حسابات خادم × 1000 USD'),
      content: const Text('اتجاه، اختراق، ارتداد، دايفرجنس؛ أرصدة افتراضية مستقلة وحسابات جديدة متوقفة. إعادة الطلب تحتفظ بأموال المجموعة وإعداداتها الحالية. لا تشغيل أو اتصال سوقي تلقائي.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('إلغاء')),
        FilledButton(key: const Key('observed-experiment-confirm'), onPressed: () => Navigator.pop(context, true), child: const Text('إعداد المجموعة')),
      ],
    ));
    if (accepted != true || !mounted || busy) return;
    setState(() { busy = true; error = null; });
    try {
      parseObservedExperiment(await widget.api.request('POST', '/api/observed-paper/experiment', {'source': 'alpaca'}), 'alpaca');
    } catch (_) {
      if (mounted) setState(() => error = 'لم يتأكد إعداد المجموعة؛ حدّث الحسابات للتحقق. لم تُعد الكتابة تلقائيًا.');
    } finally {
      if (mounted) setState(() { busy = false; saved = null; events = []; });
    }
    if (mounted && error == null) await load(selected: observedExperimentIds('alpaca').first);
  }
  Future<void> comparison() async {
    final selected = observedExperimentIds('alpaca');
    if (busy || !selected.every(ids.contains)) return;
    setState(() { busy = true; error = null; });
    Map<String, dynamic>? report;
    try {
      final query = Uri(queryParameters: {'accounts': selected.join(',')}).query;
      report = parseObservedComparison(await widget.api.request('GET', '/api/observed-paper/comparison?$query'), selected, 'alpaca');
    } catch (_) {
      if (mounted) setState(() => error = 'تعذر التحقق من مقارنة الحسابات؛ حدّث الحالة وأعد القراءة.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
    if (!mounted || report == null) return;
    final verified = report;
    await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => ObservedComparisonScreen(report: verified)));
  }
  @override Widget build(BuildContext context) {
    final value=saved?.state;
    return Scaffold(appBar:AppBar(title:const Text('دفتر الخادم الافتراضي'),actions:[IconButton(key:const Key('observed-refresh'),onPressed:busy?null:()=>load(),icon:const Icon(Icons.refresh))]),
      body:ListView(padding:const EdgeInsets.all(16),children:[
        const Text('حسابات مستقلة عن Demo ودفتر الهاتف. الأرصدة افتراضية، ولا تُرسل أوامر إلى وسيط.'),
        if(runtime!=null)Text('العامل: ${observedRuntimeLabel(runtime!['state'])} • نبض حديث: ${runtime!['heartbeatFresh']==true?"نعم":"لا"}'),
        if(runtime!=null)Text('وقت قراءة الخادم: ${runtime!['serverTime']} • حدّث الصفحة للتحقق مجددًا.'),
        const Text('الدخول السوقي الجديد مقفل حاليًا حتى اكتمال تحقق أهلية العقد وGreeks. تشغيل الحساب لا يثبت تشغيل العامل أو صلاحية بيانات السوق.'),
        if(busy)const LinearProgressIndicator(),
        if(error!=null)Text(error!,key:const Key('observed-error')),
        OutlinedButton(key:const Key('observed-create'),onPressed:busy?null:create,child:const Text('إنشاء حساب افتراضي مستقل')),
        OutlinedButton(key:const Key('observed-experiment'),onPressed:busy?null:experiment,child:const Text('إعداد أربعة حسابات × 1000 USD')),
        if(observedExperimentIds('alpaca').every(ids.contains))OutlinedButton(key:const Key('observed-comparison'),onPressed:busy?null:comparison,child:const Text('مقارنة الحسابات الأربعة')),
        if(ids.isNotEmpty)DropdownButton<String>(value:account,isExpanded:true,items:[for(final id in ids)DropdownMenuItem(value:id,child:Text(id))],onChanged:busy?null:(id)=>load(selected:id)),
        if(value!=null)...[
          Text('${value['name']} • ${value['source']} • إصدار ${saved!.version}',key:const Key('observed-account')),
          Text('نقد ${(value['cash']/100).toStringAsFixed(2)} USD • محقق ${(value['realized']/100).toStringAsFixed(2)} USD • رسوم ${(value['fees']/100).toStringAsFixed(2)} USD'),
          const Text('قيمة التصفية والربح غير المحقق غير معروضين دون علامات سوق مؤهلة. النقد ليس قيمة المحفظة.'),
          OutlinedButton(key:const Key('observed-configure'),onPressed:busy||value['enabled']==true?null:()async {
            final config=await showDialog<Map<String,dynamic>>(context:context,builder:(_)=>ObservedServerConfig(config:observedObject(value['config'])));
            if(mounted&&config!=null)await control({'kind':'CONFIGURE','config':config});
          },child:const Text('إعداد الاستراتيجية والمخاطر والعقود')),
          FilledButton(key:const Key('observed-toggle'),onPressed:busy?null:()=>control({'kind':'ENABLE','enabled':value['enabled']!=true}),
            child:Text(value['enabled']==true?'إيقاف الحساب':'تشغيل الحساب الافتراضي')),
          for(final entry in observedObject(value['positions']).entries)Card(child:Padding(padding:const EdgeInsets.all(12),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
            Text('${entry.key} • ${entry.value['contract']} • ${entry.value['quantity']} عقود'),
            if(entry.value['closeIntent']!=null)Text('إغلاق متبقٍ: ${entry.value['closeIntent']['quantity']} • ${entry.value['closeIntent']['reason']}'),
            OutlinedButton(key:Key('observed-close-${entry.key}'),onPressed:busy?null:()=>control({'kind':'REQUEST_CLOSE','symbol':entry.key}),child:const Text('طلب إغلاق المركز المملوك')),
            if(value['enabled']==false&&entry.value['closeIntent']!=null)OutlinedButton(onPressed:busy?null:()=>control({'kind':'CANCEL_CLOSE','symbol':entry.key}),child:const Text('إلغاء طلب الإغلاق قبل التسوية')),
            OutlinedButton(key:Key('observed-settle-${entry.key}'),onPressed:busy||value['enabled']==true||entry.value['closeIntent']!=null?null:()=>settle(entry.value['contract'] as String),child:const Text('تسوية افتراضية صريحة')),
          ]))),
          if(observedObject(value['deliveries']).isNotEmpty)const Text('توجد أسهم تسليم؛ تتطلب تسوية افتراضية صريحة ومراجعة، والدخول الجديد محجوب.'),
          for(final entry in observedObject(value['deliveries']).entries)Card(child:ListTile(title:Text('${entry.key} • ${entry.value['quantity']} أسهم تسليم'),
            trailing:TextButton(onPressed:busy||value['enabled']==true?null:()=>settle(null,deliverySymbol:entry.key),child:const Text('تصرف افتراضي')))),
          OutlinedButton(key:const Key('observed-performance'),onPressed:busy?null:performance,child:const Text('أداء الإيصالات الأصلية')),
          OutlinedButton(key:const Key('observed-valuation'),onPressed:busy?null:valuation,child:const Text('تقييم العروض المحفوظة')),
          OutlinedButton(key:const Key('observed-events'),onPressed:busy?null:loadEvents,child:const Text('تحميل صفحة القرارات الأصلية التالية')),
          for(final event in events)ListTile(title:Text('#${event.version} • ${event.original['command']['kind']}'),subtitle:Text(event.original['at'] as String),
            onTap:()=>Navigator.push(context,MaterialPageRoute<void>(builder:(_)=>ObservedServerReplay(account:account!,event:event)))),
        ],
      ]));
  }
  Future<void> valuation() async {
    final current=saved,id=account;if(current==null||id==null||busy)return;
    setState(()=>busy=true);
    Map<String,dynamic>? report;
    try {
      report=parseObservedValuation(await widget.api.request('GET','${path(id)}/valuation'),current);
    }catch(_){if(mounted)setState(()=>error='تعذر التحقق من تقييم مطابق لإصدار الحساب؛ حدّث الحالة ثم أعد الطلب.');}
    finally{if(mounted)setState(()=>busy=false);}
    if(!mounted||report==null)return;
    final verified=report;
    await Navigator.push(context,MaterialPageRoute<void>(builder:(_)=>ObservedValuationScreen(report:verified)));
  }
  Future<void> performance() async {
    final current=saved,id=account;if(current==null||id==null||busy)return;
    setState(()=>busy=true);
    Map<String,dynamic>? report;
    try {
      final value=observedObject(await widget.api.request('GET','${path(id)}/performance'));
      if(value['contract']!='observed-paper-performance-v1'||value['account']!=id||value['source']!=current.state['source']||
          value['externalOrder']!=false||value['version']!=current.version||value['eventHash']!=current.eventHash||
          value['realizedPnlCents']!=current.state['realized']||value['cashCents']!=current.state['cash']||
          value['feesCents']!=current.state['fees']) {
        throw const FormatException();
      }
      for(final key in ['maximumRealizedDrawdownCents','closedQuoteRoundTrips','settlementAffectedClosuresExcluded','buyContracts','sellContracts','addFills']) {
        if(!observedInteger(value[key]))throw const FormatException();
      }
      report=value;
    }catch(_){if(mounted)setState(()=>error='تعذر التحقق من التقرير المطابق لإصدار الحساب؛ حدّث الحالة ثم أعد الطلب.');}
    finally{if(mounted)setState(()=>busy=false);}
    if(!mounted||report==null)return;
    final r=report;
    await showDialog<void>(context:context,builder:(context)=>AlertDialog(title:const Text('أداء الإيصالات الأصلية'),
      content:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.start,children:[
        Text('الربح المحقق ${(r['realizedPnlCents']/100).toStringAsFixed(2)} USD • الرسوم ${(r['feesCents']/100).toStringAsFixed(2)} USD'),
        Text('أقصى تراجع للمحقق ${(r['maximumRealizedDrawdownCents']/100).toStringAsFixed(2)} USD'),
        Text('دورات خيار مغلقة بالأسعار ${r['closedQuoteRoundTrips']} • إغلاقات متأثرة بالتسوية مستبعدة من الإحصاء ${r['settlementAffectedClosuresExcluded']}'),
        Text('عقود مشتراة ${r['buyContracts']} • مباعة ${r['sellContracts']} • تعبئات تعزيز ${r['addFills']}'),
        const Text('التراجع للمحقق لا يقيس تراجع قيمة المحفظة. لا ربح غير محقق أو Sharpe دون تقييم كامل مؤهل. التسويات مشمولة في الربح المحقق والرسوم، ومستبعدة من إحصاء دورات الخيار.'),
      ])),actions:[TextButton(onPressed:()=>Navigator.pop(context),child:const Text('إغلاق'))]));
  }
  Future<void> settle(String? contract,{String? deliverySymbol}) async {
    final current=saved,status=runtime;
    if(current==null||status==null||busy||current.state['enabled']==true)return;
    final request=await showDialog<Map<String,dynamic>>(context:context,builder:(_)=>ObservedServerSettlement(
      state:current.state,contract:contract,deliverySymbol:deliverySymbol,serverTime:observationStamp(status['serverTime'])));
    if(mounted&&request!=null)await control({'kind':'SETTLE','request':request});
  }
}

class ObservedServerReplay extends StatefulWidget {
  final String account;
  final ObservedServerEvent event;
  const ObservedServerReplay({super.key,required this.account,required this.event});
  @override State<ObservedServerReplay> createState()=>_ObservedServerReplayState();
}
class _ObservedServerReplayState extends State<ObservedServerReplay> {
  late final Map<String,dynamic> original;
  late final String raw;
  Map<String,dynamic>? observation;
  String? symbol;
  int cursor=0;
  bool compare=false;
  @override void initState() {
    super.initState();raw=const JsonEncoder.withIndent('  ').convert(widget.event.original);
    original=jsonDecode(raw) as Map<String,dynamic>;
    final command=observedObject(original['command']);
    if(command['kind']=='CYCLE') {
      try {
        final candidate=observedObject(command['observation']),symbols=observedObject(candidate['bars']);
        if(symbols.isNotEmpty){symbol=symbols.keys.first;cursor=(symbols[symbol] as List).length-1;observation=candidate;}
      }catch(_){observation=null;}
    }
  }
  @override Widget build(BuildContext context) {
    final saved=observation,rows=saved==null||symbol==null?null:saved['bars'][symbol] as List;
    final query=rows==null?null:<String,dynamic>{'account':widget.account,'symbol':symbol,'source':saved!['source'],
      'capturedAt':saved['capturedAt'],'bars':rows,'cursor':cursor};
    final result=query==null?null:compareStrategies(query);
    final valid=result?['status']=='COMPARED',last=valid&&cursor==rows!.length-1;
    final prefix=valid?[for(final raw in rows!.take(cursor+1))MarketBar(observationStamp(raw['at']),
      (raw['o'] as num).toDouble(),(raw['h'] as num).toDouble(),(raw['l'] as num).toDouble(),(raw['c'] as num).toDouble(),(raw['v'] as num).toDouble())]:<MarketBar>[];
    return Scaffold(appBar:AppBar(title:const Text('قرار الخادم المحفوظ')),body:ListView(padding:const EdgeInsets.all(16),children:[
      Text('${widget.account} • حدث ${widget.event.version}'),
      const Text('عرض محلي للأصل المستلم من الخادم. لا اتصال بمزود ولا تعديل للحساب. بصمة الخادم مرجع وليست توقيعًا مستقلًا.'),
      if(saved!=null&&symbol!=null)DropdownButton<String>(value:symbol,isExpanded:true,items:[for(final key in observedObject(saved['bars']).keys)DropdownMenuItem(value:key,child:Text(key))],
        onChanged:(key){if(key!=null)setState((){symbol=key;cursor=(saved['bars'][key] as List).length-1;});}),
      if(valid)...[
        Text('${cursor+1}/${rows!.length}',key:const Key('observed-replay-cursor')),
        if(rows.length>1)Slider(key:const Key('observed-replay-slider'),value:cursor.toDouble(),min:0,max:(rows.length-1).toDouble(),divisions:rows.length-1,onChanged:(v)=>setState(()=>cursor=v.round())),
        DirectLabs(rows:prefix,symbol:symbol!,source:'SERVER SAVED • ${saved!['source']} • ${saved['stockFeed']}'),
        OutlinedButton(key:const Key('observed-replay-compare'),onPressed:()=>setState(()=>compare=!compare),child:const Text('مقارنة لاحقة على البادئة فقط')),
        if(compare)SelectableText(const JsonEncoder.withIndent('  ').convert(result),key:const Key('observed-replay-result')),
        const Text('الحساب اللاحق لا يثبت أن كامل النافذة كان متاحًا عند مؤشر أقدم؛ لا نتيجة مالية أو تعبئة افتراضية من الشموع.'),
      ]else const Text('لا مصدر شموع كاملًا صالحًا في هذا الحدث. الأصل النصي متاح دون اختلاق شارت.'),
      if(last||!valid)SelectableText(raw,key:const Key('observed-original'))
      else const Text('الإيصال والسبب النهائي مخفيان عند المؤشر الأقدم.'),
    ]));
  }
}
