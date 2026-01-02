import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../config/theme.dart';
import '../models/chat_session.dart';
import '../models/server_config.dart';
import '../models/workspace.dart';
import '../providers/providers.dart';

/// 回收站页面 - 显示已删除的 sessions 和 workspaces
class TrashScreen extends ConsumerStatefulWidget {
  const TrashScreen({super.key});

  @override
  ConsumerState<TrashScreen> createState() => _TrashScreenState();
}

class _TrashScreenState extends ConsumerState<TrashScreen> {
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadDeletedWorkspaces();
  }

  Future<void> _loadDeletedWorkspaces() async {
    await ref.read(serverProvider.notifier).refreshAllDeletedWorkspaces();
    if (mounted) {
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final sessionState = ref.watch(sessionProvider);
    final serverState = ref.watch(serverProvider);
    final deletedSessions = sessionState.deletedSessions;
    final deletedWorkspaces = serverState.allDeletedWorkspaces;

    final hasContent = deletedSessions.isNotEmpty || deletedWorkspaces.isNotEmpty;

    return Scaffold(
      backgroundColor: isDark ? ZiaOlive.shade900 : ZiaOlive.shade50,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: const Text(
          'Trash',
          style: TextStyle(fontWeight: FontWeight.w600),
        ),
        actions: [
          if (hasContent)
            TextButton(
              onPressed: () => _confirmEmptyTrash(context, ref, deletedSessions.length, deletedWorkspaces.length),
              child: Text(
                'Empty',
                style: TextStyle(color: ZiaOlive.error),
              ),
            ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : !hasContent
              ? _buildEmptyState()
              : _buildContent(context, ref, deletedSessions, deletedWorkspaces, isDark),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.delete_outline,
            size: 64,
            color: ZiaOlive.shade200,
          ),
          const SizedBox(height: 16),
          Text(
            'Trash is empty',
            style: TextStyle(
              color: ZiaOlive.shade300,
              fontSize: 16,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Deleted items will appear here',
            style: TextStyle(
              color: ZiaOlive.shade200,
              fontSize: 14,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildContent(
    BuildContext context,
    WidgetRef ref,
    List<ChatSession> sessions,
    List<({ServerConfig server, WorkspaceInfo workspace})> workspaces,
    bool isDark,
  ) {
    final borderColor = isDark ? ZiaOlive.shade700 : ZiaOlive.shade100;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // Workspaces section
        if (workspaces.isNotEmpty) ...[
          _buildSectionHeader('Workspaces', workspaces.length),
          const SizedBox(height: 8),
          ...workspaces.map((item) => Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: _WorkspaceTile(
              workspace: item.workspace,
              server: item.server,
              borderColor: borderColor,
              isDark: isDark,
              onRestore: () => _restoreWorkspace(context, ref, item.server, item.workspace),
              onDelete: () => _confirmDeleteWorkspace(context, ref, item.server, item.workspace),
            ),
          )),
          const SizedBox(height: 16),
        ],

        // Sessions section
        if (sessions.isNotEmpty) ...[
          _buildSectionHeader('Sessions', sessions.length),
          const SizedBox(height: 8),
          ...sessions.map((session) => Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: _SessionTile(
              session: session,
              borderColor: borderColor,
              isDark: isDark,
              onRestore: () => _restoreSession(context, ref, session),
              onDelete: () => _confirmDeleteSession(context, ref, session),
            ),
          )),
        ],
      ],
    );
  }

  Widget _buildSectionHeader(String title, int count) {
    return Row(
      children: [
        Text(
          title,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: ZiaOlive.shade400,
          ),
        ),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(
            color: ZiaOlive.shade500.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(
            '$count',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w500,
              color: ZiaOlive.shade500,
            ),
          ),
        ),
      ],
    );
  }

  void _restoreSession(BuildContext context, WidgetRef ref, ChatSession session) {
    ref.read(sessionProvider.notifier).restoreSession(session.id);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Restored "${session.name}"')),
    );
  }

  void _restoreWorkspace(BuildContext context, WidgetRef ref, ServerConfig server, WorkspaceInfo workspace) async {
    final success = await ref.read(serverProvider.notifier).restoreWorkspace(server.id, workspace.id);
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(success ? 'Restored "${workspace.name}"' : 'Failed to restore workspace'),
        ),
      );
    }
  }

  void _confirmDeleteSession(BuildContext context, WidgetRef ref, ChatSession session) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Permanently'),
        content: Text('Delete "${session.name}" permanently? This cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(context);
              ref.read(sessionProvider.notifier).permanentlyDeleteSession(session.id);
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text('Deleted "${session.name}"')),
              );
            },
            style: FilledButton.styleFrom(backgroundColor: ZiaOlive.error),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
  }

  void _confirmDeleteWorkspace(BuildContext context, WidgetRef ref, ServerConfig server, WorkspaceInfo workspace) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Permanently'),
        content: Text('Delete "${workspace.name}" permanently? This cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(context);
              final success = await ref.read(serverProvider.notifier).deleteWorkspace(
                server.id,
                workspace.id,
                permanent: true,
              );
              if (context.mounted) {
                // 刷新已删除列表
                await ref.read(serverProvider.notifier).fetchDeletedWorkspaces(server.id);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(success ? 'Deleted "${workspace.name}"' : 'Failed to delete workspace'),
                  ),
                );
              }
            },
            style: FilledButton.styleFrom(backgroundColor: ZiaOlive.error),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
  }

  void _confirmEmptyTrash(BuildContext context, WidgetRef ref, int sessionCount, int workspaceCount) {
    final totalCount = sessionCount + workspaceCount;
    final items = <String>[];
    if (sessionCount > 0) items.add('$sessionCount session${sessionCount > 1 ? 's' : ''}');
    if (workspaceCount > 0) items.add('$workspaceCount workspace${workspaceCount > 1 ? 's' : ''}');

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Empty Trash'),
        content: Text('Delete ${items.join(' and ')} permanently? This cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(context);
              // Empty sessions
              if (sessionCount > 0) {
                await ref.read(sessionProvider.notifier).emptyTrash();
              }
              // Empty workspaces
              if (workspaceCount > 0) {
                final serverState = ref.read(serverProvider);
                for (final item in serverState.allDeletedWorkspaces) {
                  await ref.read(serverProvider.notifier).deleteWorkspace(
                    item.server.id,
                    item.workspace.id,
                    permanent: true,
                  );
                }
                await ref.read(serverProvider.notifier).refreshAllDeletedWorkspaces();
              }
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Trash emptied')),
                );
              }
            },
            style: FilledButton.styleFrom(backgroundColor: ZiaOlive.error),
            child: const Text('Empty Trash'),
          ),
        ],
      ),
    );
  }
}

class _WorkspaceTile extends StatelessWidget {
  final WorkspaceInfo workspace;
  final ServerConfig server;
  final Color borderColor;
  final bool isDark;
  final VoidCallback onRestore;
  final VoidCallback onDelete;

  const _WorkspaceTile({
    required this.workspace,
    required this.server,
    required this.borderColor,
    required this.isDark,
    required this.onRestore,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: isDark ? ZiaOlive.shade800 : Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: borderColor, width: 0.5),
      ),
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        leading: Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: ZiaOlive.shade500.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Icon(
            Icons.folder_outlined,
            color: ZiaOlive.shade400,
            size: 20,
          ),
        ),
        title: Text(
          workspace.name,
          style: const TextStyle(fontWeight: FontWeight.w500),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              server.name,
              style: TextStyle(
                fontSize: 12,
                color: ZiaOlive.shade300,
              ),
            ),
            Text(
              workspace.path,
              style: TextStyle(
                fontSize: 11,
                color: ZiaOlive.shade200,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            IconButton(
              icon: Icon(Icons.restore, color: ZiaOlive.shade500),
              onPressed: onRestore,
              tooltip: 'Restore',
            ),
            IconButton(
              icon: Icon(Icons.delete_forever, color: ZiaOlive.error),
              onPressed: onDelete,
              tooltip: 'Delete permanently',
            ),
          ],
        ),
      ),
    );
  }
}

class _SessionTile extends StatelessWidget {
  final ChatSession session;
  final Color borderColor;
  final bool isDark;
  final VoidCallback onRestore;
  final VoidCallback onDelete;

  const _SessionTile({
    required this.session,
    required this.borderColor,
    required this.isDark,
    required this.onRestore,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final deletedAt = session.deletedAt;
    final deletedText = deletedAt != null
        ? 'Deleted ${_formatDate(deletedAt)}'
        : 'Deleted';

    return Container(
      decoration: BoxDecoration(
        color: isDark ? ZiaOlive.shade800 : Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: borderColor, width: 0.5),
      ),
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        leading: Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: ZiaOlive.shade500.withValues(alpha: 0.1),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Icon(
            Icons.chat_bubble_outline,
            color: ZiaOlive.shade400,
            size: 20,
          ),
        ),
        title: Text(
          session.name,
          style: const TextStyle(fontWeight: FontWeight.w500),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              session.workspaceName,
              style: TextStyle(
                fontSize: 12,
                color: ZiaOlive.shade300,
              ),
            ),
            Text(
              deletedText,
              style: TextStyle(
                fontSize: 11,
                color: ZiaOlive.shade200,
              ),
            ),
          ],
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            IconButton(
              icon: Icon(Icons.restore, color: ZiaOlive.shade500),
              onPressed: onRestore,
              tooltip: 'Restore',
            ),
            IconButton(
              icon: Icon(Icons.delete_forever, color: ZiaOlive.error),
              onPressed: onDelete,
              tooltip: 'Delete permanently',
            ),
          ],
        ),
      ),
    );
  }

  String _formatDate(DateTime date) {
    final now = DateTime.now();
    final diff = now.difference(date);

    if (diff.inDays == 0) {
      return 'today';
    } else if (diff.inDays == 1) {
      return 'yesterday';
    } else if (diff.inDays < 7) {
      return '${diff.inDays} days ago';
    } else {
      return DateFormat('MMM d').format(date);
    }
  }
}
