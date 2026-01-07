import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_slidable/flutter_slidable.dart';
import 'package:go_router/go_router.dart';

import '../config/theme.dart';
import '../models/chat_session.dart';
import '../models/server_config.dart';
import '../models/workspace.dart';
import '../providers/providers.dart';
import '../router.dart';
import '../widgets/command_target.dart';

/// Workspace 详情页面 - 显示该 workspace 下的所有 sessions
class WorkspaceDetailScreen extends ConsumerStatefulWidget {
  final ServerConfig server;
  final WorkspaceInfo workspace;

  const WorkspaceDetailScreen({
    super.key,
    required this.server,
    required this.workspace,
  });

  @override
  ConsumerState<WorkspaceDetailScreen> createState() => _WorkspaceDetailScreenState();
}

class _WorkspaceDetailScreenState extends ConsumerState<WorkspaceDetailScreen> {
  @override
  void initState() {
    super.initState();
    // 同步该 workspace 的 sessions
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(sessionProvider.notifier).syncSessionsFromServer(
        widget.server,
        widget.workspace.id,
        widget.workspace.name,
      );
    });
  }

  void _openSession(ChatSession session) {
    ref.read(sessionProvider.notifier).setActiveSession(session.id);
    context.push(AppRoutes.sessionPath(
      widget.server.id,
      widget.workspace.id,
      session.id,
    ));
  }

  void _createNewSession() async {
    final session = await ref.read(sessionProvider.notifier).createSession(
      serverId: widget.server.id,
      workspaceId: widget.workspace.id,
      workspaceName: widget.workspace.name,
    );

    if (mounted) {
      ref.read(sessionProvider.notifier).setActiveSession(session.id);
      context.push(AppRoutes.sessionPath(
        widget.server.id,
        widget.workspace.id,
        session.id,
      ));
    }
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
        content: Text('Delete "${session.name}"?'),
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

  @override
  Widget build(BuildContext context) {
    final sessionState = ref.watch(sessionProvider);
    final serverState = ref.watch(serverProvider);
    final isOnline = serverState.isServerOnline(widget.server.id);

    final sessions = sessionState.getSessionsForWorkspace(
      widget.server.id,
      widget.workspace.id,
    );

    // 按最后活跃时间排序
    sessions.sort((a, b) => b.lastActiveAt.compareTo(a.lastActiveAt));

    return ScreenScope(
      screenId: 'workspace_detail',
      child: Scaffold(
        appBar: AppBar(
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () => context.go(AppRoutes.home),
          ),
          title: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                widget.workspace.name,
                style: const TextStyle(fontSize: 18),
              ),
              Row(
                children: [
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: isOnline ? ZiaOlive.success : ZiaOlive.error,
                    ),
                  ),
                  const SizedBox(width: 4),
                  Text(
                    widget.server.name,
                    style: TextStyle(
                      fontSize: 12,
                      color: ZiaOlive.shade300,
                    ),
                  ),
                ],
              ),
            ],
          ),
          actions: [
            IconButton(
              icon: const Icon(Icons.folder_open_outlined),
              tooltip: 'Files',
              onPressed: () {
                context.push(AppRoutes.filesPath(
                  widget.server.id,
                  widget.workspace.id,
                ));
              },
            ),
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: 'Refresh',
              onPressed: () async {
                await ref.read(sessionProvider.notifier).syncSessionsFromServer(
                  widget.server,
                  widget.workspace.id,
                  widget.workspace.name,
                );
              },
            ),
          ],
        ),
        body: sessions.isEmpty
            ? _buildEmptySessions()
            : _buildSessionsList(sessions),
        floatingActionButton: FloatingActionButton(
          onPressed: _createNewSession,
          tooltip: 'New Session',
          child: const Icon(Icons.add),
        ),
      ),
    );
  }

  Widget _buildEmptySessions() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.chat_bubble_outline,
            size: 64,
            color: ZiaOlive.shade200,
          ),
          const SizedBox(height: 16),
          Text(
            'No sessions yet',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Text(
            'Start a new session to begin',
            style: TextStyle(color: ZiaOlive.shade200),
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: _createNewSession,
            icon: const Icon(Icons.add),
            label: const Text('New Session'),
          ),
        ],
      ),
    );
  }

  Widget _buildSessionsList(List<ChatSession> sessions) {
    return RefreshIndicator(
      onRefresh: () async {
        await ref.read(sessionProvider.notifier).syncSessionsFromServer(
          widget.server,
          widget.workspace.id,
          widget.workspace.name,
        );
      },
      child: ListView.separated(
        padding: const EdgeInsets.symmetric(vertical: 8),
        itemCount: sessions.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final session = sessions[index];
          return _SessionListTile(
            session: session,
            onTap: () => _openSession(session),
            onRename: () => _showRenameDialog(session),
            onDelete: () => _confirmDeleteSession(session),
          );
        },
      ),
    );
  }
}

/// Session 列表项
class _SessionListTile extends StatelessWidget {
  final ChatSession session;
  final VoidCallback onTap;
  final VoidCallback onRename;
  final VoidCallback onDelete;

  const _SessionListTile({
    required this.session,
    required this.onTap,
    required this.onRename,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final isConnected = session.connectionState == SessionConnectionState.connected;
    final isProcessing = session.isProcessing;
    final hasUnread = session.hasUnread;

    final tile = ListTile(
      onTap: onTap,
      leading: isProcessing
          ? const SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Container(
              width: 12,
              height: 12,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: isConnected ? ZiaOlive.success : ZiaOlive.shade200,
              ),
            ),
      title: Row(
        children: [
          Flexible(
            child: Text(
              session.name,
              style: TextStyle(
                fontWeight: hasUnread ? FontWeight.w700 : FontWeight.w500,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (hasUnread) ...[
            const SizedBox(width: 8),
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
      subtitle: session.messages.isNotEmpty
          ? Text(
              _getLastMessagePreview(session),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: hasUnread ? ZiaOlive.shade400 : ZiaOlive.shade200,
              ),
            )
          : null,
      trailing: Text(
        _formatTime(session.lastActiveAt),
        style: TextStyle(
          fontSize: 12,
          color: ZiaOlive.shade200,
        ),
      ),
    );

    // 使用 Slidable 包裹，左划显示操作按钮
    return Slidable(
      key: ValueKey(session.id),
      endActionPane: ActionPane(
        motion: const BehindMotion(),
        extentRatio: 0.4,
        children: [
          SlidableAction(
            onPressed: (_) => onRename(),
            backgroundColor: ZiaOlive.shade400,
            foregroundColor: Colors.white,
            icon: Icons.edit_outlined,
            label: 'Rename',
          ),
          SlidableAction(
            onPressed: (_) => onDelete(),
            backgroundColor: ZiaOlive.error,
            foregroundColor: Colors.white,
            icon: Icons.delete_outline,
            label: 'Delete',
          ),
        ],
      ),
      child: tile,
    );
  }

  String _getLastMessagePreview(ChatSession session) {
    if (session.messages.isEmpty) return '';
    final last = session.messages.last;
    final content = last.content;
    return content.length > 60 ? '${content.substring(0, 60)}...' : content;
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
