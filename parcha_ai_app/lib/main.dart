import 'package:flutter/material.dart';

import 'home_screen.dart';
import 'theme.dart';

void main() {
  runApp(const ParchaAiApp());
}

class ParchaAiApp extends StatelessWidget {
  const ParchaAiApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ParchaAI',
      debugShowCheckedModeBanner: false,
      theme: getAppTheme(),
      home: const HomeScreen(),
    );
  }
}
