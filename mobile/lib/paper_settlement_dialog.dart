import 'package:flutter/material.dart';
import 'market_paper.dart';
import 'paper_settlement.dart';

/// Explicit manual paper evidence, separate from qualified OPRA quote fills.
/// No external order path; preview is invalidated on every field change.
class PaperSettlementDialog extends StatefulWidget {
  final MarketPaper paper;
  final String accountId,contract;
  final bool delivery;
  const PaperSettlementDialog({super.key,required this.paper,required this.accountId,
    required this.contract,this.delivery=false});
  @override State<PaperSettlementDialog> createState()=>_PaperSettlementDialogState();
}
class _PaperSettlementDialogState extends State<PaperSettlementDialog> {
  final quantity=TextEditingController(text:'1'),price=TextEditingController(),fee=TextEditingController(text:'0.00');
  final reference=TextEditingController(),effective=TextEditingController();
  late String action;
  late final String receiptId;
  PaperRow? request,result;
  String? error;
  bool saving=false;
  @override void initState() {
    super.initState();action=widget.delivery?'SELL_DELIVERY':'EXERCISE';
    effective.text=widget.paper.now().toUtc().toIso8601String();
    receiptId='manual-${widget.paper.now().microsecondsSinceEpoch}-${widget.paper.journal.length}';
  }
  @override void dispose() {
    for(final c in [quantity,price,fee,reference,effective]){c.dispose();}
    super.dispose();
  }
  int cents(String raw) {
    final match=RegExp(r'^(\d+)(?:\.(\d{1,2}))?$').firstMatch(raw.trim());
    if(match==null)throw const FormatException('أدخل مبلغ USD غير سالب بمنزلتين عشريتين كحد أقصى.');
    return int.parse(match[1]!)*100+int.parse((match[2]??'').padRight(2,'0'));
  }
  void changed(String _) =>setState((){request=null;result=null;error=null;});
  void preview() {
    try {
      final a=widget.paper.account(widget.accountId);
      if(!widget.paper.ready||widget.paper.busy||a['enabled']==true)throw StateError('أوقف تقييم الحساب أولًا.');
      final r=<String,dynamic>{'id':receiptId,'action':action,'contract':widget.contract,
        'quantity':int.parse(quantity.text.trim()),'underlyingCents':cents(price.text),'feeCents':cents(fee.text),
        'effectiveAt':effective.text.trim(),'recordedAt':widget.paper.now().toUtc().toIso8601String(),
        'source':'manual_paper','reference':reference.text.trim()};
      final symbol=RegExp(r'^([A-Z]{1,6})\d').firstMatch(widget.contract)!.group(1);
      final projected=projectPaperSettlement((a['positions'] as Map)[symbol] as Map?,
        (a['deliveryPositions'] as Map?)?[symbol] as Map?,a['cash'] as int,r,widget.paper.now());
      setState((){request=r;result=projected;error=null;});
    }catch(e){setState((){request=null;result=null;error='لا يمكن اعتماد هذه البيانات: $e';});}
  }
  Future<void> save() async {
    if(request==null||saving)return;
    setState(()=>saving=true);
    try {
      await widget.paper.settle(widget.accountId,request!);
      if(mounted)Navigator.pop(context,true);
    }catch(e){if(mounted)setState((){saving=false;error='لم تُعتمد التسوية: $e';});}
  }
  Widget field(TextEditingController controller,String label,String key,{bool numeric=false})=>TextField(
    key:ValueKey(key),controller:controller,enabled:!saving,onChanged:changed,
    keyboardType:numeric?const TextInputType.numberWithOptions(decimal:true):TextInputType.text,
    decoration:InputDecoration(labelText:label));
  @override Widget build(BuildContext context)=>AlertDialog(
    title:const Text('إيصال تسوية ورقي صريح'),
    content:SizedBox(width:480,child:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.start,children:[
      Text(widget.contract),
      const Text('تسجيل محاسبي افتراضي يدوي، وليس تأكيد وسيط أو سعر OPRA أو أمر تداول. لا ممارسة تلقائية. الأسهم المستلمة بلا تقييم سوقي وتمنع دخول خيارات جديدة حتى تصفيتها ورقيًا.'),
      DropdownButtonFormField<String>(key:const Key('settlement-action'),initialValue:action,isExpanded:true,
        items:widget.delivery?const [DropdownMenuItem(value:'SELL_DELIVERY',child:Text('بيع الأسهم المستلمة ورقيًا'))]:[
          const DropdownMenuItem(value:'EXERCISE',child:Text('ممارسة وتحويل إلى أسهم / نقد')),
          const DropdownMenuItem(value:'EXPIRE_WORTHLESS',child:Text('انتهاء بلا قيمة — رصد عند الإقفال')),
          if(RegExp(r'P\d{8}$').hasMatch(widget.contract))const DropdownMenuItem(value:'BUY_FOR_PUT',child:Text('اقتناء ورقي لأسهم تسليم Put المملوك'))],
        onChanged:saving?null:(v){if(v!=null){action=v;changed('');}}),
      field(quantity,widget.delivery||action=='BUY_FOR_PUT'?'عدد الأسهم':'عدد العقود','settlement-quantity',numeric:true),
      field(price,'سعر السهم في الرصد (USD)','settlement-price',numeric:true),
      field(fee,'رسوم الإيصال الإجمالية (USD)','settlement-fee',numeric:true),
      field(effective,'وقت الحدث ISO مع منطقة زمنية؛ الانتهاء عند إقفال الجلسة','settlement-effective'),
      field(reference,'مرجع الرصد الورقي الأصلي','settlement-reference'),
      if(error!=null)Text(error!,key:const Key('settlement-error')),
      if(result!=null)Text('تغير النقد: ${(result!['cashDelta']/100).toStringAsFixed(2)} USD\n'
        'تغير الأسهم: ${result!['shareDelta']} • أساس التكلفة: ${(result!['shareBasisDelta']/100).toStringAsFixed(2)} USD\n'
        'P&L محقق: ${(result!['realizedPnl']/100).toStringAsFixed(2)} USD',key:const Key('settlement-preview-result')),
    ]))),
    actions:[
      TextButton(onPressed:saving?null:()=>Navigator.pop(context),child:const Text('إلغاء')),
      OutlinedButton(key:const Key('settlement-preview'),onPressed:saving?null:preview,child:const Text('معاينة الأثر')),
      FilledButton(key:const Key('settlement-save'),onPressed:saving||request==null?null:save,child:const Text('اعتماد الإيصال الورقي')),
    ],
  );
}
