import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// 命令目标类型
enum TargetType {
  button,
  input,
  listItem,
  toggle,
  screen,
}

/// 命令目标
class CommandTarget {
  final String id;
  final TargetType type;
  final String? label;
  final VoidCallback? onTap;
  final void Function(String)? onInput;
  final String Function()? getText;
  final Map<String, dynamic> Function()? getState;

  CommandTarget({
    required this.id,
    required this.type,
    this.label,
    this.onTap,
    this.onInput,
    this.getText,
    this.getState,
  });

  Map<String, dynamic> toJson() => {
    'id': id,
    'type': type.name,
    if (label != null) 'label': label,
    if (getState != null) 'state': getState!(),
    if (getText != null) 'text': getText!(),
  };
}

/// 远程命令
class RemoteCommand {
  final String action;
  final String target;
  final Map<String, dynamic> params;

  RemoteCommand({
    required this.action,
    required this.target,
    this.params = const {},
  });

  factory RemoteCommand.fromJson(dynamic json) {
    final map = json is String ? jsonDecode(json) as Map<String, dynamic> : json as Map<String, dynamic>;
    return RemoteCommand(
      action: map['action'] as String,
      target: map['target'] as String,
      params: map['params'] as Map<String, dynamic>? ?? {},
    );
  }
}

/// 命令执行结果
class CommandResult {
  final bool success;
  final Map<String, dynamic>? data;
  final String? error;

  CommandResult.success([this.data]) : success = true, error = null;
  CommandResult.failure(this.error) : success = false, data = null;

  Map<String, dynamic> toJson() => {
    'success': success,
    if (data != null) 'data': data,
    if (error != null) 'error': error,
  };
}

/// 远程命令服务 - 单例
class RemoteCommandService {
  static final RemoteCommandService instance = RemoteCommandService._();
  RemoteCommandService._();

  static const _channel = MethodChannel('com.mule/command');

  // 注册的目标
  final Map<String, CommandTarget> _targets = {};

  // 页面栈
  final List<String> _screenStack = ['home'];

  /// 当前页面
  String get currentScreen => _screenStack.last;

  /// 所有注册的目标 ID
  List<String> get targetIds => _targets.keys.toList();

  /// 初始化（设置 MethodChannel 监听）
  void init() {
    _channel.setMethodCallHandler(_handleMethodCall);
    debugPrint('[RemoteCommand] Service initialized');
  }

  Future<dynamic> _handleMethodCall(MethodCall call) async {
    debugPrint('[RemoteCommand] Method: ${call.method}, args: ${call.arguments}');

    switch (call.method) {
      case 'execute':
        try {
          final command = RemoteCommand.fromJson(call.arguments);
          final result = await execute(command);
          return jsonEncode(result.toJson());
        } catch (e) {
          return jsonEncode(CommandResult.failure(e.toString()).toJson());
        }
      default:
        return jsonEncode(CommandResult.failure('Unknown method: ${call.method}').toJson());
    }
  }

  /// 注册目标
  void register(CommandTarget target) {
    _targets[target.id] = target;
    debugPrint('[RemoteCommand] Registered: ${target.id}');
  }

  /// 注销目标
  void unregister(String id) {
    _targets.remove(id);
    debugPrint('[RemoteCommand] Unregistered: $id');
  }

  /// 页面入栈
  void pushScreen(String screen) {
    _screenStack.add(screen);
    debugPrint('[RemoteCommand] Push screen: $screen, stack: $_screenStack');
  }

  /// 页面出栈
  void popScreen() {
    if (_screenStack.length > 1) {
      final popped = _screenStack.removeLast();
      debugPrint('[RemoteCommand] Pop screen: $popped, stack: $_screenStack');
    }
  }

  /// 执行命令
  Future<CommandResult> execute(RemoteCommand command) async {
    debugPrint('[RemoteCommand] Execute: ${command.action} on ${command.target}');

    switch (command.action) {
      case 'tap':
        return _executeTap(command.target);
      case 'input':
        final text = command.params['text'] as String?;
        if (text == null) {
          return CommandResult.failure('Missing "text" param for input action');
        }
        return _executeInput(command.target, text);
      case 'query':
        return _executeQuery(command.target);
      case 'get_text':
        return _executeGetText(command.target);
      default:
        return CommandResult.failure('Unknown action: ${command.action}');
    }
  }

  CommandResult _executeTap(String targetId) {
    final target = _targets[targetId];
    if (target == null) {
      return CommandResult.failure('Target not found: $targetId');
    }
    if (target.onTap == null) {
      return CommandResult.failure('Target is not tappable: $targetId');
    }

    target.onTap!();
    return CommandResult.success({'tapped': targetId});
  }

  CommandResult _executeInput(String targetId, String text) {
    final target = _targets[targetId];
    if (target == null) {
      return CommandResult.failure('Target not found: $targetId');
    }
    if (target.onInput == null) {
      return CommandResult.failure('Target does not accept input: $targetId');
    }

    target.onInput!(text);
    return CommandResult.success({'input': targetId, 'text': text});
  }

  CommandResult _executeGetText(String targetId) {
    final target = _targets[targetId];
    if (target == null) {
      return CommandResult.failure('Target not found: $targetId');
    }
    if (target.getText == null) {
      return CommandResult.failure('Target does not have text: $targetId');
    }

    return CommandResult.success({'text': target.getText!()});
  }

  CommandResult _executeQuery(String targetId) {
    if (targetId == 'current' || targetId == 'screen') {
      // 查询当前屏幕的所有目标
      final screenTargets = _targets.entries
          .where((e) => e.key.startsWith(currentScreen))
          .map((e) => e.value.toJson())
          .toList();

      return CommandResult.success({
        'screen': currentScreen,
        'targets': screenTargets,
      });
    }

    if (targetId == 'all') {
      // 查询所有目标
      return CommandResult.success({
        'screen': currentScreen,
        'screenStack': _screenStack,
        'targets': _targets.values.map((t) => t.toJson()).toList(),
      });
    }

    // 查询特定目标
    final target = _targets[targetId];
    if (target == null) {
      return CommandResult.failure('Target not found: $targetId');
    }

    return CommandResult.success(target.toJson());
  }

  /// 释放资源
  void dispose() {
    _channel.setMethodCallHandler(null);
    _targets.clear();
  }
}
