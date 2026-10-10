# إعداد iPhone — V1.0 RC2

المشروع يضم تطبيق Flutter مشتركًا لـAndroid وiOS، العربية RTL، الثيمات الثلاثة وDemo محليًا. وجود مشروع Xcode ليس دليل بناء. النتيجة الفعلية للبناء الحالي، بما فيها رابط تشغيل macOS، مسجلة في تقرير GitHub Actions.

## إعادة البناء غير الموقع على macOS

يلزم macOS وXcode وFlutter الموافق لإصدار CI. من مجلد `mobile`:

```bash
export IOS_BUNDLE_ID=com.example.optionsTrader
bash scripts/bootstrap.sh
flutter analyze
flutter test
flutter build ios --release --no-codesign --build-name=1.0.0 --build-number=11
```

استبدل معرّف المثال بمعرّف تملكه لاحقًا. السكربت يتحقق من صيغة Reverse DNS ويحدّث Runner وRunnerTests. المدخل `bundle_id` في workflow iOS يدعم تخصيصه في تشغيل يدوي.

`Runner.app` غير الموقع ليس IPA قابلاً للتوزيع، ولا رابط TestFlight، ولا دليل تثبيت على iPhone. ملف النتائج السحابي يحتفظ بالبناء والاختبارات للفحص فقط.

## ما يلزم لاحقًا للتوزيع

- عضوية Apple Developer مناسبة، ومعرّف App ID وربطه بتطبيق App Store Connect.
- شهادة توزيع وProvisioning Profile أو إدارة توقيع آمنة على runner مخول.
- تخزين مفاتيح التوقيع وبيانات App Store Connect في قناة Secrets آمنة، خارج Git والمحادثة وArtifacts.
- بناء Archive موقع، تصدير IPA، رفعه ومعالجته ثم إضافة مختبري TestFlight وفق صلاحيات الحساب.
- اختبار جهاز فعلي للحفظ والتخطيط العربي والوصول والأداء والخلفية، ثم توثيق النتائج الفعلية.

لم تُشتر عضوية أو خدمة بناء ولم تُرفع نسخة إلى App Store Connect خلال هذه المهمة. لا حاجة لتوقيع iOS لإجراء اختبارات Flutter المشتركة على CI. Live وIBKR والمحلل الخارجي تبقى معطلة.
