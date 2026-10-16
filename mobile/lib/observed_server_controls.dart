import 'dart:convert';
import 'package:flutter/material.dart';
import 'direct_alpaca.dart';
import 'market_strategy.dart';
import 'paper_settlement.dart';
import 'paper_time.dart';

String observedRuntimeLabel(dynamic state)=>switch(state) {
  'DISABLED'=>'متوقف', 'NO_ACTIVE_DEMAND'=>'لا حسابات نشطة',
  'LEDGER_BLOCKED'=>'الدفتر يحتاج مراجعة', 'SESSION_CLOSED'=>'الجلسة مغلقة',
  'DATA_UNAVAILABLE'=>'البيانات غير متاحة', 'RUNNING_VIRTUAL'=>'يقيّم الحسابات الافتراضية',
  'PARTIALLY_BLOCKED'=>'بعض الحسابات محجوبة', _=>'لم يُثبت تشغيله',
};

const observedLimits=<String,(String,int,int)>{
  'quantity':('عدد العقود المطلوب',1,100),'riskPercent':('المخاطرة %',1,20),
  'allocationPercent':('حد تخصيص النقد %',1,100),'dailyLossPercent':('حد الخسارة اليومية %',1,20),
  'maxPositions':('الحد الأقصى للمراكز',1,10),'maxContracts':('الحد الأقصى للعقود',1,100),
  'stopPercent':('وقف الخسارة %',1,95),'takePercent':('جني الربح %',1,500),
  'trailPercent':('الوقف المتحرك %؛ صفر لتعطيله',0,95),'partialPercent':('جني جزئي %؛ صفر لتعطيله',0,500),
  'maxHoldingDays':('أقصى أيام الاحتفاظ',1,365),
};

/// Explicit bounded OCC watchlist. Does not invent a chain or claim eligibility.
Map<String,dynamic> observedContracts(String input) {
  final result=<String,dynamic>{};
  for(final line in input.split(RegExp(r'[\s,]+')).where((s)=>s.isNotEmpty)) {
    final m=OptionQuote.pattern.firstMatch(line);
    if(m==null||int.parse(m[6]!)<=0||int.parse(m[6]!)%10!=0)throw const FormatException('هوية OCC قياسية بسعر تنفيذ بالسنت مطلوبة.');
    observationStamp('20${m[2]}-${m[3]}-${m[4]}T00:00:00Z');
    final symbol=m[1]!,direction=m[5]=='C'?'CALL':'PUT';
    final choices=result.putIfAbsent(symbol,()=> <String,dynamic>{}) as Map<String,dynamic>;
    if(choices.containsKey(direction))throw const FormatException('عقد واحد فقط لكل رمز واتجاه.');
    choices[direction]=line;
  }
  if(result.length>10)throw const FormatException('الحد الأقصى عشرة رموز.');
  return result;
}

class ObservedServerConfig extends StatefulWidget {
  final Map<String,dynamic> config;
  const ObservedServerConfig({super.key,required this.config});
  @override State<ObservedServerConfig> createState()=>_ObservedServerConfigState();
}
class _ObservedServerConfigState extends State<ObservedServerConfig> {
  late String strategy,holding;
  late final Map<String,TextEditingController> fields;
  late final TextEditingController contracts;
  String? error;
  @override void initState() {
    super.initState();strategy=widget.config['strategy'] as String;holding=widget.config['holdingMode'] as String;
    fields={for(final key in observedLimits.keys)key:TextEditingController(text:'${widget.config[key]}')};
    contracts=TextEditingController(text:(widget.config['contracts'] as Map).values.expand((r)=>(r as Map).values).join('\n'));
  }
  @override void dispose(){for(final c in [...fields.values,contracts]){c.dispose();}super.dispose();}
  void save() {
    try {
      final result=<String,dynamic>{'strategy':strategy,'holdingMode':holding,'contracts':observedContracts(contracts.text.trim())};
      for(final entry in fields.entries) {
        final value=int.tryParse(entry.value.text.trim()),limit=observedLimits[entry.key]!;
        if(value==null||value<limit.$2||value>limit.$3)throw FormatException('${limit.$1}: من ${limit.$2} إلى ${limit.$3}.');
        result[entry.key]=value;
      }
      Navigator.pop(context,result);
    }on FormatException catch(e){setState(()=>error=e.message);}
  }
  @override Widget build(BuildContext context)=>AlertDialog(title:const Text('سياسة الحساب المتوقف'),
    content:SizedBox(width:480,child:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,children:[
      const Text('العقود قائمة مراقبة صريحة. حفظها لا يثبت سيولتها أو أهليتها ولا يفتح قفل الدخول السوقي.'),
      DropdownButtonFormField<String>(key:const Key('observed-strategy'),initialValue:strategy,isExpanded:true,
        items:[for(final key in marketStrategies)DropdownMenuItem(value:key,child:Text(key))],onChanged:(v){if(v!=null)strategy=v;}),
      DropdownButtonFormField<String>(initialValue:holding,isExpanded:true,items:const [DropdownMenuItem(value:'intraday',child:Text('داخل الجلسة')),DropdownMenuItem(value:'swing',child:Text('عدة جلسات'))],onChanged:(v){if(v!=null)holding=v;}),
      for(final entry in fields.entries)TextField(key:Key('observed-config-${entry.key}'),controller:entry.value,keyboardType:TextInputType.number,decoration:InputDecoration(labelText:observedLimits[entry.key]!.$1)),
      TextField(key:const Key('observed-contracts'),controller:contracts,maxLines:5,decoration:const InputDecoration(labelText:'رموز OCC؛ عقد واحد في كل سطر')),
      if(error!=null)Text(error!,key:const Key('observed-config-error')),
    ]))),actions:[TextButton(onPressed:()=>Navigator.pop(context),child:const Text('إلغاء')),
      FilledButton(key:const Key('observed-config-save'),onPressed:save,child:const Text('حفظ السياسة'))]);
}

class ObservedServerSettlement extends StatefulWidget {
  final Map<String,dynamic> state;
  final String? contract,deliverySymbol;
  final DateTime serverTime;
  const ObservedServerSettlement({super.key,required this.state,required this.contract,this.deliverySymbol,required this.serverTime});
  @override State<ObservedServerSettlement> createState()=>_ObservedServerSettlementState();
}
class _ObservedServerSettlementState extends State<ObservedServerSettlement> {
  final quantity=TextEditingController(text:'1'),price=TextEditingController(),fee=TextEditingController(text:'0');
  final reference=TextEditingController(),effective=TextEditingController(),contract=TextEditingController();
  late String action,receipt;
  Map<String,dynamic>? request,result;
  String? error;
  @override void initState(){super.initState();action=widget.deliverySymbol==null?'EXERCISE':'SELL_DELIVERY';
    contract.text=widget.contract??'';effective.text=widget.serverTime.toUtc().toIso8601String();receipt='manual-${DateTime.now().microsecondsSinceEpoch}';}
  @override void dispose(){for(final c in [quantity,price,fee,reference,effective,contract]){c.dispose();}super.dispose();}
  int cents(String text) {
    final m=RegExp(r'^(\d+)(?:\.(\d{1,2}))?$').firstMatch(text.trim());
    if(m==null)throw const FormatException();
    return int.parse(m[1]!)*100+int.parse((m[2]??'').padRight(2,'0'));
  }
  void changed(String _) {setState((){request=null;result=null;error=null;});}
  void preview() {
    try {
      if(widget.state['enabled']!=false)throw const FormatException();
      final value=contract.text.trim(),symbol=OptionQuote.pattern.firstMatch(value)?.group(1);
      if(symbol==null||(widget.deliverySymbol!=null&&symbol!=widget.deliverySymbol))throw const FormatException();
      final p=(widget.state['positions'] as Map)[symbol] as Map?,d=(widget.state['deliveries'] as Map)[symbol] as Map?;
      if(p?['closeIntent']!=null)throw const FormatException();
      final r=<String,dynamic>{'id':receipt,'action':action,'contract':value,'quantity':int.parse(quantity.text.trim()),
        'underlyingCents':cents(price.text),'feeCents':cents(fee.text),'effectiveAt':effective.text.trim(),
        'recordedAt':widget.serverTime.toUtc().toIso8601String(),'source':'manual_paper','reference':reference.text.trim()};
      final at=observationStamp(r['effectiveAt']);
      for(final inventory in [p,d]){if(inventory!=null&&at.isBefore(observationStamp(inventory['changedAt'])))throw const FormatException();}
      final projected=projectPaperSettlement(p==null?null:{...p,'entryFees':0},d,widget.state['cash'] as int,r,widget.serverTime);
      setState((){request=r;result=projected;error=null;});
    }catch(_){setState((){request=null;result=null;error='تعذر اعتماد المعاينة. راجع الكمية والتوقيت والملكية والتمويل ومرجع الرصد.';});}
  }
  Widget field(TextEditingController c,String label,String key)=>TextField(key:Key(key),controller:c,onChanged:changed,decoration:InputDecoration(labelText:label));
  @override Widget build(BuildContext context)=>AlertDialog(title:const Text('تسوية افتراضية على الخادم'),
    content:SizedBox(width:480,child:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,children:[
      const Text('إيصال محاسبي يدوي. راجع الأثر قبل الإرسال. الخادم يعيد فحص الإصدار والملكية والتمويل؛ ليست تسوية وسيط أو أمر تداول.'),
      if(widget.contract==null)field(contract,'عقد OCC الأصلي المرتبط بأسهم التسليم','observed-settlement-contract')else Text(widget.contract!),
      DropdownButtonFormField<String>(initialValue:action,isExpanded:true,items:widget.deliverySymbol!=null?const [DropdownMenuItem(value:'SELL_DELIVERY',child:Text('بيع الأسهم افتراضيًا'))]:[
        const DropdownMenuItem(value:'EXERCISE',child:Text('ممارسة الخيار')),
        const DropdownMenuItem(value:'EXPIRE_WORTHLESS',child:Text('انتهاء بلا قيمة عند الإقفال')),
        if(RegExp(r'P\d{8}$').hasMatch(widget.contract??''))const DropdownMenuItem(value:'BUY_FOR_PUT',child:Text('تمويل أسهم تسليم Put'))],
        onChanged:(v){if(v!=null){action=v;changed('');}}),
      field(quantity,action=='SELL_DELIVERY'||action=='BUY_FOR_PUT'?'عدد الأسهم':'عدد العقود','observed-settlement-quantity'),
      field(price,'سعر السهم في الرصد USD','observed-settlement-price'),field(fee,'رسوم الإيصال USD','observed-settlement-fee'),
      field(effective,'وقت الحدث ISO مع المنطقة الزمنية','observed-settlement-effective'),field(reference,'مرجع الرصد الأصلي','observed-settlement-reference'),
      if(error!=null)Text(error!,key:const Key('observed-settlement-error')),
      if(result!=null)Text('تغير النقد ${(result!['cashDelta']/100).toStringAsFixed(2)} USD\nتغير الأسهم ${result!['shareDelta']}\nالربح المحقق ${(result!['realizedPnl']/100).toStringAsFixed(2)} USD',key:const Key('observed-settlement-result')),
    ]))),actions:[TextButton(onPressed:()=>Navigator.pop(context),child:const Text('إلغاء')),
      OutlinedButton(key:const Key('observed-settlement-preview'),onPressed:preview,child:const Text('معاينة الأثر')),
      FilledButton(key:const Key('observed-settlement-save'),onPressed:request==null?null:()=>Navigator.pop(context,jsonDecode(jsonEncode(request)) as Map<String,dynamic>),child:const Text('اعتماد الإيصال'))]);
}
