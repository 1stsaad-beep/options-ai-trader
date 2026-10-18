import 'package:flutter/material.dart';
import 'package:trader_core/trader_core.dart';

import '../services/app_controller.dart';

/// Add a new account (always created in Paper mode) or edit an existing
/// account's keys when [editAccountId] is given.
class AddAccountScreen extends StatefulWidget {
  final AppController controller;
  final String? editAccountId;
  const AddAccountScreen({super.key, required this.controller, this.editAccountId});

  @override
  State<AddAccountScreen> createState() => _AddAccountScreenState();
}

class _AddAccountScreenState extends State<AddAccountScreen> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _cash = TextEditingController(text: '10000');
  final Map<String, TextEditingController> _fields = {};
  BrokerKind _broker = BrokerKind.simulator;
  bool _saving = false;
  String? _message;

  bool get _editing => widget.editAccountId != null;

  @override
  void initState() {
    super.initState();
    final rt = _editing ? widget.controller.account(widget.editAccountId!) : null;
    if (rt != null) {
      _broker = rt.profile.broker;
      _name.text = rt.profile.name;
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _cash.dispose();
    for (final c in _fields.values) {
      c.dispose();
    }
    super.dispose();
  }

  TextEditingController _ctl(String key) => _fields.putIfAbsent(key, TextEditingController.new);

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _message = null;
    });
    final creds = {for (final f in BrokerCredentialSpec.forKind(_broker)) f.key: _ctl(f.key).text.trim()};
    String id;
    if (_editing) {
      id = widget.editAccountId!;
      await widget.controller.updateCredentials(id, creds);
    } else {
      final cash = (double.tryParse(_cash.text.trim()) ?? 10000) * 100;
      final p = await widget.controller.addAccount(
        name: _name.text.trim(),
        broker: _broker,
        credentials: creds,
        startingCashCents: cash.round(),
      );
      id = p.id;
    }
    final error = await widget.controller.testConnection(id);
    if (!mounted) return;
    setState(() {
      _saving = false;
      _message = error == null ? 'تم الاتصال بنجاح' : 'تم الحفظ، لكن فشل الاتصال: $error';
    });
    if (error == null) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    final spec = BrokerCredentialSpec.forKind(_broker);
    return Scaffold(
      appBar: AppBar(title: Text(_editing ? 'تعديل المفاتيح' : 'إضافة حساب')),
      body: Form(
        key: _form,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (!_editing) ...[
              TextFormField(
                controller: _name,
                decoration: const InputDecoration(labelText: 'اسم الحساب', hintText: 'مثال: Alpaca تجريبي 1'),
                validator: (v) => (v == null || v.trim().isEmpty) ? 'أدخل اسمًا' : null,
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<BrokerKind>(
                initialValue: _broker,
                decoration: const InputDecoration(labelText: 'الوسيط'),
                items: [
                  for (final k in BrokerKind.values)
                    if (widget.controller.registry.supports(k)) DropdownMenuItem(value: k, child: Text(k.arabic)),
                ],
                onChanged: (k) => setState(() => _broker = k ?? BrokerKind.simulator),
              ),
              const SizedBox(height: 12),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    _broker == BrokerKind.simulator
                        ? 'المحاكي الداخلي: أموال وهمية وأسعار اصطناعية، لا يحتاج مفاتيح أو إنترنت.'
                        : 'يُنشأ الحساب في وضع Paper دائمًا. استخدم مفاتيح حساب Paper من ${_broker.arabic}. '
                            'تُحفظ المفاتيح مشفرة في خزنة الجهاز فقط ولا تُرسل لأي جهة غير الوسيط.',
                  ),
                ),
              ),
              if (_broker == BrokerKind.simulator)
                TextFormField(
                  controller: _cash,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: 'رأس المال الوهمي (دولار)'),
                  validator: (v) => (double.tryParse(v ?? '') ?? 0) >= 500 ? null : 'الحد الأدنى 500 دولار',
                ),
            ],
            for (final f in spec)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: TextFormField(
                  controller: _ctl(f.key),
                  obscureText: f.secret,
                  autocorrect: false,
                  enableSuggestions: false,
                  textDirection: TextDirection.ltr,
                  decoration: InputDecoration(labelText: f.labelAr, helperText: f.hintAr, helperMaxLines: 3),
                  validator: (v) => !f.optional && (v == null || v.trim().isEmpty) ? 'مطلوب' : null,
                ),
              ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _saving ? null : _save,
              icon: _saving
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.save),
              label: const Text('حفظ واختبار الاتصال'),
            ),
            if (_message != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_message!)),
          ],
        ),
      ),
    );
  }
}
