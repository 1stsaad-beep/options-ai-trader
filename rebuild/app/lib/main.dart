import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'screens/accounts_screen.dart';
import 'services/app_controller.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final controller = AppController()..load();
  runApp(OptionsAiTraderApp(controller: controller));
}

class OptionsAiTraderApp extends StatelessWidget {
  final AppController controller;
  const OptionsAiTraderApp({super.key, required this.controller});

  @override
  Widget build(BuildContext context) {
    ThemeData theme(Brightness b) => ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF0F766E), brightness: b),
          useMaterial3: true,
        );
    return MaterialApp(
      title: 'Options AI Trader',
      debugShowCheckedModeBanner: false,
      locale: const Locale('ar'),
      supportedLocales: const [Locale('ar')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      // Arabic locale makes every route RTL; the builder guarantees it even if
      // a widget overrides the locale.
      builder: (context, child) => Directionality(textDirection: TextDirection.rtl, child: child!),
      theme: theme(Brightness.light),
      darkTheme: theme(Brightness.dark),
      themeMode: ThemeMode.system,
      home: AccountsScreen(controller: controller),
    );
  }
}
