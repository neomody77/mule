import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../config/theme.dart';
import '../models/chat_session.dart' show ChatSession, SessionConnectionState, PendingPrompt, TodoItem, TodoStatus;
import '../models/server_config.dart';
import '../providers/providers.dart';
import '../router.dart';
import '../widgets/command_target.dart';
import '../widgets/message_bubble.dart';
import '../widgets/file_drawer.dart';

/// Session 聊天界面
class SessionScreen extends ConsumerStatefulWidget {
  final ChatSession session;
  final ServerConfig server;

  const SessionScreen({
    super.key,
    required this.session,
    required this.server,
  });

  @override
  ConsumerState<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends ConsumerState<SessionScreen> with WidgetsBindingObserver {
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final FocusNode _focusNode = FocusNode();
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();

  static const _adbChannel = MethodChannel('com.claudecode.claude_code_remote/adb');

  late String _sessionId;
  int _lastMessageCount = 0;
  int _lastContentLength = 0;
  bool _userScrolledUp = false;
  double _lastKeyboardHeight = 0;
  bool _isInputEmpty = true; // 追踪输入框是否为空
  String _lastDraft = ''; // 追踪 draft 变化（用于取消后恢复）

  // 判断是否在底部附近（允许半屏的误差）
  bool get _isAtBottom {
    if (!_scrollController.hasClients) return true;
    final maxScroll = _scrollController.position.maxScrollExtent;
    final currentScroll = _scrollController.position.pixels;
    final viewportHeight = _scrollController.position.viewportDimension;
    // 如果距离底部不超过半屏，认为是在底部
    return maxScroll - currentScroll < viewportHeight / 2;
  }

  @override
  void initState() {
    super.initState();
    _sessionId = widget.session.id;

    // 注册键盘监听
    WidgetsBinding.instance.addObserver(this);

    // 监听滚动位置
    _scrollController.addListener(_onScroll);

    // 监听输入框焦点变化，获得焦点时滚动到底部
    _focusNode.addListener(_onFocusChange);

    // 监听输入框内容变化，保存草稿
    _inputController.addListener(_onInputChanged);

    // 设置 ADB 方法通道处理器
    _adbChannel.setMethodCallHandler(_handleAdbMethod);

    // 连接 WebSocket 并滚动到底部
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _connect();
      // 恢复草稿内容
      _restoreDraft();
      // 进入时强制滚动到底部（延迟一下等消息加载）
      Future.delayed(const Duration(milliseconds: 300), () {
        if (mounted) _forceScrollToBottom();
      });
    });
  }

  void _restoreDraft() {
    final session = ref.read(sessionProvider).getSession(_sessionId);
    if (session != null && session.draft.isNotEmpty) {
      _inputController.text = session.draft;
      // 同步更新输入框空状态
      setState(() {
        _isInputEmpty = session.draft.trim().isEmpty;
      });
    }
  }

  void _onInputChanged() {
    // 保存草稿（避免发送后也触发保存，通过检查内容来判断）
    final content = _inputController.text;
    ref.read(sessionProvider.notifier).saveDraft(_sessionId, content);

    // 更新输入框是否为空的状态
    final isEmpty = content.trim().isEmpty;
    if (isEmpty != _isInputEmpty) {
      setState(() {
        _isInputEmpty = isEmpty;
      });
    }
  }

  void _onScroll() {
    // 用户向上滚动时标记
    if (!_isAtBottom) {
      _userScrolledUp = true;
    } else {
      _userScrolledUp = false;
    }
  }

  void _onFocusChange() {
    // 当输入框获得焦点时，滚动到底部
    if (_focusNode.hasFocus) {
      _userScrolledUp = false;
      // 延迟一下等键盘弹出
      Future.delayed(const Duration(milliseconds: 100), () {
        if (mounted) _forceScrollToBottom();
      });
    }
  }

  void _connect() {
    ref.read(sessionProvider.notifier).connectSession(_sessionId, widget.server);
  }

  Future<dynamic> _handleAdbMethod(MethodCall call) async {
    debugPrint('[SessionScreen] ADB method: ${call.method}, args: ${call.arguments}');
    switch (call.method) {
      case 'sendMessage':
        final message = call.arguments as String;
        _inputController.text = message;
        _sendMessage();
        return true;
      case 'tapSend':
        _sendMessage();
        return true;
      case 'setText':
        final text = call.arguments as String;
        _inputController.text = text;
        return true;
      default:
        return false;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _adbChannel.setMethodCallHandler(null);
    _scrollController.removeListener(_onScroll);
    _focusNode.removeListener(_onFocusChange);
    _inputController.removeListener(_onInputChanged);
    _inputController.dispose();
    _scrollController.dispose();
    _focusNode.dispose();
    // 注意：不断开连接，保持订阅以便接收后台任务通知
    super.dispose();
  }

  void _goBack() {
    // 清除活跃 session（后续消息将标记为未读）
    ref.read(sessionProvider.notifier).setActiveSession(null);
    context.go(AppRoutes.home);
  }

  @override
  void didChangeMetrics() {
    super.didChangeMetrics();
    // 键盘弹出/关闭时滚动到底部
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final bottomInset = MediaQuery.of(context).viewInsets.bottom;
      if (bottomInset != _lastKeyboardHeight) {
        _lastKeyboardHeight = bottomInset;
        // 键盘状态变化时，如果用户在底部附近，滚动到最新位置
        if (!_userScrolledUp) {
          _scrollToBottomIfNeeded();
        }
      }
    });
  }

  /// 智能滚动：只有当用户在底部时才自动滚动
  void _scrollToBottomIfNeeded() {
    if (!_userScrolledUp && _scrollController.hasClients) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scrollController.hasClients) {
          _scrollController.animateTo(
            _scrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 150),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  /// 强制滚动到底部（进入页面时使用）
  void _forceScrollToBottom() {
    if (_scrollController.hasClients) {
      _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
    }
  }

  void _sendMessage() {
    final content = _inputController.text.trim();
    if (content.isEmpty) return;

    ref.read(sessionProvider.notifier).sendMessage(_sessionId, content);
    _inputController.clear();
    // 清除草稿
    ref.read(sessionProvider.notifier).saveDraft(_sessionId, '');

    // 用户发送消息后，重置滚动状态并滚动到底部
    _userScrolledUp = false;
    _scrollToBottomIfNeeded();
  }

  @override
  Widget build(BuildContext context) {
    final sessionState = ref.watch(sessionProvider);
    final session = sessionState.getSession(_sessionId);

    // 检测消息变化或内容更新（streaming），触发自动滚动
    final currentMessageCount = session?.messages.length ?? 0;
    final lastMessage = session?.messages.lastOrNull;
    final currentContentLength = lastMessage?.content.length ?? 0;

    // 新消息或最后一条消息内容变化时滚动
    if (currentMessageCount > _lastMessageCount ||
        (currentMessageCount > 0 && currentContentLength > _lastContentLength)) {
      _scrollToBottomIfNeeded();
    }
    _lastMessageCount = currentMessageCount;
    _lastContentLength = currentContentLength;

    // 检测 draft 变化（取消任务后恢复 pending prompts 到输入框）
    final currentDraft = session?.draft ?? '';
    if (currentDraft != _lastDraft && currentDraft.isNotEmpty && _inputController.text.isEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _inputController.text.isEmpty) {
          _inputController.text = currentDraft;
          _inputController.selection = TextSelection.collapsed(offset: currentDraft.length);
        }
      });
    }
    _lastDraft = currentDraft;

    return ScreenScope(
      screenId: 'session',
      child: Scaffold(
        key: _scaffoldKey,
        endDrawer: FileDrawer(
          server: widget.server,
          workspaceId: widget.session.workspaceId,
        ),
        appBar: AppBar(
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () => _goBack(),
          ).withCommand('session.back', onTap: () => _goBack()),
          title: session == null
              ? const Text('Session')
              : Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Flexible(
                      child: GestureDetector(
                        onTap: () => _handleTitleTap(session.connectionState),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              session.name,
                              overflow: TextOverflow.ellipsis,
                            ),
                            _buildConnectionStatus(session.connectionState),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    GestureDetector(
                      onTap: _showRenameDialog,
                      child: Icon(Icons.edit, size: 16, color: ZiaOlive.shade300),
                    ),
                    const SizedBox(width: 8),
                    GestureDetector(
                      onTap: _generateTitle,
                      child: Icon(Icons.auto_awesome, size: 16, color: ZiaOlive.shade300),
                    ),
                  ],
                ),
          actions: [
            // Todo 按钮 - 有任务时显示
            if (session != null && session.todos.isNotEmpty)
              IconButton(
                icon: Badge(
                  label: Text('${session.todos.where((t) => t.status != TodoStatus.completed).length}'),
                  isLabelVisible: session.todos.any((t) => t.status != TodoStatus.completed),
                  child: const Icon(Icons.checklist),
                ),
                onPressed: _showTodoSheet,
                tooltip: 'Tasks',
              ),
            // Reset 按钮
            IconButton(
              icon: const Icon(Icons.restart_alt),
              onPressed: _confirmClearMessages,
              tooltip: 'Reset Session',
            ),
            // Compact 按钮
            IconButton(
              icon: const Icon(Icons.compress),
              onPressed: _compactContext,
              tooltip: 'Compact Context',
            ),
            // Files 按钮
            IconButton(
              icon: const Icon(Icons.folder_outlined),
              onPressed: _openFileDrawer,
              tooltip: 'Files',
            ),
          ],
        ),
        body: Column(
        children: [
          // 面包屑导航
          _buildBreadcrumb(),

          // 消息列表
          Expanded(
            child: session == null
                ? const Center(child: Text('Session not found'))
                : session.messages.isEmpty
                    ? _buildEmptyState()
                    : ListView.builder(
                        controller: _scrollController,
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        itemCount: session.messages.length,
                        itemBuilder: (context, index) {
                          final message = session.messages[index];
                          return MessageBubble(
                            key: ValueKey(message.id),
                            message: message,
                          );
                        },
                      ),
          ),

          // Pending prompts（固定在输入栏上方）
          if (session != null && session.pendingPrompts.isNotEmpty)
            _buildPendingPrompts(session.pendingPrompts),

          // 输入栏
          _buildInputBar(session),
        ],
      ),
      ),
    );
  }

  Widget _buildBreadcrumb() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        border: Border(
          bottom: BorderSide(
            color: Theme.of(context).dividerColor,
            width: 0.5,
          ),
        ),
      ),
      child: Row(
        children: [
          Icon(Icons.dns_outlined, size: 14, color: ZiaOlive.shade300),
          const SizedBox(width: 4),
          Text(
            widget.server.name,
            style: TextStyle(fontSize: 12, color: ZiaOlive.shade300),
          ),
          Icon(Icons.chevron_right, size: 14, color: ZiaOlive.shade200),
          Icon(Icons.folder_outlined, size: 14, color: ZiaOlive.shade300),
          const SizedBox(width: 4),
          Text(
            widget.session.workspaceName,
            style: TextStyle(fontSize: 12, color: ZiaOlive.shade300),
          ),
        ],
      ),
    );
  }

  Widget _buildConnectionStatus(SessionConnectionState state) {
    String text;
    Color color;

    switch (state) {
      case SessionConnectionState.connected:
        text = 'Connected';
        color = ZiaOlive.success;
      case SessionConnectionState.connecting:
        text = 'Connecting...';
        color = ZiaOlive.warning;
      case SessionConnectionState.disconnected:
        text = 'Disconnected';
        color = ZiaOlive.shade200;
      case SessionConnectionState.error:
        text = 'Connection Error';
        color = ZiaOlive.error;
    }

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 4),
        Text(
          text,
          style: TextStyle(
            fontSize: 12,
            color: ZiaOlive.shade200,
          ),
        ),
      ],
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.chat_bubble_outline,
            size: 64,
            color: ZiaOlive.shade200,
          ),
          const SizedBox(height: 16),
          Text(
            'Start a conversation',
            style: TextStyle(
              fontSize: 18,
              color: ZiaOlive.shade300,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Ask Claude to help you with coding tasks',
            style: TextStyle(
              color: ZiaOlive.shade200,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPendingPrompts(List<PendingPrompt> pendingPrompts) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: ZiaOlive.shade600.withValues(alpha: 0.1),
        border: Border(
          top: BorderSide(
            color: ZiaOlive.shade400.withValues(alpha: 0.3),
            width: 0.5,
          ),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.hourglass_empty,
                size: 14,
                color: ZiaOlive.shade400,
              ),
              const SizedBox(width: 4),
              Text(
                'Queued (${pendingPrompts.length})',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                  color: ZiaOlive.shade400,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          ...pendingPrompts.map((prompt) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: ZiaOlive.shade600.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    prompt.content.length > 50
                        ? '${prompt.content.substring(0, 50)}...'
                        : prompt.content,
                    style: TextStyle(
                      fontSize: 13,
                      color: ZiaOlive.shade300,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              )),
        ],
      ),
    );
  }

  Widget _buildInputBar(ChatSession? session) {
    final isConnected = session?.connectionState == SessionConnectionState.connected;
    final isProcessing = session?.isProcessing ?? false;

    return Container(
      padding: EdgeInsets.only(
        left: 16,
        right: 8,
        top: 8,
        bottom: MediaQuery.of(context).padding.bottom + 8,
      ),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        border: Border(
          top: BorderSide(
            color: Theme.of(context).dividerColor,
            width: 0.5,
          ),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: CommandInput(
              targetId: 'session.input',
              label: 'Message input',
              controller: _inputController,
              child: Focus(
                onKeyEvent: (node, event) {
                  // Web 端: Enter 发送, Shift+Enter 换行
                  // 检测 IME composing 状态，避免中文输入法回车触发发送
                  if (event is KeyDownEvent &&
                      event.logicalKey == LogicalKeyboardKey.enter &&
                      !HardwareKeyboard.instance.isShiftPressed &&
                      !_inputController.value.composing.isValid) {
                    if (isConnected && _inputController.text.trim().isNotEmpty) {
                      _sendMessage();
                    }
                    return KeyEventResult.handled;
                  }
                  return KeyEventResult.ignored;
                },
                child: TextField(
                  controller: _inputController,
                  focusNode: _focusNode,
                  // 始终允许用户选中输入框，方便提前输入
                  decoration: InputDecoration(
                    hintText: !isConnected
                        ? 'Waiting for connection...'
                        : isProcessing
                            ? 'Type to provide feedback...'
                            : 'Type a message...',
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(24),
                      borderSide: BorderSide.none,
                    ),
                    filled: true,
                    fillColor: Theme.of(context).colorScheme.surfaceContainerHighest,
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 12,
                    ),
                  ),
                  maxLines: 4,
                  minLines: 1,
                  // 使用 newline 让安卓键盘显示换行键（不是发送键）
                  textInputAction: TextInputAction.newline,
                  keyboardType: TextInputType.multiline,
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          // 停止按钮（处理中时显示）
          if (isProcessing)
            IconButton(
              icon: const Icon(Icons.stop_circle_outlined),
              onPressed: () => ref.read(sessionProvider.notifier).cancelTask(_sessionId),
              tooltip: 'Cancel',
              color: ZiaOlive.error,
            ).withCommand('session.cancel', onTap: () {
              ref.read(sessionProvider.notifier).cancelTask(_sessionId);
            }),
          // 发送按钮 / 功能菜单按钮
          _isInputEmpty
              ? IconButton(
                  icon: const Icon(Icons.add_circle_outline),
                  onPressed: _showFunctionMenu,
                  tooltip: 'Menu',
                  color: ZiaOlive.shade500,
                ).withCommand('session.menu', onTap: _showFunctionMenu)
              : IconButton(
                  icon: const Icon(Icons.send),
                  onPressed: isConnected ? _sendMessage : null,
                  tooltip: 'Send',
                  color: ZiaOlive.shade500,
                ).withCommand('session.send', onTap: _sendMessage),
        ],
      ),
    );
  }

  void _showTodoSheet() {
    final session = ref.read(sessionProvider).getSession(_sessionId);
    if (session == null || session.todos.isEmpty) return;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.4,
        minChildSize: 0.2,
        maxChildSize: 0.8,
        expand: false,
        builder: (context, scrollController) => Column(
          children: [
            // 拖动指示器
            Container(
              margin: const EdgeInsets.symmetric(vertical: 8),
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: ZiaOlive.shade200,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            // 标题
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  Icon(Icons.checklist, size: 20, color: ZiaOlive.shade400),
                  const SizedBox(width: 8),
                  Text(
                    'Tasks',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: ZiaOlive.shade500,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${session.todos.where((t) => t.status == TodoStatus.completed).length}/${session.todos.length}',
                    style: TextStyle(
                      fontSize: 14,
                      color: ZiaOlive.shade300,
                    ),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            // Todo 列表
            Expanded(
              child: ListView.builder(
                controller: scrollController,
                padding: const EdgeInsets.all(16),
                itemCount: session.todos.length,
                itemBuilder: (context, index) => _buildTodoItem(session.todos[index]),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTodoItem(TodoItem todo) {
    final (icon, color) = switch (todo.status) {
      TodoStatus.completed => (Icons.check_circle, ZiaOlive.success),
      TodoStatus.inProgress => (Icons.radio_button_checked, ZiaOlive.warning),
      TodoStatus.pending => (Icons.radio_button_unchecked, ZiaOlive.shade300),
    };

    final text = todo.status == TodoStatus.inProgress
        ? todo.activeForm
        : todo.content;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                fontSize: 13,
                color: todo.status == TodoStatus.completed
                    ? ZiaOlive.shade300
                    : ZiaOlive.shade500,
                decoration: todo.status == TodoStatus.completed
                    ? TextDecoration.lineThrough
                    : null,
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _openFileDrawer() {
    _scaffoldKey.currentState?.openEndDrawer();
  }

  void _compactContext() {
    final session = ref.read(sessionProvider).getSession(_sessionId);
    if (session == null) return;

    // 防抖：正在压缩中时忽略
    if (session.isCompacting) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Compacting in progress...'),
          duration: Duration(seconds: 1),
        ),
      );
      return;
    }

    // 检查是否有消息可以压缩
    if (session.messages.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('No messages to compact'),
          duration: Duration(seconds: 1),
        ),
      );
      return;
    }

    ref.read(sessionProvider.notifier).compactContext(_sessionId);
  }

  void _generateTitle() {
    final session = ref.read(sessionProvider).getSession(_sessionId);
    if (session == null) return;

    // 检查是否有消息
    if (session.messages.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('No messages to generate title from'),
          duration: Duration(seconds: 1),
        ),
      );
      return;
    }

    ref.read(sessionProvider.notifier).generateTitle(_sessionId);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Generating title...'),
        duration: Duration(seconds: 1),
      ),
    );
  }

  void _confirmClearMessages() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Reset Session'),
        content: const Text('Clear all messages and reset context? This will start a fresh conversation.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              ref.read(sessionProvider.notifier).resetSession(_sessionId);
              Navigator.pop(context);
            },
            child: const Text('Reset'),
          ),
        ],
      ),
    );
  }

  void _handleTitleTap(SessionConnectionState state) {
    if (state == SessionConnectionState.connected) {
      // 已连接：发送 ping
      ref.read(sessionProvider.notifier).pingSession(_sessionId);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Ping sent'),
          duration: Duration(seconds: 1),
        ),
      );
    } else {
      // 未连接：尝试重连
      _connect();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Reconnecting...'),
          duration: Duration(seconds: 1),
        ),
      );
    }
  }

  void _showRenameDialog() {
    final session = ref.read(sessionProvider).getSession(_sessionId);
    if (session == null) return;

    final controller = TextEditingController(text: session.name);

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Rename Session'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'Session Name',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final newName = controller.text.trim();
              if (newName.isNotEmpty) {
                ref.read(sessionProvider.notifier).renameSession(_sessionId, newName);
              }
              Navigator.pop(context);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  /// 显示功能菜单
  void _showFunctionMenu() {
    showModalBottomSheet(
      context: context,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 拖动指示器
            Container(
              margin: const EdgeInsets.symmetric(vertical: 8),
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: ZiaOlive.shade200,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            // 菜单项
            _buildMenuItem(
              icon: Icons.image,
              label: 'Send Image',
              subtitle: 'Pick from gallery or take photo',
              onTap: () {
                Navigator.pop(context);
                _showImageSourcePicker();
              },
            ),
            _buildMenuItem(
              icon: Icons.folder_outlined,
              label: 'Browse Files',
              subtitle: 'View workspace files',
              onTap: () {
                Navigator.pop(context);
                _openFileDrawer();
              },
            ),
            _buildMenuItem(
              icon: Icons.code,
              label: 'Quick Prompts',
              subtitle: 'Common coding commands',
              onTap: () {
                Navigator.pop(context);
                _showQuickPrompts();
              },
            ),
            _buildMenuItem(
              icon: Icons.compress,
              label: 'Compact Context',
              subtitle: 'Summarize conversation to save tokens',
              onTap: () {
                Navigator.pop(context);
                _compactContext();
              },
            ),
            _buildMenuItem(
              icon: Icons.checklist,
              label: 'View Tasks',
              subtitle: 'Show current todo list',
              onTap: () {
                Navigator.pop(context);
                _showTodoSheet();
              },
            ),
            _buildMenuItem(
              icon: Icons.bug_report_outlined,
              label: 'Report Issue',
              subtitle: 'Save session state for debugging',
              onTap: () {
                Navigator.pop(context);
                _sendFeedback();
              },
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  Widget _buildMenuItem({
    required IconData icon,
    required String label,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return ListTile(
      leading: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: ZiaOlive.shade100.withValues(alpha: 0.3),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Icon(icon, color: ZiaOlive.shade500, size: 24),
      ),
      title: Text(
        label,
        style: TextStyle(
          fontWeight: FontWeight.w500,
          color: ZiaOlive.shade500,
        ),
      ),
      subtitle: Text(
        subtitle,
        style: TextStyle(
          fontSize: 12,
          color: ZiaOlive.shade300,
        ),
      ),
      onTap: onTap,
    );
  }

  /// 显示快捷命令菜单
  void _showQuickPrompts() {
    final prompts = [
      ('Continue', 'Continue where you left off'),
      ('Explain', 'Explain this code'),
      ('Fix', 'Fix the error'),
      ('Test', 'Write tests for this'),
      ('Refactor', 'Refactor this code'),
      ('Review', 'Review changes'),
    ];

    showModalBottomSheet(
      context: context,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 拖动指示器
            Container(
              margin: const EdgeInsets.symmetric(vertical: 8),
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: ZiaOlive.shade200,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            // 标题
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  Icon(Icons.code, size: 20, color: ZiaOlive.shade400),
                  const SizedBox(width: 8),
                  Text(
                    'Quick Prompts',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: ZiaOlive.shade500,
                    ),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            // 快捷命令列表
            Padding(
              padding: const EdgeInsets.all(12),
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                children: prompts.map((p) => ActionChip(
                  label: Text(p.$1),
                  avatar: Icon(
                    _getPromptIcon(p.$1),
                    size: 18,
                    color: ZiaOlive.shade400,
                  ),
                  onPressed: () {
                    Navigator.pop(context);
                    _inputController.text = p.$1;
                    _sendMessage();
                  },
                  backgroundColor: ZiaOlive.shade100.withValues(alpha: 0.3),
                  side: BorderSide.none,
                )).toList(),
              ),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  IconData _getPromptIcon(String prompt) {
    return switch (prompt) {
      'Continue' => Icons.play_arrow,
      'Explain' => Icons.help_outline,
      'Fix' => Icons.build,
      'Test' => Icons.science,
      'Refactor' => Icons.auto_fix_high,
      'Review' => Icons.rate_review,
      _ => Icons.code,
    };
  }

  /// 发送反馈（保存当前会话状态用于调试）
  void _sendFeedback() {
    final connectionPool = ref.read(sessionProvider.notifier).connectionPool;
    connectionPool.sendFeedback(_sessionId);

    // 显示提示
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: const Text('Session state saved for analysis'),
        backgroundColor: ZiaOlive.shade500,
        duration: const Duration(seconds: 2),
      ),
    );
  }

  /// 显示图片来源选择器
  void _showImageSourcePicker() {
    showModalBottomSheet(
      context: context,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 拖动指示器
            Container(
              margin: const EdgeInsets.symmetric(vertical: 8),
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: ZiaOlive.shade200,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            // 标题
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  Icon(Icons.image, size: 20, color: ZiaOlive.shade400),
                  const SizedBox(width: 8),
                  Text(
                    'Send Image',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: ZiaOlive.shade500,
                    ),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            // 选项
            ListTile(
              leading: Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: ZiaOlive.shade100.withValues(alpha: 0.3),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(Icons.photo_library, color: ZiaOlive.shade500),
              ),
              title: Text('Photo Library', style: TextStyle(color: ZiaOlive.shade500)),
              subtitle: Text('Choose from gallery', style: TextStyle(fontSize: 12, color: ZiaOlive.shade300)),
              onTap: () {
                Navigator.pop(context);
                _pickImage(ImageSource.gallery);
              },
            ),
            // 仅在移动端显示相机选项
            if (!kIsWeb)
              ListTile(
                leading: Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: ZiaOlive.shade100.withValues(alpha: 0.3),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(Icons.camera_alt, color: ZiaOlive.shade500),
                ),
                title: Text('Camera', style: TextStyle(color: ZiaOlive.shade500)),
                subtitle: Text('Take a photo', style: TextStyle(fontSize: 12, color: ZiaOlive.shade300)),
                onTap: () {
                  Navigator.pop(context);
                  _pickImage(ImageSource.camera);
                },
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  /// 选择并发送图片
  Future<void> _pickImage(ImageSource source) async {
    try {
      final picker = ImagePicker();
      final XFile? image = await picker.pickImage(
        source: source,
        maxWidth: 1920,
        maxHeight: 1920,
        imageQuality: 85,
      );

      if (image == null) return;

      // 读取图片字节
      final bytes = await image.readAsBytes();
      final fileName = image.name;

      // 显示发送确认对话框
      if (!mounted) return;
      _showImagePreviewDialog(bytes, fileName);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Failed to pick image: $e'),
          backgroundColor: ZiaOlive.error,
        ),
      );
    }
  }

  /// 显示图片预览确认对话框
  void _showImagePreviewDialog(Uint8List bytes, String fileName) {
    final promptController = TextEditingController();

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Send Image'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 图片预览
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: Image.memory(
                bytes,
                width: 200,
                height: 200,
                fit: BoxFit.cover,
              ),
            ),
            const SizedBox(height: 16),
            // 可选提示文字
            TextField(
              controller: promptController,
              decoration: InputDecoration(
                hintText: 'Add a message (optional)',
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              ),
              maxLines: 2,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(context);
              _sendImageToChat(bytes, fileName, promptController.text.trim());
            },
            child: const Text('Send'),
          ),
        ],
      ),
    );
  }

  /// 发送图片到聊天
  Future<void> _sendImageToChat(Uint8List bytes, String fileName, String prompt) async {
    try {
      // 发送图片消息
      ref.read(sessionProvider.notifier).sendImageMessage(
        _sessionId,
        bytes,
        fileName,
        prompt: prompt.isEmpty ? null : prompt,
      );

      // 滚动到底部
      _userScrolledUp = false;
      _scrollToBottomIfNeeded();

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Image sent'),
          duration: Duration(seconds: 1),
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Failed to send image: $e'),
          backgroundColor: ZiaOlive.error,
        ),
      );
    }
  }
}
