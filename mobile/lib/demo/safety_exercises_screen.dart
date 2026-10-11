import 'package:flutter/material.dart';
import 'safety_exercises.dart';

class DemoSafetyExercisesScreen extends StatefulWidget {
  const DemoSafetyExercisesScreen({super.key});
  @override
  State<DemoSafetyExercisesScreen> createState()=>_DemoSafetyExercisesScreenState();
}
class _DemoSafetyExercisesScreenState extends State<DemoSafetyExercisesScreen> {
  List<DemoExerciseResult>? results;
  @override
  Widget build(BuildContext context)=>Scaffold(
    appBar:AppBar(title:const Text('اختبارات حماية معزولة')),
    body:ListView(padding:const EdgeInsets.all(16),children:[
      const Text('تعمل الاختبارات بمحرك Demo الفعلي في ذاكرة مستقلة. لا تُقرأ حساباتك ولا تُغيّر مخاطرك أو بياناتك المحفوظة. لا اتصال خارجي.'),
      const Text('حساب الاختبار: 20,000 دولار اصطناعي؛ وقف 20% وجني 30%. حالة الوقف المتحرك: 20% مع هدف 500% لعزل شرطه. هذه إعدادات العينة فقط.'),
      const Text('العكس يستخدم إشارة PUT الكمية في AAPL وإشارة CALL في NVDA؛ لا يختلق إشارة معاكسة لسوق Demo المختار.'),
      FilledButton(key:const Key('run-safety-exercises'),onPressed:()=>setState(()=>results=DemoSafetyExercises.run()),
        child:const Text('تشغيل الاختبارات الخمسة')),
      if(results!=null) Text('نجح ${results!.where((r)=>r.passed).length} من ${results!.length}',key:const Key('exercise-summary')),
      for(final r in results??<DemoExerciseResult>[]) Card(child:ExpansionTile(
        key:Key('exercise-${r.name}'),initiallyExpanded:!r.passed,
        leading:Icon(r.passed?Icons.check_circle:Icons.error_outline),
        title:Text('${r.name} • ${r.passed?"ناجح":"فشل"}'),
        children:[for(final line in r.evidence)ListTile(dense:true,title:Text(line))])),
      const Text('النجاح يثبت السيناريو الاصطناعي المعروض فقط؛ لا يثبت تنفيذ وسيط أو جهاز لم يُختبر.'),
    ]));
}
