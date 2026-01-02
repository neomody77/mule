import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/theme.dart';
import '../models/chat_session.dart' show ChatSession, SessionConnectionState, PendingPrompt, TodoItem, TodoStatus;
import '../models/server_config.dart';
import '../providers/providers.dart';
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

    // 设置 ADB 方法通道处理器
    _adbChannel.setMethodCallHandler(_handleAdbMethod);

    // 连接 WebSocket 并滚动到底部
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _connect();
      // 进入时强制滚动到底部（延迟一下等消息加载）
      Future.delayed(const Duration(milliseconds: 300), () {
        if (mounted) _forceScrollToBottom();
      });
    });
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
    _inputController.dispose();
    _scrollController.dispose();
    _focusNode.dispose();
    // 注意：不断开连接，保持订阅以便接收后台任务通知
    super.dispose();
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
            onPressed: () => Navigator.pop(context),
          ).withCommand('session.back', onTap: () => Navigator.pop(context)),
          title: session == null
              ? const Text('Session')
              : GestureDetector(
                  onTap: _showRenameDialog,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Flexible(
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
                      const SizedBox(width: 4),
                      Icon(Icons.edit, size: 16, color: ZiaOlive.shade300),
                    ],
                  ),
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
            // Files 按钮
            IconButton(
              icon: const Icon(Icons.folder_outlined),
              onPressed: _openFileDrawer,
              tooltip: 'Files',
            ),
            // Compact 按钮
            IconButton(
              icon: const Icon(Icons.compress),
              onPressed: _compactContext,
              tooltip: 'Compact Context',
            ),
            // Clear 按钮
            IconButton(
              icon: const Icon(Icons.delete_outline),
              onPressed: _confirmClearMessages,
              tooltip: 'Clear Messages',
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
          // 发送按钮
          IconButton(
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
    ref.read(sessionProvider.notifier).compactContext(_sessionId);
  }

  void _confirmClearMessages() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear Messages'),
        content: const Text('Clear all messages in this session?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final session = ref.read(sessionProvider).getSession(_sessionId);
              session?.clearMessages();
              Navigator.pop(context);
            },
            child: const Text('Clear'),
          ),
        ],
      ),
    );
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
}
