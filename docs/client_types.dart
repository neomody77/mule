/// Mule WebSocket 客户端类型定义
/// 用于 Flutter 客户端开发

// ============== 权限相关 ==============

/// 权限决策类型
enum PermissionDecision {
  approved,           // 单次批准
  approvedForSession, // 会话期间自动批准
  denied,             // 拒绝
  abort,              // 中止任务
}

extension PermissionDecisionExt on PermissionDecision {
  String get value {
    switch (this) {
      case PermissionDecision.approved:
        return 'approved';
      case PermissionDecision.approvedForSession:
        return 'approved_for_session';
      case PermissionDecision.denied:
        return 'denied';
      case PermissionDecision.abort:
        return 'abort';
    }
  }
}

/// 权限请求
class PermissionRequest {
  final String toolUseId;
  final String toolName;
  final Map<String, dynamic> toolInput;
  final String description;
  final List<dynamic> options;

  PermissionRequest({
    required this.toolUseId,
    required this.toolName,
    required this.toolInput,
    required this.description,
    this.options = const [],
  });

  factory PermissionRequest.fromJson(Map<String, dynamic> json) {
    return PermissionRequest(
      toolUseId: json['tool_use_id'] ?? '',
      toolName: json['tool_name'] ?? '',
      toolInput: json['tool_input'] ?? {},
      description: json['description'] ?? '',
      options: json['options'] ?? [],
    );
  }
}

// ============== 模式相关 ==============

/// 控制模式
enum ControlMode {
  local,  // 本地控制
  remote, // 远程控制
}

extension ControlModeExt on ControlMode {
  String get value => name;

  static ControlMode fromString(String s) {
    return s == 'local' ? ControlMode.local : ControlMode.remote;
  }
}

/// 模式切换原因
enum ModeChangeReason {
  userRequest,  // 用户请求
  timeout,      // 超时
  disconnect,   // 断开连接
  handoff,      // 交接
}

extension ModeChangeReasonExt on ModeChangeReason {
  static ModeChangeReason fromString(String s) {
    switch (s) {
      case 'user_request':
        return ModeChangeReason.userRequest;
      case 'timeout':
        return ModeChangeReason.timeout;
      case 'disconnect':
        return ModeChangeReason.disconnect;
      case 'handoff':
        return ModeChangeReason.handoff;
      default:
        return ModeChangeReason.userRequest;
    }
  }
}

/// 模式状态
class ModeStatus {
  final ControlMode mode;
  final double? switchedAt;
  final ModeChangeReason? reason;
  final ControlMode? previousMode;
  final int remoteConnections;
  final bool localActive;

  ModeStatus({
    required this.mode,
    this.switchedAt,
    this.reason,
    this.previousMode,
    this.remoteConnections = 0,
    this.localActive = false,
  });

  factory ModeStatus.fromJson(Map<String, dynamic> json) {
    return ModeStatus(
      mode: ControlModeExt.fromString(json['mode'] ?? 'remote'),
      switchedAt: json['switched_at']?.toDouble(),
      reason: json['reason'] != null
          ? ModeChangeReasonExt.fromString(json['reason'])
          : null,
      previousMode: json['previous_mode'] != null
          ? ControlModeExt.fromString(json['previous_mode'])
          : null,
      remoteConnections: json['remote_connections'] ?? 0,
      localActive: json['local_active'] ?? false,
    );
  }
}

// ============== 工具调用相关 ==============

/// 工具调用
class ToolUse {
  final String id;
  final String name;
  final Map<String, dynamic> input;
  final String? description;

  ToolUse({
    required this.id,
    required this.name,
    required this.input,
    this.description,
  });

  factory ToolUse.fromJson(Map<String, dynamic> json) {
    return ToolUse(
      id: json['id'] ?? '',
      name: json['name'] ?? '',
      input: json['input'] ?? {},
      description: json['description'],
    );
  }
}

/// 工具调用结果
class ToolResult {
  final String id;
  final String content;
  final bool isError;

  ToolResult({
    required this.id,
    required this.content,
    this.isError = false,
  });

  factory ToolResult.fromJson(Map<String, dynamic> json) {
    return ToolResult(
      id: json['id'] ?? '',
      content: json['content'] ?? '',
      isError: json['is_error'] ?? false,
    );
  }
}

// ============== WebSocket 消息 ==============

/// 客户端发送的消息
abstract class ClientMessage {
  String get type;
  Map<String, dynamic> toJson();
}

/// 订阅消息
class SubscribeMessage implements ClientMessage {
  @override
  String get type => 'subscribe';

  final String workspaceId;
  final String sessionId;

  SubscribeMessage({
    required this.workspaceId,
    required this.sessionId,
  });

  @override
  Map<String, dynamic> toJson() => {
    'type': type,
    'workspace_id': workspaceId,
    'session_id': sessionId,
  };
}

/// Prompt 消息
class PromptMessage implements ClientMessage {
  @override
  String get type => 'prompt';

  final String workspaceId;
  final String sessionId;
  final String content;
  final ImageData? image;

  PromptMessage({
    required this.workspaceId,
    required this.sessionId,
    required this.content,
    this.image,
  });

  @override
  Map<String, dynamic> toJson() {
    final json = {
      'type': type,
      'workspace_id': workspaceId,
      'session_id': sessionId,
      'content': content,
    };
    if (image != null) {
      json['image'] = image!.toJson();
    }
    return json;
  }
}

/// 图片数据
class ImageData {
  final String data; // base64
  final String mediaType;

  ImageData({required this.data, this.mediaType = 'image/jpeg'});

  Map<String, dynamic> toJson() => {
    'data': data,
    'media_type': mediaType,
  };
}

/// 权限响应消息
class PermissionResponseMessage implements ClientMessage {
  @override
  String get type => 'permission_response';

  final String workspaceId;
  final String sessionId;
  final String toolUseId;
  final PermissionDecision decision;
  final Map<String, dynamic>? updatedInput;

  PermissionResponseMessage({
    required this.workspaceId,
    required this.sessionId,
    required this.toolUseId,
    required this.decision,
    this.updatedInput,
  });

  @override
  Map<String, dynamic> toJson() {
    final json = {
      'type': type,
      'workspace_id': workspaceId,
      'session_id': sessionId,
      'tool_use_id': toolUseId,
      'decision': decision.value,
    };
    if (updatedInput != null) {
      json['updated_input'] = updatedInput;
    }
    return json;
  }
}

/// 模式切换消息
class SwitchModeMessage implements ClientMessage {
  @override
  String get type => 'switch_mode';

  final String workspaceId;
  final String sessionId;
  final ControlMode mode;

  SwitchModeMessage({
    required this.workspaceId,
    required this.sessionId,
    required this.mode,
  });

  @override
  Map<String, dynamic> toJson() => {
    'type': type,
    'workspace_id': workspaceId,
    'session_id': sessionId,
    'mode': mode.value,
  };
}

/// 获取模式消息
class GetModeMessage implements ClientMessage {
  @override
  String get type => 'get_mode';

  final String workspaceId;
  final String sessionId;

  GetModeMessage({
    required this.workspaceId,
    required this.sessionId,
  });

  @override
  Map<String, dynamic> toJson() => {
    'type': type,
    'workspace_id': workspaceId,
    'session_id': sessionId,
  };
}

/// 请求交接消息
class RequestHandoffMessage implements ClientMessage {
  @override
  String get type => 'request_handoff';

  final String workspaceId;
  final String sessionId;
  final ControlMode toMode;

  RequestHandoffMessage({
    required this.workspaceId,
    required this.sessionId,
    required this.toMode,
  });

  @override
  Map<String, dynamic> toJson() => {
    'type': type,
    'workspace_id': workspaceId,
    'session_id': sessionId,
    'to_mode': toMode.value,
  };
}

// ============== 服务器事件 ==============

/// 服务器事件类型
enum ServerEventType {
  subscribed,
  unsubscribed,
  textDelta,
  toolUseStart,
  toolResult,
  toolProgress,
  messageEnd,
  status,
  error,
  userMessage,
  // 权限相关
  permissionRequest,
  permissionResponded,
  pendingPermissions,
  // 模式相关
  modeChanged,
  modeStatus,
  handoffResult,
}

/// 服务器事件
class ServerEvent {
  final ServerEventType type;
  final String? workspaceId;
  final String? sessionId;
  final Map<String, dynamic> data;

  ServerEvent({
    required this.type,
    this.workspaceId,
    this.sessionId,
    required this.data,
  });

  factory ServerEvent.fromJson(Map<String, dynamic> json) {
    final eventStr = json['event'] as String? ?? '';
    final type = _parseEventType(eventStr);

    return ServerEvent(
      type: type,
      workspaceId: json['workspace_id'],
      sessionId: json['session_id'],
      data: json['data'] ?? {},
    );
  }

  static ServerEventType _parseEventType(String event) {
    switch (event) {
      case 'subscribed':
        return ServerEventType.subscribed;
      case 'unsubscribed':
        return ServerEventType.unsubscribed;
      case 'text_delta':
        return ServerEventType.textDelta;
      case 'tool_use_start':
        return ServerEventType.toolUseStart;
      case 'tool_result':
        return ServerEventType.toolResult;
      case 'tool_progress':
        return ServerEventType.toolProgress;
      case 'message_end':
        return ServerEventType.messageEnd;
      case 'status':
        return ServerEventType.status;
      case 'error':
        return ServerEventType.error;
      case 'user_message':
        return ServerEventType.userMessage;
      case 'permission_request':
        return ServerEventType.permissionRequest;
      case 'permission_responded':
        return ServerEventType.permissionResponded;
      case 'pending_permissions':
        return ServerEventType.pendingPermissions;
      case 'mode_changed':
        return ServerEventType.modeChanged;
      case 'mode_status':
        return ServerEventType.modeStatus;
      case 'handoff_result':
        return ServerEventType.handoffResult;
      default:
        return ServerEventType.error;
    }
  }

  // 便捷方法
  String? get text => data['text'];
  ToolUse? get toolUse => data.containsKey('name') ? ToolUse.fromJson(data) : null;
  ToolResult? get toolResult => data.containsKey('content') ? ToolResult.fromJson(data) : null;
  PermissionRequest? get permissionRequest =>
      type == ServerEventType.permissionRequest ? PermissionRequest.fromJson(data) : null;
  ModeStatus? get modeStatus =>
      type == ServerEventType.modeStatus ? ModeStatus.fromJson(data) : null;
}


// ============== 使用示例 ==============
/*

// 连接 WebSocket
final ws = WebSocketChannel.connect(Uri.parse('ws://localhost:8000/ws?token=xxx'));

// 订阅会话
ws.sink.add(jsonEncode(SubscribeMessage(
  workspaceId: 'default',
  sessionId: 'my-session',
).toJson()));

// 发送 prompt
ws.sink.add(jsonEncode(PromptMessage(
  workspaceId: 'default',
  sessionId: 'my-session',
  content: '帮我写一个 Hello World',
).toJson()));

// 处理事件
ws.stream.listen((message) {
  final event = ServerEvent.fromJson(jsonDecode(message));

  switch (event.type) {
    case ServerEventType.textDelta:
      print('AI: ${event.text}');
      break;
    case ServerEventType.permissionRequest:
      // 显示权限审批 UI
      final req = event.permissionRequest!;
      showPermissionDialog(req);
      break;
    case ServerEventType.modeChanged:
      print('Mode changed to: ${event.data['mode']}');
      break;
    default:
      break;
  }
});

// 响应权限请求
ws.sink.add(jsonEncode(PermissionResponseMessage(
  workspaceId: 'default',
  sessionId: 'my-session',
  toolUseId: 'xxx',
  decision: PermissionDecision.approved,
).toJson()));

// 切换到本地模式
ws.sink.add(jsonEncode(SwitchModeMessage(
  workspaceId: 'default',
  sessionId: 'my-session',
  mode: ControlMode.local,
).toJson()));

*/
