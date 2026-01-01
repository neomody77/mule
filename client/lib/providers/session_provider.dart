import 'dart:async';

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
        .where((s) => s.serverId == serverId && s.workspaceId == workspaceId)
        .toList();
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

  /// 加载保存的 sessions
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
    final session = ChatSession(
      id: const Uuid().v4(),
      serverId: serverId,
      workspaceId: workspaceId,
      workspaceName: workspaceName,
      name: name ?? 'New Session',
    );

    state = state.copyWith(sessions: [...state.sessions, session]);
    await _save();

    return session;
  }

  /// 删除 session
  Future<void> deleteSession(String sessionId) async {
    await _connectionPool.unsubscribe(sessionId);

    final newSessions = state.sessions.where((s) => s.id != sessionId).toList();
    state = state.copyWith(
      sessions: newSessions,
      clearActiveSession: state.activeSessionId == sessionId,
    );

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

    // 每次进入都发送订阅（服务器会返回 subscribed，触发状态变为 connected）
    await _connectionPool.subscribe(
      sessionId: sessionId,
      workspaceId: session.workspaceId,
      serverConfig: serverConfig,
    );
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
    );
    _addMessage(sessionId, userMessage);

    _connectionPool.sendPrompt(sessionId, content);

    _updateSession(sessionId, (s) => s.copyWith(isProcessing: true));
  }

  /// 取消当前任务
  void cancelTask(String sessionId) {
    _connectionPool.sendCancel(sessionId);
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

  /// 处理连接池事件
  void _handleEvent(WsEvent event) {
    final sessionId = event.sessionId;
    if (sessionId.isEmpty) return;

    debugPrint('[SessionNotifier] Event for $sessionId: ${event.event}');

    // 如果收到消息相关事件，且不是当前活跃的 session，标记为未读
    final isMessageEvent = ['text_delta', 'tool_use_start', 'message_end'].contains(event.event);
    if (isMessageEvent && state.activeSessionId != sessionId) {
      _updateSession(sessionId, (s) => s.copyWith(hasUnread: true));
    }

    switch (event.event) {
      case 'text_delta':
        _handleTextDelta(sessionId, event.data);
        break;
      case 'tool_use_start':
        _handleToolStart(sessionId, event.data);
        break;
      case 'tool_result':
        _handleToolResult(sessionId, event.data);
        break;
      case 'message_end':
        _handleMessageEnd(sessionId);
        break;
      case 'error':
        _handleError(sessionId, event.data);
        break;
      case 'task_info':
        _handleTaskInfo(sessionId, event.data);
        break;
      case 'status':
        _handleStatus(sessionId, event.data);
        break;
      case 'prompt_queued':
        _handlePromptQueued(sessionId, event.data);
        break;
      case 'prompt_dequeued':
        _handlePromptDequeued(sessionId, event.data);
        break;
      case 'session_title_updated':
        _handleSessionTitleUpdated(sessionId, event.data);
        break;
    }
  }

  void _handleTextDelta(String sessionId, Map<String, dynamic> data) {
    final text = data['text'] as String? ?? '';
    final session = state.getSession(sessionId);
    if (session == null) return;

    // 如果最后一条是 status 消息（如 thinking），先移除它
    if (session.messages.isNotEmpty &&
        session.messages.last.type == MessageType.status) {
      _removeLastMessage(sessionId);
    }

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

    // 如果最后一条是 status 消息（如 thinking），先移除它
    if (session.messages.isNotEmpty &&
        session.messages.last.type == MessageType.status) {
      _removeLastMessage(sessionId);
    }

    final toolId = data['id'] as String? ?? const Uuid().v4();

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
      name: data['name'] as String? ?? 'unknown',
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
      // 任务开始
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
      // 显示 thinking 状态（替换之前的 task_start）
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
    } else if (statusType == 'cancelled') {
      // 先停止最后一条消息的 streaming 状态
      _updateLastMessage(sessionId, (m) => m.copyWith(isStreaming: false));
      // 添加取消状态消息
      _addMessage(
        sessionId,
        ChatMessage(
          type: MessageType.status,
          content: message ?? 'Task cancelled',
        ),
      );
      _updateSession(sessionId, (s) => s.copyWith(isProcessing: false));
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
      if (change.state == WsConnectionState.disconnected ||
          change.state == WsConnectionState.error) {
        updated = updated.copyWith(isProcessing: false);
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
