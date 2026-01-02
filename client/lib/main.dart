import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_web_plugins/url_strategy.dart';

import 'config/theme.dart';
import 'models/server_config.dart';
import 'router.dart';
import 'services/auto_connect_service.dart';
import 'services/remote_command_service.dart';

/// 全局变量：启动时检测到的自动连接配置
ServerConfig? _pendingAutoConnectServer;

/// 获取待处理的自动连接服务器
ServerConfig? getPendingAutoConnectServer() {
  final server = _pendingAutoConnectServer;
  _pendingAutoConnectServer = null; // 只获取一次
  return server;
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 使用 path URL 策略（去掉 #）
  usePathUrlStrategy();

  // ignore: avoid_print
  print('====== Mule App Starting - Build v20260103_router_v2 ======');

  // 初始化远程命令服务
  RemoteCommandService.instance.init();

  // 检查 URL 中的自动连接参数
  _pendingAutoConnectServer = await AutoConnectService.instance.checkAndProcessAutoConnect();

  runApp(const ProviderScope(child: MyApp()));
}

class MyApp extends ConsumerWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);

    return MaterialApp.router(
      title: 'Mule',
      debugShowCheckedModeBanner: false,
      theme: MuleTheme.light,
      darkTheme: MuleTheme.dark,
      themeMode: ThemeMode.system,
      routerConfig: router,
    );
  }
}
