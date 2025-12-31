import 'package:flutter/material.dart';

import '../services/remote_command_service.dart';

/// Widget 扩展 - 最低侵入性方式
extension CommandTargetExtension on Widget {
  /// 为 Widget 添加命令目标（可点击）
  Widget withCommand(String targetId, {String? label, VoidCallback? onTap}) {
    return _CommandWrapper(
      targetId: targetId,
      label: label,
      onTap: onTap,
      child: this,
    );
  }
}

/// 命令包装器 - 用于扩展方法
class _CommandWrapper extends StatefulWidget {
  final String targetId;
  final String? label;
  final VoidCallback? onTap;
  final Widget child;

  const _CommandWrapper({
    required this.targetId,
    this.label,
    this.onTap,
    required this.child,
  });

  @override
  State<_CommandWrapper> createState() => _CommandWrapperState();
}

class _CommandWrapperState extends State<_CommandWrapper> {
  @override
  void initState() {
    super.initState();
    _register();
  }

  @override
  void didUpdateWidget(_CommandWrapper oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.targetId != widget.targetId) {
      RemoteCommandService.instance.unregister(oldWidget.targetId);
      _register();
    }
  }

  void _register() {
    RemoteCommandService.instance.register(CommandTarget(
      id: widget.targetId,
      type: TargetType.button,
      label: widget.label,
      onTap: widget.onTap,
    ));
  }

  @override
  void dispose() {
    RemoteCommandService.instance.unregister(widget.targetId);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// 输入框命令目标 - 需要特殊处理
class CommandInput extends StatefulWidget {
  final String targetId;
  final String? label;
  final TextEditingController controller;
  final Widget child;

  const CommandInput({
    super.key,
    required this.targetId,
    this.label,
    required this.controller,
    required this.child,
  });

  @override
  State<CommandInput> createState() => _CommandInputState();
}

class _CommandInputState extends State<CommandInput> {
  @override
  void initState() {
    super.initState();
    _register();
  }

  @override
  void didUpdateWidget(CommandInput oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.targetId != widget.targetId) {
      RemoteCommandService.instance.unregister(oldWidget.targetId);
      _register();
    }
  }

  void _register() {
    RemoteCommandService.instance.register(CommandTarget(
      id: widget.targetId,
      type: TargetType.input,
      label: widget.label,
      onInput: (text) {
        widget.controller.text = text;
      },
      getText: () => widget.controller.text,
    ));
  }

  @override
  void dispose() {
    RemoteCommandService.instance.unregister(widget.targetId);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// 屏幕范围 - 自动管理页面栈
class ScreenScope extends StatefulWidget {
  final String screenId;
  final Widget child;

  const ScreenScope({
    super.key,
    required this.screenId,
    required this.child,
  });

  @override
  State<ScreenScope> createState() => _ScreenScopeState();
}

class _ScreenScopeState extends State<ScreenScope> {
  @override
  void initState() {
    super.initState();
    RemoteCommandService.instance.pushScreen(widget.screenId);
  }

  @override
  void dispose() {
    RemoteCommandService.instance.popScreen();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// 列表项命令目标 - 带状态
class CommandListItem extends StatefulWidget {
  final String targetId;
  final String? label;
  final VoidCallback? onTap;
  final Map<String, dynamic> Function()? getState;
  final Widget child;

  const CommandListItem({
    super.key,
    required this.targetId,
    this.label,
    this.onTap,
    this.getState,
    required this.child,
  });

  @override
  State<CommandListItem> createState() => _CommandListItemState();
}

class _CommandListItemState extends State<CommandListItem> {
  @override
  void initState() {
    super.initState();
    _register();
  }

  @override
  void didUpdateWidget(CommandListItem oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.targetId != widget.targetId) {
      RemoteCommandService.instance.unregister(oldWidget.targetId);
      _register();
    }
  }

  void _register() {
    RemoteCommandService.instance.register(CommandTarget(
      id: widget.targetId,
      type: TargetType.listItem,
      label: widget.label,
      onTap: widget.onTap,
      getState: widget.getState,
    ));
  }

  @override
  void dispose() {
    RemoteCommandService.instance.unregister(widget.targetId);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
