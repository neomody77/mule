import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../config/theme.dart';
import '../main.dart' show getPendingAutoConnectServer;
import '../models/chat_session.dart';
import '../models/server_config.dart';
import '../models/workspace.dart';
import '../providers/providers.dart';
import '../providers/ui_state_provider.dart';
import '../router.dart';
import '../widgets/command_target.dart';

/// 主页 - Workspace 卡片视图
class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  @override
  void initState() {
    super.initState();
    // ignore: avoid_print
    print('>>>>>> [HomeScreen] initState called <<<<<<');
    WidgetsBinding.instance.addPostFrameCallback((_) {
      // ignore: avoid_print
      print('>>>>>> [HomeScreen] postFrameCallback started <<<<<<');
      _initAsync();
    });
  }

  Future<void> _initAsync() async {
    try {
      debugPrint('[HomeScreen] _initAsync started');

      // 检查是否有自动连接的服务器
      await _handleAutoConnect();

      // 刷新服务器列表，获取返回的 workspaces
      debugPrint('[HomeScreen] Calling refreshAllServers...');
      final serverWorkspaces = await ref.read(serverProvider.notifier).refreshAllServers();
      debugPrint('[HomeScreen] refreshAllServers returned ${serverWorkspaces.length} servers with workspaces');

      // 同步所有 workspace 的 sessions（使用返回值，避免时序问题）
      debugPrint('[HomeScreen] Calling _syncAllSessions...');
      await _syncAllSessions(serverWorkspaces);
      debugPrint('[HomeScreen] _syncAllSessions completed');

      // App 启动时，只要有 server 就建立 WebSocket 连接
      final servers = ref.read(serverProvider).servers;
      if (servers.isNotEmpty) {
        ref.read(sessionProvider.notifier).connectAllServers(servers);
      }
    } catch (e, stack) {
      debugPrint('[HomeScreen] _initAsync error: $e');
      debugPrint('[HomeScreen] Stack: $stack');
    }
  }

  /// 处理自动连接
  Future<void> _handleAutoConnect() async {
    final autoConnectServer = getPendingAutoConnectServer();
    if (autoConnectServer == null) return;

    // 检查是否已存在相同配置的服务器
    final existingServers = ref.read(serverProvider).servers;
    final existingServer = existingServers.where(
      (s) => s.host == autoConnectServer.host &&
             s.port == autoConnectServer.port &&
             s.token == autoConnectServer.token,
    ).firstOrNull;

    ServerConfig serverToUse;

    if (existingServer != null) {
      // 使用已存在的服务器
      serverToUse = existingServer;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Using existing server: ${existingServer.name}')),
        );
      }
    } else {
      // 添加新服务器
      serverToUse = await ref.read(serverProvider.notifier).addServer(
        name: autoConnectServer.name,
        host: autoConnectServer.host,
        port: autoConnectServer.port,
        token: autoConnectServer.token,
        useHttps: autoConnectServer.useHttps,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Added server: ${serverToUse.name}')),
        );
      }
    }

    // 等待服务器刷新完成
    await ref.read(serverProvider.notifier).refreshServer(serverToUse.id);

    // 获取 default workspace 并创建新 session
    final workspaces = ref.read(serverProvider).getWorkspaces(serverToUse.id);
    if (workspaces.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('No workspaces found on server')),
        );
      }
      return;
    }

    // 优先选择 default workspace
    final defaultWorkspace = workspaces.firstWhere(
      (w) => w.id == 'default',
      orElse: () => workspaces.first,
    );

    // 创建新 session (不传 name，让 provider 使用 ID 前 8 位)
    final session = await ref.read(sessionProvider.notifier).createSession(
      serverId: serverToUse.id,
      workspaceId: defaultWorkspace.id,
      workspaceName: defaultWorkspace.name,
    );

    // 连接服务器
    ref.read(sessionProvider.notifier).connectAllServers([serverToUse]);

    // 设置为活跃 session 并导航
    ref.read(sessionProvider.notifier).setActiveSession(session.id);

    if (mounted) {
      context.go(AppRoutes.sessionPath(
        serverToUse.id,
        defaultWorkspace.id,
        session.id,
      ));
    }
  }

  /// 同步所有 workspace 的 sessions
  /// [serverWorkspaces] 是从 refreshAllServers 返回的结果，避免时序问题
  Future<void> _syncAllSessions([Map<ServerConfig, List<WorkspaceInfo>>? serverWorkspaces]) async {
    final sessionNotifier = ref.read(sessionProvider.notifier);
    debugPrint('[HomeScreen] _syncAllSessions: serverWorkspaces=${serverWorkspaces?.length ?? "null"}');

    // 如果有传入的 serverWorkspaces，直接使用（避免时序问题）
    if (serverWorkspaces != null && serverWorkspaces.isNotEmpty) {
      debugPrint('[HomeScreen] Using passed serverWorkspaces');
      for (final entry in serverWorkspaces.entries) {
        final server = entry.key;
        final workspaces = entry.value;
        debugPrint('[HomeScreen] Syncing ${workspaces.length} workspaces for ${server.name}');
        for (final ws in workspaces) {
          debugPrint('[HomeScreen] Syncing workspace ${ws.id}');
          await sessionNotifier.syncSessionsFromServer(server, ws.id, ws.name);
        }
      }
      return;
    }

    // 否则从 state 读取（用于手动刷新场景）
    debugPrint('[HomeScreen] Using state.servers');
    final serverState = ref.read(serverProvider);
    for (final server in serverState.servers) {
      final workspaces = serverState.getWorkspaces(server.id);
      if (workspaces.isEmpty) continue;

      for (final ws in workspaces) {
        await sessionNotifier.syncSessionsFromServer(server, ws.id, ws.name);
      }
    }
  }

  void _showNewSessionDialog({String? serverId, String? workspaceId, String? workspaceName}) {
    final serverState = ref.read(serverProvider);

    if (serverState.servers.isEmpty) {
      _showAddServerFirst();
      return;
    }

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _NewSessionSheet(
        initialServerId: serverId,
        initialWorkspaceId: workspaceId,
        initialWorkspaceName: workspaceName,
      ),
    );
  }

  void _showAddServerFirst() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('No Servers'),
        content: const Text(
          'Please add a server first in Settings.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(context);
              context.push(AppRoutes.settings);
            },
            child: const Text('Go to Settings'),
          ),
        ],
      ),
    );
  }

  void _showCreateWorkspaceDialog() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => const _CreateWorkspaceSheet(),
    );
  }

  void _openSession(ChatSession session) {
    final serverState = ref.read(serverProvider);
    final server = serverState.getServer(session.serverId);
    if (server == null) return;

    ref.read(sessionProvider.notifier).setActiveSession(session.id);

    context.go(AppRoutes.sessionPath(
      server.id,
      session.workspaceId,
      session.id,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final serverState = ref.watch(serverProvider);
    final sessionState = ref.watch(sessionProvider);
    final uiState = ref.watch(uiStateProvider);
    final viewMode = uiState.workspaceViewMode;

    return ScreenScope(
      screenId: 'home',
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Mule'),
          actions: [
            // 视图切换按钮
            IconButton(
              icon: Icon(
                viewMode == WorkspaceViewMode.card
                    ? Icons.view_list_outlined
                    : Icons.grid_view_outlined,
              ),
              onPressed: () {
                ref.read(uiStateProvider.notifier).toggleViewMode();
              },
              tooltip: viewMode == WorkspaceViewMode.card ? 'List View' : 'Card View',
            ),
            IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: () async {
                final serverWorkspaces = await ref.read(serverProvider.notifier).refreshAllServers();
                await _syncAllSessions(serverWorkspaces);
              },
              tooltip: 'Refresh',
            ).withCommand('home.refresh', onTap: () async {
              final serverWorkspaces = await ref.read(serverProvider.notifier).refreshAllServers();
              await _syncAllSessions(serverWorkspaces);
            }),
            GestureDetector(
              onTap: () => context.go(AppRoutes.settings),
              child: const Padding(
                padding: EdgeInsets.all(8.0),
                child: Icon(Icons.settings_outlined),
              ),
            ),
          ],
        ),
        body: serverState.servers.isEmpty
            ? _buildEmptyServers()
            : viewMode == WorkspaceViewMode.card
                ? _buildWorkspaceCards(serverState, sessionState)
                : _buildWorkspaceList(serverState, sessionState),
        floatingActionButton: serverState.servers.isEmpty
            ? null
            : FloatingActionButton(
                onPressed: _showCreateWorkspaceDialog,
                tooltip: 'New Workspace',
                child: const Icon(Icons.create_new_folder_outlined),
              ).withCommand('home.create_workspace', onTap: _showCreateWorkspaceDialog),
      ),
    );
  }

  Widget _buildEmptyServers() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.dns_outlined,
            size: 64,
            color: ZiaOlive.shade200,
          ),
          const SizedBox(height: 16),
          Text(
            'No servers configured',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Text(
            'Add a server to get started',
            style: TextStyle(color: ZiaOlive.shade200),
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: () => context.go(AppRoutes.settings),
            icon: const Icon(Icons.add),
            label: const Text('Add Server'),
          ),
        ],
      ),
    );
  }

  Widget _buildWorkspaceCards(
    ServerState serverState,
    SessionState sessionState,
  ) {
    // 收集所有 workspace（从所有 server）
    final workspaceList = <_WorkspaceCardData>[];

    for (final server in serverState.servers) {
      final workspaces = serverState.getWorkspaces(server.id);
      final isOnline = serverState.isServerOnline(server.id);

      for (final ws in workspaces) {
        // 获取该 workspace 下的所有 sessions
        final sessions = sessionState
            .getSessionsForWorkspace(server.id, ws.id);

        workspaceList.add(_WorkspaceCardData(
          server: server,
          workspaceId: ws.id,
          workspaceName: ws.name,
          sessions: sessions,
          isServerOnline: isOnline,
        ));
      }
    }

    // 排序：default workspace 永远在最上面
    workspaceList.sort((a, b) {
      // default workspace 优先
      if (a.workspaceId == 'default' && b.workspaceId != 'default') return -1;
      if (a.workspaceId != 'default' && b.workspaceId == 'default') return 1;
      // 其余按名称排序
      return a.workspaceName.compareTo(b.workspaceName);
    });

    if (workspaceList.isEmpty) {
      return _buildNoWorkspaces();
    }

    return RefreshIndicator(
      onRefresh: () async {
        final serverWorkspaces = await ref.read(serverProvider.notifier).refreshAllServers();
        // 同步所有 workspace 的 sessions
        await _syncAllSessions(serverWorkspaces);
      },
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: workspaceList.length,
        itemBuilder: (context, index) {
          final data = workspaceList[index];
          return _WorkspaceCard(
            data: data,
            onNewSession: () => _showNewSessionDialog(
              serverId: data.server.id,
              workspaceId: data.workspaceId,
              workspaceName: data.workspaceName,
            ),
            onOpenSession: _openSession,
            onRenameSession: _showRenameDialog,
            onDeleteSession: _confirmDeleteSession,
            onDeleteWorkspace: data.workspaceId != 'default'
                ? () => _confirmDeleteWorkspace(data)
                : null,
          );
        },
      ),
    );
  }

  Widget _buildNoWorkspaces() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.folder_outlined,
            size: 64,
            color: ZiaOlive.shade200,
          ),
          const SizedBox(height: 16),
          Text(
            'No workspaces found',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Text(
            'Create workspaces on your server',
            style: TextStyle(color: ZiaOlive.shade200),
          ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: () {
              ref.read(serverProvider.notifier).refreshAllServers();
            },
            icon: const Icon(Icons.refresh),
            label: const Text('Refresh'),
          ),
        ],
      ),
    );
  }

  /// 列表视图模式 - 点击进入 workspace 详情页
  Widget _buildWorkspaceList(
    ServerState serverState,
    SessionState sessionState,
  ) {
    // 收集所有 workspace
    final workspaceList = <_WorkspaceCardData>[];

    for (final server in serverState.servers) {
      final workspaces = serverState.getWorkspaces(server.id);
      final isOnline = serverState.isServerOnline(server.id);

      for (final ws in workspaces) {
        final sessions = sessionState.getSessionsForWorkspace(server.id, ws.id);

        workspaceList.add(_WorkspaceCardData(
          server: server,
          workspaceId: ws.id,
          workspaceName: ws.name,
          sessions: sessions,
          isServerOnline: isOnline,
        ));
      }
    }

    // 排序：default workspace 在最上面
    workspaceList.sort((a, b) {
      if (a.workspaceId == 'default' && b.workspaceId != 'default') return -1;
      if (a.workspaceId != 'default' && b.workspaceId == 'default') return 1;
      return a.workspaceName.compareTo(b.workspaceName);
    });

    if (workspaceList.isEmpty) {
      return _buildNoWorkspaces();
    }

    return RefreshIndicator(
      onRefresh: () async {
        final serverWorkspaces = await ref.read(serverProvider.notifier).refreshAllServers();
        await _syncAllSessions(serverWorkspaces);
      },
      child: ListView.separated(
        padding: const EdgeInsets.symmetric(vertical: 8),
        itemCount: workspaceList.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final data = workspaceList[index];
          return _WorkspaceListTile(
            data: data,
            onTap: () {
              context.push(AppRoutes.workspacePath(
                data.server.id,
                data.workspaceId,
              ));
            },
            onDelete: data.workspaceId != 'default'
                ? () => _confirmDeleteWorkspace(data)
                : null,
          );
        },
      ),
    );
  }

  void _showRenameDialog(ChatSession session) {
    final controller = TextEditingController(text: session.name);

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Rename Session'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'Session Name',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final newName = controller.text.trim();
              if (newName.isNotEmpty) {
                ref.read(sessionProvider.notifier).renameSession(session.id, newName);
              }
              Navigator.pop(context);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  void _confirmDeleteSession(ChatSession session) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Session'),
        content: Text('Delete "${session.name}"? This cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              ref.read(sessionProvider.notifier).deleteSession(session.id);
              Navigator.pop(context);
            },
            style: FilledButton.styleFrom(
              backgroundColor: ZiaOlive.error,
            ),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
  }

  void _confirmDeleteWorkspace(_WorkspaceCardData data) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Workspace'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Delete "${data.workspaceName}"?'),
            if (data.sessions.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                'This will also delete ${data.sessions.length} session(s).',
                style: TextStyle(color: ZiaOlive.error, fontSize: 13),
              ),
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(context);
              final success = await ref.read(serverProvider.notifier).deleteWorkspace(
                data.server.id,
                data.workspaceId,
              );
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(success
                        ? 'Deleted "${data.workspaceName}"'
                        : 'Failed to delete workspace'),
                  ),
                );
              }
            },
            style: FilledButton.styleFrom(
              backgroundColor: ZiaOlive.error,
            ),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
  }
}

/// Workspace 卡片数据
class _WorkspaceCardData {
  final ServerConfig server;
  final String workspaceId;
  final String workspaceName;
  final List<ChatSession> sessions;
  final bool isServerOnline;

  _WorkspaceCardData({
    required this.server,
    required this.workspaceId,
    required this.workspaceName,
    required this.sessions,
    required this.isServerOnline,
  });
}

/// Workspace 卡片组件（支持折叠，使用 Riverpod 持久化）
class _WorkspaceCard extends ConsumerWidget {
  final _WorkspaceCardData data;
  final VoidCallback onNewSession;
  final void Function(ChatSession) onOpenSession;
  final void Function(ChatSession) onRenameSession;
  final void Function(ChatSession) onDeleteSession;
  final VoidCallback? onDeleteWorkspace;

  const _WorkspaceCard({
    required this.data,
    required this.onNewSession,
    required this.onOpenSession,
    required this.onRenameSession,
    required this.onDeleteSession,
    this.onDeleteWorkspace,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final borderColor = isDark ? ZiaOlive.shade700 : ZiaOlive.shade100;

    // 从 Riverpod 读取展开状态（持久化）
    final isExpanded = ref.watch(workspaceExpandedProvider((
      serverId: data.server.id,
      workspaceId: data.workspaceId,
    )));

    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 卡片头部：workspace 名称 + new session 按钮
          CommandListItem(
            targetId: 'home.workspace.${data.workspaceId}',
            label: data.workspaceName,
            onTap: () {
              ref.read(uiStateProvider.notifier).toggleWorkspaceExpanded(
                data.server.id,
                data.workspaceId,
              );
            },
            getState: () => {
              'expanded': isExpanded,
              'sessionCount': data.sessions.length,
              'serverOnline': data.isServerOnline,
            },
            child: InkWell(
            onTap: () {
              ref.read(uiStateProvider.notifier).toggleWorkspaceExpanded(
                data.server.id,
                data.workspaceId,
              );
            },
            borderRadius: isExpanded
                ? const BorderRadius.vertical(top: Radius.circular(12))
                : BorderRadius.circular(12),
            child: Container(
              padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
              decoration: BoxDecoration(
                border: isExpanded
                    ? Border(bottom: BorderSide(color: borderColor, width: 0.5))
                    : null,
              ),
              child: Row(
                children: [
                  // 展开/折叠指示器
                  AnimatedRotation(
                    turns: isExpanded ? 0.25 : 0,
                    duration: const Duration(milliseconds: 200),
                    child: Icon(
                      Icons.chevron_right,
                      size: 20,
                      color: ZiaOlive.shade300,
                    ),
                  ),
                  const SizedBox(width: 8),
                  // Workspace 图标和名称
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: ZiaOlive.shade500.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Icon(
                      data.workspaceId == 'default'
                          ? Icons.home_outlined
                          : Icons.folder_outlined,
                      color: ZiaOlive.shade500,
                      size: 20,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Flexible(
                              child: Text(
                                data.workspaceName,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w600,
                                  fontSize: 15,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            if (data.workspaceId == 'default') ...[
                              const SizedBox(width: 6),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 6,
                                  vertical: 2,
                                ),
                                decoration: BoxDecoration(
                                  color: ZiaOlive.shade500.withValues(alpha: 0.1),
                                  borderRadius: BorderRadius.circular(4),
                                ),
                                child: Text(
                                  'Default',
                                  style: TextStyle(
                                    fontSize: 10,
                                    color: ZiaOlive.shade500,
                                    fontWeight: FontWeight.w500,
                                  ),
                                ),
                              ),
                            ],
                            if (data.sessions.isNotEmpty) ...[
                              const SizedBox(width: 8),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 6,
                                  vertical: 2,
                                ),
                                decoration: BoxDecoration(
                                  color: ZiaOlive.shade100,
                                  borderRadius: BorderRadius.circular(10),
                                ),
                                child: Text(
                                  '${data.sessions.length}',
                                  style: TextStyle(
                                    fontSize: 11,
                                    color: ZiaOlive.shade400,
                                    fontWeight: FontWeight.w500,
                                  ),
                                ),
                              ),
                            ],
                          ],
                        ),
                        Row(
                          children: [
                            Container(
                              width: 6,
                              height: 6,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: data.isServerOnline
                                    ? ZiaOlive.success
                                    : ZiaOlive.error,
                              ),
                            ),
                            const SizedBox(width: 4),
                            Text(
                              data.server.name,
                              style: TextStyle(
                                fontSize: 12,
                                color: ZiaOlive.shade200,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  // 更多操作（非 default workspace 才显示删除）
                  if (data.workspaceId != 'default')
                    PopupMenuButton<String>(
                      icon: Icon(Icons.more_vert, size: 20, color: ZiaOlive.shade300),
                      padding: EdgeInsets.zero,
                      onSelected: (value) {
                        if (value == 'delete' && onDeleteWorkspace != null) {
                          onDeleteWorkspace!();
                        }
                      },
                      itemBuilder: (context) => [
                        const PopupMenuItem(
                          value: 'delete',
                          child: Row(
                            children: [
                              Icon(Icons.delete_outline, size: 18, color: Colors.red),
                              SizedBox(width: 8),
                              Text('Delete Workspace', style: TextStyle(color: Colors.red)),
                            ],
                          ),
                        ),
                      ],
                    ),
                ],
              ),
            ),
          ),
          ),  // Close CommandListItem

          // Sessions 列表（可折叠）
          AnimatedCrossFade(
            firstChild: _buildSessionsList(borderColor),
            secondChild: const SizedBox.shrink(),
            crossFadeState: isExpanded
                ? CrossFadeState.showFirst
                : CrossFadeState.showSecond,
            duration: const Duration(milliseconds: 200),
          ),
        ],
      ),
    );
  }

  Widget _buildSessionsList(Color borderColor) {
    if (data.sessions.isEmpty) {
      return Padding(
        padding: const EdgeInsets.all(24),
        child: Center(
          child: Column(
            children: [
              Icon(
                Icons.chat_bubble_outline,
                size: 32,
                color: ZiaOlive.shade200,
              ),
              const SizedBox(height: 8),
              Text(
                'No sessions',
                style: TextStyle(
                  color: ZiaOlive.shade200,
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 12),
              TextButton.icon(
                onPressed: onNewSession,
                icon: const Icon(Icons.add, size: 18),
                label: const Text('Start a session'),
              ).withCommand(
                'home.new_session.${data.workspaceId}',
                label: 'New Session in ${data.workspaceName}',
                onTap: onNewSession,
              ),
            ],
          ),
        ),
      );
    }

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        // Sessions 列表
        ListView.separated(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: data.sessions.length,
          separatorBuilder: (_, __) => Divider(
            height: 1,
            indent: 16,
            endIndent: 16,
            color: borderColor,
          ),
          itemBuilder: (context, index) {
            final session = data.sessions[index];
            return CommandListItem(
              targetId: 'home.session.${session.id}',
              label: session.name,
              onTap: () => onOpenSession(session),
              getState: () => {
                'name': session.name,
                'connected': session.connectionState == SessionConnectionState.connected,
                'processing': session.isProcessing,
              },
              child: _SessionTile(
                session: session,
                onTap: () => onOpenSession(session),
                onRename: () => onRenameSession(session),
                onDelete: () => onDeleteSession(session),
              ),
            );
          },
        ),
        // 底部新建按钮
        Divider(height: 1, indent: 16, endIndent: 16, color: borderColor),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: TextButton.icon(
            onPressed: onNewSession,
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Start a new session'),
          ).withCommand(
            'home.new_session.${data.workspaceId}',
            label: 'New Session in ${data.workspaceName}',
            onTap: onNewSession,
          ),
        ),
      ],
    );
  }
}

/// Session 列表项（支持左划显示操作按钮）
class _SessionTile extends StatefulWidget {
  final ChatSession session;
  final VoidCallback onTap;
  final VoidCallback onRename;
  final VoidCallback onDelete;

  const _SessionTile({
    required this.session,
    required this.onTap,
    required this.onRename,
    required this.onDelete,
  });

  @override
  State<_SessionTile> createState() => _SessionTileState();
}

class _SessionTileState extends State<_SessionTile> with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<Offset> _slideAnimation;
  static const double _actionButtonWidth = 75.0;
  static const double _totalActionWidth = _actionButtonWidth * 2;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 200),
    );
    _slideAnimation = Tween<Offset>(
      begin: Offset.zero,
      end: const Offset(-_totalActionWidth, 0),
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeOut));
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _handleDragUpdate(DragUpdateDetails details) {
    final delta = details.primaryDelta ?? 0;
    final newValue = _controller.value - delta / _totalActionWidth;
    _controller.value = newValue.clamp(0.0, 1.0);
  }

  void _handleDragEnd(DragEndDetails details) {
    if (_controller.value > 0.5) {
      _controller.forward();
    } else {
      _controller.reverse();
    }
  }

  void _closeActions() {
    _controller.reverse();
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
    final isConnected = session.connectionState == SessionConnectionState.connected;
    final isProcessing = session.isProcessing;
    final hasUnread = session.hasUnread;

    return GestureDetector(
      onHorizontalDragUpdate: _handleDragUpdate,
      onHorizontalDragEnd: _handleDragEnd,
      child: Stack(
        children: [
          // 操作按钮（在右侧）
          Positioned.fill(
            child: Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                // Rename 按钮
                GestureDetector(
                  onTap: () {
                    _closeActions();
                    widget.onRename();
                  },
                  child: Container(
                    width: _actionButtonWidth,
                    color: ZiaOlive.shade400,
                    alignment: Alignment.center,
                    child: const Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.edit_outlined, color: Colors.white, size: 20),
                        SizedBox(height: 4),
                        Text(
                          'Rename',
                          style: TextStyle(color: Colors.white, fontSize: 11),
                        ),
                      ],
                    ),
                  ),
                ),
                // Delete 按钮
                GestureDetector(
                  onTap: () {
                    _closeActions();
                    widget.onDelete();
                  },
                  child: Container(
                    width: _actionButtonWidth,
                    color: ZiaOlive.error,
                    alignment: Alignment.center,
                    child: const Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.delete_outline, color: Colors.white, size: 20),
                        SizedBox(height: 4),
                        Text(
                          'Delete',
                          style: TextStyle(color: Colors.white, fontSize: 11),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
          // 主内容（可滑动）
          AnimatedBuilder(
            animation: _slideAnimation,
            builder: (context, child) {
              return Transform.translate(
                offset: _slideAnimation.value,
                child: child,
              );
            },
            child: Material(
              color: Theme.of(context).cardColor,
              child: InkWell(
                onTap: () {
                  if (_controller.value > 0) {
                    _closeActions();
                  } else {
                    widget.onTap();
                  }
                },
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  child: Row(
                    children: [
                      // 状态指示
                      if (isProcessing)
                        const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      else
                        Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: isConnected ? ZiaOlive.success : ZiaOlive.shade200,
                          ),
                        ),
                      const SizedBox(width: 12),

                      // Session 名称和预览
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Flexible(
                                  child: Text(
                                    session.name,
                                    style: TextStyle(
                                      fontWeight: hasUnread ? FontWeight.w700 : FontWeight.w500,
                                      fontSize: 14,
                                    ),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                                // 未读徽章
                                if (hasUnread) ...[
                                  const SizedBox(width: 6),
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: Colors.red,
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                    child: const Text(
                                      'NEW',
                                      style: TextStyle(
                                        color: Colors.white,
                                        fontSize: 9,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                  ),
                                ],
                              ],
                            ),
                            if (session.messages.isNotEmpty)
                              Text(
                                _getLastMessagePreview(session),
                                style: TextStyle(
                                  fontSize: 12,
                                  color: hasUnread ? ZiaOlive.shade400 : ZiaOlive.shade200,
                                  fontWeight: hasUnread ? FontWeight.w500 : FontWeight.normal,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                          ],
                        ),
                      ),

                      // 时间
                      Text(
                        _formatTime(session.lastActiveAt),
                        style: TextStyle(
                          fontSize: 11,
                          color: hasUnread ? ZiaOlive.shade400 : ZiaOlive.shade200,
                          fontWeight: hasUnread ? FontWeight.w500 : FontWeight.normal,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _getLastMessagePreview(ChatSession session) {
    if (session.messages.isEmpty) return '';
    final last = session.messages.last;
    final content = last.content;
    return content.length > 50 ? '${content.substring(0, 50)}...' : content;
  }

  String _formatTime(DateTime time) {
    final now = DateTime.now();
    final diff = now.difference(time);

    if (diff.inMinutes < 1) return 'now';
    if (diff.inHours < 1) return '${diff.inMinutes}m';
    if (diff.inDays < 1) return '${diff.inHours}h';
    if (diff.inDays < 7) return '${diff.inDays}d';
    return '${time.month}/${time.day}';
  }
}

/// 新建 Session 底部表单
class _NewSessionSheet extends ConsumerStatefulWidget {
  final String? initialServerId;
  final String? initialWorkspaceId;
  final String? initialWorkspaceName;

  const _NewSessionSheet({
    this.initialServerId,
    this.initialWorkspaceId,
    this.initialWorkspaceName,
  });

  @override
  ConsumerState<_NewSessionSheet> createState() => _NewSessionSheetState();
}

class _NewSessionSheetState extends ConsumerState<_NewSessionSheet> {
  ServerConfig? _selectedServer;
  WorkspaceInfo? _selectedWorkspace;
  final _nameController = TextEditingController();

  @override
  void initState() {
    super.initState();
    final serverState = ref.read(serverProvider);

    // 如果有初始值，设置它
    if (widget.initialServerId != null) {
      _selectedServer = serverState.getServer(widget.initialServerId!);

      if (_selectedServer != null && widget.initialWorkspaceId != null) {
        final workspaces = serverState.getWorkspaces(_selectedServer!.id);
        _selectedWorkspace = workspaces.where((w) => w.id == widget.initialWorkspaceId).firstOrNull;
      }
    } else if (serverState.servers.isNotEmpty) {
      _selectedServer = serverState.servers.first;
    }
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  void _createSession() async {
    if (_selectedServer == null || _selectedWorkspace == null) return;

    final session = await ref.read(sessionProvider.notifier).createSession(
      serverId: _selectedServer!.id,
      workspaceId: _selectedWorkspace!.id,
      workspaceName: _selectedWorkspace!.name,
      // 如果用户没有输入名字，传 null 让 provider 使用 ID 前 8 位
      name: _nameController.text.trim().isEmpty
          ? null
          : _nameController.text.trim(),
    );

    if (mounted) {
      Navigator.pop(context); // 关闭 bottom sheet

      // 设置为活跃 session
      ref.read(sessionProvider.notifier).setActiveSession(session.id);

      context.go(AppRoutes.sessionPath(
        _selectedServer!.id,
        _selectedWorkspace!.id,
        session.id,
      ));
    }
  }

  @override
  Widget build(BuildContext context) {
    final serverState = ref.watch(serverProvider);
    final hasInitialWorkspace = widget.initialWorkspaceId != null;

    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).scaffoldBackgroundColor,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
      ),
      padding: EdgeInsets.only(
        left: 24,
        right: 24,
        top: 24,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // 标题
          Row(
            children: [
              Text(
                'New Session',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const Spacer(),
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
          const SizedBox(height: 24),

          // 如果有预设的 workspace，显示信息
          if (hasInitialWorkspace) ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: ZiaOlive.shade500.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(Icons.folder_outlined, color: ZiaOlive.shade500, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          widget.initialWorkspaceName ?? widget.initialWorkspaceId!,
                          style: const TextStyle(fontWeight: FontWeight.w500),
                        ),
                        Text(
                          _selectedServer?.name ?? '',
                          style: TextStyle(
                            fontSize: 12,
                            color: ZiaOlive.shade300,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
          ] else ...[
            // 选择服务器
            DropdownButtonFormField<ServerConfig>(
              value: _selectedServer,
              decoration: const InputDecoration(
                labelText: 'Server',
                prefixIcon: Icon(Icons.dns_outlined),
              ),
              items: serverState.servers.map((server) {
                final isOnline = serverState.isServerOnline(server.id);
                return DropdownMenuItem(
                  value: server,
                  child: Row(
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: isOnline ? ZiaOlive.success : ZiaOlive.error,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(server.name),
                    ],
                  ),
                );
              }).toList(),
              onChanged: (server) {
                setState(() {
                  _selectedServer = server;
                  _selectedWorkspace = null;
                });
              },
            ),
            const SizedBox(height: 16),

            // 选择工作区
            if (_selectedServer != null) ...[
              DropdownButtonFormField<WorkspaceInfo>(
                value: _selectedWorkspace,
                decoration: const InputDecoration(
                  labelText: 'Workspace',
                  prefixIcon: Icon(Icons.folder_outlined),
                ),
                items: serverState
                    .getWorkspaces(_selectedServer!.id)
                    .map((ws) => DropdownMenuItem(
                          value: ws,
                          child: Text(ws.name),
                        ))
                    .toList(),
                onChanged: (ws) {
                  setState(() {
                    _selectedWorkspace = ws;
                  });
                },
              ),
              const SizedBox(height: 16),
            ],
          ],

          // Session 名称
          TextField(
            controller: _nameController,
            decoration: const InputDecoration(
              labelText: 'Session Name (optional)',
              prefixIcon: Icon(Icons.chat_bubble_outline),
              hintText: 'e.g., Bug Fix, Docs, Feature',
            ),
          ),
          const SizedBox(height: 24),

          // 创建按钮
          FilledButton(
            onPressed: _selectedServer != null && _selectedWorkspace != null
                ? _createSession
                : null,
            child: const Text('Create Session'),
          ),
        ],
      ),
    );
  }
}

/// 创建 Workspace 底部表单
class _CreateWorkspaceSheet extends ConsumerStatefulWidget {
  const _CreateWorkspaceSheet();

  @override
  ConsumerState<_CreateWorkspaceSheet> createState() => _CreateWorkspaceSheetState();
}

class _CreateWorkspaceSheetState extends ConsumerState<_CreateWorkspaceSheet> {
  ServerConfig? _selectedServer;
  final _nameController = TextEditingController();
  final _descController = TextEditingController();
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    final serverState = ref.read(serverProvider);
    if (serverState.servers.isNotEmpty) {
      // 默认选择第一个在线的服务器
      _selectedServer = serverState.servers.firstWhere(
        (s) => serverState.isServerOnline(s.id),
        orElse: () => serverState.servers.first,
      );
    }
  }

  @override
  void dispose() {
    _nameController.dispose();
    _descController.dispose();
    super.dispose();
  }

  Future<void> _createWorkspace() async {
    if (_selectedServer == null || _nameController.text.trim().isEmpty) return;

    setState(() => _isLoading = true);

    try {
      final workspace = await ref.read(serverProvider.notifier).createWorkspace(
        _selectedServer!.id,
        name: _nameController.text.trim(),
        description: _descController.text.trim().isEmpty
            ? null
            : _descController.text.trim(),
      );

      if (mounted) {
        Navigator.pop(context);
        if (workspace != null) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Created "${workspace.name}"')),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Failed to create workspace')),
          );
        }
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final serverState = ref.watch(serverProvider);

    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).scaffoldBackgroundColor,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
      ),
      padding: EdgeInsets.only(
        left: 24,
        right: 24,
        top: 24,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // 标题
          Row(
            children: [
              Text(
                'New Workspace',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const Spacer(),
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
          const SizedBox(height: 24),

          // 选择服务器
          DropdownButtonFormField<ServerConfig>(
            value: _selectedServer,
            decoration: const InputDecoration(
              labelText: 'Server',
              prefixIcon: Icon(Icons.dns_outlined),
            ),
            items: serverState.servers.map((server) {
              final isOnline = serverState.isServerOnline(server.id);
              return DropdownMenuItem(
                value: server,
                child: Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: isOnline ? ZiaOlive.success : ZiaOlive.error,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(server.name),
                  ],
                ),
              );
            }).toList(),
            onChanged: (server) {
              setState(() => _selectedServer = server);
            },
          ),
          const SizedBox(height: 16),

          // Workspace 名称
          TextField(
            controller: _nameController,
            decoration: const InputDecoration(
              labelText: 'Workspace Name *',
              prefixIcon: Icon(Icons.folder_outlined),
              hintText: 'e.g., my-project',
            ),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 16),

          // 描述（可选）
          TextField(
            controller: _descController,
            decoration: const InputDecoration(
              labelText: 'Description (optional)',
              prefixIcon: Icon(Icons.description_outlined),
              hintText: 'Brief description of the workspace',
            ),
            maxLines: 2,
          ),
          const SizedBox(height: 24),

          // 创建按钮
          FilledButton(
            onPressed: _selectedServer != null &&
                    _nameController.text.trim().isNotEmpty &&
                    !_isLoading
                ? _createWorkspace
                : null,
            child: _isLoading
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Text('Create Workspace'),
          ),
        ],
      ),
    );
  }
}

/// Workspace 列表项（用于列表视图模式）
class _WorkspaceListTile extends StatelessWidget {
  final _WorkspaceCardData data;
  final VoidCallback onTap;
  final VoidCallback? onDelete;

  const _WorkspaceListTile({
    required this.data,
    required this.onTap,
    this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap,
      leading: Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: ZiaOlive.shade500.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Icon(
          data.workspaceId == 'default'
              ? Icons.home_outlined
              : Icons.folder_outlined,
          color: ZiaOlive.shade500,
        ),
      ),
      title: Row(
        children: [
          Flexible(
            child: Text(
              data.workspaceName,
              style: const TextStyle(fontWeight: FontWeight.w600),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (data.workspaceId == 'default') ...[
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: ZiaOlive.shade500.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                'Default',
                style: TextStyle(
                  fontSize: 10,
                  color: ZiaOlive.shade500,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          ],
        ],
      ),
      subtitle: Row(
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: data.isServerOnline ? ZiaOlive.success : ZiaOlive.error,
            ),
          ),
          const SizedBox(width: 4),
          Text(
            data.server.name,
            style: TextStyle(
              fontSize: 12,
              color: ZiaOlive.shade200,
            ),
          ),
          const SizedBox(width: 12),
          Text(
            '${data.sessions.length} session${data.sessions.length == 1 ? '' : 's'}',
            style: TextStyle(
              fontSize: 12,
              color: ZiaOlive.shade300,
            ),
          ),
        ],
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.chevron_right, color: ZiaOlive.shade300),
          if (onDelete != null)
            PopupMenuButton<String>(
              icon: Icon(Icons.more_vert, size: 20, color: ZiaOlive.shade300),
              onSelected: (value) {
                if (value == 'delete') {
                  onDelete!();
                }
              },
              itemBuilder: (context) => [
                const PopupMenuItem(
                  value: 'delete',
                  child: Row(
                    children: [
                      Icon(Icons.delete_outline, size: 18, color: Colors.red),
                      SizedBox(width: 8),
                      Text('Delete', style: TextStyle(color: Colors.red)),
                    ],
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }
}
