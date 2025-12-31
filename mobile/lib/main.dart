import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'config/theme.dart';
import 'screens/home_screen.dart';
import 'services/remote_command_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 初始化远程命令服务
  RemoteCommandService.instance.init();

  runApp(const ProviderScope(child: MyApp()));
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Mule',
      debugShowCheckedModeBanner: false,
      theme: MuleTheme.light,
      darkTheme: MuleTheme.dark,
      themeMode: ThemeMode.system,
      home: const HomeScreen(),
    );
  }
}
