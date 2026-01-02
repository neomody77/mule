import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/message.dart';

/// 消息气泡组件
class MessageBubble extends StatefulWidget {
  final ChatMessage message;

  const MessageBubble({super.key, required this.message});

  @override
  State<MessageBubble> createState() => _MessageBubbleState();
}

class _MessageBubbleState extends State<MessageBubble> {
  // 跟踪每个工具调用的展开状态
  final Set<String> _expandedToolCalls = {};

  ChatMessage get message => widget.message;

  @override
  Widget build(BuildContext context) {
    final isUser = message.type == MessageType.user;
    final isError = message.type == MessageType.error;
    final isStatus = message.type == MessageType.status;
    final isToolCall = message.type == MessageType.toolCall;

    if (isStatus) {
      return _buildStatusMessage(context);
    }

    // 工具调用消息 - 单独渲染，不用气泡包裹
    if (isToolCall && message.toolCalls.isNotEmpty) {
      return Align(
        alignment: Alignment.centerLeft,
        child: Container(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.85,
          ),
          margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: message.toolCalls.map((tc) => _buildToolCall(context, tc)).toList(),
          ),
        ),
      );
    }

    // 用户消息：pending 时使用浅色（同色系 shade200）
    final isPending = message.isPending;
    Color userBubbleColor;
    Color userTextColor;
    if (isUser) {
      if (isPending) {
        // 浅色：ZiaOlive.shade200
        userBubbleColor = const Color(0xFF96A493);
        userTextColor = Colors.white.withOpacity(0.9);
      } else {
        userBubbleColor = Theme.of(context).colorScheme.primary;
        userTextColor = Theme.of(context).colorScheme.onPrimary;
      }
    } else {
      userBubbleColor = isError
          ? Theme.of(context).colorScheme.errorContainer
          : Theme.of(context).colorScheme.surfaceContainerHighest;
      userTextColor = Theme.of(context).colorScheme.onSurface;
    }

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.85,
        ),
        margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: userBubbleColor,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (message.content.isNotEmpty) _buildContent(context, isUser, userTextColor),
            if (message.toolCalls.isNotEmpty) ...[
              const SizedBox(height: 8),
              ...message.toolCalls.map((tc) => _buildToolCall(context, tc)),
            ],
            if (message.isStreaming) _buildStreamingIndicator(context),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusMessage(BuildContext context) {
    return Center(
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 8),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (message.isStreaming) ...[
              SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(width: 8),
            ],
            Text(
              message.content,
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
                fontSize: 12,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildContent(BuildContext context, bool isUser, Color textColor) {
    if (isUser) {
      return Text(
        message.content,
        style: TextStyle(
          color: textColor,
        ),
      );
    }

    // 判断是否为大块消息（超过 200 字符或包含代码块）
    final isLargeMessage = message.content.length > 200 ||
        message.content.contains('```');

    // Assistant 消息使用 Markdown 渲染
    // 使用 SelectionArea 包裹以支持文本选择，同时保持链接点击功能
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SelectionArea(
          child: MarkdownBody(
            data: message.content,
            selectable: false,
            onTapLink: (text, href, title) {
              debugPrint('[MessageBubble] Link tapped: text=$text, href=$href');
              _launchUrl(href);
            },
            styleSheet: MarkdownStyleSheet(
              p: TextStyle(
                color: Theme.of(context).colorScheme.onSurface,
              ),
              a: TextStyle(
                color: Theme.of(context).colorScheme.primary,
                decoration: TextDecoration.underline,
              ),
              code: TextStyle(
                backgroundColor: Theme.of(context).colorScheme.surfaceContainerHigh,
                fontFamily: 'monospace',
              ),
              codeblockDecoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surfaceContainerHigh,
                borderRadius: BorderRadius.circular(8),
              ),
            ),
          ),
        ),
        if (isLargeMessage) ...[
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: InkWell(
              onTap: () => _copyToClipboard(context, message.content),
              borderRadius: BorderRadius.circular(4),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.content_copy,
                      size: 14,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '复制',
                      style: TextStyle(
                        fontSize: 12,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ],
    );
  }

  void _copyToClipboard(BuildContext context, String text) {
    Clipboard.setData(ClipboardData(text: text));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('已复制'),
        duration: Duration(seconds: 1),
      ),
    );
  }

  Future<void> _launchUrl(String? url) async {
    debugPrint('[MessageBubble] onTapLink called with url: $url');
    if (url == null || url.isEmpty) {
      debugPrint('[MessageBubble] URL is null or empty');
      return;
    }
    final uri = Uri.tryParse(url);
    if (uri == null) {
      debugPrint('[MessageBubble] Failed to parse URL: $url');
      return;
    }
    final canLaunch = await canLaunchUrl(uri);
    debugPrint('[MessageBubble] canLaunchUrl: $canLaunch');
    if (canLaunch) {
      final result = await launchUrl(uri, mode: LaunchMode.externalApplication);
      debugPrint('[MessageBubble] launchUrl result: $result');
    } else {
      debugPrint('[MessageBubble] Cannot launch URL: $url');
    }
  }

  Widget _buildToolCall(BuildContext context, ToolCall toolCall) {
    final hasResult = toolCall.result != null;
    final isExecuting = toolCall.isExecuting;
    final isError = toolCall.result?['is_error'] == true;
    final isExpanded = _expandedToolCalls.contains(toolCall.id);

    // 显示描述或默认的工具名
    final displayText = toolCall.description ?? toolCall.name;

    // 获取结果内容
    final resultContent = toolCall.result?['content'] as String?;
    final hasContent = resultContent != null && resultContent.isNotEmpty;

    return GestureDetector(
      onTap: hasContent
          ? () {
              setState(() {
                if (isExpanded) {
                  _expandedToolCalls.remove(toolCall.id);
                } else {
                  _expandedToolCalls.add(toolCall.id);
                }
              });
            }
          : null,
      child: Container(
        margin: const EdgeInsets.only(top: 4),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surface,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: isError
                ? Theme.of(context).colorScheme.error
                : Theme.of(context).colorScheme.outline.withValues(alpha: 0.3),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 工具调用头部
            Row(
              children: [
                Icon(
                  _getToolIcon(toolCall.name),
                  size: 14,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    displayText,
                    style: TextStyle(
                      fontSize: 12,
                      color: Theme.of(context).colorScheme.onSurface,
                      fontFamily: toolCall.name == 'Bash' ? 'monospace' : null,
                    ),
                    overflow: TextOverflow.ellipsis,
                    maxLines: 2,
                  ),
                ),
                const SizedBox(width: 6),
                if (isExecuting)
                  const SizedBox(
                    width: 12,
                    height: 12,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                else if (hasResult) ...[
                  Icon(
                    isError ? Icons.error_outline : Icons.check_circle_outline,
                    size: 14,
                    color: isError
                        ? Theme.of(context).colorScheme.error
                        : Colors.green,
                  ),
                  // 展开/收起指示器
                  if (hasContent) ...[
                    const SizedBox(width: 4),
                    Icon(
                      isExpanded ? Icons.expand_less : Icons.expand_more,
                      size: 16,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ],
                ],
              ],
            ),
            // 显示结果内容（仅当展开时显示完整内容）
            if (hasContent) ...[
              const SizedBox(height: 8),
              AnimatedCrossFade(
                firstChild: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.surfaceContainerHigh,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    resultContent.length > 100
                        ? '${resultContent.substring(0, 100)}...'
                        : resultContent,
                    style: TextStyle(
                      fontSize: 11,
                      fontFamily: 'monospace',
                      color: isError
                          ? Theme.of(context).colorScheme.error
                          : Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                secondChild: Container(
                  width: double.infinity,
                  constraints: const BoxConstraints(maxHeight: 300),
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.surfaceContainerHigh,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: SingleChildScrollView(
                    child: Text(
                      resultContent,
                      style: TextStyle(
                        fontSize: 11,
                        fontFamily: 'monospace',
                        color: isError
                            ? Theme.of(context).colorScheme.error
                            : Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ),
                ),
                crossFadeState: isExpanded
                    ? CrossFadeState.showSecond
                    : CrossFadeState.showFirst,
                duration: const Duration(milliseconds: 200),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildToolResult(BuildContext context, ToolCall toolCall) {
    final result = toolCall.result!;
    String displayText;

    if (result['error'] != null) {
      displayText = 'Error: ${result['error']}';
    } else if (result['content'] != null) {
      // 读取文件结果
      final content = result['content'] as String;
      displayText = content.length > 200
          ? '${content.substring(0, 200)}...'
          : content;
    } else if (result['stdout'] != null) {
      // 命令执行结果
      final stdout = result['stdout'] as String;
      final stderr = result['stderr'] as String? ?? '';
      displayText = stdout.isNotEmpty ? stdout : stderr;
      if (displayText.length > 200) {
        displayText = '${displayText.substring(0, 200)}...';
      }
    } else if (result['success'] == true) {
      displayText = 'Success';
    } else {
      displayText = result.toString();
      if (displayText.length > 200) {
        displayText = '${displayText.substring(0, 200)}...';
      }
    }

    return Text(
      displayText,
      style: TextStyle(
        fontSize: 11,
        fontFamily: 'monospace',
        color: Theme.of(context).colorScheme.onSurfaceVariant,
      ),
      maxLines: 5,
      overflow: TextOverflow.ellipsis,
    );
  }

  Widget _buildStreamingIndicator(BuildContext context) {
    // 如果消息内容为空且没有工具调用，显示 "Thinking..."
    final showThinking = message.content.isEmpty && message.toolCalls.isEmpty;

    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          if (showThinking) ...[
            const SizedBox(width: 8),
            Text(
              'Thinking...',
              style: TextStyle(
                fontSize: 12,
                fontStyle: FontStyle.italic,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ],
      ),
    );
  }

  // 工具图标映射
  static const _toolIcons = {
    'Read': Icons.file_open_outlined,
    'Write': Icons.edit_document,
    'Edit': Icons.edit_outlined,
    'Bash': Icons.terminal,
    'Glob': Icons.folder_outlined,
    'Grep': Icons.search,
    'Task': Icons.account_tree_outlined,
    'WebSearch': Icons.language,
    'WebFetch': Icons.download_outlined,
  };

  IconData _getToolIcon(String toolName) {
    return _toolIcons[toolName] ?? Icons.build_outlined;
  }
}
