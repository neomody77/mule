import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../config/theme.dart';
import '../models/server_config.dart';

/// CLI 会话列表页面
class CLISessionsScreen extends ConsumerStatefulWidget {
  final ServerConfig server;

  const CLISessionsScreen({super.key, required this.server});

  @override
  ConsumerState<CLISessionsScreen> createState() => _CLISessionsScreenState();
}

class _CLISessionsScreenState extends ConsumerState<CLISessionsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  List<CLIProject> _projects = [];
  List<String> _activeSessions = [];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _loadData();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      await Future.wait([
        _loadProjects(),
        _loadActiveSessions(),
      ]);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _loadProjects() async {
    final uri = Uri.parse(
      '${widget.server.httpBaseUrl}/api/cli/projects',
    );

    final response = await http.get(
      uri,
      headers: {'Authorization': 'Bearer ${widget.server.token}'},
    );

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      setState(() {
        _projects = data.map((p) => CLIProject.fromJson(p)).toList();
      });
    } else {
      throw Exception('Failed to load projects: ${response.statusCode}');
    }
  }

  Future<void> _loadActiveSessions() async {
    final uri = Uri.parse(
      '${widget.server.httpBaseUrl}/api/cli/sessions/active',
    );

    final response = await http.get(
      uri,
      headers: {'Authorization': 'Bearer ${widget.server.token}'},
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      setState(() {
        _activeSessions = List<String>.from(data['sessions'] ?? []);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('CLI Sessions'),
        bottom: TabBar(
          controller: _tabController,
          tabs: [
            Tab(
              icon: const Icon(Icons.play_circle_outline),
              text: 'Active (${_activeSessions.length})',
            ),
            Tab(
              icon: const Icon(Icons.folder_outlined),
              text: 'Projects (${_projects.length})',
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadData,
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _buildError()
              : TabBarView(
                  controller: _tabController,
                  children: [
                    _buildActiveSessions(),
                    _buildProjects(),
                  ],
                ),
    );
  }

  Widget _buildError() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.error_outline, size: 48, color: ZiaOlive.error),
          const SizedBox(height: 16),
          Text(_error ?? 'Unknown error'),
          const SizedBox(height: 16),
          OutlinedButton(
            onPressed: _loadData,
            child: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  Widget _buildActiveSessions() {
    if (_activeSessions.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.terminal, size: 64, color: ZiaOlive.shade200),
            const SizedBox(height: 16),
            Text(
              'No active CLI sessions',
              style: TextStyle(color: ZiaOlive.shade300),
            ),
            const SizedBox(height: 8),
            Text(
              'Run "mule" on your computer to start a session',
              style: TextStyle(color: ZiaOlive.shade200, fontSize: 12),
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _activeSessions.length,
      itemBuilder: (context, index) {
        final sessionId = _activeSessions[index];
        return Card(
          margin: const EdgeInsets.only(bottom: 12),
          child: ListTile(
            leading: Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: ZiaOlive.success.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(Icons.terminal, color: ZiaOlive.success),
            ),
            title: Text(
              sessionId.length > 20
                  ? '${sessionId.substring(0, 20)}...'
                  : sessionId,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            subtitle: Row(
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: ZiaOlive.success,
                  ),
                ),
                const SizedBox(width: 6),
                const Text('Active'),
              ],
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => _openCLISession(sessionId),
          ),
        );
      },
    );
  }

  Widget _buildProjects() {
    if (_projects.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.folder_off_outlined, size: 64, color: ZiaOlive.shade200),
            const SizedBox(height: 16),
            Text(
              'No Claude Code projects found',
              style: TextStyle(color: ZiaOlive.shade300),
            ),
            const SizedBox(height: 8),
            Text(
              'Projects appear after running Claude Code on your computer',
              style: TextStyle(color: ZiaOlive.shade200, fontSize: 12),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _projects.length,
      itemBuilder: (context, index) {
        final project = _projects[index];
        return Card(
          margin: const EdgeInsets.only(bottom: 12),
          child: ExpansionTile(
            leading: Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: ZiaOlive.shade500.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(Icons.folder_outlined, color: ZiaOlive.shade500),
            ),
            title: Text(
              project.name,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            subtitle: Text(
              '${project.sessionCount} session(s)',
              style: TextStyle(color: ZiaOlive.shade300, fontSize: 12),
            ),
            children: [
              _ProjectSessionsList(
                server: widget.server,
                projectPath: project.path,
                onSessionTap: _openProjectSession,
              ),
            ],
          ),
        );
      },
    );
  }

  void _openCLISession(String sessionId) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => CLISessionDetailScreen(
          server: widget.server,
          sessionId: sessionId,
          isActive: true,
        ),
      ),
    );
  }

  void _openProjectSession(String sessionId, String projectPath) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => CLISessionDetailScreen(
          server: widget.server,
          sessionId: sessionId,
          projectPath: projectPath,
          isActive: _activeSessions.contains(sessionId),
        ),
      ),
    );
  }
}

/// 项目会话列表
class _ProjectSessionsList extends StatefulWidget {
  final ServerConfig server;
  final String projectPath;
  final void Function(String sessionId, String projectPath) onSessionTap;

  const _ProjectSessionsList({
    required this.server,
    required this.projectPath,
    required this.onSessionTap,
  });

  @override
  State<_ProjectSessionsList> createState() => _ProjectSessionsListState();
}

class _ProjectSessionsListState extends State<_ProjectSessionsList> {
  List<CLISession> _sessions = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadSessions();
  }

  Future<void> _loadSessions() async {
    final uri = Uri.parse(
      '${widget.server.httpBaseUrl}/api/cli/projects/${widget.projectPath}/sessions',
    );

    try {
      final response = await http.get(
        uri,
        headers: {'Authorization': 'Bearer ${widget.server.token}'},
      );

      if (response.statusCode == 200) {
        final List<dynamic> data = jsonDecode(response.body);
        setState(() {
          _sessions = data.map((s) => CLISession.fromJson(s)).toList();
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return const Padding(
        padding: EdgeInsets.all(16),
        child: Center(child: CircularProgressIndicator()),
      );
    }

    if (_sessions.isEmpty) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          'No sessions found',
          style: TextStyle(color: ZiaOlive.shade300),
        ),
      );
    }

    return Column(
      children: _sessions.map((session) {
        return ListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: 24),
          leading: Icon(
            Icons.chat_bubble_outline,
            color: ZiaOlive.shade400,
            size: 20,
          ),
          title: Text(
            session.lastPrompt ?? session.sessionId,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          subtitle: Text(
            '${session.messageCount} messages',
            style: TextStyle(fontSize: 12, color: ZiaOlive.shade300),
          ),
          trailing: session.totalCostUsd != null
              ? Text(
                  '\$${session.totalCostUsd!.toStringAsFixed(4)}',
                  style: TextStyle(fontSize: 12, color: ZiaOlive.shade300),
                )
              : null,
          onTap: () => widget.onSessionTap(session.sessionId, widget.projectPath),
        );
      }).toList(),
    );
  }
}

/// CLI 会话详情页
class CLISessionDetailScreen extends ConsumerStatefulWidget {
  final ServerConfig server;
  final String sessionId;
  final String? projectPath;
  final bool isActive;

  const CLISessionDetailScreen({
    super.key,
    required this.server,
    required this.sessionId,
    this.projectPath,
    this.isActive = false,
  });

  @override
  ConsumerState<CLISessionDetailScreen> createState() =>
      _CLISessionDetailScreenState();
}

class _CLISessionDetailScreenState extends ConsumerState<CLISessionDetailScreen> {
  final TextEditingController _promptController = TextEditingController();
  List<dynamic> _messages = [];
  bool _isLoading = true;
  Map<String, dynamic>? _pendingPermission;

  @override
  void initState() {
    super.initState();
    _loadMessages();
  }

  @override
  void dispose() {
    _promptController.dispose();
    super.dispose();
  }

  Future<void> _loadMessages() async {
    // 活跃会话不从文件加载，等待实时消息
    if (widget.isActive) {
      setState(() {
        _messages = [];
        _isLoading = false;
      });
      return;
    }

    // 历史会话从文件加载
    final queryParams = <String, String>{
      'limit': '100',
    };
    if (widget.projectPath != null) {
      queryParams['project_path'] = widget.projectPath!;
    }

    final uri = Uri.parse(
      '${widget.server.httpBaseUrl}/api/cli/sessions/${widget.sessionId}/messages',
    ).replace(queryParameters: queryParams);

    try {
      final response = await http.get(
        uri,
        headers: {'Authorization': 'Bearer ${widget.server.token}'},
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _messages = data['messages'] ?? [];
          _isLoading = false;
        });
      } else {
        setState(() => _isLoading = false);
      }
    } catch (e) {
      setState(() => _isLoading = false);
    }
  }

  Future<void> _sendPrompt() async {
    final prompt = _promptController.text.trim();
    if (prompt.isEmpty || !widget.isActive) return;

    _promptController.clear();

    final uri = Uri.parse(
      '${widget.server.httpBaseUrl}/api/cli/sessions/${widget.sessionId}/prompt',
    ).replace(queryParameters: {'prompt': prompt});

    try {
      await http.post(
        uri,
        headers: {'Authorization': 'Bearer ${widget.server.token}'},
      );

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Prompt sent to CLI')),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to send prompt: $e')),
      );
    }
  }

  Future<void> _respondToPermission(String behavior) async {
    if (_pendingPermission == null) return;

    final toolUseId = _pendingPermission!['tool_use_id'] as String?;
    if (toolUseId == null) return;

    final uri = Uri.parse(
      '${widget.server.httpBaseUrl}/api/cli/sessions/${widget.sessionId}/permission/$toolUseId',
    ).replace(queryParameters: {'behavior': behavior});

    try {
      await http.post(
        uri,
        headers: {'Authorization': 'Bearer ${widget.server.token}'},
      );

      setState(() => _pendingPermission = null);
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to respond: $e')),
      );
    }
  }

  Future<void> _interruptCLI() async {
    final uri = Uri.parse(
      '${widget.server.httpBaseUrl}/api/cli/sessions/${widget.sessionId}/interrupt',
    );

    try {
      await http.post(
        uri,
        headers: {'Authorization': 'Bearer ${widget.server.token}'},
      );

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Interrupt signal sent')),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to interrupt: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.sessionId.length > 20
                  ? '${widget.sessionId.substring(0, 20)}...'
                  : widget.sessionId,
              style: const TextStyle(fontSize: 16),
            ),
            Row(
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: widget.isActive ? ZiaOlive.success : ZiaOlive.shade300,
                  ),
                ),
                const SizedBox(width: 6),
                Text(
                  widget.isActive ? 'Active' : 'Inactive',
                  style: TextStyle(
                    fontSize: 12,
                    color: widget.isActive ? ZiaOlive.success : ZiaOlive.shade300,
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          if (widget.isActive)
            IconButton(
              icon: const Icon(Icons.stop),
              onPressed: _interruptCLI,
              tooltip: 'Interrupt',
            ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadMessages,
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: Column(
        children: [
          // 权限请求横幅
          if (_pendingPermission != null) _buildPermissionBanner(),

          // 消息列表
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : _buildMessagesList(),
          ),

          // 输入区域（仅活跃会话）
          if (widget.isActive) _buildInputArea(),
        ],
      ),
    );
  }

  Widget _buildPermissionBanner() {
    final toolName = _pendingPermission!['tool_name'] as String? ?? 'Unknown';
    final toolInput = _pendingPermission!['tool_input'] as Map<String, dynamic>?;

    return Container(
      padding: const EdgeInsets.all(16),
      color: Colors.orange.withValues(alpha: 0.1),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.security, color: Colors.orange),
              const SizedBox(width: 8),
              const Expanded(
                child: Text(
                  'Permission Required',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Colors.orange,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text('Tool: $toolName'),
          if (toolInput != null) ...[
            const SizedBox(height: 4),
            Text(
              jsonEncode(toolInput),
              style: const TextStyle(fontSize: 12, fontFamily: 'monospace'),
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => _respondToPermission('deny'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: ZiaOlive.error,
                  ),
                  child: const Text('Deny'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: FilledButton(
                  onPressed: () => _respondToPermission('allow'),
                  child: const Text('Allow'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildMessagesList() {
    if (_messages.isEmpty) {
      return Center(
        child: Text(
          'No messages yet',
          style: TextStyle(color: ZiaOlive.shade300),
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _messages.length,
      itemBuilder: (context, index) {
        final msg = _messages[index];
        return _buildMessageTile(msg);
      },
    );
  }

  Widget _buildMessageTile(Map<String, dynamic> msg) {
    final type = msg['type'] as String? ?? 'unknown';

    Color bgColor;
    IconData icon;
    String title;

    switch (type) {
      case 'user':
        bgColor = ZiaOlive.shade500.withValues(alpha: 0.1);
        icon = Icons.person;
        title = 'User';
        break;
      case 'assistant':
        bgColor = ZiaOlive.shade100;
        icon = Icons.smart_toy;
        title = 'Assistant';
        break;
      case 'result':
        bgColor = Colors.green.withValues(alpha: 0.1);
        icon = Icons.check_circle;
        title = 'Result';
        break;
      default:
        bgColor = Colors.grey.withValues(alpha: 0.1);
        icon = Icons.info;
        title = type;
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: ZiaOlive.shade400),
              const SizedBox(width: 6),
              Text(
                title,
                style: TextStyle(
                  fontWeight: FontWeight.w600,
                  color: ZiaOlive.shade400,
                  fontSize: 12,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            _extractContent(msg),
            style: const TextStyle(fontSize: 14),
          ),
        ],
      ),
    );
  }

  String _extractContent(Map<String, dynamic> msg) {
    final type = msg['type'] as String? ?? '';
    final message = msg['message'] as Map<String, dynamic>?;

    if (message != null) {
      final content = message['content'];
      if (content is List) {
        final texts = content
            .whereType<Map<String, dynamic>>()
            .where((c) => c['type'] == 'text')
            .map((c) => c['text'] as String? ?? '')
            .join('\n');
        if (texts.isNotEmpty) return texts;
      }
    }

    if (type == 'result') {
      final costUsd = msg['costUsd'];
      return 'Completed${costUsd != null ? ' (\$${costUsd.toStringAsFixed(4)})' : ''}';
    }

    return jsonEncode(msg).substring(0, 200.clamp(0, jsonEncode(msg).length));
  }

  Widget _buildInputArea() {
    return Container(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 8,
        bottom: MediaQuery.of(context).padding.bottom + 8,
      ),
      decoration: BoxDecoration(
        color: Theme.of(context).scaffoldBackgroundColor,
        border: Border(
          top: BorderSide(color: ZiaOlive.shade100),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _promptController,
              decoration: InputDecoration(
                hintText: 'Send prompt to CLI...',
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(24),
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 12,
                ),
              ),
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _sendPrompt(),
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(
            onPressed: _sendPrompt,
            icon: const Icon(Icons.send),
          ),
        ],
      ),
    );
  }
}

/// CLI 项目模型
class CLIProject {
  final String path;
  final String name;
  final String fullPath;
  final int sessionCount;
  final DateTime? lastModified;

  CLIProject({
    required this.path,
    required this.name,
    required this.fullPath,
    required this.sessionCount,
    this.lastModified,
  });

  factory CLIProject.fromJson(Map<String, dynamic> json) {
    return CLIProject(
      path: json['path'] as String,
      name: json['name'] as String,
      fullPath: json['full_path'] as String,
      sessionCount: json['session_count'] as int? ?? 0,
      lastModified: json['last_modified'] != null
          ? DateTime.tryParse(json['last_modified'] as String)
          : null,
    );
  }
}

/// CLI 会话模型
class CLISession {
  final String sessionId;
  final String projectPath;
  final DateTime? createdAt;
  final DateTime? lastMessageAt;
  final int messageCount;
  final String? lastPrompt;
  final double? totalCostUsd;

  CLISession({
    required this.sessionId,
    required this.projectPath,
    this.createdAt,
    this.lastMessageAt,
    this.messageCount = 0,
    this.lastPrompt,
    this.totalCostUsd,
  });

  factory CLISession.fromJson(Map<String, dynamic> json) {
    return CLISession(
      sessionId: json['session_id'] as String,
      projectPath: json['project_path'] as String,
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'] as String)
          : null,
      lastMessageAt: json['last_message_at'] != null
          ? DateTime.tryParse(json['last_message_at'] as String)
          : null,
      messageCount: json['message_count'] as int? ?? 0,
      lastPrompt: json['last_prompt'] as String?,
      totalCostUsd: json['total_cost_usd'] as double?,
    );
  }
}
