import 'dart:convert';
import 'package:flutter/material.dart';
import 'demo/chart_painter.dart';
import 'direct_replay.dart';

/// An offline view of one account-scoped event supplied by its ledger.
/// At an earlier cursor the final decision snapshot is deliberately hidden.
class DirectDecisionView extends StatefulWidget {
  final Map<String,dynamic> event;
  const DirectDecisionView({super.key,required this.event});
  @override State<DirectDecisionView> createState()=>_DirectDecisionViewState();
}
class _DirectDecisionViewState extends State<DirectDecisionView> {
  DirectDecisionRecord? record;
  late final String raw;
  int cursor=0;
  @override void initState() {
    super.initState();raw=const JsonEncoder.withIndent('  ').convert(widget.event);
    try{record=DirectDecisionRecord.read(widget.event);cursor=record!.bars.length-1;}
    on FormatException {record=null;}
  }
  @override Widget build(BuildContext context) {
    final saved=record,event=saved?.original??widget.event;
    final prefix=saved==null||cursor<0?null:saved.bars.take(cursor+1).toList();
    final finalCursor=saved==null||cursor==saved.bars.length-1;
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
          SelectableText(raw,key:const Key('replay-original-json')),
        ]else const Text('لم نصل إلى وقت القرار بعد؛ تُحجب لقطته وسببه وعلامته حتى نهاية المصدر المحفوظ.',key:Key('replay-before-decision')),
      ]));
  }
}
