import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../config/theme.dart';
import '../models/server_config.dart';
import '../providers/providers.dart';
import '../router.dart';
import '../widgets/command_target.dart';
import 'trash_screen.dart';

// Web-specific imports
import 'dart:html' if (dart.library.io) 'settings_screen_stub.dart' as html;

/// 服务器配置 JSON 格式
/// {
///   "name": "My Server",
///   "host": "192.168.1.100",
///   "port": 8000,
///   "token": "xxx",
///   "https": false
/// }
class ServerConfigData {
  final String name;
  final String host;
  final int port;
  final String token;
  final bool useHttps;

  ServerConfigData({
    required this.name,
    required this.host,
    required this.port,
    required this.token,
    this.useHttps = false,
  });

  factory ServerConfigData.fromJson(Map<String, dynamic> json) {
    return ServerConfigData(
      name: json['name'] as String? ?? 'Server',
      host: json['host'] as String,
      port: json['port'] as int? ?? 8000,
      token: json['token'] as String,
      useHttps: json['https'] as bool? ?? false,
    );
  }

  static ServerConfigData? tryParse(String text) {
    try {
      final json = jsonDecode(text);
      if (json is Map<String, dynamic> && json.containsKey('host') && json.containsKey('token')) {
        return ServerConfigData.fromJson(json);
      }
    } catch (_) {}
    return null;
  }
}

/// 设置页面 - 服务器管理
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final borderColor = isDark ? ZiaOlive.shade700 : ZiaOlive.shade100;
    final cardColor = isDark ? ZiaOlive.shade800 : Colors.white;
    final labelColor = isDark ? ZiaOlive.shade200 : ZiaOlive.shade300;

    final serverState = ref.watch(serverProvider);

    return ScreenScope(
      screenId: 'settings',
      child: Scaffold(
        appBar: AppBar(
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () {
              if (context.canPop()) {
                context.pop();
              } else {
                context.go(AppRoutes.home);
              }
            },
          ).withCommand('settings.back', onTap: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go(AppRoutes.home);
            }
          }),
          title: const Text('Settings'),
        ),
        body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        children: [
          // Servers Section
          _buildSectionHeader('Servers', labelColor),
          const SizedBox(height: 8),
          Container(
            decoration: BoxDecoration(
              color: cardColor,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: borderColor, width: 0.5),
            ),
            child: Column(
              children: [
                // 服务器列表
                ...serverState.servers.asMap().entries.map((entry) {
                  final index = entry.key;
                  final server = entry.value;
                  final isOnline = serverState.isServerOnline(server.id);
                  final isLast = index == serverState.servers.length - 1;

                  return CommandListItem(
                    targetId: 'settings.server.${server.id}',
                    label: server.name,
                    getState: () => {
                      'name': server.name,
                      'address': server.address,
                      'online': isOnline,
                    },
                    child: _ServerTile(
                      server: server,
                      isOnline: isOnline,
                      showBorder: !isLast || true, // 始终显示底边
                      borderColor: borderColor,
                    ),
                  );
                }),

                // 添加方式选择
                _AddServerOptions(borderColor: borderColor),
              ],
            ),
          ),

          const SizedBox(height: 24),

          // Data Section
          _buildSectionHeader('Data', labelColor),
          const SizedBox(height: 8),
          Container(
            decoration: BoxDecoration(
              color: cardColor,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: borderColor, width: 0.5),
            ),
            child: InkWell(
              onTap: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (_) => const TrashScreen()),
                );
              },
              borderRadius: BorderRadius.circular(12),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    Container(
                      width: 32,
                      height: 32,
                      decoration: BoxDecoration(
                        color: ZiaOlive.error.withValues(alpha: 0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Icon(
                        Icons.delete_outline,
                        color: ZiaOlive.error,
                        size: 18,
                      ),
                    ),
                    const SizedBox(width: 12),
                    const Expanded(
                      child: Text(
                        'Trash',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    Icon(
                      Icons.chevron_right,
                      color: ZiaOlive.shade200,
                      size: 20,
                    ),
                  ],
                ),
              ),
            ),
          ),

          const SizedBox(height: 32),

          // About Section
          _buildSectionHeader('About', labelColor),
          const SizedBox(height: 8),
          Container(
            decoration: BoxDecoration(
              color: cardColor,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: borderColor, width: 0.5),
            ),
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: ZiaOlive.shade500.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(
                    Icons.code,
                    color: ZiaOlive.shade500,
                    size: 20,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Mule',
                        style: TextStyle(
                          fontWeight: FontWeight.w600,
                          fontSize: 15,
                        ),
                      ),
                      Text(
                        'Version 1.0.0',
                        style: TextStyle(
                          color: labelColor,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      ),
    );
  }

  Widget _buildSectionHeader(String title, Color color) {
    return Padding(
      padding: const EdgeInsets.only(left: 4),
      child: Text(
        title.toUpperCase(),
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

/// 添加服务器选项
class _AddServerOptions extends ConsumerWidget {
  final Color borderColor;

  const _AddServerOptions({required this.borderColor});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: borderColor, width: 0.5)),
      ),
      child: Row(
        children: [
          // 手动添加
          Expanded(
            child: InkWell(
              onTap: () => _showManualAddDialog(context),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 14),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.add, size: 18, color: ZiaOlive.shade500),
                    const SizedBox(width: 6),
                    Text(
                      'Manual',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w500,
                        color: ZiaOlive.shade500,
                      ),
                    ),
                  ],
                ),
              ),
            ).withCommand('settings.add_manual', onTap: () => _showManualAddDialog(context)),
          ),
          Container(width: 0.5, height: 40, color: borderColor),
          // 从剪切板
          Expanded(
            child: InkWell(
              onTap: () => _pasteFromClipboard(context, ref),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 14),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.content_paste, size: 18, color: ZiaOlive.shade500),
                    const SizedBox(width: 6),
                    Text(
                      'Paste',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w500,
                        color: ZiaOlive.shade500,
                      ),
                    ),
                  ],
                ),
              ),
            ).withCommand('settings.add_paste', onTap: () => _pasteFromClipboard(context, ref)),
          ),
          Container(width: 0.5, height: 40, color: borderColor),
          // 扫码
          Expanded(
            child: InkWell(
              onTap: () => _scanQRCode(context),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 14),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.qr_code_scanner, size: 18, color: ZiaOlive.shade500),
                    const SizedBox(width: 6),
                    Text(
                      'Scan',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w500,
                        color: ZiaOlive.shade500,
                      ),
                    ),
                  ],
                ),
              ),
            ).withCommand('settings.add_scan', onTap: () => _scanQRCode(context)),
          ),
        ],
      ),
    );
  }

  void _showManualAddDialog(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => const _ServerFormSheet(),
    );
  }

  Future<void> _pasteFromClipboard(BuildContext context, WidgetRef ref) async {
    try {
      final data = await Clipboard.getData(Clipboard.kTextPlain);
      if (data?.text == null || data!.text!.isEmpty) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Clipboard is empty')),
          );
        }
        return;
      }

      final config = ServerConfigData.tryParse(data.text!);
      if (config == null) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Invalid server config in clipboard')),
          );
        }
        return;
      }

      if (context.mounted) {
        _showConfirmAddDialog(context, ref, config);
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $e')),
        );
      }
    }
  }

  void _scanQRCode(BuildContext context) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => const _QRScannerScreen(),
      ),
    );
  }

  void _showConfirmAddDialog(BuildContext context, WidgetRef ref, ServerConfigData config) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add Server'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Name: ${config.name}'),
            Text('Host: ${config.host}:${config.port}'),
            Text('HTTPS: ${config.useHttps ? "Yes" : "No"}'),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              await ref.read(serverProvider.notifier).addServer(
                    name: config.name,
                    host: config.host,
                    port: config.port,
                    token: config.token,
                    useHttps: config.useHttps,
                  );
              if (context.mounted) {
                Navigator.pop(context);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Added ${config.name}')),
                );
              }
            },
            child: const Text('Add'),
          ),
        ],
      ),
    );
  }
}

/// 二维码扫描页面
class _QRScannerScreen extends ConsumerStatefulWidget {
  const _QRScannerScreen();

  @override
  ConsumerState<_QRScannerScreen> createState() => _QRScannerScreenState();
}

class _QRScannerScreenState extends ConsumerState<_QRScannerScreen> {
  final MobileScannerController _controller = MobileScannerController();
  bool _isProcessing = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_isProcessing) return;

    final barcode = capture.barcodes.firstOrNull;
    if (barcode?.rawValue == null) return;

    final config = ServerConfigData.tryParse(barcode!.rawValue!);
    if (config == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Invalid QR code')),
      );
      return;
    }

    setState(() => _isProcessing = true);
    _controller.stop();

    // 显示确认对话框
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Add Server'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Name: ${config.name}'),
            Text('Host: ${config.host}:${config.port}'),
            Text('HTTPS: ${config.useHttps ? "Yes" : "No"}'),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _controller.start();
              setState(() => _isProcessing = false);
            },
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () async {
              await ref.read(serverProvider.notifier).addServer(
                    name: config.name,
                    host: config.host,
                    port: config.port,
                    token: config.token,
                    useHttps: config.useHttps,
                  );
              if (context.mounted) {
                Navigator.pop(context); // 关闭对话框
                Navigator.pop(context); // 返回设置页
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Added ${config.name}')),
                );
              }
            },
            child: const Text('Add'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Scan QR Code'),
        actions: [
          IconButton(
            icon: ValueListenableBuilder(
              valueListenable: _controller,
              builder: (context, state, child) {
                return Icon(
                  state.torchState == TorchState.on
                      ? Icons.flash_on
                      : Icons.flash_off,
                );
              },
            ),
            onPressed: () => _controller.toggleTorch(),
          ),
          IconButton(
            icon: const Icon(Icons.flip_camera_ios),
            onPressed: () => _controller.switchCamera(),
          ),
        ],
      ),
      body: Stack(
        children: [
          MobileScanner(
            controller: _controller,
            onDetect: _onDetect,
          ),
          // 扫描框
          Center(
            child: Container(
              width: 250,
              height: 250,
              decoration: BoxDecoration(
                border: Border.all(color: ZiaOlive.shade500, width: 2),
                borderRadius: BorderRadius.circular(12),
              ),
            ),
          ),
          // 提示文字
          Positioned(
            bottom: 100,
            left: 0,
            right: 0,
            child: Text(
              'Scan server QR code',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white,
                fontSize: 16,
                shadows: [
                  Shadow(
                    color: Colors.black.withValues(alpha: 0.5),
                    blurRadius: 4,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 服务器列表项
class _ServerTile extends ConsumerWidget {
  final ServerConfig server;
  final bool isOnline;
  final bool showBorder;
  final Color borderColor;

  const _ServerTile({
    required this.server,
    required this.isOnline,
    required this.showBorder,
    required this.borderColor,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      decoration: BoxDecoration(
        border: showBorder
            ? Border(bottom: BorderSide(color: borderColor, width: 0.5))
            : null,
      ),
      child: InkWell(
        onTap: () => _showEditDialog(context),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              // 状态指示
              Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: isOnline ? ZiaOlive.success : ZiaOlive.error,
                ),
              ),
              const SizedBox(width: 12),

              // 服务器信息
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      server.name,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    Text(
                      server.address,
                      style: TextStyle(
                        fontSize: 13,
                        color: ZiaOlive.shade200,
                      ),
                    ),
                  ],
                ),
              ),

              // 更多操作
              PopupMenuButton<String>(
                icon: Icon(Icons.more_vert, size: 20, color: ZiaOlive.shade300),
                onSelected: (value) => _handleAction(context, ref, value),
                itemBuilder: (context) => [
                  const PopupMenuItem(
                    value: 'edit',
                    child: Row(
                      children: [
                        Icon(Icons.edit_outlined, size: 20),
                        SizedBox(width: 8),
                        Text('Edit'),
                      ],
                    ),
                  ),
                  const PopupMenuItem(
                    value: 'refresh',
                    child: Row(
                      children: [
                        Icon(Icons.refresh, size: 20),
                        SizedBox(width: 8),
                        Text('Refresh'),
                      ],
                    ),
                  ),
                  const PopupMenuItem(
                    value: 'delete',
                    child: Row(
                      children: [
                        Icon(Icons.delete_outline, size: 20, color: Colors.red),
                        SizedBox(width: 8),
                        Text('Delete', style: TextStyle(color: Colors.red)),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _handleAction(BuildContext context, WidgetRef ref, String action) {
    switch (action) {
      case 'edit':
        _showEditDialog(context);
        break;
      case 'refresh':
        ref.read(serverProvider.notifier).refreshServer(server.id);
        break;
      case 'delete':
        _confirmDelete(context, ref);
        break;
    }
  }

  void _showEditDialog(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _ServerFormSheet(server: server),
    );
  }

  void _confirmDelete(BuildContext context, WidgetRef ref) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Server'),
        content: Text('Delete "${server.name}"? All sessions for this server will be removed.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              ref.read(serverProvider.notifier).deleteServer(server.id);
              Navigator.pop(context);
            },
            style: FilledButton.styleFrom(backgroundColor: ZiaOlive.error),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
  }
}

/// 服务器表单
class _ServerFormSheet extends ConsumerStatefulWidget {
  final ServerConfig? server;

  const _ServerFormSheet({this.server});

  @override
  ConsumerState<_ServerFormSheet> createState() => _ServerFormSheetState();
}

class _ServerFormSheetState extends ConsumerState<_ServerFormSheet> {
  late final TextEditingController _nameController;
  late final TextEditingController _hostController;
  late final TextEditingController _portController;
  late final TextEditingController _tokenController;
  late bool _useHttps;

  bool _isLoading = false;

  bool get isEditing => widget.server != null;

  /// 从当前页面 URL 获取服务器默认配置（仅 PWA/Web 模式）
  static ({String name, String host, int port, bool useHttps})? _getDefaultsFromUrl() {
    if (!kIsWeb) return null;

    try {
      final location = html.window.location;
      // ignore: unnecessary_cast - 使用 as dynamic 避免平台差异导致的 null 检查问题
      final protocol = (location.protocol as dynamic)?.toString() ?? '';
      final hostname = (location.hostname as dynamic)?.toString() ?? '';
      final portStr = (location.port as dynamic)?.toString() ?? '';

      if (hostname.isEmpty) return null;

      // 解析端口，如果为空则使用默认端口
      int port = 8080;
      if (portStr.isNotEmpty) {
        port = int.tryParse(portStr) ?? 8080;
      } else {
        // 没有端口时，根据协议使用默认端口
        port = protocol == 'https:' ? 443 : 80;
      }

      final useHttps = protocol == 'https:';

      // 生成服务器名称
      String name = hostname;
      if (hostname.contains('.')) {
        // 使用域名的第一部分作为名称
        name = hostname.split('.').first;
      }
      // 首字母大写
      if (name.isNotEmpty) {
        name = name[0].toUpperCase() + name.substring(1);
      }

      return (name: name, host: hostname, port: port, useHttps: useHttps);
    } catch (e) {
      return null;
    }
  }

  @override
  void initState() {
    super.initState();

    if (widget.server != null) {
      // 编辑模式：使用现有服务器配置
      _nameController = TextEditingController(text: widget.server!.name);
      _hostController = TextEditingController(text: widget.server!.host);
      _portController = TextEditingController(text: widget.server!.port.toString());
      _tokenController = TextEditingController(text: widget.server!.token);
      _useHttps = widget.server!.useHttps;
    } else {
      // 新增模式：尝试从 URL 获取默认值（PWA 模式）
      final defaults = _getDefaultsFromUrl();
      _nameController = TextEditingController(text: defaults?.name ?? '');
      _hostController = TextEditingController(text: defaults?.host ?? '');
      _portController = TextEditingController(text: (defaults?.port ?? 8080).toString());
      _tokenController = TextEditingController(text: ''); // Token 始终需要手动输入
      _useHttps = defaults?.useHttps ?? false;
    }
  }

  @override
  void dispose() {
    _nameController.dispose();
    _hostController.dispose();
    _portController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  void _save() async {
    final name = _nameController.text.trim();
    final host = _hostController.text.trim();
    final port = int.tryParse(_portController.text) ?? 8000;
    final token = _tokenController.text.trim();

    if (name.isEmpty || host.isEmpty || token.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please fill in all required fields')),
      );
      return;
    }

    // 检查是否存在相同配置的服务器
    final serverState = ref.read(serverProvider);
    final existingServer = serverState.findDuplicateServer(
      host,
      port,
      excludeId: widget.server?.id, // 编辑模式时排除自身
    );

    if (existingServer != null) {
      // 已存在相同配置，询问用户
      final shouldContinue = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Server Already Exists'),
          content: Text(
            'A server with the same address ($host:$port) already exists as "${existingServer.name}".\n\nDo you want to update the existing server instead?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Update Existing'),
            ),
          ],
        ),
      );

      if (shouldContinue != true) return;

      // 更新现有服务器
      setState(() => _isLoading = true);
      try {
        await ref.read(serverProvider.notifier).updateServer(
          existingServer.copyWith(
            name: name,
            token: token,
            useHttps: _useHttps,
          ),
        );
        if (mounted) {
          Navigator.pop(context);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Updated "${existingServer.name}"')),
          );
        }
      } finally {
        if (mounted) setState(() => _isLoading = false);
      }
      return;
    }

    setState(() => _isLoading = true);

    try {
      if (isEditing) {
        await ref.read(serverProvider.notifier).updateServer(widget.server!.copyWith(
          name: name,
          host: host,
          port: port,
          token: token,
          useHttps: _useHttps,
        ));
      } else {
        await ref.read(serverProvider.notifier).addServer(
          name: name,
          host: host,
          port: port,
          token: token,
          useHttps: _useHttps,
        );
      }

      if (mounted) Navigator.pop(context);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).scaffoldBackgroundColor,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
      ),
      padding: EdgeInsets.only(
        left: 24,
        right: 24,
        top: 24,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // 标题
            Row(
              children: [
                Text(
                  isEditing ? 'Edit Server' : 'Add Server',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
            const SizedBox(height: 24),

            // 服务器名称
            TextField(
              controller: _nameController,
              decoration: const InputDecoration(
                labelText: 'Name *',
                hintText: 'e.g., Home Server',
                prefixIcon: Icon(Icons.label_outline),
              ),
            ),
            const SizedBox(height: 16),

            // Host
            TextField(
              controller: _hostController,
              decoration: const InputDecoration(
                labelText: 'Host *',
                hintText: 'e.g., 192.168.1.100',
                prefixIcon: Icon(Icons.dns_outlined),
              ),
            ),
            const SizedBox(height: 16),

            // Port
            TextField(
              controller: _portController,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: const InputDecoration(
                labelText: 'Port',
                hintText: '8000',
                prefixIcon: Icon(Icons.numbers),
              ),
            ),
            const SizedBox(height: 16),

            // Token
            TextField(
              controller: _tokenController,
              obscureText: true,
              decoration: const InputDecoration(
                labelText: 'API Token *',
                hintText: 'Enter your token',
                prefixIcon: Icon(Icons.key_outlined),
              ),
            ),
            const SizedBox(height: 16),

            // HTTPS 开关
            SwitchListTile(
              title: const Text('Use HTTPS'),
              value: _useHttps,
              onChanged: (v) => setState(() => _useHttps = v),
              contentPadding: EdgeInsets.zero,
            ),
            const SizedBox(height: 24),

            // 保存按钮
            FilledButton(
              onPressed: _isLoading ? null : _save,
              child: _isLoading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : Text(isEditing ? 'Save' : 'Add Server'),
            ),
          ],
        ),
      ),
    );
  }
}
