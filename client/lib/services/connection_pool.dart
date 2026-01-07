import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../models/server_config.dart';

/// WebSocket 连接状态
enum WsConnectionState {
  disconnected,
  connecting,
  connected,
  error,
}

/// WebSocket 事件
class WsEvent {
  final String sessionId;
  final String workspaceId;
  final String event;
  final Map<String, dynamic> data;

  WsEvent({
    required this.sessionId,
    required this.workspaceId,
    required this.event,
    required this.data,
  });

  factory WsEvent.fromJson(Map<String, dynamic> json) {
    return WsEvent(
      sessionId: json['session_id'] as String? ?? '',
      workspaceId: json['workspace_id'] as String? ?? '',
      event: json['event'] as String,
      data: json['data'] as Map<String, dynamic>? ?? {},
    );
  }
}

/// Session 订阅信息
class SessionSubscription {
  final String sessionId;
  final String workspaceId;
  final String serverId;

  SessionSubscription({
    required this.sessionId,
    required this.workspaceId,
    required this.serverId,
  });

  String get key => '$workspaceId:$sessionId';
}

/// 服务器连接（共享）
class ServerConnection {
  final String serverId;
  final ServerConfig config;

  WebSocketChannel? channel;
  WsConnectionState state = WsConnectionState.disconnected;
  Timer? heartbeatTimer;
  Timer? reconnectTimer;
  int reconnectAttempts = 0;

  // 该服务器上订阅的 sessions
  final Set<String> subscribedSessions = {};

  ServerConnection({
    required this.serverId,
    required this.config,
  });

  String get wsUrl => '${config.wsBaseUrl}/ws?token=${config.token}';
}

/// 连接池 - 每服务器一个连接，多 session 复用
class ConnectionPool {
  static const int _maxReconnectAttempts = 5;

  // serverId -> ServerConnection
  final Map<String, ServerConnection> _connections = {};

  // sessionKey (workspaceId:sessionId) -> SessionSubscription
  final Map<String, SessionSubscription> _subscriptions = {};

  // 全局事件流
  final _eventController = StreamController<WsEvent>.broadcast();

  // 连接状态变化流 (服务器级别)
  final _serverStateController =
      StreamController<({String serverId, WsConnectionState state})>.broadcast();

  // Session 状态变化流
  final _sessionStateController =
      StreamController<({String sessionId, WsConnectionState state})>.broadcast();

  /// 事件流（所有 session 的事件）
  Stream<WsEvent> get eventStream => _eventController.stream;

  /// 服务器连接状态流
  Stream<({String serverId, WsConnectionState state})> get serverStateStream =>
      _serverStateController.stream;

  /// Session 状态流
  Stream<({String sessionId, WsConnectionState state})> get sessionStateStream =>
      _sessionStateController.stream;

  /// 获取特定 session 的事件流
  Stream<WsEvent> sessionEventStream(String sessionId) {
    return eventStream.where((e) => e.sessionId == sessionId);
  }

  /// 获取服务器连接状态
  WsConnectionState getServerState(String serverId) {
    return _connections[serverId]?.state ?? WsConnectionState.disconnected;
  }

  /// 获取 session 连接状态（基于其服务器的连接状态）
  WsConnectionState getSessionState(String sessionId) {
    final sub = _subscriptions.values.where((s) => s.sessionId == sessionId).firstOrNull;
    if (sub == null) return WsConnectionState.disconnected;
    return getServerState(sub.serverId);
  }

  /// 检查 session 是否已订阅
  bool isSubscribed(String sessionId) {
    return _subscriptions.values.any((s) => s.sessionId == sessionId);
  }

  /// 获取所有活跃 session IDs
  List<String> get activeSessionIds {
    return _subscriptions.entries
        .where((e) {
          final serverId = e.value.serverId;
          return _connections[serverId]?.state == WsConnectionState.connected;
        })
        .map((e) => e.value.sessionId)
        .toList();
  }

  /// 连接到指定服务器（不订阅任何 session，仅建立 WebSocket 连接）
  Future<void> connectServer(ServerConfig serverConfig) async {
    await _ensureServerConnected(serverConfig);
    debugPrint('[ConnectionPool] Server connected: ${serverConfig.id}');
  }

  /// 检查服务器是否已连接
  bool isServerConnected(String serverId) {
    return _connections[serverId]?.state == WsConnectionState.connected;
  }

  /// 订阅 session（自动连接服务器）
  /// 每次进入 session 都发送订阅消息，服务器会返回订阅成功
  Future<void> subscribe({
    required String sessionId,
    required String workspaceId,
    required ServerConfig serverConfig,
  }) async {
    final sessionKey = '$workspaceId:$sessionId';

    // 创建或更新订阅记录
    final subscription = SessionSubscription(
      sessionId: sessionId,
      workspaceId: workspaceId,
      serverId: serverConfig.id,
    );
    _subscriptions[sessionKey] = subscription;

    // 通知 connecting 状态
    _sessionStateController.add((sessionId: sessionId, state: WsConnectionState.connecting));

    // 确保服务器已连接
    await _ensureServerConnected(serverConfig);

    // 每次进入都发送订阅消息（服务器会返回 subscribed 事件）
    _sendSubscribe(serverConfig.id, workspaceId, sessionId);

    debugPrint('[ConnectionPool] Subscribing: $sessionKey');
  }

  /// 取消订阅 session
  Future<void> unsubscribe(String sessionId) async {
    final entry = _subscriptions.entries
        .where((e) => e.value.sessionId == sessionId)
        .firstOrNull;

    if (entry == null) return;

    final subscription = entry.value;
    final sessionKey = entry.key;

    // 发送取消订阅消息
    _sendUnsubscribe(subscription.serverId, subscription.workspaceId, sessionId);

    // 移除订阅记录
    _subscriptions.remove(sessionKey);

    // 更新服务器连接的订阅列表
    final conn = _connections[subscription.serverId];
    if (conn != null) {
      conn.subscribedSessions.remove(sessionKey);

      // 如果服务器没有其他订阅，可以考虑断开（但保持连接以便接收后台任务通知）
      // 这里我们保持连接
    }

    debugPrint('[ConnectionPool] Unsubscribed: $sessionKey');
  }

  /// 确保服务器已连接
  Future<void> _ensureServerConnected(ServerConfig config) async {
    if (_connections.containsKey(config.id)) {
      final conn = _connections[config.id]!;
      if (conn.state == WsConnectionState.connected) {
        return;
      }
      if (conn.state == WsConnectionState.connecting) {
        // 等待连接完成
        await _waitForConnection(config.id);
        return;
      }
    }

    // 创建新连接
    final connection = ServerConnection(
      serverId: config.id,
      config: config,
    );
    _connections[config.id] = connection;

    await _doConnect(connection);
  }

  Future<void> _waitForConnection(String serverId, {Duration timeout = const Duration(seconds: 10)}) async {
    final completer = Completer<void>();
    late StreamSubscription sub;

    sub = _serverStateController.stream.listen((event) {
      if (event.serverId == serverId) {
        if (event.state == WsConnectionState.connected) {
          completer.complete();
          sub.cancel();
        } else if (event.state == WsConnectionState.error ||
            event.state == WsConnectionState.disconnected) {
          completer.completeError('Connection failed');
          sub.cancel();
        }
      }
    });

    try {
      await completer.future.timeout(timeout);
    } catch (e) {
      sub.cancel();
      rethrow;
    }
  }

  Future<void> _doConnect(ServerConnection connection) async {
    _setServerState(connection, WsConnectionState.connecting);

    try {
      final url = connection.wsUrl;
      debugPrint('[ConnectionPool] Connecting to server: ${connection.serverId} at $url');

      connection.channel = WebSocketChannel.connect(Uri.parse(url));

      await connection.channel!.ready.timeout(
        const Duration(seconds: 10),
        onTimeout: () {
          throw TimeoutException('Connection timeout');
        },
      );

      _setServerState(connection, WsConnectionState.connected);
      connection.reconnectAttempts = 0;

      // 监听消息
      connection.channel!.stream.listen(
        (message) => _onMessage(connection, message),
        onError: (error) => _onError(connection, error),
        onDone: () => _onDone(connection),
      );

      // 启动心跳
      _startHeartbeat(connection);

      // 重新订阅所有该服务器的 session
      _resubscribeAll(connection);

    } catch (e) {
      debugPrint('[ConnectionPool] Connect error: $e');
      _setServerState(connection, WsConnectionState.error);
      _scheduleReconnect(connection);
    }
  }

  void _resubscribeAll(ServerConnection connection) {
    for (final entry in _subscriptions.entries) {
      if (entry.value.serverId == connection.serverId) {
        _sendSubscribe(
          connection.serverId,
          entry.value.workspaceId,
          entry.value.sessionId,
        );
      }
    }
  }

  /// 断开服务器连接
  Future<void> disconnectServer(String serverId) async {
    final connection = _connections[serverId];
    if (connection == null) return;

    _stopHeartbeat(connection);
    connection.reconnectTimer?.cancel();
    connection.reconnectTimer = null;
    connection.reconnectAttempts = 0;

    await connection.channel?.sink.close();
    connection.channel = null;

    _setServerState(connection, WsConnectionState.disconnected);
    _connections.remove(serverId);

    // 移除该服务器的所有订阅
    _subscriptions.removeWhere((_, sub) => sub.serverId == serverId);
  }

  /// 断开所有连接
  Future<void> disconnectAll() async {
    final serverIds = List<String>.from(_connections.keys);
    for (final serverId in serverIds) {
      await disconnectServer(serverId);
    }
  }

  // ============== 发送消息 ==============

  void _sendSubscribe(String serverId, String workspaceId, String sessionId) {
    _sendToServer(serverId, {
      'type': 'subscribe',
      'workspace_id': workspaceId,
      'session_id': sessionId,
    });
  }

  void _sendUnsubscribe(String serverId, String workspaceId, String sessionId) {
    _sendToServer(serverId, {
      'type': 'unsubscribe',
      'workspace_id': workspaceId,
      'session_id': sessionId,
    });
  }

  /// 发送提示消息
  void sendPrompt(String sessionId, String content) {
    final sub = _findSubscription(sessionId);
    if (sub == null) return;

    _sendToServer(sub.serverId, {
      'type': 'prompt',
      'workspace_id': sub.workspaceId,
      'session_id': sub.sessionId,
      'content': content,
    });
  }

  /// 发送带图片的提示消息
  void sendPromptWithImage(
    String sessionId,
    String content,
    String imageBase64,
    String mediaType,
  ) {
    final sub = _findSubscription(sessionId);
    if (sub == null) return;

    _sendToServer(sub.serverId, {
      'type': 'prompt',
      'workspace_id': sub.workspaceId,
      'session_id': sub.sessionId,
      'content': content,
      'image': {
        'data': imageBase64,
        'media_type': mediaType,
      },
    });
  }

  /// 发送取消请求
  void sendCancel(String sessionId) {
    final sub = _findSubscription(sessionId);
    if (sub == null) return;

    _sendToServer(sub.serverId, {
      'type': 'cancel',
      'workspace_id': sub.workspaceId,
      'session_id': sub.sessionId,
    });
  }

  /// 发送同步请求
  void sendSync(String sessionId) {
    final sub = _findSubscription(sessionId);
    if (sub == null) return;

    _sendToServer(sub.serverId, {
      'type': 'sync',
      'workspace_id': sub.workspaceId,
      'session_id': sub.sessionId,
    });
  }

  /// 发送压缩上下文请求
  void sendCompact(String sessionId) {
    final sub = _findSubscription(sessionId);
    if (sub == null) return;

    _sendToServer(sub.serverId, {
      'type': 'compact',
      'workspace_id': sub.workspaceId,
      'session_id': sub.sessionId,
    });
  }

  /// 发送生成标题请求
  void sendGenerateTitle(String sessionId) {
    final sub = _findSubscription(sessionId);
    if (sub == null) return;

    _sendToServer(sub.serverId, {
      'type': 'generate_title',
      'workspace_id': sub.workspaceId,
      'session_id': sub.sessionId,
    });
  }

  /// 发送 ping (通过 serverId)
  void sendPing(String serverId) {
    _sendToServer(serverId, {'type': 'ping'});
  }

  /// 发送 ping (通过 sessionId)
  void sendPingForSession(String sessionId) {
    final sub = _findSubscription(sessionId);
    if (sub == null) return;
    _sendToServer(sub.serverId, {'type': 'ping'});
  }

  SessionSubscription? _findSubscription(String sessionId) {
    return _subscriptions.values.where((s) => s.sessionId == sessionId).firstOrNull;
  }

  void _sendToServer(String serverId, Map<String, dynamic> data) {
    final connection = _connections[serverId];
    if (connection != null &&
        connection.channel != null &&
        connection.state == WsConnectionState.connected) {
      connection.channel!.sink.add(jsonEncode(data));
    }
  }

  // ============== 消息处理 ==============

  void _onMessage(ServerConnection connection, dynamic message) {
    try {
      final json = jsonDecode(message as String) as Map<String, dynamic>;
      final eventType = json['event'] as String?;

      // 处理 pong/ping（心跳响应，不转发）
      if (eventType == 'pong' || eventType == 'ping') {
        return;
      }

      // 处理订阅确认 - 收到后将 session 状态变为 connected
      if (eventType == 'subscribed') {
        final data = json['data'] as Map<String, dynamic>?;
        final sessionId = data?['session_id'] as String?;
        debugPrint('[ConnectionPool] subscribed: $data');
        if (sessionId != null) {
          _sessionStateController.add((sessionId: sessionId, state: WsConnectionState.connected));
        }
        return;
      }

      // 处理取消订阅确认
      if (eventType == 'unsubscribed') {
        debugPrint('[ConnectionPool] unsubscribed: ${json['data']}');
        return;
      }

      final event = WsEvent.fromJson(json);
      debugPrint('[ConnectionPool] [${event.sessionId}] Event: ${event.event}');

      _eventController.add(event);
    } catch (e) {
      debugPrint('[ConnectionPool] Parse error: $e');
    }
  }

  void _onError(ServerConnection connection, dynamic error) {
    debugPrint('[ConnectionPool] [${connection.serverId}] Error: $error');
    _setServerState(connection, WsConnectionState.error);
    _scheduleReconnect(connection);
  }

  void _onDone(ServerConnection connection) {
    debugPrint('[ConnectionPool] [${connection.serverId}] Connection closed');
    _setServerState(connection, WsConnectionState.disconnected);
    _stopHeartbeat(connection);
    _scheduleReconnect(connection);
  }

  void _setServerState(ServerConnection connection, WsConnectionState newState) {
    if (connection.state != newState) {
      connection.state = newState;
      _serverStateController.add((serverId: connection.serverId, state: newState));

      // 通知所有该服务器上的 session
      for (final entry in _subscriptions.entries) {
        if (entry.value.serverId == connection.serverId) {
          _sessionStateController.add((sessionId: entry.value.sessionId, state: newState));
        }
      }
    }
  }

  void _startHeartbeat(ServerConnection connection) {
    _stopHeartbeat(connection);
    connection.heartbeatTimer = Timer.periodic(
      const Duration(seconds: 25),
      (_) => sendPing(connection.serverId),
    );
  }

  void _stopHeartbeat(ServerConnection connection) {
    connection.heartbeatTimer?.cancel();
    connection.heartbeatTimer = null;
  }

  void _scheduleReconnect(ServerConnection connection) {
    if (connection.reconnectAttempts >= _maxReconnectAttempts) {
      debugPrint('[ConnectionPool] [${connection.serverId}] Max reconnect attempts reached');
      return;
    }

    // 只有当还有订阅时才重连
    final hasSubscriptions = _subscriptions.values.any((s) => s.serverId == connection.serverId);
    if (!hasSubscriptions) {
      debugPrint('[ConnectionPool] [${connection.serverId}] No subscriptions, skip reconnect');
      return;
    }

    connection.reconnectTimer?.cancel();
    connection.reconnectAttempts++;

    final delay = Duration(seconds: connection.reconnectAttempts * 2);
    debugPrint(
        '[ConnectionPool] [${connection.serverId}] Reconnecting in ${delay.inSeconds}s (attempt ${connection.reconnectAttempts})');

    connection.reconnectTimer = Timer(delay, () {
      if (_connections.containsKey(connection.serverId)) {
        _doConnect(connection);
      }
    });
  }

  /// 释放资源
  void dispose() {
    disconnectAll();
    _eventController.close();
    _serverStateController.close();
    _sessionStateController.close();
  }
}
