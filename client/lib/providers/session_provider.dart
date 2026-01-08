import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../models/chat_session.dart';
import '../models/message.dart';
import '../models/server_config.dart';
import '../services/connection_pool.dart';

/// Session 状态
class SessionState {
  final List<ChatSession> sessions;
  final String? activeSessionId;
  final bool isLoading;

  const SessionState({
    this.sessions = const [],
    this.activeSessionId,
    this.isLoading = false,
  });

  SessionState copyWith({
    List<ChatSession>? sessions,
    String? activeSessionId,
    bool clearActiveSession = false,
    bool? isLoading,
  }) {
    return SessionState(
      sessions: sessions ?? this.sessions,
      activeSessionId: clearActiveSession ? null : (activeSessionId ?? this.activeSessionId),
      isLoading: isLoading ?? this.isLoading,
    );
  }

  ChatSession? get activeSession {
    if (activeSessionId == null) return null;
    return getSession(activeSessionId!);
  }

  ChatSession? getSession(String sessionId) {
    try {
      return sessions.firstWhere((s) => s.id == sessionId);
    } catch (_) {
      return null;
    }
  }

  List<ChatSession> getSessionsForWorkspace(String serverId, String workspaceId) {
    return sessions
        .where((s) => s.serverId == serverId && s.workspaceId == workspaceId && !s.deleted)
        .toList();
  }

  /// 获取已删除的 sessions（回收站）
  List<ChatSession> get deletedSessions {
    return sessions.where((s) => s.deleted).toList()
      ..sort((a, b) => (b.deletedAt ?? b.lastActiveAt).compareTo(a.deletedAt ?? a.lastActiveAt));
  }
}

/// Session Notifier
class SessionNotifier extends StateNotifier<SessionState> {
  static const String _storageKey = 'mule_sessions';

  final ConnectionPool _connectionPool = ConnectionPool();
  StreamSubscription? _eventSubscription;
  StreamSubscription? _sessionStateSubscription;

  SessionNotifier() : super(const SessionState()) {
    _eventSubscription = _connectionPool.eventStream.listen(_handleEvent);
    _sessionStateSubscription = _connectionPool.sessionStateStream.listen(_handleStateChange);
  }

  ConnectionPool get connectionPool => _connectionPool;

  /// 连接到所有已配置的服务器（App 启动时调用）
  Future<void> connectAllServers(List<ServerConfig> servers) async {
    for (final server in servers) {
      try {
        await _connectionPool.connectServer(server);
      } catch (e) {
        debugPrint('[SessionNotifier] Failed to connect server ${server.id}: $e');
      }
    }
  }

  /// 加载保存的 sessions（本地缓存）
  Future<void> load() async {
    state = state.copyWith(isLoading: true);
    try {
      final prefs = await SharedPreferences.getInstance();
      final json = prefs.getString(_storageKey);
      if (json != null) {
        final sessions = ChatSessionList.decode(json);
        state = state.copyWith(sessions: sessions, isLoading: false);
      } else {
        state = state.copyWith(isLoading: false);
      }
    } catch (e) {
      state = state.copyWith(isLoading: false);
    }
  }

  /// 从服务器同步指定 workspace 的 sessions
  Future<void> syncSessionsFromServer(
    ServerConfig serverConfig,
    String workspaceId,
    String workspaceName,
  ) async {
    debugPrint('[SessionNotifier] syncSessionsFromServer: workspace=$workspaceId');
    try {
      final dio = Dio();
      dio.options.headers['Authorization'] = 'Bearer ${serverConfig.token}';
      dio.options.headers['X-API-Token'] = serverConfig.token;

      final url = '${serverConfig.httpBaseUrl}/api/workspaces/$workspaceId/sessions';
      debugPrint('[SessionNotifier] Fetching sessions from: $url');

      final response = await dio.get(url);

      final List<dynamic> serverSessions = response.data;
      debugPrint('[SessionNotifier] Fetched ${serverSessions.length} sessions from server');

      // 获取当前该 workspace 的本地 sessions
      final localSessions = state.sessions
          .where((s) => s.serverId == serverConfig.id && s.workspaceId == workspaceId)
          .toList();
      final localSessionIds = localSessions.map((s) => s.id).toSet();

      // 合并服务器 sessions
      final newSessions = <ChatSession>[];
      for (final serverSession in serverSessions) {
        final sessionId = serverSession['id'] as String;
        final title = serverSession['title'] as String?;
        final createdAt = serverSession['created_at'] as String?;
        final updatedAt = serverSession['updated_at'] as String?;

        if (localSessionIds.contains(sessionId)) {
          // 本地已有，更新标题（如果服务端有标题）
          final localSession = localSessions.firstWhere((s) => s.id == sessionId);
          if (title != null && title.isNotEmpty && localSession.name != title) {
            localSession.name = title;
          }
          newSessions.add(localSession);
          localSessionIds.remove(sessionId);
        } else {
          // 本地没有，创建新的
          newSessions.add(ChatSession(
            id: sessionId,
            serverId: serverConfig.id,
            workspaceId: workspaceId,
            workspaceName: workspaceName,
            // 如果没有 title，使用 session ID 的前 8 位
            name: (title != null && title.isNotEmpty) ? title : sessionId.substring(0, 8),
            createdAt: createdAt != null ? DateTime.tryParse(createdAt) : null,
          ));
        }
      }

      // 保留不属于此 workspace 的 sessions
      final otherSessions = state.sessions
          .where((s) => !(s.serverId == serverConfig.id && s.workspaceId == workspaceId))
          .toList();

      // 按更新时间排序（新的在前）
      newSessions.sort((a, b) => (b.createdAt ?? DateTime.now()).compareTo(a.createdAt ?? DateTime.now()));

      state = state.copyWith(sessions: [...otherSessions, ...newSessions]);
      await _save();
    } catch (e) {
      debugPrint('[SessionNotifier] Failed to sync sessions from server: $e');
    }
  }

  /// 保存 sessions
  Future<void> _save() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_storageKey, ChatSessionList.encode(state.sessions));
    } catch (e) {
      // ignore
    }
  }

  /// 创建新 session
  Future<ChatSession> createSession({
    required String serverId,
    required String workspaceId,
    required String workspaceName,
    String? name,
  }) async {
    final sessionId = const Uuid().v4();
    final session = ChatSession(
      id: sessionId,
      serverId: serverId,
      workspaceId: workspaceId,
      workspaceName: workspaceName,
      // 如果没有提供名字，使用 session ID 的前 8 位
      name: name ?? sessionId.substring(0, 8),
    );

    state = state.copyWith(sessions: [...state.sessions, session]);
    await _save();

    return session;
  }

  /// 软删除 session（移到回收站）
  Future<void> deleteSession(String sessionId) async {
    await _connectionPool.unsubscribe(sessionId);

    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      final session = newSessions[index];
      newSessions[index] = session.copyWith(
        deleted: true,
        deletedAt: DateTime.now(),
      );
      state = state.copyWith(
        sessions: newSessions,
        clearActiveSession: state.activeSessionId == sessionId,
      );
      await _save();
    }
  }

  /// 恢复 session（从回收站恢复）
  Future<void> restoreSession(String sessionId) async {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      final session = newSessions[index];
      newSessions[index] = session.copyWith(
        deleted: false,
        clearDeletedAt: true,
      );
      state = state.copyWith(sessions: newSessions);
      await _save();
    }
  }

  /// 永久删除 session
  Future<void> permanentlyDeleteSession(String sessionId) async {
    await _connectionPool.unsubscribe(sessionId);

    final newSessions = state.sessions.where((s) => s.id != sessionId).toList();
    state = state.copyWith(
      sessions: newSessions,
      clearActiveSession: state.activeSessionId == sessionId,
    );

    await _save();
  }

  /// 清空回收站
  Future<void> emptyTrash() async {
    final deletedIds = state.sessions.where((s) => s.deleted).map((s) => s.id).toList();
    for (final id in deletedIds) {
      await _connectionPool.unsubscribe(id);
    }

    final newSessions = state.sessions.where((s) => !s.deleted).toList();
    state = state.copyWith(sessions: newSessions);
    await _save();
  }

  /// 重命名 session
  Future<void> renameSession(String sessionId, String newName) async {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      newSessions[index].name = newName;
      state = state.copyWith(sessions: newSessions);
      await _save();
    }
  }

  /// 设置活跃 session（进入 session 页面时调用）
  void setActiveSession(String? sessionId) {
    // 如果设置了新的活跃 session，清除其未读标记
    if (sessionId != null) {
      _updateSession(sessionId, (s) => s.copyWith(hasUnread: false));
    }

    state = state.copyWith(
      activeSessionId: sessionId,
      clearActiveSession: sessionId == null,
    );
  }

  /// 订阅 session（连接到服务器并订阅该 session 的事件）
  /// 每次进入 session 都发送订阅请求，状态从 connecting -> connected
  Future<void> connectSession(String sessionId, ServerConfig serverConfig) async {
    final session = state.getSession(sessionId);
    if (session == null) return;

    // 立即设置为 connecting 状态
    _updateSession(sessionId, (s) => s.copyWith(
      connectionState: SessionConnectionState.connecting,
    ));

    // 加载服务端消息历史（如果本地没有消息）
    if (session.messages.isEmpty) {
      await _loadMessageHistory(sessionId, session.workspaceId, serverConfig);
    }

    // 每次进入都发送订阅（服务器会返回 subscribed，触发状态变为 connected）
    await _connectionPool.subscribe(
      sessionId: sessionId,
      workspaceId: session.workspaceId,
      serverConfig: serverConfig,
    );
  }

  /// 从服务端加载消息历史（分批加载：先显示最近5条，后台加载剩余）
  Future<void> _loadMessageHistory(
    String sessionId,
    String workspaceId,
    ServerConfig serverConfig,
  ) async {
    try {
      final messagesData = await _fetchMessages(workspaceId, sessionId, serverConfig);
      if (messagesData.isEmpty) return;

      final allMessages = _parseMessages(messagesData);
      final totalCount = allMessages.length;

      if (totalCount <= 5) {
        // 消息少于5条，直接全部加载
        _addMessagesToSession(sessionId, allMessages);
        debugPrint('[SessionNotifier] Loaded all $totalCount messages');
      } else {
        // 先加载最近5条
        final recentMessages = allMessages.sublist(totalCount - 5);
        _addMessagesToSession(sessionId, recentMessages);
        debugPrint('[SessionNotifier] Loaded recent 5 messages, loading remaining ${totalCount - 5}...');

        // 后台加载剩余消息并插入到前面
        Future.delayed(const Duration(milliseconds: 100), () {
          final olderMessages = allMessages.sublist(0, totalCount - 5);
          _prependMessagesToSession(sessionId, olderMessages);
          debugPrint('[SessionNotifier] Loaded remaining ${olderMessages.length} messages');
        });
      }
    } catch (e) {
      debugPrint('[SessionNotifier] Failed to load message history: $e');
    }
  }

  /// 将消息插入到 session 消息列表前面
  void _prependMessagesToSession(String sessionId, List<ChatMessage> messages) {
    if (messages.isEmpty) return;

    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      final session = newSessions[index];
      // 插入到前面
      session.messages.insertAll(0, messages);
      state = state.copyWith(sessions: newSessions);
    }
  }

  Future<List<dynamic>> _fetchMessages(
    String workspaceId,
    String sessionId,
    ServerConfig serverConfig,
  ) async {
    final dio = Dio();
    dio.options.headers['Authorization'] = 'Bearer ${serverConfig.token}';
    dio.options.headers['X-API-Token'] = serverConfig.token;

    final response = await dio.get(
      '${serverConfig.httpBaseUrl}/api/workspaces/$workspaceId/sessions/$sessionId/messages',
    );
    return response.data['messages'] ?? [];
  }

  List<ChatMessage> _parseMessages(List<dynamic> messagesData) {
    final messages = <ChatMessage>[];

    // 消息解析器映射
    final parsers = <String, void Function(String, Map<String, dynamic>?, List<ChatMessage>)>{
      'user': (content, _, msgs) => msgs.add(ChatMessage(type: MessageType.user, content: content)),
      'assistant': (content, _, msgs) => msgs.add(ChatMessage(type: MessageType.assistant, content: content)),
      'tool_use': (content, data, msgs) => msgs.add(ChatMessage(
        type: MessageType.toolCall,
        toolCalls: [ToolCall(id: data?['id'] ?? '', name: data?['name'] ?? '', description: content)],
      )),
      'tool_result': (content, data, msgs) => _updateToolResult(msgs, data?['id'] ?? '', content, data?['is_error'] ?? false),
    };

    for (final msgData in messagesData) {
      final type = msgData['type'] as String;
      final content = msgData['content'] as String? ?? '';
      final data = msgData['data'] as Map<String, dynamic>?;
      parsers[type]?.call(content, data, messages);
    }

    return messages;
  }

  void _updateToolResult(List<ChatMessage> messages, String toolId, String content, bool isError) {
    for (int i = messages.length - 1; i >= 0; i--) {
      final msg = messages[i];
      if (msg.type == MessageType.toolCall &&
          msg.toolCalls.isNotEmpty &&
          msg.toolCalls.first.id == toolId) {
        messages[i] = msg.updateToolCall(toolId, (tc) => tc.copyWith(
          result: {'content': content, 'is_error': isError},
          isExecuting: false,
        ));
        break;
      }
    }
  }

  void _addMessagesToSession(String sessionId, List<ChatMessage> messages) {
    if (messages.isEmpty) return;

    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      for (final msg in messages) {
        newSessions[index].addMessage(msg);
      }
      state = state.copyWith(sessions: newSessions);
    }
  }

  /// 断开 session 连接（仅更新 UI 状态，不取消订阅）
  /// 用户手动断开时调用，不会真正取消订阅，下次进入时重新订阅即可
  Future<void> disconnectSession(String sessionId) async {
    // 仅更新 UI 状态，不发送 unsubscribe 消息
    _updateSession(sessionId, (s) => s.copyWith(
      connectionState: SessionConnectionState.disconnected,
    ));
  }

  /// 发送消息
  void sendMessage(String sessionId, String content) {
    final session = state.getSession(sessionId);
    if (session == null) return;

    final userMessage = ChatMessage(
      type: MessageType.user,
      content: content,
      isPending: true, // 发送时标记为 pending
    );
    _addMessage(sessionId, userMessage);

    _connectionPool.sendPrompt(sessionId, content);

    _updateSession(sessionId, (s) => s.copyWith(isProcessing: true));
  }

  /// 发送带图片的消息
  void sendImageMessage(
    String sessionId,
    Uint8List imageBytes,
    String fileName, {
    String? prompt,
  }) {
    final session = state.getSession(sessionId);
    if (session == null) return;

    // 根据文件名确定 MIME 类型
    final ext = fileName.split('.').last.toLowerCase();
    final mediaType = switch (ext) {
      'png' => 'image/png',
      'gif' => 'image/gif',
      'webp' => 'image/webp',
      _ => 'image/jpeg', // 默认 jpeg
    };

    // 转换为 base64
    final imageBase64 = base64Encode(imageBytes);

    // 构建显示内容
    final displayContent = prompt ?? '[Image: $fileName]';

    final userMessage = ChatMessage(
      type: MessageType.user,
      content: displayContent,
      isPending: true,
      imageData: imageBytes, // 本地显示用
    );
    _addMessage(sessionId, userMessage);

    _connectionPool.sendPromptWithImage(
      sessionId,
      prompt ?? 'Please analyze this image.',
      imageBase64,
      mediaType,
    );

    _updateSession(sessionId, (s) => s.copyWith(isProcessing: true));
  }

  /// 取消当前任务
  void cancelTask(String sessionId) {
    _connectionPool.sendCancel(sessionId);
  }

  /// 压缩上下文
  void compactContext(String sessionId) {
    _connectionPool.sendCompact(sessionId);
  }

  /// AI 生成标题
  void generateTitle(String sessionId) {
    _connectionPool.sendGenerateTitle(sessionId);
  }

  /// 发送 ping
  void pingSession(String sessionId) {
    _connectionPool.sendPingForSession(sessionId);
  }

  /// 保存输入框草稿
  void saveDraft(String sessionId, String draft) {
    _updateSession(sessionId, (s) => s.copyWith(draft: draft));
    // 延迟保存，避免频繁写入
    Future.delayed(const Duration(milliseconds: 500), () => _save());
  }

  /// 清除 session 消息
  void clearMessages(String sessionId) {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      newSessions[index].clearMessages();
      state = state.copyWith(sessions: newSessions);
      _save();
    }
  }

  // 事件处理器映射
  late final Map<String, void Function(String, Map<String, dynamic>)> _eventHandlers = {
    'text_delta': _handleTextDelta,
    'tool_use_start': _handleToolStart,
    'tool_result': _handleToolResult,
    'message_end': (sid, _) => _handleMessageEnd(sid),
    'error': _handleError,
    'task_info': _handleTaskInfo,
    'status': _handleStatus,
    'prompt_queued': _handlePromptQueued,
    'prompt_dequeued': _handlePromptDequeued,
    'session_title_updated': _handleSessionTitleUpdated,
    'user_message': _handleUserMessage,
    'todos_sync': _handleTodosSync,
  };

  // 标记未读的事件类型
  static const _messageEvents = {'text_delta', 'tool_use_start', 'message_end'};

  /// 处理连接池事件
  void _handleEvent(WsEvent event) {
    final sessionId = event.sessionId;
    if (sessionId.isEmpty) return;

    debugPrint('[SessionNotifier] Event for $sessionId: ${event.event}');

    // 如果收到消息相关事件，且不是当前活跃的 session，标记为未读
    if (_messageEvents.contains(event.event) && state.activeSessionId != sessionId) {
      _updateSession(sessionId, (s) => s.copyWith(hasUnread: true));
    }

    // 使用 handler map 分发事件
    _eventHandlers[event.event]?.call(sessionId, event.data);
  }

  void _handleTextDelta(String sessionId, Map<String, dynamic> data) {
    final text = data['text'] as String? ?? '';
    final session = state.getSession(sessionId);
    if (session == null) return;

    // 移除所有 status 消息（如 thinking）
    _removeAllStatusMessages(sessionId);

    // 去重：如果最后一条消息内容相同，跳过
    final updatedSession = state.getSession(sessionId);
    if (updatedSession != null &&
        updatedSession.messages.isNotEmpty &&
        updatedSession.messages.last.type == MessageType.assistant &&
        updatedSession.messages.last.content == text) {
      return;
    }

    // 每次都添加新消息（按顺序展示）
    _addMessage(
      sessionId,
      ChatMessage(
        type: MessageType.assistant,
        content: text,
      ),
    );
  }

  void _handleToolStart(String sessionId, Map<String, dynamic> data) {
    final session = state.getSession(sessionId);
    if (session == null) return;

    // 移除所有 status 消息（如 thinking）
    _removeAllStatusMessages(sessionId);

    final toolId = data['id'] as String? ?? const Uuid().v4();
    final toolName = data['name'] as String? ?? 'unknown';

    // 特殊处理 TodoWrite 工具 - 更新 session 的 todo list
    if (toolName == 'TodoWrite') {
      _handleTodoWrite(sessionId, data);
      return; // 不显示为普通工具调用
    }

    // 去重：检查是否已有相同 toolId 的消息
    final updatedSession = state.getSession(sessionId);
    if (updatedSession != null) {
      for (final msg in updatedSession.messages) {
        if (msg.type == MessageType.toolCall &&
            msg.toolCalls.isNotEmpty &&
            msg.toolCalls.first.id == toolId) {
          return; // 已存在，跳过
        }
      }
    }

    final toolCall = ToolCall(
      id: toolId,
      name: toolName,
      description: data['description'] as String?,
      isExecuting: true,
    );

    // 每次工具调用都添加新消息
    _addMessage(
      sessionId,
      ChatMessage(
        type: MessageType.toolCall,
        toolCalls: [toolCall],
      ),
    );
  }

  /// 处理 TodoWrite 工具调用
  void _handleTodoWrite(String sessionId, Map<String, dynamic> data) {
    final input = data['input'] as Map<String, dynamic>?;
    if (input == null) return;

    final todosData = input['todos'] as List<dynamic>?;
    if (todosData == null) return;

    final todos = todosData
        .map((t) => TodoItem.fromJson(t as Map<String, dynamic>))
        .toList();

    debugPrint('[SessionNotifier] TodoWrite: ${todos.length} todos');
    _updateSession(sessionId, (s) => s.copyWith(todos: todos));
  }

  /// 处理 todos_sync 事件（订阅时从服务端加载）
  void _handleTodosSync(String sessionId, Map<String, dynamic> data) {
    final todosData = data['todos'] as List<dynamic>?;
    if (todosData == null || todosData.isEmpty) return;

    final todos = todosData
        .map((t) => TodoItem.fromJson(t as Map<String, dynamic>))
        .toList();

    debugPrint('[SessionNotifier] Todos sync: ${todos.length} todos');
    _updateSession(sessionId, (s) => s.copyWith(todos: todos));
  }

  void _handleToolResult(String sessionId, Map<String, dynamic> data) {
    final toolId = data['id'] as String?;
    final content = data['content'] as String?;
    final isError = data['is_error'] as bool? ?? false;

    // 找到对应的工具消息并更新
    if (toolId != null) {
      final session = state.getSession(sessionId);
      if (session == null) return;

      // 从后往前找到对应 toolId 的消息
      for (int i = session.messages.length - 1; i >= 0; i--) {
        final msg = session.messages[i];
        if (msg.type == MessageType.toolCall &&
            msg.toolCalls.isNotEmpty &&
            msg.toolCalls.first.id == toolId) {
          _updateMessageAt(sessionId, i, (m) {
            return m.updateToolCall(toolId, (tc) {
              return tc.copyWith(
                result: {'content': content, 'is_error': isError},
                isExecuting: false,
              );
            });
          });
          break;
        }
      }
    }
  }

  void _handleMessageEnd(String sessionId) {
    final session = state.getSession(sessionId);
    if (session == null) return;

    // 如果最后一条是 status 消息（如 Thinking...），移除它
    if (session.messages.isNotEmpty &&
        session.messages.last.type == MessageType.status) {
      _removeLastMessage(sessionId);
    }

    // 停止最后一条消息的 streaming 状态
    _updateLastMessage(sessionId, (m) => m.copyWith(isStreaming: false));

    _updateSession(sessionId, (s) => s.copyWith(isProcessing: false));
  }

  void _handleError(String sessionId, Map<String, dynamic> data) {
    final message = data['message'] as String? ?? 'Unknown error';
    _addMessage(
      sessionId,
      ChatMessage(
        type: MessageType.error,
        content: message,
      ),
    );
    _updateSession(sessionId, (s) => s.copyWith(
      isProcessing: false,
      error: message,
    ));
  }

  void _handleTaskInfo(String sessionId, Map<String, dynamic> data) {
    final status = data['status'] as String?;
    if (status == 'running') {
      _updateSession(sessionId, (s) => s.copyWith(isProcessing: true));
    } else if (status == 'completed' || status == 'failed') {
      _updateSession(sessionId, (s) => s.copyWith(isProcessing: false));
    }
  }

  void _handlePromptQueued(String sessionId, Map<String, dynamic> data) {
    final id = data['id'] as String? ?? '';
    final content = data['content'] as String? ?? '';
    final position = data['position'] as int? ?? 1;

    final session = state.getSession(sessionId);
    if (session == null) return;

    final pending = PendingPrompt(id: id, content: content, position: position);
    final newPendingList = [...session.pendingPrompts, pending];

    _updateSession(sessionId, (s) => s.copyWith(pendingPrompts: newPendingList));
  }

  void _handlePromptDequeued(String sessionId, Map<String, dynamic> data) {
    // 服务端发送 ids 列表，表示所有被处理的 prompts
    final ids = (data['ids'] as List<dynamic>?)?.cast<String>() ?? [];

    final session = state.getSession(sessionId);
    if (session == null) return;

    // 移除所有匹配 id 的 pending prompts
    final idsSet = ids.toSet();
    final newPendingList = session.pendingPrompts.where((p) => !idsSet.contains(p.id)).toList();
    _updateSession(sessionId, (s) => s.copyWith(pendingPrompts: newPendingList));
  }

  void _handleStatus(String sessionId, Map<String, dynamic> data) {
    final statusType = data['type'] as String?;
    final message = data['message'] as String?;

    if (statusType == 'task_start') {
      // 任务开始 - 清除 pending 状态
      _clearPendingMessages(sessionId);
      _updateSession(sessionId, (s) => s.copyWith(isProcessing: true));
      // 添加 task_start 状态消息
      final session = state.getSession(sessionId);
      if (session != null &&
          (session.messages.isEmpty || session.messages.last.type != MessageType.status)) {
        _addMessage(
          sessionId,
          ChatMessage(
            type: MessageType.status,
            content: message ?? 'Starting task...',
            isStreaming: true,
          ),
        );
      }
    } else if (statusType == 'thinking') {
      // 显示 thinking 状态（替换之前的 task_start）- 也清除 pending 状态
      _clearPendingMessages(sessionId);
      _updateSession(sessionId, (s) => s.copyWith(isProcessing: true));
      // 如果最后一条是 status 消息，更新它；否则添加新的
      final session = state.getSession(sessionId);
      if (session != null && session.messages.isNotEmpty &&
          session.messages.last.type == MessageType.status) {
        _updateLastMessage(sessionId, (m) => m.copyWith(
          content: message ?? 'Thinking...',
        ));
      } else if (session != null) {
        _addMessage(
          sessionId,
          ChatMessage(
            type: MessageType.status,
            content: message ?? 'Thinking...',
            isStreaming: true,
          ),
        );
      }
    } else if (statusType == 'compacting') {
      // 压缩上下文中
      _updateSession(sessionId, (s) => s.copyWith(isProcessing: true, isCompacting: true));
      _addMessage(
        sessionId,
        ChatMessage(
          type: MessageType.status,
          content: message ?? 'Compacting context...',
          isStreaming: true,
        ),
      );
    } else if (statusType == 'compact_done') {
      // 压缩完成
      _removeAllStatusMessages(sessionId);
      _addMessage(
        sessionId,
        ChatMessage(
          type: MessageType.status,
          content: message ?? 'Context compacted',
        ),
      );
      _updateSession(sessionId, (s) => s.copyWith(isProcessing: false, isCompacting: false));
    } else if (statusType == 'cancelled') {
      // 先停止最后一条消息的 streaming 状态
      _updateLastMessage(sessionId, (m) => m.copyWith(isStreaming: false));

      // 从服务端返回的 cleared_prompts 恢复内容到 draft
      final clearedPrompts = (data['cleared_prompts'] as List<dynamic>?)?.cast<String>() ?? [];
      String? restoredDraft;
      if (clearedPrompts.isNotEmpty) {
        restoredDraft = clearedPrompts.join('\n');
      }

      // 添加取消状态消息
      _addMessage(
        sessionId,
        ChatMessage(
          type: MessageType.status,
          content: message ?? 'Task cancelled',
        ),
      );
      _updateSession(sessionId, (s) => s.copyWith(
        isProcessing: false,
        pendingPrompts: [],  // 清空 pending prompts
        draft: restoredDraft ?? s.draft,  // 恢复到 draft
      ));
    }
  }

  void _handleSessionTitleUpdated(String sessionId, Map<String, dynamic> data) {
    final title = data['title'] as String?;
    if (title != null && title.isNotEmpty) {
      debugPrint('[SessionNotifier] Session title updated: $title');
      _updateSession(sessionId, (s) => s.copyWith(name: title));
      _save();
    }
  }

  /// 处理其他客户端发送的用户消息
  void _handleUserMessage(String sessionId, Map<String, dynamic> data) {
    final content = data['content'] as String?;
    if (content == null || content.isEmpty) return;

    final session = state.getSession(sessionId);
    if (session == null) return;

    // 检查是否已经有这条消息（发送者本地已添加）
    // 如果最后一条消息是用户消息且内容相同，说明是自己发送的，跳过
    if (session.messages.isNotEmpty) {
      final lastMsg = session.messages.last;
      if (lastMsg.type == MessageType.user && lastMsg.content == content) {
        debugPrint('[SessionNotifier] Skipping duplicate user message');
        return;
      }
    }

    debugPrint('[SessionNotifier] Received user message from other client: $content');
    _addMessage(sessionId, ChatMessage(
      type: MessageType.user,
      content: content,
    ));
  }

  /// 处理 session 连接状态变化
  void _handleStateChange(({String sessionId, WsConnectionState state}) change) {
    final sessionState = switch (change.state) {
      WsConnectionState.disconnected => SessionConnectionState.disconnected,
      WsConnectionState.connecting => SessionConnectionState.connecting,
      WsConnectionState.connected => SessionConnectionState.connected,
      WsConnectionState.error => SessionConnectionState.error,
    };

    _updateSession(change.sessionId, (s) {
      var updated = s.copyWith(
        connectionState: sessionState,
        error: change.state == WsConnectionState.error ? 'Connection error' : null,
      );

      // 断开连接时，保存当前处理状态以便重连后同步
      if (change.state == WsConnectionState.disconnected ||
          change.state == WsConnectionState.error) {
        if (s.isProcessing) {
          // 标记断开前正在处理，用于重连后同步
          updated = updated.copyWith(
            isProcessing: false,
            wasProcessingBeforeDisconnect: true,
          );
        }
      }

      // 重连成功后，如果断开前正在处理，主动发送 sync 请求
      if (change.state == WsConnectionState.connected && s.wasProcessingBeforeDisconnect) {
        debugPrint('[SessionNotifier] Reconnected, syncing task status for session ${change.sessionId}');
        _connectionPool.sendSync(change.sessionId);
        updated = updated.copyWith(wasProcessingBeforeDisconnect: false);
      }

      return updated;
    });
  }

  void _addMessage(String sessionId, ChatMessage message) {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      newSessions[index].addMessage(message);
      state = state.copyWith(sessions: newSessions);
    }
  }

  /// 清除所有 pending 用户消息的 pending 状态
  void _clearPendingMessages(String sessionId) {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      final session = newSessions[index];
      bool hasChanges = false;
      for (int i = 0; i < session.messages.length; i++) {
        final msg = session.messages[i];
        if (msg.type == MessageType.user && msg.isPending) {
          session.messages[i] = msg.copyWith(isPending: false);
          hasChanges = true;
        }
      }
      if (hasChanges) {
        state = state.copyWith(sessions: newSessions);
      }
    }
  }

  void _removeLastMessage(String sessionId) {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      if (newSessions[index].messages.isNotEmpty) {
        newSessions[index].messages.removeLast();
        state = state.copyWith(sessions: newSessions);
      }
    }
  }

  /// 移除所有 status 消息（如 Thinking...）
  void _removeAllStatusMessages(String sessionId) {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      final session = newSessions[index];
      final originalLength = session.messages.length;
      session.messages.removeWhere((m) => m.type == MessageType.status);
      if (session.messages.length != originalLength) {
        state = state.copyWith(sessions: newSessions);
      }
    }
  }

  void _updateLastMessage(
    String sessionId,
    ChatMessage Function(ChatMessage) updater,
  ) {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      newSessions[index].updateLastMessage(updater);
      state = state.copyWith(sessions: newSessions);
    }
  }

  void _updateMessageAt(
    String sessionId,
    int messageIndex,
    ChatMessage Function(ChatMessage) updater,
  ) {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      final session = newSessions[index];
      if (messageIndex >= 0 && messageIndex < session.messages.length) {
        session.messages[messageIndex] = updater(session.messages[messageIndex]);
        state = state.copyWith(sessions: newSessions);
      }
    }
  }

  void _updateSession(
    String sessionId,
    ChatSession Function(ChatSession) updater,
  ) {
    final index = state.sessions.indexWhere((s) => s.id == sessionId);
    if (index >= 0) {
      final newSessions = [...state.sessions];
      newSessions[index] = updater(newSessions[index]);
      state = state.copyWith(sessions: newSessions);
    }
  }

  @override
  void dispose() {
    _eventSubscription?.cancel();
    _sessionStateSubscription?.cancel();
    _connectionPool.dispose();
    super.dispose();
  }
}

/// Session Provider
final sessionProvider = StateNotifierProvider<SessionNotifier, SessionState>((ref) {
  final notifier = SessionNotifier();
  notifier.load();
  return notifier;
});
