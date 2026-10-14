import 'dart:convert';
import 'package:flutter/material.dart';
import 'demo/chart_painter.dart';
import 'direct_replay.dart';
import 'observed_option_replay.dart';

/// An offline view of one account-scoped event supplied by its ledger.
/// At an earlier cursor the final decision snapshot is deliberately hidden.
class DirectDecisionView extends StatefulWidget {
  final Map<String,dynamic> event;
  final List<Map<String,dynamic>> observations;
  final DateTime? asOf;
  const DirectDecisionView({super.key,required this.event,this.observations=const [],this.asOf});
  @override State<DirectDecisionView> createState()=>_DirectDecisionViewState();
}
class _DirectDecisionViewState extends State<DirectDecisionView> {
  DirectDecisionRecord? record;
  late final String raw;
  late final Map<String,dynamic> original;
  late final List<Map<String,dynamic>> observations;
  late final DateTime asOf;
  bool compare=false;
  int horizon=300,slippage=0;
  int cursor=0;
  @override void initState() {
    super.initState();raw=const JsonEncoder.withIndent('  ').convert(widget.event);
    original=jsonDecode(raw) as Map<String,dynamic>;
    observations=(jsonDecode(jsonEncode(widget.observations)) as List).cast<Map<String,dynamic>>();
    asOf=widget.asOf??DateTime.now().toUtc();
    try{record=DirectDecisionRecord.read(widget.event);cursor=record!.bars.length-1;}
    on FormatException {record=null;}
  }
  @override Widget build(BuildContext context) {
    final saved=record,event=saved?.original??original;
    final prefix=saved==null||cursor<0?null:saved.bars.take(cursor+1).toList();
    final finalCursor=saved==null||cursor==saved.bars.length-1;
    final outcome=compare?replayObservedOption({'entry':original,'observations':observations,
      'asOf':asOf.toIso8601String(),'horizonSeconds':horizon,'slippageCents':slippage}):null;
    return Scaffold(appBar:AppBar(title:const Text('إعادة عرض القرار المحفوظ')),
      body:ListView(padding:const EdgeInsets.all(16),children:[
        Text('${event['account']} • ${event['symbol']} • ${event['at']}'),
        const Text('قراءة محلية للأصل المحفوظ؛ لا اتصال بالسوق ولا تنفيذ. المحور لسعر السهم، وسعر الخيار في إيصال الصفقة.'),
        if(saved==null)const Text('تعذر التحقق من شموع القرار؛ الأصل النصي متاح دون توليد شارت بديل.',key:Key('replay-invalid')),
        if(saved!=null&&!saved.completeSource)const Text('مصدر قديم أو جزئي: لا يثبت احتواء كل شموع التحليل الأصلي.',key:Key('replay-partial')),
        if(prefix!=null&&prefix.isNotEmpty)...[
          Text('${prefix.length}/${saved!.bars.length} • UTC ${prefix.last.time.toIso8601String()}',key:const Key('replay-cursor')),
          if(saved.bars.length>1)Slider(key:const Key('replay-slider'),value:cursor.toDouble(),min:0,
            max:(saved.bars.length-1).toDouble(),divisions:saved.bars.length-1,
            onChanged:(value)=>setState(()=>cursor=value.round())),
          SizedBox(height:320,child:LayoutBuilder(builder:(context,c)=>CustomPaint(key:const Key('decision-replay-chart'),
            size:Size(c.maxWidth,320),painter:DemoCandlePainter(
              [for(var i=0;i<prefix.length;i++)prefix[i].candle(i)],{},[],
              finalCursor?directTradeMarkers(prefix,1,event['symbol'] as String,[event]):[],
              Theme.of(context).colorScheme,0,false,false,[],priceLabel:'STOCK • saved observation',
              timeLabels:{for(var i=0;i<prefix.length;i++)i:prefix[i].time.toIso8601String().substring(11,16)})))),
        ],
        if(finalCursor)...[
          Text('القرار الأصلي: ${event['decision']}',key:const Key('replay-original-reason')),
          Text('القاعدة الأصلية: ${event['evidence']?['rule']??"غير مسجلة"}'),
          const Text('لقطة البحث والإيصال أدناه محفوظان وقت الحدث. لا يُعاد تفسير القرار بخوارزمية أحدث.'),
          if(event['fill']?['side']=='BUY')...[
            OutlinedButton(key:const Key('option-replay-toggle'),onPressed:()=>setState(()=>compare=!compare),
              child:const Text('ماذا لو احتفظت؟ — عروض خيارات محفوظة')),
            if(compare)...[
              const Text('مقارنة لاحقة منفصلة؛ لا تعبئة ولا ربح محقق. يلزم عرض OPRA معلوم قبل وقت الخروج الافتراضي وبعمر ≤30 ثانية. لا استيفاء للفجوات ولا تقدير سعر من السهم.'),
              Wrap(spacing:8,children:[for(final seconds in [60,300])ChoiceChip(label:Text('${seconds~/60} دقيقة احتفاظ'),
                selected:horizon==seconds,onSelected:(_)=>setState(()=>horizon=seconds)),
                for(final cents in [0,5,10])ChoiceChip(label:Text('$cents سنت انزلاق معاكس'),selected:slippage==cents,
                  onSelected:(_)=>setState(()=>slippage=cents))]),
              Text(outcome!['status']=='OBSERVED_COUNTERFACTUAL'?
                'نتيجة افتراضية بعد العمولة والانزلاق: ${((outcome['pnlCents'] as int)/100).toStringAsFixed(2)} USD • المصدر ${outcome['source']}'
                :'لا نتيجة مالية متحققة من البيانات المتاحة: ${outcome['status']}',key:const Key('option-replay-result')),
              const Text('عمولة الخروج المفترضة 0.65 USD لكل عقد. كمية العرض الظاهرة حد أعلى؛ لا محاكاة أولوية طابور أو تنفيذ وسيط. المصادر المستوردة غير موثقة التوقيع.'),
              SelectableText(const JsonEncoder.withIndent('  ').convert(outcome),key:const Key('option-replay-json')),
            ],
          ],
          SelectableText(raw,key:const Key('replay-original-json')),
        ]else const Text('لم نصل إلى وقت القرار بعد؛ تُحجب لقطته وسببه وعلامته حتى نهاية المصدر المحفوظ.',key:Key('replay-before-decision')),
      ]));
  }
}
