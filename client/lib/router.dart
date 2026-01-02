import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'models/chat_session.dart';
import 'models/server_config.dart';
import 'providers/providers.dart';
import 'screens/home_screen.dart';
import 'screens/session_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/file_manager_screen.dart';
import 'screens/file_viewer_screen.dart';

/// 路由路径常量
class AppRoutes {
  static const home = '/';
  static const settings = '/settings';
  static const session = '/session/:serverId/:workspaceId/:sessionId';
  static const files = '/files/:serverId/:workspaceId';
  static const fileViewer = '/files/:serverId/:workspaceId/view';

  /// 构建 session 路径
  static String sessionPath(String serverId, String workspaceId, String sessionId) =>
      '/session/$serverId/$workspaceId/$sessionId';

  /// 构建 files 路径
  static String filesPath(String serverId, String workspaceId) =>
      '/files/$serverId/$workspaceId';

  /// 构建 file viewer 路径
  static String fileViewerPath(String serverId, String workspaceId, String filePath, String fileName) =>
      '/files/$serverId/$workspaceId/view?path=${Uri.encodeComponent(filePath)}&name=${Uri.encodeComponent(fileName)}';
}

/// GoRouter provider
final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: AppRoutes.home,
    debugLogDiagnostics: true,
    routes: [
      // 首页
      GoRoute(
        path: AppRoutes.home,
        name: 'home',
        builder: (context, state) => const HomeScreen(),
      ),

      // 设置页
      GoRoute(
        path: AppRoutes.settings,
        name: 'settings',
        builder: (context, state) => const SettingsScreen(),
      ),

      // Session 页面
      GoRoute(
        path: AppRoutes.session,
        name: 'session',
        builder: (context, state) {
          final serverId = state.pathParameters['serverId']!;
          final workspaceId = state.pathParameters['workspaceId']!;
          final sessionId = state.pathParameters['sessionId']!;

          // 从 provider 获取 session 和 server
          final container = ProviderScope.containerOf(context);
          final serverState = container.read(serverProvider);
          final sessionState = container.read(sessionProvider);

          final server = serverState.getServer(serverId);
          final session = sessionState.getSession(sessionId);

          // 如果找不到，返回首页
          if (server == null || session == null) {
            return const HomeScreen();
          }

          return SessionScreen(
            session: session,
            server: server,
          );
        },
      ),

      // 文件管理器
      GoRoute(
        path: AppRoutes.files,
        name: 'files',
        builder: (context, state) {
          final serverId = state.pathParameters['serverId']!;
          final workspaceId = state.pathParameters['workspaceId']!;

          final container = ProviderScope.containerOf(context);
          final serverState = container.read(serverProvider);
          final server = serverState.getServer(serverId);

          if (server == null) {
            return const HomeScreen();
          }

          return FileManagerScreen(
            server: server,
            workspaceId: workspaceId,
          );
        },
      ),

      // 文件查看器
      GoRoute(
        path: AppRoutes.fileViewer,
        name: 'fileViewer',
        builder: (context, state) {
          final serverId = state.pathParameters['serverId']!;
          final workspaceId = state.pathParameters['workspaceId']!;
          final filePath = state.uri.queryParameters['path'] ?? '';
          final fileName = state.uri.queryParameters['name'] ?? 'File';

          final container = ProviderScope.containerOf(context);
          final serverState = container.read(serverProvider);
          final server = serverState.getServer(serverId);

          if (server == null) {
            return const HomeScreen();
          }

          return FileViewerScreen(
            server: server,
            workspaceId: workspaceId,
            filePath: filePath,
            fileName: fileName,
          );
        },
      ),
    ],

    // 错误页面
    errorBuilder: (context, state) => Scaffold(
      appBar: AppBar(title: const Text('Page Not Found')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 64, color: Colors.grey),
            const SizedBox(height: 16),
            Text('Page not found: ${state.uri}'),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: () => context.go(AppRoutes.home),
              child: const Text('Go Home'),
            ),
          ],
        ),
      ),
    ),
  );
});
