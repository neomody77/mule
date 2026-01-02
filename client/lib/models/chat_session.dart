import 'dart:convert';

import 'message.dart';

/// 连接状态
enum SessionConnectionState {
  disconnected,
  connecting,
  connected,
  error,
}

/// 待执行的提示
class PendingPrompt {
  final String id;
  final String content;
  final int position;

  PendingPrompt({required this.id, required this.content, required this.position});
}

/// Todo 状态
enum TodoStatus {
  pending,
  inProgress,
  completed,
}

/// Todo 项目
class TodoItem {
  final String content;
  final String activeForm;
  final TodoStatus status;

  TodoItem({
    required this.content,
    required this.activeForm,
    required this.status,
  });

  factory TodoItem.fromJson(Map<String, dynamic> json) {
    final statusStr = json['status'] as String? ?? 'pending';
    final status = switch (statusStr) {
      'in_progress' => TodoStatus.inProgress,
      'completed' => TodoStatus.completed,
      _ => TodoStatus.pending,
    };
    return TodoItem(
      content: json['content'] as String? ?? '',
      activeForm: json['activeForm'] as String? ?? '',
      status: status,
    );
  }
}

/// 聊天会话模型
class ChatSession {
  final String id;
  final String serverId;
  final String workspaceId;
  final String workspaceName;
  String name;
  final DateTime createdAt;
  DateTime lastActiveAt;
  List<ChatMessage> messages;
  SessionConnectionState connectionState;
  bool isProcessing;
  String? error;
  bool hasUnread; // 是否有未读消息（用户离开页面后收到的消息）
  List<PendingPrompt> pendingPrompts; // 排队中的消息
  List<TodoItem> todos; // 当前任务的 todo list
  bool deleted; // 是否已软删除
  DateTime? deletedAt; // 删除时间

  ChatSession({
    required this.id,
    required this.serverId,
    required this.workspaceId,
    required this.workspaceName,
    required this.name,
    DateTime? createdAt,
    DateTime? lastActiveAt,
    List<ChatMessage>? messages,
    this.connectionState = SessionConnectionState.disconnected,
    this.isProcessing = false,
    this.error,
    this.hasUnread = false,
    List<PendingPrompt>? pendingPrompts,
    List<TodoItem>? todos,
    this.deleted = false,
    this.deletedAt,
  })  : createdAt = createdAt ?? DateTime.now(),
        lastActiveAt = lastActiveAt ?? DateTime.now(),
        messages = messages ?? [],
        pendingPrompts = pendingPrompts ?? [],
        todos = todos ?? [];

  /// 是否已连接
  bool get isConnected => connectionState == SessionConnectionState.connected;

  /// 添加消息
  void addMessage(ChatMessage message) {
    messages.add(message);
    lastActiveAt = DateTime.now();
  }

  /// 更新最后一条消息
  void updateLastMessage(ChatMessage Function(ChatMessage) updater) {
    if (messages.isNotEmpty) {
      messages[messages.length - 1] = updater(messages.last);
      lastActiveAt = DateTime.now();
    }
  }

  /// 清空消息
  void clearMessages() {
    messages.clear();
  }

  /// 从 JSON 创建（不包含 messages，用于持久化 session 元数据）
  factory ChatSession.fromJson(Map<String, dynamic> json) {
    return ChatSession(
      id: json['id'] as String,
      serverId: json['serverId'] as String,
      workspaceId: json['workspaceId'] as String,
      workspaceName: json['workspaceName'] as String,
      name: json['name'] as String,
      createdAt: DateTime.parse(json['createdAt'] as String),
      lastActiveAt: DateTime.parse(json['lastActiveAt'] as String),
      deleted: json['deleted'] as bool? ?? false,
      deletedAt: json['deletedAt'] != null
          ? DateTime.parse(json['deletedAt'] as String)
          : null,
    );
  }

  /// 转为 JSON（不包含 messages）
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'serverId': serverId,
      'workspaceId': workspaceId,
      'workspaceName': workspaceName,
      'name': name,
      'createdAt': createdAt.toIso8601String(),
      'lastActiveAt': lastActiveAt.toIso8601String(),
      'deleted': deleted,
      'deletedAt': deletedAt?.toIso8601String(),
    };
  }

  /// 复制
  ChatSession copyWith({
    String? id,
    String? serverId,
    String? workspaceId,
    String? workspaceName,
    String? name,
    DateTime? createdAt,
    DateTime? lastActiveAt,
    List<ChatMessage>? messages,
    SessionConnectionState? connectionState,
    bool? isProcessing,
    String? error,
    bool? hasUnread,
    List<PendingPrompt>? pendingPrompts,
    List<TodoItem>? todos,
    bool? deleted,
    DateTime? deletedAt,
    bool clearDeletedAt = false,
  }) {
    return ChatSession(
      id: id ?? this.id,
      serverId: serverId ?? this.serverId,
      workspaceId: workspaceId ?? this.workspaceId,
      workspaceName: workspaceName ?? this.workspaceName,
      name: name ?? this.name,
      createdAt: createdAt ?? this.createdAt,
      lastActiveAt: lastActiveAt ?? this.lastActiveAt,
      messages: messages ?? List.from(this.messages),
      connectionState: connectionState ?? this.connectionState,
      isProcessing: isProcessing ?? this.isProcessing,
      error: error,
      hasUnread: hasUnread ?? this.hasUnread,
      pendingPrompts: pendingPrompts ?? List.from(this.pendingPrompts),
      todos: todos ?? List.from(this.todos),
      deleted: deleted ?? this.deleted,
      deletedAt: clearDeletedAt ? null : (deletedAt ?? this.deletedAt),
    );
  }

  @override
  String toString() => 'ChatSession($name @ $workspaceName)';

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is ChatSession &&
          runtimeType == other.runtimeType &&
          id == other.id;

  @override
  int get hashCode => id.hashCode;
}

/// Session 列表的 JSON 序列化辅助
class ChatSessionList {
  static String encode(List<ChatSession> sessions) {
    return jsonEncode(sessions.map((s) => s.toJson()).toList());
  }

  static List<ChatSession> decode(String json) {
    final List<dynamic> list = jsonDecode(json);
    return list.map((e) => ChatSession.fromJson(e)).toList();
  }
}
