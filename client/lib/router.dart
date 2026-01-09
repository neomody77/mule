import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'config/theme.dart';
import 'models/chat_session.dart';
import 'models/server_config.dart';
import 'providers/providers.dart';
import 'screens/home_screen.dart';
import 'screens/session_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/file_manager_screen.dart';
import 'screens/file_viewer_screen.dart';
import 'screens/workspace_detail_screen.dart';

/// 路由路径常量
class AppRoutes {
  static const home = '/';
  static const settings = '/settings';
  static const workspace = '/workspace/:serverId/:workspaceId';
  static const session = '/session/:serverId/:workspaceId/:sessionId';
  static const files = '/files/:serverId/:workspaceId';
  static const fileViewer = '/files/:serverId/:workspaceId/view';

  /// 构建 workspace 详情路径
  static String workspacePath(String serverId, String workspaceId) =>
      '/workspace/$serverId/$workspaceId';

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
  // 让 push/pop 也更新 URL（GoRouter 8.0+ 默认关闭）
  GoRouter.optionURLReflectsImperativeAPIs = true;

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

      // Workspace 详情页（列表模式）
      GoRoute(
        path: AppRoutes.workspace,
        name: 'workspace',
        builder: (context, state) {
          final serverId = state.pathParameters['serverId']!;
          final workspaceId = state.pathParameters['workspaceId']!;

          return _WorkspaceLoader(
            serverId: serverId,
            workspaceId: workspaceId,
          );
        },
      ),

      // Session 页面
      GoRoute(
        path: AppRoutes.session,
        name: 'session',
        builder: (context, state) {
          final serverId = state.pathParameters['serverId']!;
          final workspaceId = state.pathParameters['workspaceId']!;
          final sessionId = state.pathParameters['sessionId']!;

          return _SessionLoader(
            serverId: serverId,
            workspaceId: workspaceId,
            sessionId: sessionId,
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

/// Session 加载器 - 等待数据加载后显示 SessionScreen
class _SessionLoader extends ConsumerStatefulWidget {
  final String serverId;
  final String workspaceId;
  final String sessionId;

  const _SessionLoader({
    required this.serverId,
    required this.workspaceId,
    required this.sessionId,
  });

  @override
  ConsumerState<_SessionLoader> createState() => _SessionLoaderState();
}

class _SessionLoaderState extends ConsumerState<_SessionLoader> {
  bool _initialized = false;
  bool _notFound = false;

  @override
  void initState() {
    super.initState();
    _initData();
  }

  Future<void> _initData() async {
    // 等待 provider 初始化完成
    await Future.delayed(const Duration(milliseconds: 100));

    if (!mounted) return;

    // 检查数据是否已加载
    final serverState = ref.read(serverProvider);
    final sessionState = ref.read(sessionProvider);

    final server = serverState.getServer(widget.serverId);
    final session = sessionState.getSession(widget.sessionId);

    if (server != null && session != null) {
      setState(() => _initialized = true);
      return;
    }

    // 如果没有数据，尝试等待更长时间（数据可能正在从存储加载）
    for (var i = 0; i < 20; i++) {
      await Future.delayed(const Duration(milliseconds: 100));
      if (!mounted) return;

      final serverState = ref.read(serverProvider);
      final sessionState = ref.read(sessionProvider);

      final server = serverState.getServer(widget.serverId);
      final session = sessionState.getSession(widget.sessionId);

      if (server != null && session != null) {
        setState(() => _initialized = true);
        return;
      }
    }

    // 超时，跳转到首页
    if (mounted) {
      setState(() => _notFound = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_notFound) {
      // 数据加载超时，显示错误并提供返回首页按钮
      return Scaffold(
        appBar: AppBar(title: const Text('Session Not Found')),
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.error_outline, size: 64, color: ZiaOlive.shade200),
              const SizedBox(height: 16),
              const Text('Session not found or data not loaded'),
              const SizedBox(height: 24),
              FilledButton(
                onPressed: () => context.go(AppRoutes.home),
                child: const Text('Go Home'),
              ),
            ],
          ),
        ),
      );
    }

    if (!_initialized) {
      // 显示加载中
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const CircularProgressIndicator(),
              const SizedBox(height: 16),
              Text(
                'Loading session...',
                style: TextStyle(color: ZiaOlive.shade300),
              ),
            ],
          ),
        ),
      );
    }

    // 数据已加载，显示 SessionScreen
    final serverState = ref.watch(serverProvider);
    final sessionState = ref.watch(sessionProvider);

    final server = serverState.getServer(widget.serverId);
    final session = sessionState.getSession(widget.sessionId);

    if (server == null || session == null) {
      // 数据在加载后又丢失了
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) context.go(AppRoutes.home);
      });
      return const SizedBox.shrink();
    }

    return SessionScreen(
      session: session,
      server: server,
    );
  }
}

/// Workspace 加载器 - 等待数据加载后显示 WorkspaceDetailScreen
class _WorkspaceLoader extends ConsumerStatefulWidget {
  final String serverId;
  final String workspaceId;

  const _WorkspaceLoader({
    required this.serverId,
    required this.workspaceId,
  });

  @override
  ConsumerState<_WorkspaceLoader> createState() => _WorkspaceLoaderState();
}

class _WorkspaceLoaderState extends ConsumerState<_WorkspaceLoader> {
  bool _initialized = false;
  bool _notFound = false;

  @override
  void initState() {
    super.initState();
    _initData();
  }

  Future<void> _initData() async {
    await Future.delayed(const Duration(milliseconds: 100));

    if (!mounted) return;

    // 检查数据是否已加载
    final serverState = ref.read(serverProvider);
    final server = serverState.getServer(widget.serverId);
    final workspaces = serverState.getWorkspaces(widget.serverId);
    final workspace = workspaces.where((w) => w.id == widget.workspaceId).firstOrNull;

    if (server != null && workspace != null) {
      setState(() => _initialized = true);
      return;
    }

    // 等待数据加载
    for (var i = 0; i < 20; i++) {
      await Future.delayed(const Duration(milliseconds: 100));
      if (!mounted) return;

      final serverState = ref.read(serverProvider);
      final server = serverState.getServer(widget.serverId);
      final workspaces = serverState.getWorkspaces(widget.serverId);
      final workspace = workspaces.where((w) => w.id == widget.workspaceId).firstOrNull;

      if (server != null && workspace != null) {
        setState(() => _initialized = true);
        return;
      }
    }

    if (mounted) {
      setState(() => _notFound = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_notFound) {
      return Scaffold(
        appBar: AppBar(title: const Text('Workspace Not Found')),
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.error_outline, size: 64, color: ZiaOlive.shade200),
              const SizedBox(height: 16),
              const Text('Workspace not found or data not loaded'),
              const SizedBox(height: 24),
              FilledButton(
                onPressed: () => context.go(AppRoutes.home),
                child: const Text('Go Home'),
              ),
            ],
          ),
        ),
      );
    }

    if (!_initialized) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const CircularProgressIndicator(),
              const SizedBox(height: 16),
              Text(
                'Loading workspace...',
                style: TextStyle(color: ZiaOlive.shade300),
              ),
            ],
          ),
        ),
      );
    }

    final serverState = ref.watch(serverProvider);
    final server = serverState.getServer(widget.serverId);
    final workspaces = serverState.getWorkspaces(widget.serverId);
    final workspace = workspaces.where((w) => w.id == widget.workspaceId).firstOrNull;

    if (server == null || workspace == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) context.go(AppRoutes.home);
      });
      return const SizedBox.shrink();
    }

    return WorkspaceDetailScreen(
      server: server,
      workspace: workspace,
    );
  }
}
