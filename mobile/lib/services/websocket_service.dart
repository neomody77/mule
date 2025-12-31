import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../config/app_config.dart';

/// WebSocket 连接状态
enum WsConnectionState {
  disconnected,
  connecting,
  connected,
  error,
}

/// WebSocket 事件
class WsEvent {
  final String event;
  final Map<String, dynamic> data;

  WsEvent({required this.event, required this.data});

  factory WsEvent.fromJson(Map<String, dynamic> json) {
    return WsEvent(
      event: json['event'] as String,
      data: json['data'] as Map<String, dynamic>? ?? {},
    );
  }
}

/// WebSocket 服务
class WebSocketService {
  WebSocketChannel? _channel;
  String? _currentWorkspaceId;

  final _stateController = StreamController<WsConnectionState>.broadcast();
  final _eventController = StreamController<WsEvent>.broadcast();

  Timer? _heartbeatTimer;
  Timer? _reconnectTimer;
  int _reconnectAttempts = 0;
  static const int _maxReconnectAttempts = 5;

  WsConnectionState _state = WsConnectionState.disconnected;

  /// 当前连接状态
  WsConnectionState get state => _state;

  /// 连接状态流
  Stream<WsConnectionState> get stateStream => _stateController.stream;

  /// 事件流
  Stream<WsEvent> get eventStream => _eventController.stream;

  /// 是否已连接
  bool get isConnected => _state == WsConnectionState.connected;

  /// 当前工作区 ID
  String? get currentWorkspaceId => _currentWorkspaceId;

  /// 连接到工作区
  Future<void> connect(String workspaceId) async {
    if (_state == WsConnectionState.connecting) return;

    // 如果已连接到其他工作区，先断开
    if (_currentWorkspaceId != null && _currentWorkspaceId != workspaceId) {
      await disconnect();
    }

    _currentWorkspaceId = workspaceId;
    _setState(WsConnectionState.connecting);

    try {
      final url = AppConfig.getWsUrl(workspaceId);
      _channel = WebSocketChannel.connect(Uri.parse(url));

      // 等待连接建立
      await _channel!.ready;

      _setState(WsConnectionState.connected);
      _reconnectAttempts = 0;

      // 监听消息
      _channel!.stream.listen(
        _onMessage,
        onError: _onError,
        onDone: _onDone,
      );

      // 启动心跳
      _startHeartbeat();
    } catch (e) {
      _setState(WsConnectionState.error);
      _scheduleReconnect();
    }
  }

  /// 断开连接
  Future<void> disconnect() async {
    _stopHeartbeat();
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _reconnectAttempts = 0;

    await _channel?.sink.close();
    _channel = null;
    _currentWorkspaceId = null;

    _setState(WsConnectionState.disconnected);
  }

  /// 发送提示消息
  void sendPrompt(String content) {
    _send({'type': 'prompt', 'content': content});
  }

  /// 发送取消请求
  void sendCancel() {
    _send({'type': 'cancel'});
  }

  /// 发送 ping
  void sendPing() {
    _send({'type': 'ping'});
  }

  void _send(Map<String, dynamic> data) {
    if (_channel != null && _state == WsConnectionState.connected) {
      _channel!.sink.add(jsonEncode(data));
    }
  }

  void _onMessage(dynamic message) {
    debugPrint('[WebSocketService] Received message: $message');
    try {
      final json = jsonDecode(message as String) as Map<String, dynamic>;
      final event = WsEvent.fromJson(json);
      debugPrint('[WebSocketService] Parsed event: ${event.event}');

      // 处理 pong
      if (event.event == 'pong' || event.event == 'ping') {
        return;
      }

      _eventController.add(event);
    } catch (e) {
      debugPrint('[WebSocketService] Parse error: $e');
      _eventController.add(WsEvent(
        event: 'error',
        data: {'message': 'Failed to parse message: $e'},
      ));
    }
  }

  void _onError(dynamic error) {
    _setState(WsConnectionState.error);
    _eventController.add(WsEvent(
      event: 'error',
      data: {'message': error.toString()},
    ));
    _scheduleReconnect();
  }

  void _onDone() {
    _setState(WsConnectionState.disconnected);
    _stopHeartbeat();
    _scheduleReconnect();
  }

  void _setState(WsConnectionState newState) {
    if (_state != newState) {
      _state = newState;
      _stateController.add(newState);
    }
  }

  void _startHeartbeat() {
    _stopHeartbeat();
    _heartbeatTimer = Timer.periodic(
      const Duration(seconds: 25),
      (_) => sendPing(),
    );
  }

  void _stopHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
  }

  void _scheduleReconnect() {
    if (_currentWorkspaceId == null) return;
    if (_reconnectAttempts >= _maxReconnectAttempts) return;

    _reconnectTimer?.cancel();
    _reconnectAttempts++;

    final delay = Duration(seconds: _reconnectAttempts * 2);
    _reconnectTimer = Timer(delay, () {
      if (_currentWorkspaceId != null) {
        connect(_currentWorkspaceId!);
      }
    });
  }

  /// 释放资源
  void dispose() {
    disconnect();
    _stateController.close();
    _eventController.close();
  }
}
